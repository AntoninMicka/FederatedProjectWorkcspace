# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Pinned same-node bridge for previewing and generating publication sites."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile

from spikes.configuration import local_path
from spikes.metadata import MAX_METADATA, parse_json, require, uuid
from spikes.module_manifest import read_module_manifest


MAX_CONFIG = 256 * 1024
MAX_HTML = 1024 * 1024
MODULE_ID = 'cz.proofofidea.publication-experiment-registry'
REQUIRED_CAPABILITIES = {'publication-sites.preview', 'publication-sites.generate'}
REVIEWED_MANIFEST = (Path(__file__).resolve().parents[1] / 'modules'
                     / 'publication-experiment-registry.module.json')
REVIEWED_SOURCES = (Path(__file__).resolve().parents[1] / 'modules'
                    / 'publication-experiment-registry.source.json')


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')) + '\n').encode()


def _atomic_write(path, data):
    path = Path(path)
    temporary = path.parent / ('.' + path.name + '.tmp')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.close(fd); fd = -1
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary.exists():
            temporary.unlink()


class PublicationCms:
    """Node-local CMS state; project Git and credentials are never touched."""
    def __init__(self, state_dir, *, reviewed_manifest=REVIEWED_MANIFEST,
                 reviewed_sources=REVIEWED_SOURCES,
                 python_executable=sys.executable, checkpoint=lambda stage: None):
        self.state_dir = Path(state_dir).absolute()
        self.reviewed_manifest = Path(reviewed_manifest).absolute()
        self.reviewed_sources = Path(reviewed_sources).absolute()
        self.python_executable = python_executable
        self.checkpoint = checkpoint

    def _root(self):
        if not os.path.lexists(self.state_dir):
            self.state_dir.mkdir(mode=0o700)
        info = self.state_dir.lstat()
        require(self.state_dir.absolute() == self.state_dir.resolve()
                and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'CMS state directory requires owned mode 0700 without symlinks')
        return self.state_dir

    @property
    def binding_path(self):
        return self._root() / 'publication-cms-binding.json'

    @property
    def config_path(self):
        return self._root() / 'publication-sites.json'

    @property
    def journal_path(self):
        return self._root() / 'publication-cms-operations.sqlite'

    def _database(self):
        path = self.journal_path
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe CMS operation journal')
        db = sqlite3.connect(path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS operations ('
                   'operation_id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL, '
                   'request_json TEXT NOT NULL, state TEXT NOT NULL, receipt_json TEXT)')
        db.commit()
        return db

    @contextmanager
    def _writer(self):
        path = self._root() / 'publication-cms.lock'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe CMS writer lock')
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _load_json(self, path, maximum=MAX_CONFIG):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode), 'CMS input must be a regular file')
            raw = os.read(fd, maximum + 1)
        finally:
            os.close(fd)
        require(len(raw) <= maximum, 'CMS input exceeds size limit')
        return parse_json(raw, maximum)

    def _load_binding(self):
        value = self._load_json(self.binding_path, MAX_METADATA)
        require(isinstance(value, dict) and set(value) == {'module_root', 'source_revision'},
                'Invalid CMS module binding')
        root = local_path(value['module_root'])
        revision = value['source_revision']
        require(isinstance(revision, str) and bool(re.fullmatch(r'[0-9a-f]{40,64}', revision)),
                'CMS binding requires a full source revision')
        return {'module_root': str(root), 'source_revision': revision}

    def _git(self, root, *args):
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                                text=True, timeout=10, check=False)
        require(result.returncode == 0, 'CMS module Git revision is unavailable')
        return result.stdout.strip()

    def _verify(self, binding):
        root = Path(binding['module_root'])
        require(root.is_dir() and root.absolute() == root.resolve(),
                'CMS module root is unavailable or contains symlinks')
        revision = self._git(root, 'rev-parse', 'HEAD')
        require(revision == binding['source_revision'], 'CMS module revision changed')
        require(not self._git(root, 'status', '--porcelain=v1', '--untracked-files=normal'),
                'CMS module checkout has unreviewed changes')
        reviewed = read_module_manifest(self.reviewed_manifest)
        actual = read_module_manifest(root / 'module.json')
        require(reviewed == actual and actual['module_id'] == MODULE_ID,
                'CMS module manifest differs from the reviewed declaration')
        capabilities = {item['id'] for item in actual['capabilities']}
        require(REQUIRED_CAPABILITIES <= capabilities,
                'CMS module does not declare required capabilities')
        source_review = self._load_json(self.reviewed_sources, MAX_METADATA)
        require(isinstance(source_review, dict)
                and set(source_review) == {'schema_version', 'module_id', 'runtime_files'}
                and source_review['schema_version'] == 1
                and source_review['module_id'] == MODULE_ID
                and isinstance(source_review['runtime_files'], dict),
                'Invalid reviewed CMS source declaration')
        runtime_files = source_review['runtime_files']
        require(0 < len(runtime_files) <= 32, 'Invalid reviewed CMS runtime file list')
        actual_python = {str(path.relative_to(root)) for path in (root / 'src').rglob('*.py')}
        reviewed_python = {path for path in runtime_files if path.endswith('.py')}
        require(actual_python == reviewed_python,
                'CMS module Python runtime differs from the reviewed source set')
        for relative, expected in runtime_files.items():
            require(isinstance(relative, str) and isinstance(expected, str)
                    and bool(re.fullmatch(r'[0-9a-f]{64}', expected)),
                    'Invalid reviewed CMS source hash')
            target = root / relative
            require(target.is_file() and target.resolve().is_relative_to(root),
                    'Reviewed CMS runtime file is unavailable')
            require(hashlib.sha256(target.read_bytes()).hexdigest() == expected,
                    'CMS module runtime differs from reviewed content')
        return root, revision

    def configure(self, request):
        require(isinstance(request, dict) and set(request) == {'module_root', 'source_revision'},
                'Invalid CMS module binding request')
        root = local_path(request['module_root'])
        binding = {'module_root': str(root), 'source_revision': request['source_revision']}
        with self._writer():
            with self._database() as db:
                pending = db.execute("SELECT 1 FROM operations WHERE state='prepared' LIMIT 1").fetchone()
            require(not pending, 'Finish CMS recovery before changing the module binding')
            self._verify(binding)
            _atomic_write(self.binding_path, _canonical(binding))
        return self.status()

    def _config(self, root):
        path = self.config_path if self.config_path.exists() else root / 'data' / 'sites.json'
        return self._load_json(path)

    def _digest(self, config, revision):
        raw = _canonical(config)
        require(len(raw) <= MAX_CONFIG, 'CMS config exceeds size limit')
        return hashlib.sha256(revision.encode() + b'\0' + raw).hexdigest(), raw

    def _run(self, root, raw, output):
        with tempfile.TemporaryDirectory(prefix='publication-cms-', dir=self._root()) as temp:
            sites = Path(temp) / 'sites.json'
            sites.write_bytes(raw)
            env = {'PATH': os.environ.get('PATH', ''), 'LANG': 'C.UTF-8'}
            bootstrap = ('import runpy,sys;root=sys.argv.pop(1);sys.path.insert(0,root);'
                         "runpy.run_module('publication_registry.sitegen',run_name='__main__')")
            result = subprocess.run([
                self.python_executable, '-I', '-c', bootstrap, str(root / 'src'),
                '--registry', str(root / 'data' / 'registry.json'),
                '--sites', str(sites), '--template', str(root / 'templates' / 'site.html'),
                '--output', str(output),
            ], cwd=root, env=env, capture_output=True, timeout=30, check=False)
            require(result.returncode == 0, 'CMS module rejected the site configuration')

    def _complete(self, db, operation_id, request, root, revision):
        digest, raw = self._digest(request['config'], revision)
        require(digest == request['preview_sha256'], 'CMS preview is stale or belongs to another revision')
        output = root / 'dist' / 'sites'
        self._run(root, raw, output)
        self.checkpoint('output-generated')
        _atomic_write(self.config_path, raw)
        self.checkpoint('config-saved')
        hostnames = sorted(item['hostname'] for item in request['config']['sites'])
        receipt = {'operation_id': operation_id, 'state': 'completed',
                   'preview_sha256': digest, 'source_revision': revision,
                   'generated_hostnames': hostnames, 'output': 'dist/sites'}
        db.execute("UPDATE operations SET state='completed',receipt_json=? "
                   "WHERE operation_id=? AND state='prepared'",
                   (json.dumps(receipt, ensure_ascii=False, sort_keys=True), operation_id))
        db.commit()
        return receipt

    def _recover(self, root, revision):
        with self._database() as db:
            rows = db.execute("SELECT operation_id,request_json FROM operations "
                              "WHERE state='prepared' ORDER BY rowid").fetchall()
            for operation_id, raw in rows:
                self._complete(db, operation_id, json.loads(raw), root, revision)

    def status(self):
        try:
            binding = self._load_binding()
        except FileNotFoundError:
            return {'binding': None, 'compatible': False, 'config': None,
                    'message': 'Publikační CMS modul zatím není připojen.'}
        try:
            root, revision = self._verify(binding)
            with self._writer():
                self._recover(root, revision)
            return {'binding': binding, 'compatible': True, 'config': self._config(root),
                    'message': 'Připojený modul odpovídá připnuté revizi a reviewovanému runtime obsahu.'}
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
            return {'binding': binding, 'compatible': False, 'config': None,
                    'message': str(exc)}

    def preview(self, request):
        require(isinstance(request, dict) and set(request) == {'config', 'hostname'},
                'Invalid CMS preview request')
        binding = self._load_binding()
        root, revision = self._verify(binding)
        digest, raw = self._digest(request['config'], revision)
        with tempfile.TemporaryDirectory(prefix='publication-preview-', dir=self._root()) as temp:
            output = Path(temp) / 'sites'
            self._run(root, raw, output)
            target = output / request['hostname'] / 'index.html'
            require(target.is_file() and target.parent.parent == output,
                    'Requested CMS hostname is not present in the preview')
            html = target.read_bytes()
            require(len(html) <= MAX_HTML, 'CMS preview exceeds size limit')
        return {'hostname': request['hostname'], 'html': html.decode('utf-8'),
                'preview_sha256': digest, 'source_revision': revision}

    def generate(self, request):
        required = {'operation_id', 'preview_sha256', 'approved', 'config'}
        require(isinstance(request, dict) and set(request) == required
                and request['approved'] is True, 'Invalid or unconfirmed CMS generation request')
        uuid(request['operation_id'])
        binding = self._load_binding()
        root, revision = self._verify(binding)
        digest, _ = self._digest(request['config'], revision)
        require(digest == request['preview_sha256'], 'CMS preview is stale or changed')
        request_json = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        request_sha = hashlib.sha256(request_json.encode()).hexdigest()
        with self._writer(), self._database() as db:
            row = db.execute('SELECT request_sha256,state,receipt_json FROM operations WHERE operation_id=?',
                             (request['operation_id'],)).fetchone()
            if row:
                require(row[0] == request_sha, 'CMS operation ID belongs to another request')
                if row[1] == 'completed':
                    return json.loads(row[2])
            else:
                db.execute('INSERT INTO operations VALUES(?,?,?,?,NULL)',
                           (request['operation_id'], request_sha, request_json, 'prepared'))
                db.commit()
                self.checkpoint('prepared')
            return self._complete(db, request['operation_id'], request, root, revision)
