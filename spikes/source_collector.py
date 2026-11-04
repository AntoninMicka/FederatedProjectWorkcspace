# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""MON-02: approved static UTF-8 text captures, then separate Workspace import.

PublicSourceRuns owns fetch intent/staging. Workspace owns publication intent,
Git CAS and receipts. Neither step creates an Event or executes source text.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import time
import zlib
from urllib.parse import urlsplit

from spikes.artifacts import Artifacts
from spikes.configuration import committed_project, parse_node, read_config
from spikes.metadata import parse_json, require, timestamp, uuid, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.projects import directory
from spikes.public_source import (HTTPResult, PublicSourceBinding, PublicSourceError,
    PublicSourceRejected, PublicSourceRequest, PublicSourceRuns, StaticHTMLAdapter,
    normalize_url, url_origin)
from spikes.reporting import operation_uuid, pinned
from spikes.reporting_schema import (PRIVACY, SCHEMA, digest, encoded, fields, hex_id,
                                     records, ref, sequence, text, validate_record)

POLICY = 'fpw-reporting-collector-policy-v1'
PLAN = 'fpw-reporting-collection-plan-v1'
IMPORT = 'fpw-reporting-collection-import-v1'


def public_url(value):
    require(isinstance(value, str) and value == normalize_url(value)
            and not urlsplit(value).query and not any(c.isspace() for c in value),
            'Collector requires canonical public HTTPS URL without query/credentials')
    # Limit the first vertical to unambiguous ASCII paths. In particular, no
    # encoded path may bypass robots matching in the reused bounded parser.
    require(re.fullmatch(r'/[A-Za-z0-9/._~-]*', urlsplit(value).path),
            'Collector supports plain ASCII paths without percent escapes')
    path = urlsplit(value).path
    require('//' not in path and not {'.', '..'} & set(path.split('/')),
            'Collector URL must not contain ambiguous path segments')


def policy(value):
    fields(value, 'schema type binding urls source_role license access_reviewed')
    require(value['schema'] == POLICY and value['type'] == 'static-utf8-text-v1',
            'Unsupported collector policy')
    binding = PublicSourceBinding.parse(value['binding'])
    require(re.fullmatch(r'[A-Za-z_-]+/[0-9.]+', binding.user_agent), 'Expected simple identified crawler User-Agent')
    sequence(value['urls'], public_url, minimum=1)
    require(all(url_origin(u) in binding.origins for u in value['urls']), 'URL outside policy origins')
    require(value['source_role'] in {'primary', 'secondary', 'community', 'unknown'}, 'Invalid source role')
    fields(value['license'], 'identifier terms_ref capture_allowed retention_policy')
    text(value['license']['identifier'])
    ref(value['license']['terms_ref']); ref(value['license']['retention_policy'])
    require(value['license']['capture_allowed'] is True and value['access_reviewed'] is True,
            'Capture requires explicit license/terms/access review')
    return binding


class TextAdapter(StaticHTMLAdapter):
    """A deliberately narrower policy over the existing SSRF/TLS transport."""
    def __init__(self, runs, *, backoff, **kwargs):
        super().__init__(runs, **kwargs)
        self.backoff = backoff

    @staticmethod
    def _decode(result, request):
        decoded = StaticHTMLAdapter._decode(result, request)
        if result.headers.get('content-encoding', '').strip().lower() == 'gzip':
            inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
            inflater.decompress(result.body, request['max_decoded_bytes'] + 1)
            require(inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail,
                    'Collector requires one complete gzip member without trailing bytes')
        return decoded

    def _fetch(self, binding, request, phase, deadline):
        try:
            return self._checked_fetch(binding, request, phase, deadline)
        except ValueError as exc:
            raise PublicSourceRejected(str(exc), code='collector-response-rejected') from exc

    def _checked_fetch(self, binding, request, phase, deadline):
        result = super()._fetch(binding, request, phase, deadline)
        require(self.monotonic() < deadline, 'Collector fetch deadline expired')
        headers = self._headers(result.headers)
        expected = url_origin(request['candidate_url']) + '/robots.txt' if phase == 'robots' else request['candidate_url']
        require(result.url == expected, 'Collector transport changed approved URL')
        if result.status in {429, 503}:
            self.backoff(url_origin(expected), headers.get('retry-after'))
            raise PublicSourceError('Source is rate limited or unavailable', code='overloaded')
        if phase == 'robots' and result.status != 200:
            raise PublicSourceRejected('Collector requires a successful robots preflight', code='robots-unavailable')
        if result.status == 200:
            require(len(result.body) <= request['max_wire_bytes'], 'Collector response exceeds wire limit')
            if 'content-length' in headers:
                require(headers['content-length'].isdigit() and int(headers['content-length']) == len(result.body),
                        'Incomplete collector response')
            mime = headers.get('content-type', '').split(';', 1)[0].strip().lower()
            require(mime == 'text/plain', 'Collector accepts text/plain only')
            require('no-store' not in headers.get('cache-control', '').lower(), 'Source prohibits storage')
            decoded = self._decode(HTTPResult(result.status, headers, result.body, result.url), request)
            # Validate UTF-8/charset/NUL before any staging can become succeeded.
            from spikes.public_source import project_text
            project_text(decoded, headers['content-type'], request['max_text_chars'])
            require(b'\0' not in decoded, 'Collector text contains NUL')
            if phase == 'robots':
                # Refuse rule dialects this conservative vertical cannot compare
                # safely; generic reader behavior is deliberately unchanged.
                require(all(ord(c) < 128 for c in decoded.decode('utf-8')) and b'%' not in decoded,
                        'Collector robots rules require supported ASCII paths')
                for line in decoded.decode('utf-8').splitlines():
                    clean = line.split('#', 1)[0]
                    key, separator, value = clean.partition(':')
                    if separator and key.strip().lower() in {'allow', 'disallow'}:
                        pattern = value.strip()
                        require(not pattern or re.fullmatch(r'/[A-Za-z0-9/._~-]*', pattern),
                                'Collector robots requires literal prefix rules without wildcards/anchors')
                return HTTPResult(result.status, headers, decoded, result.url)
        return result


class SourceCollector:
    def __init__(self, node_path, *, transport=None, resolver=None, clock=time.time):
        self.node = Path(node_path).absolute()
        self.artifacts = Artifacts(self.node)
        self.transport, self.resolver, self.clock = transport, resolver, clock
        self.state = self.node.parent / ('.' + self.node.name + '.source-collector')

    def now(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat().replace('+00:00', 'Z')

    @contextmanager
    def locked(self, *, publication=False):
        require(self.node == self.node.resolve(), 'Collector node path must not use symlinks')
        existed = os.path.lexists(self.state)
        self.state.mkdir(mode=0o700, exist_ok=True)
        directory(self.state, private=True)
        parent_fd = os.open(self.state.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        fd = os.open(self.state / 'collector.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a+b') as handle:
            info = os.fstat(handle.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077, 'Unsafe collector lock')
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            runs = PublicSourceRuns(self.state)
            journal_present = runs.path.exists() and runs.path.stat().st_size > 0
            if (existed or publication) and not journal_present:
                require(publication, 'Collector fetch journal is missing; manual reconciliation required')
                # Workspace receipt/recovery must survive fetch-authority loss.
                # Do not silently create an empty replacement fetch journal.
                yield runs
                return
            with runs.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS collector_backoff(origin TEXT PRIMARY KEY, until REAL NOT NULL)')
                db.commit()
            yield runs

    def actor(self):
        node = parse_node(read_config(self.node), location=self.node)
        return node['id'], ProjectCreation(self.node).author_id()

    @staticmethod
    def resolve(workspace, project_id, reference, current_files, entities):
        ref(reference)
        require(reference['project_id'] == project_id, 'Collector policy requires local authorized references')
        require(workspace.git.run('rev-parse', '--verify', reference['commit_id'] + '^{commit}').stdout.strip()
                == reference['commit_id'], 'Collector reference must pin a commit')
        committed_project(workspace.git, reference['commit_id'], project_id, check_worktree=False)
        files = workspace.git.snapshot(reference['commit_id'])
        metas = validate_snapshot(files)
        require(reference['artifact_id'] in metas and
                pinned(project_id, reference['commit_id'], reference['artifact_id'], files, metas) == reference,
                'Collector pinned reference differs')
        # A changed/removed policy is a revoked approval, even though its old
        # bytes remain readable in Git. No silent pin update is permitted.
        require(reference['path'] in current_files and digest(current_files[reference['path']]) == reference['sha256'],
                'Collector input was changed, deleted or revoked')
        return files[reference['path']], entities[reference['artifact_id']]

    def context(self, ws, project_id, task_ref, files, entities):
        raw, task_meta = self.resolve(ws, project_id, task_ref, files, entities)
        task = validate_record(parse_json(raw, maximum=1024 * 1024))
        require(task['type'] == 'ReportingTask', 'Collector requires ReportingTask')
        all_records = records(files, entities)
        require(all_records.get(task_ref['artifact_id']) == task,
                'Collector requires a registered reporting task, not captured source instructions')
        require(not any(any(p['artifact_id'] == task['revision_id'] for p in r['previous'])
                        for r in all_records.values()), 'Task revision is superseded')
        policy_ref = task['value']['source_policy']
        raw, policy_meta = self.resolve(ws, project_id, policy_ref, files, entities)
        require(policy_meta['kind'] == 'document' and policy_meta['provenance'] == 'user',
                'Collector policy must be an explicitly authored local document')
        rules = parse_json(raw); binding = policy(rules)
        privacy = max([task_meta['privacy'], policy_meta['privacy']], key=PRIVACY.get)
        for reference in (rules['license']['terms_ref'], rules['license']['retention_policy']):
            _, meta = self.resolve(ws, project_id, reference, files, entities)
            privacy = max(privacy, meta['privacy'], key=PRIVACY.get)
        require(privacy != 'local-only', 'Local-only task/policy cannot authorize external collection')
        return task, policy_ref, rules, binding, privacy

    def preview(self, project_id, task_ref, url, title, run_id, *, created_at=None):
        uuid(project_id); uuid(run_id); public_url(url); text(title)
        require(len(title) <= 200 and not any(c in title for c in '\r\n'), 'Invalid capture title')
        node, author = self.actor()
        ws = self.artifacts.workspace(project_id); ws.recover()
        with ws.journal.lock(), ws.journal.connect() as db:
            ws._writable()
            head = ws.git.head(); committed_project(ws.git, head, project_id)
            files = ws.git.snapshot(head); entities = validate_snapshot(files)
            ws._read_locked(db, expected_head=head)
            task, policy_ref, rules, binding, privacy = self.context(ws, project_id, task_ref, files, entities)
            require(url in rules['urls'], 'URL is not explicitly allowlisted')
            when = created_at or self.now(); timestamp(when)
            return dict(schema=PLAN, project_id=project_id, base_head=head, task_ref=task_ref,
                        policy_ref=policy_ref, run_id=run_id, url=url, title=title, privacy=privacy,
                        node_id=node, user_id=author, created_at=when, binding=binding.serialize(),
                        license=rules['license'], source_role=rules['source_role'],
                        effects=['GET ' + url_origin(url) + '/robots.txt', 'GET ' + url])

    @staticmethod
    def approved(value, sha256, confirm):
        require(confirm is True, 'Explicit --confirm is required')
        require(digest(encoded(value)) == sha256, 'Preview digest changed')

    def fetch(self, plan, sha256, *, confirm=False, checkpoint=lambda stage: None):
        self.approved(plan, sha256, confirm)
        fields(plan, 'schema project_id base_head task_ref policy_ref run_id url title privacy node_id user_id created_at binding license source_role effects')
        require(plan['schema'] == PLAN, 'Unsupported collector plan')
        with self.locked() as runs:
            row = runs.get(plan['run_id'])
            if row is None or row['state'] == 'prepared':
                expected = self.preview(plan['project_id'], plan['task_ref'], plan['url'], plan['title'],
                                        plan['run_id'], created_at=plan['created_at'])
                require(expected == plan, 'Task/policy/project changed; review a new preview')
            else:
                require(row['preview'] == plan and row['node_id'] == self.actor()[0]
                        and row['user_id'] == self.actor()[1], 'Collector run belongs to another request/actor')
            binding = PublicSourceBinding.parse(plan['binding'])
            runs.recover()
            # Replays of succeeded runs use only verified durable staging. A
            # new operation must obey durable per-origin Retry-After backoff.
            if row is None or row['state'] == 'prepared':
                with runs.connect() as db:
                    blocked = db.execute('SELECT until FROM collector_backoff WHERE origin=?', (url_origin(plan['url']),)).fetchone()
                require(blocked is None or blocked[0] <= self.clock(), 'Collector origin is in Retry-After backoff')
            request = dict(schema_version=1, run_id=plan['run_id'], task_id=self._task_entity(plan),
                user_id=plan['user_id'], project_id=plan['project_id'], privacy=plan['privacy'],
                expected_head=plan['base_head'], binding_id=binding.binding_id, binding_revision=binding.revision,
                adapter=binding.adapter_id, candidate_source_id=plan['run_id'], candidate_url=plan['url'],
                purpose='Explicit reporting source capture; remote content is untrusted data.',
                accept=['text/html', 'text/plain'], created_at=plan['created_at'],
                **{key: getattr(binding, key) for key in ('max_wire_bytes', 'max_decoded_bytes', 'max_text_chars',
                                                        'max_compression_ratio', 'timeout_seconds')})
            row = runs.prepare(request=PublicSourceRequest.parse(request), preview=plan, binding=binding, node_id=plan['node_id'])
            checkpoint('fetch-prepared')
            def backoff(origin, retry_after):
                seconds = 60
                if retry_after:
                    try:
                        seconds = max(seconds, int(retry_after)) if retry_after.isdecimal() else max(
                            seconds, parsedate_to_datetime(retry_after).timestamp() - self.clock())
                    except (TypeError, ValueError, OverflowError):
                        seconds = 86400  # Malformed server delay never becomes an immediate retry.
                with runs.connect() as db:
                    try:
                        until = self.clock() + seconds
                    except OverflowError:
                        until = float('inf')  # Never shorten an unrepresentable server embargo.
                    db.execute('INSERT INTO collector_backoff VALUES (?,?) ON CONFLICT(origin) DO UPDATE SET until=MAX(until,excluded.until)',
                               (origin, until)); db.commit()
            def transport(*args):
                checkpoint('fetch-dispatching')
                return self.transport(*args)
            adapter = TextAdapter(runs, backoff=backoff,
                transport=transport if self.transport else None, resolver=self.resolver, now=self.now)
            result = adapter.dispatch(plan['run_id'], binding, preview_sha256=sha256)
            checkpoint('fetch-succeeded')
            return result

    def _task_entity(self, plan):
        ws = self.artifacts.workspace(plan['project_id'])
        files = ws.git.snapshot(plan['task_ref']['commit_id'])
        return validate_record(parse_json(files[plan['task_ref']['path']], maximum=1024 * 1024))['entity_id']

    def status(self, run_id):
        with self.locked() as runs:
            runs.recover()
            row = runs.get(run_id)
            require(row is not None and row['user_id'] == self.actor()[1] and row['node_id'] == self.actor()[0],
                    'Collector run unavailable')
            return dict(run_id=run_id, state=row['state'], error_code=row['error_code'], result=row['result'])

    def candidate(self, ws, runs, row, operation_id, base_head, when):
        plan = row['preview']; project_id = plan['project_id']
        require(row['state'] == 'succeeded', 'Only complete captures may be imported')
        require(ws.git.head() == base_head, 'Project changed; review a fresh import preview')
        committed_project(ws.git, base_head, project_id)
        files = ws.git.snapshot(base_head); entities = validate_snapshot(files)
        task, policy_ref, rules, binding, privacy = self.context(ws, project_id, plan['task_ref'], files, entities)
        require(policy_ref == plan['policy_ref'] and rules['license'] == plan['license']
                and privacy == plan['privacy'] and binding.serialize() == plan['binding'], 'Capture policy changed')
        raw, _ = runs.read_staging(plan['run_id'])
        result = row['result']; timestamp(when)
        matches = [r for r in records(files, entities).values() if r['type'] == 'Source'
                   and r['value']['task_ref'] == plan['task_ref'] and r['value']['locator'] == plan['url']]
        parent_ids = {p['artifact_id'] for r in matches for p in r['previous']}
        tips = [r for r in matches if r['revision_id'] not in parent_ids]
        require(len(tips) <= 1, 'Conflicting source identities for URL require human reconciliation')
        previous = [pinned(project_id, base_head, tips[0]['revision_id'], files, entities)] if tips else []
        raw_id = operation_uuid(operation_id, 'raw:0'); record_id = operation_uuid(operation_id, 'record:0')
        filename = 'original.txt.gz' if result['headers'].get('content-encoding', '').lower() == 'gzip' else 'original.txt'
        raw_path = f'artifacts/{raw_id}/' + filename
        metadata = dict(schema_version=2, id=raw_id, title=plan['title'], kind='source', created_at=when,
            author_id=plan['user_id'], privacy=privacy, provenance='external', file=filename,
            source_url=plan['url'], tags=['untrusted-external', 'reporting-collector'],
            description='Untrusted captured bytes; no instructions, events or approval inferred.',
            **{'import': dict(imported_at=when, imported_by=plan['user_id'], content_sha256=digest(raw),
                importer=dict(name='reporting-source-collector', version='1'),
                source_mime_type=result['headers']['content-type'])})
        if result['external_revision'] is not None:
            metadata['import']['source_revision'] = result['external_revision']
        record = dict(schema=SCHEMA, type='Source', entity_id=tips[0]['entity_id'] if tips else operation_uuid(operation_id, 'entity:0'),
            revision_id=record_id, previous=previous, recorded_at=when, recorded_by=plan['user_id'], privacy=privacy,
            provenance=dict(method='import', inputs=[plan['task_ref'], policy_ref], run_refs=[dict(run_id=plan['run_id'],
                manifest_sha256=row['preview_sha256'], result_sha256=digest(encoded(result)))]),
            value=dict(schema='fpw-reporting-source-v1', task_ref=plan['task_ref'], title=plan['title'], locator=plan['url'],
                declared_author=None, source_role=rules['source_role'],
                publication_date=dict(precision='unknown', start=None, end=None, basis=[]),
                imported_at=tips[0]['value']['imported_at'] if tips else when, retrieved_at=result['fetched_at'],
                capture_state='captured', raw_ref=dict(artifact_id=raw_id, path=raw_path, sha256=digest(raw), at='same-commit'),
                availability='available', license=rules['license']))
        validate_record(record)
        changes = {raw_path: raw, f'artifacts/{raw_id}/metadata.json': encoded(metadata),
            f'artifacts/{record_id}/record.json': encoded(record),
            f'artifacts/{record_id}/metadata.json': encoded(dict(schema_version=1, id=record_id,
                title=plan['title'], kind='document', created_at=when, author_id=plan['user_id'], privacy=privacy,
                provenance='user', file='record.json', tags=[SCHEMA]))}
        require(not any(p in files for p in changes), 'Collector artifact ID already exists')
        preview = dict(schema=IMPORT, project_id=project_id, base_head=base_head, run_id=plan['run_id'],
            operation_id=operation_id, recorded_at=when, user_id=plan['user_id'], node_id=plan['node_id'],
            result_sha256=digest(encoded(result)), record=record, raw_metadata=metadata,
            files={p: digest(b) for p, b in changes.items()})
        return preview, changes

    def preview_import(self, run_id, operation_id):
        uuid(run_id); uuid(operation_id)
        with self.locked() as runs:
            runs.recover(); row = runs.get(run_id)
            require(row is not None and row['user_id'] == self.actor()[1] and row['node_id'] == self.actor()[0], 'Collector run unavailable')
            ws = self.artifacts.workspace(row['project_id']); ws.recover()
            with ws.journal.lock(), ws.journal.connect() as db:
                ws._writable(); ws._read_locked(db)
                return self.candidate(ws, runs, row, operation_id, ws.git.head(), self.now())[0]

    def publish(self, preview, sha256, *, confirm=False, checkpoint=lambda stage: None):
        self.approved(preview, sha256, confirm)
        fields(preview, 'schema project_id base_head run_id operation_id recorded_at user_id node_id result_sha256 record raw_metadata files')
        require(preview['schema'] == IMPORT, 'Unsupported import preview')
        uuid(preview['operation_id']); uuid(preview['project_id']); hex_id(preview['base_head'], True)
        node, author = self.actor()
        require(preview['user_id'] == author and preview['node_id'] == node, 'Import belongs to another actor')
        with self.locked(publication=True) as runs:
            ws = self.artifacts.workspace(preview['project_id'])
            def prepare(workspace):
                require(runs.path.exists() and runs.path.stat().st_size > 0,
                        'Collector fetch journal is missing; manual reconciliation required')
                row = runs.get(preview['run_id'])
                require(row is not None and row['user_id'] == author and row['node_id'] == node, 'Collector run unavailable')
                expected, changes = self.candidate(workspace, runs, row, preview['operation_id'],
                                                    preview['base_head'], preview['recorded_at'])
                require(expected == preview, 'Capture/import candidate changed')
                return changes, 'Local workspace author', author + '@local.invalid', 'Import approved reporting source capture'
            # Receipt replay needs neither network nor surviving staging. Pending
            # recovery uses Workspace's already journaled bytes, never re-fetch.
            return ws.transact(preview['operation_id'], dict(preview, action='reporting-source-import-v1'), prepare,
                               expected_head=preview['base_head'], checkpoint=checkpoint)


def main():
    parser = argparse.ArgumentParser(description='Bounded reporting source collector; local operator only')
    parser.add_argument('--node', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('preview'); p.add_argument('project_id'); p.add_argument('task_ref', type=Path)
    p.add_argument('url'); p.add_argument('title'); p.add_argument('--run-id', required=True)
    for name in ('fetch', 'publish'):
        p = sub.add_parser(name); p.add_argument('preview', type=Path); p.add_argument('--sha256', required=True)
        p.add_argument('--confirm', action='store_true')
    p = sub.add_parser('preview-import'); p.add_argument('run_id'); p.add_argument('--operation-id', required=True)
    p = sub.add_parser('status'); p.add_argument('run_id')
    args = parser.parse_args(); service = SourceCollector(args.node)
    def read(path):
        with path.open('rb') as f:
            value = parse_json(f.read(2 * 1024 * 1024 + 1), maximum=2 * 1024 * 1024)
        if isinstance(value, dict) and value.keys() == {'value', 'sha256'}:
            require(digest(encoded(value['value'])) == value['sha256'], 'Saved CLI envelope changed')
            return value['value']
        return value
    if args.command == 'preview':
        result = service.preview(args.project_id, read(args.task_ref), args.url, args.title, args.run_id)
    elif args.command == 'fetch':
        result = service.fetch(read(args.preview), args.sha256, confirm=args.confirm)
    elif args.command == 'publish':
        result = service.publish(read(args.preview), args.sha256, confirm=args.confirm)
    elif args.command == 'preview-import':
        result = service.preview_import(args.run_id, args.operation_id)
    else:
        result = service.status(args.run_id)
    print(json.dumps(dict(value=result, sha256=digest(encoded(result))), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
