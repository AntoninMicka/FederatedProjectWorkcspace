# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Provider-neutral response-language policy stored outside project Git."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from spikes.metadata import require, uuid


DEFAULT_LANGUAGE = 'cs-CZ'
LANGUAGE_SOURCES = {'node', 'project', 'thread', 'run'}
_BCP47 = re.compile(r'^[A-Za-z]{2,3}(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?'
                    r'(?:-[A-Za-z0-9]{5,8}|-[0-9][A-Za-z0-9]{3})*$')


def language_tag(value):
    require(isinstance(value, str) and bool(_BCP47.fullmatch(value)),
            'Response language must be a supported BCP 47 form')
    parts = value.split('-')
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            normalized.append(part.upper())
        else:
            normalized.append(part.lower())
    result = '-'.join(normalized)
    require(len(result) <= 63, 'Response language tag is too long')
    return result


def response_language(tag, source):
    require(source in LANGUAGE_SOURCES, 'Invalid response language source')
    return {'tag': language_tag(tag), 'source': source, 'compliance': 'unverified'}


class ResponseLanguagePolicy:
    """Atomic node/project defaults; thread/run overrides are supplied by chat state."""
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Language policy directory requires owned mode 0700')
        self.path = self.root / 'response-language-policy.json'

    @staticmethod
    def _validate(value):
        require(isinstance(value, dict)
                and set(value) == {'schema_version', 'node_default', 'projects'}
                and value['schema_version'] == 1 and isinstance(value['projects'], dict),
                'Invalid response language policy')
        value = {'schema_version': 1, 'node_default': language_tag(value['node_default']),
                 'projects': dict(value['projects'])}
        for project_id, tag in value['projects'].items():
            uuid(project_id)
            value['projects'][project_id] = language_tag(tag)
        return value

    def load(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return {'schema_version': 1, 'node_default': DEFAULT_LANGUAGE, 'projects': {}}
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe response language policy file')
            raw = os.read(fd, 64 * 1024 + 1)
        finally:
            os.close(fd)
        require(len(raw) <= 64 * 1024, 'Response language policy exceeds 64 KiB')
        try:
            return self._validate(json.loads(raw))
        except (UnicodeError, ValueError) as exc:
            raise ValueError('Invalid response language policy JSON') from exc

    def save(self, value):
        value = self._validate(value)
        raw = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':')) + '\n').encode()
        temporary = self.root / ('.response-language-' + hashlib.sha256(
            raw + os.urandom(32)).hexdigest() + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.close(fd); fd = -1
            os.replace(temporary, self.path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if fd >= 0:
                os.close(fd)
            if temporary.exists():
                temporary.unlink()

    def configure(self, *, scope, tag, project_id=None):
        tag = language_tag(tag)
        require(scope in {'node', 'project'}, 'Invalid durable language scope')
        value = self.load()
        if scope == 'node':
            require(project_id is None, 'Node language cannot name a project')
            value['node_default'] = tag
        else:
            uuid(project_id)
            value['projects'][project_id] = tag
        self.save(value)
        return self.load()

    def resolve(self, *, project_id, thread_tag=None, run_tag=None):
        uuid(project_id)
        if run_tag is not None:
            return response_language(run_tag, 'run')
        if thread_tag is not None:
            return response_language(thread_tag, 'thread')
        value = self.load()
        if project_id in value['projects']:
            return response_language(value['projects'][project_id], 'project')
        return response_language(value['node_default'], 'node')
