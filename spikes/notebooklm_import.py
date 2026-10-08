# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bounded read-only inspection of personal NotebookLM Google Takeout TGZ files."""
from collections import Counter
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import unicodedata

from spikes.metadata import MAX_FILE, MAX_METADATA, MAX_SNAPSHOT, require


PARSER_REVISION = 'notebooklm-takeout-personal-v1'
ROOT = ('Takeout', 'NotebookLM')
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_MEMBERS = 10000
MAX_PATH_BYTES = 1024
MAX_DEPTH = 8
KNOWN_CATEGORIES = {'Sources', 'Artifacts', 'Chat History', 'Discovered Sources'}
SOURCE_TYPES = {
    'SOURCE_CONTENT_TYPE_DRIVE',
    'SOURCE_CONTENT_TYPE_URL',
    'SOURCE_CONTENT_TYPE_GOOGLE_DOC',
    'SOURCE_CONTENT_TYPE_GEMINI_CHAT',
    'SOURCE_CONTENT_TYPE_PDF',
    'SOURCE_CONTENT_TYPE_IMAGE',
    'SOURCE_CONTENT_TYPE_MARKDOWN',
}


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _timestamp(value, field):
    require(isinstance(value, str)
            and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?Z', value),
            f'Invalid NotebookLM {field}')
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'Invalid NotebookLM {field}') from exc
    return value


def _text(value, field, limit=1000):
    require(isinstance(value, str) and bool(value.strip())
            and len(value.encode('utf-8')) <= limit
            and not any(ord(char) < 32 and char not in '\t' for char in value),
            f'Invalid NotebookLM {field}')
    return value


def _json(raw, label):
    require(len(raw) <= MAX_METADATA, f'{label} exceeds 64 KiB')
    try:
        value = json.loads(raw.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f'Invalid {label}') from exc
    require(isinstance(value, dict), f'Invalid {label}')
    return value


def _path(name):
    require(isinstance(name, str) and name and not name.startswith('/')
            and '\\' not in name and not any(ord(char) < 32 or ord(char) == 127 for char in name),
            'Unsafe Takeout member path')
    normalized = unicodedata.normalize('NFC', name)
    parts = PurePosixPath(normalized).parts
    require(parts and len(parts) <= MAX_DEPTH and all(part not in {'', '.', '..'} for part in parts)
            and len(normalized.encode('utf-8')) <= MAX_PATH_BYTES,
            'Unsafe Takeout member path')
    return normalized, parts


def _member_record(member, raw):
    return {'path': member.name, 'size': member.size, 'sha256': _sha256(raw)}


class _ChatShape(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.labels = []
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        if tag.casefold() == 'script':
            self.scripts += 1
        self.depth += 1

    def handle_endtag(self, tag):
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        value = data.strip()
        if self.depth == 0 and value:
            self.labels.append(value)


def _notebook_metadata(raw):
    value = _json(raw, 'NotebookLM notebook metadata')
    require(set(value) in ({'title', 'emoji', 'metadata'},
                           {'title', 'emoji', 'metadata', 'advancedSettings'}),
            'Unsupported NotebookLM notebook metadata')
    title = _text(value['title'], 'notebook title', 200)
    require(isinstance(value['emoji'], str) and len(value['emoji'].encode('utf-8')) <= 32,
            'Invalid NotebookLM emoji')
    metadata = value['metadata']
    require(isinstance(metadata, dict)
            and set(metadata) == {'createTime', 'isShared', 'lastViewed'}
            and type(metadata['isShared']) is bool,
            'Unsupported NotebookLM notebook metadata')
    created = _timestamp(metadata['createTime'], 'createTime')
    viewed = _timestamp(metadata['lastViewed'], 'lastViewed')
    if 'advancedSettings' in value:
        advanced = value['advancedSettings']
        require(isinstance(advanced, dict) and set(advanced) == {'persona'}
                and isinstance(advanced['persona'], dict)
                and set(advanced['persona']) == {'type'},
                'Unsupported NotebookLM advanced settings')
        _text(advanced['persona']['type'], 'persona type', 200)
    return {'title': title, 'emoji': value['emoji'], 'created_at': created,
            'last_viewed': viewed, 'shared': metadata['isShared']}


def _source_metadata(raw):
    value = _json(raw, 'NotebookLM source metadata')
    require(set(value) == {'title', 'metadata'}, 'Unsupported NotebookLM source metadata')
    title = _text(value['title'], 'source title', 1000)
    metadata = value['metadata']
    require(isinstance(metadata, dict), 'Unsupported NotebookLM source metadata')
    base_keys = {'originalSourceContentType', 'revisionData', 'sourceAddedTimestamp'}
    require(base_keys <= set(metadata), 'Unsupported NotebookLM source metadata')
    source_type = metadata['originalSourceContentType']
    require(source_type in SOURCE_TYPES, 'Unsupported NotebookLM source type')
    expected_keys = (base_keys | {'googleDocsMetadata'}
                     if source_type == 'SOURCE_CONTENT_TYPE_GOOGLE_DOC' else base_keys)
    require(set(metadata) == expected_keys, 'Unsupported NotebookLM source metadata')
    if source_type == 'SOURCE_CONTENT_TYPE_GOOGLE_DOC':
        google = metadata['googleDocsMetadata']
        require(isinstance(google, dict) and set(google) == {'documentId', 'revisionId'},
                'Unsupported NotebookLM Google Docs metadata')
        _text(google['documentId'], 'Google Docs document ID', 1000)
        _text(google['revisionId'], 'Google Docs revision ID', 1000)
    added = _timestamp(metadata['sourceAddedTimestamp'], 'sourceAddedTimestamp')
    revision = metadata['revisionData']
    require(isinstance(revision, dict) and set(revision) == {'dateAdded'},
            'Unsupported NotebookLM source revision')
    _timestamp(revision['dateAdded'], 'revisionData.dateAdded')
    return {'title': title, 'source_type': source_type, 'source_created_at': added}


def _artifact_metadata(raw):
    value = _json(raw, 'NotebookLM artifact metadata')
    require(set(value) == {'sources', 'status', 'tailoredReport', 'title', 'type'},
            'Unsupported NotebookLM artifact metadata')
    title = _text(value['title'], 'artifact title', 1000)
    require(value['type'] == 'ARTIFACT_TYPE_TAILORED_REPORT'
            and value['status'] == 'ARTIFACT_STATUS_READY',
            'Unsupported NotebookLM artifact type or status')
    sources = value['sources']
    require(isinstance(sources, list) and len(sources) <= 1000,
            'Invalid NotebookLM artifact sources')
    source_ids = []
    for source in sources:
        require(isinstance(source, dict)
                and set(source) in ({'sourceId', 'sourceContentType'},
                                    {'sourceId', 'sourceContentType', 'mimeType'}),
                'Unsupported NotebookLM artifact source reference')
        identity = source['sourceId']
        require(isinstance(identity, dict) and set(identity) == {'id'}
                and isinstance(identity['id'], str)
                and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',
                                 identity['id']),
                'Invalid NotebookLM artifact source ID')
        _text(source['sourceContentType'], 'artifact source type', 200)
        if 'mimeType' in source:
            _text(source['mimeType'], 'artifact source MIME type', 200)
        source_ids.append(identity['id'])
    report = value['tailoredReport']
    require(isinstance(report, dict) and set(report) == {'generationOptions'}
            and isinstance(report['generationOptions'], dict),
            'Unsupported NotebookLM tailored report')
    return {'title': title, 'type': value['type'], 'status': value['status'],
            'source_reference_count': len(source_ids),
            'source_reference_sha256': _sha256(_canonical(source_ids))}


class NotebookLMTakeout:
    def __init__(self, path):
        self.path = Path(path).absolute()

    def _open(self):
        require(self.path == self.path.resolve(), 'Takeout path must not contain symlinks')
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        handle = os.fdopen(fd, 'rb')
        before = os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_ARCHIVE,
                'Takeout must be a regular TGZ up to 512 MiB')
        return handle, before

    def _scan(self):
        handle, before = self._open()
        try:
            archive_hash = hashlib.sha256()
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                archive_hash.update(block)
            handle.seek(0)
            try:
                bundle = tarfile.open(fileobj=handle, mode='r:gz')
                members = bundle.getmembers()
            except (tarfile.TarError, EOFError, OSError) as exc:
                raise ValueError('Invalid Takeout TGZ') from exc
            require(len(members) <= MAX_MEMBERS, 'Takeout contains too many members')
            total = 0
            names = set()
            folded = set()
            selected = []
            for member in members:
                normalized, parts = _path(member.name)
                require(member.isfile(), 'Takeout contains a non-regular member')
                require(member.size <= MAX_FILE, 'Takeout member exceeds 16 MiB')
                total += member.size
                require(total <= MAX_EXPANDED, 'Takeout expanded size exceeds 512 MiB')
                key = unicodedata.normalize('NFC', normalized)
                folded_key = key.casefold()
                require(key not in names and folded_key not in folded,
                        'Takeout contains duplicate or case-colliding paths')
                names.add(key); folded.add(folded_key)
                if parts[:2] == ROOT:
                    require(len(parts) >= 4, 'Invalid NotebookLM Takeout layout')
                    require(not normalized.casefold().endswith(
                        ('.zip', '.tar', '.tgz', '.tar.gz', '.tar.bz2', '.tar.xz')),
                        'Nested archives are not supported in NotebookLM data')
                    selected.append((member, parts))
            require(selected, 'Takeout does not contain NotebookLM data')
            after_headers = os.fstat(handle.fileno())
            require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                     before.st_ctime_ns) ==
                    (after_headers.st_dev, after_headers.st_ino, after_headers.st_size,
                     after_headers.st_mtime_ns, after_headers.st_ctime_ns),
                    'Takeout changed during inspection')
            return bundle, handle, before, archive_hash.hexdigest(), selected, total
        except Exception:
            handle.close()
            raise

    @staticmethod
    def _read(bundle, member):
        file = bundle.extractfile(member)
        require(file is not None, 'Takeout member is unreadable')
        raw = file.read(MAX_FILE + 1)
        require(len(raw) == member.size and len(raw) <= MAX_FILE,
                'Takeout member size differs from its header')
        return raw

    def _notebooks(self):
        bundle, handle, before, archive_hash, selected, expanded = self._scan()
        try:
            grouped = {}
            for member, parts in selected:
                grouped.setdefault(parts[2], []).append((member, parts))
            result = []
            for folder, rows in sorted(grouped.items()):
                result.append(self._inspect_notebook(bundle, folder, rows, archive_hash))
            after = os.fstat(handle.fileno())
            require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                     before.st_ctime_ns) ==
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                     after.st_ctime_ns), 'Takeout changed during inspection')
            return {'format': PARSER_REVISION, 'filename': self.path.name,
                    'archive_size': before.st_size, 'archive_sha256': archive_hash,
                    'declared_expanded_size': expanded, 'notebooks': result}
        finally:
            bundle.close()
            handle.close()

    def _inspect_notebook(self, bundle, folder, rows, archive_hash):
        top = [(member, parts) for member, parts in rows if len(parts) == 4]
        require(len(top) == 1, 'NotebookLM notebook needs exactly one metadata record')
        top_member, top_parts = top[0]
        require(top_parts[3].endswith(' metadata.json'),
                'Unsupported NotebookLM notebook metadata filename')
        top_raw = self._read(bundle, top_member)
        metadata = _notebook_metadata(top_raw)
        categories = Counter()
        members = []
        by_category = {}
        for member, parts in rows:
            raw = top_raw if member is top_member else self._read(bundle, member)
            members.append(_member_record(member, raw))
            if len(parts) > 4:
                category = parts[3]
                categories[category] += 1
                by_category.setdefault(category, []).append((member, parts, raw))
        unknown = sorted(set(categories) - KNOWN_CATEGORIES)
        sources = self._sources(by_category.get('Sources', []))
        artifacts = self._artifacts(by_category.get('Artifacts', []))
        chats = self._chats(by_category.get('Chat History', []))
        discovered = self._discovered(by_category.get('Discovered Sources', []))
        unsupported = [{'category': category, 'count': categories[category]}
                       for category in unknown]
        warnings = []
        if 'Notes' not in categories:
            warnings.append('Takeout neobsahuje samostatnou kategorii poznámek.')
        if artifacts:
            warnings.append('Artifact source UUID nelze doloženě propojit s exportovanými source soubory.')
        if sources:
            warnings.append('Source obsah je Takeout HTML/JSON reprezentace, nikoli původní binární zdroj.')
        manifest = {'archive_sha256': archive_hash, 'notebook_path': '/'.join(ROOT + (folder,)),
                    'parser_revision': PARSER_REVISION,
                    'members': sorted(members, key=lambda item: item['path'])}
        return dict(folder=folder, **metadata, member_count=len(rows),
                    declared_bytes=sum(member.size for member, _parts in rows),
                    categories=dict(sorted(categories.items())), sources=sources,
                    artifacts=artifacts, chats=chats, discovered_sources=discovered,
                    unsupported=unsupported, warnings=warnings,
                    importable=not unsupported,
                    selection_digest=_sha256(_canonical(manifest)))

    @staticmethod
    def _pair(metadata_rows, content_rows, category):
        available = {parts[-1]: (member, parts, raw) for member, parts, raw in content_rows}
        pairs = []
        for member, parts, raw, parsed in metadata_rows:
            name = parts[-1]
            match = re.fullmatch(r'(.+) metadata(?:\((\d+)\))?\.json', name)
            candidates = []
            if match:
                base = match.group(1) + (f'({match.group(2)})' if match.group(2) else '')
                candidates = [key for key in available if key.startswith(base + '.')]
            else:
                stem = name[:-5] if name.endswith('.json') else name
                candidates = [key for key in available if key.startswith(stem + '.')]
            require(len(candidates) == 1, f'Cannot pair NotebookLM {category} metadata and content')
            content = available.pop(candidates[0])
            pairs.append((member, parts, raw, parsed, *content))
        require(not available, f'NotebookLM {category} contains orphan content')
        return pairs

    def _sources(self, rows):
        metadata_rows, content_rows = [], []
        for member, parts, raw in rows:
            parsed = None
            if parts[-1].endswith('.json') and len(raw) <= MAX_METADATA:
                try:
                    candidate = json.loads(raw.decode('utf-8'))
                    if (isinstance(candidate, dict) and set(candidate) == {'title', 'metadata'}
                            and isinstance(candidate.get('metadata'), dict)
                            and 'originalSourceContentType' in candidate['metadata']):
                        parsed = _source_metadata(raw)
                except (UnicodeError, json.JSONDecodeError, ValueError):
                    if ' metadata' in parts[-1]:
                        raise
            if parsed is None:
                content_rows.append((member, parts, raw))
            else:
                metadata_rows.append((member, parts, raw, parsed))
        pairs = self._pair(metadata_rows, content_rows, 'source')
        result = []
        for meta_member, _meta_parts, meta_raw, parsed, content_member, content_parts, content_raw in pairs:
            suffix = PurePosixPath(content_parts[-1]).suffix.lower()
            require(suffix in {'.html', '.json'}, 'Unsupported NotebookLM source representation')
            if suffix == '.html':
                require(b'\0' not in content_raw, 'NotebookLM HTML contains NUL bytes')
                content_raw.decode('utf-8')
            result.append(dict(title=parsed['title'], source_type=parsed['source_type'],
                               source_created_at=parsed['source_created_at'],
                               representation=suffix[1:], content_path=content_member.name,
                               content_size=content_member.size, content_sha256=_sha256(content_raw),
                               metadata_path=meta_member.name, metadata_sha256=_sha256(meta_raw)))
        return sorted(result, key=lambda item: (item['title'].casefold(), item['content_path']))

    def _artifacts(self, rows):
        metadata_rows, content_rows = [], []
        for member, parts, raw in rows:
            if parts[-1].endswith(' metadata.json'):
                metadata_rows.append((member, parts, raw, _artifact_metadata(raw)))
            else:
                content_rows.append((member, parts, raw))
        pairs = self._pair(metadata_rows, content_rows, 'artifact')
        result = []
        for meta_member, _meta_parts, meta_raw, parsed, content_member, content_parts, content_raw in pairs:
            require(PurePosixPath(content_parts[-1]).suffix.lower() == '.md'
                    and b'\0' not in content_raw, 'Unsupported NotebookLM artifact representation')
            content_raw.decode('utf-8')
            result.append(dict(**parsed, representation='markdown', content_path=content_member.name,
                               content_size=content_member.size, content_sha256=_sha256(content_raw),
                               metadata_path=meta_member.name, metadata_sha256=_sha256(meta_raw)))
        return sorted(result, key=lambda item: (item['title'].casefold(), item['content_path']))

    def _chats(self, rows):
        result = []
        for member, parts, raw in rows:
            require(PurePosixPath(parts[-1]).suffix.lower() == '.html'
                    and b'\0' not in raw, 'Unsupported NotebookLM chat representation')
            parser = _ChatShape()
            try:
                parser.feed(raw.decode('utf-8'))
            except UnicodeError as exc:
                raise ValueError('NotebookLM chat is not UTF-8') from exc
            require(not parser.scripts and parser.labels
                    and all(label in {'USER:', 'MODEL:'} for label in parser.labels),
                    'Unsupported NotebookLM chat structure')
            result.append({'path': member.name, 'size': member.size, 'sha256': _sha256(raw),
                           'user_messages': parser.labels.count('USER:'),
                           'model_messages': parser.labels.count('MODEL:')})
        return sorted(result, key=lambda item: item['path'])

    def _discovered(self, rows):
        result = []
        for member, parts, raw in rows:
            require(PurePosixPath(parts[-1]).suffix.lower() == '.json',
                    'Unsupported NotebookLM discovered-sources representation')
            value = _json(raw, 'NotebookLM discovered sources')
            require(set(value) == {'createdAt', 'discoverSourcesJob', 'lastUpdateTime'},
                    'Unsupported NotebookLM discovered-sources schema')
            _timestamp(value['createdAt'], 'discovered createdAt')
            _timestamp(value['lastUpdateTime'], 'discovered lastUpdateTime')
            require(isinstance(value['discoverSourcesJob'], dict),
                    'Invalid NotebookLM discovered-sources job')
            result.append({'path': member.name, 'size': member.size, 'sha256': _sha256(raw)})
        return sorted(result, key=lambda item: item['path'])

    def preview(self):
        """Return a content-free structural preview for every exported notebook."""
        return self._notebooks()

    def materialize(self, archive_sha256, selection_digest):
        """Revalidate one preview selection and return only its exact member bytes."""
        require(isinstance(archive_sha256, str) and re.fullmatch(r'[0-9a-f]{64}', archive_sha256)
                and isinstance(selection_digest, str) and re.fullmatch(r'[0-9a-f]{64}', selection_digest),
                'Invalid NotebookLM selection')
        bundle, handle, before, actual_hash, selected, _expanded = self._scan()
        try:
            require(actual_hash == archive_sha256, 'Takeout changed since preview')
            grouped = {}
            for member, parts in selected:
                grouped.setdefault(parts[2], []).append((member, parts))
            matches = []
            for folder, rows in sorted(grouped.items()):
                preview = self._inspect_notebook(bundle, folder, rows, actual_hash)
                if preview['selection_digest'] == selection_digest:
                    matches.append((preview, rows))
            require(len(matches) == 1, 'NotebookLM selection is missing or ambiguous')
            preview, rows = matches[0]
            require(preview['importable'], 'NotebookLM selection contains unsupported data')
            members = {member.name: self._read(bundle, member) for member, _parts in rows}
            after = os.fstat(handle.fileno())
            require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                     before.st_ctime_ns) ==
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                     after.st_ctime_ns), 'Takeout changed during materialization')
            return {'preview': preview, 'members': members, 'archive_size': before.st_size,
                    'archive_sha256': actual_hash}
        finally:
            bundle.close()
            handle.close()


def preview_takeout(path):
    return NotebookLMTakeout(path).preview()
