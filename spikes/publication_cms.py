# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicitly enabled same-node bridge for discovered publication modules."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile

from spikes.metadata import MAX_METADATA, parse_json, require, uuid
from spikes.module_manifest import read_module_manifest
from spikes.publication_cloudflare import PublicationDeployment


MAX_CONFIG = 256 * 1024
MAX_HTML = 1024 * 1024
MODULE_ID = 'cz.proofofidea.publication-experiment-registry'
REQUIRED_CAPABILITIES = {'publication-sites.preview', 'publication-sites.generate'}
REVIEWED_MANIFEST = (Path(__file__).resolve().parents[1] / 'modules'
                     / 'publication-experiment-registry.module.json')
REVIEWED_SOURCES = (Path(__file__).resolve().parents[1] / 'modules'
                    / 'publication-experiment-registry.source.json')
DEFAULT_MODULE_ROOTS = (Path(__file__).resolve().parents[1] / 'modules.local',)


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
                 module_roots=DEFAULT_MODULE_ROOTS,
                 python_executable=sys.executable, checkpoint=lambda stage: None,
                 deployment_transport=None):
        self.state_dir = Path(state_dir).absolute()
        self.reviewed_manifest = Path(reviewed_manifest).absolute()
        self.reviewed_sources = Path(reviewed_sources).absolute()
        self.module_roots = tuple(Path(path).absolute() for path in module_roots)
        self.python_executable = python_executable
        self.checkpoint = checkpoint
        self.deployment = PublicationDeployment(
            self.state_dir, self._deployment_release, deployment_transport)

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
        require(isinstance(value, dict)
                and set(value) == {'module_id', 'module_version', 'enabled'}
                and value['module_id'] == MODULE_ID
                and isinstance(value['module_version'], str)
                and value['enabled'] is True,
                'Invalid CMS module binding')
        require(bool(re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)',
                                  value['module_version'])),
                'Invalid CMS module version')
        return value

    def _discover(self):
        found = []
        for modules_root in self.module_roots:
            if not modules_root.exists():
                continue
            require(modules_root.is_dir() and modules_root.resolve() == modules_root,
                    'Module discovery root is unsafe')
            for candidate in sorted(modules_root.iterdir(), key=lambda path: path.name):
                if candidate.is_symlink() or not candidate.is_dir():
                    continue
                manifest_path = candidate / 'module.json'
                if not manifest_path.is_file() or manifest_path.is_symlink():
                    continue
                try:
                    manifest = read_module_manifest(manifest_path)
                except (OSError, ValueError):
                    continue
                found.append((candidate, manifest))
        ids = [manifest['module_id'] for _, manifest in found]
        require(len(ids) == len(set(ids)), 'Multiple copies of one module were discovered')
        return found

    def _verify(self, root, actual=None):
        root = Path(root)
        require(root.is_dir() and root.absolute() == root.resolve(),
                'CMS module root is unavailable or contains symlinks')
        reviewed = read_module_manifest(self.reviewed_manifest)
        actual = actual or read_module_manifest(root / 'module.json')
        require(actual['module_id'] == MODULE_ID, 'Unexpected CMS module identity')
        require(actual['schema_version'] == reviewed['schema_version']
                and actual['module_version'] == reviewed['module_version']
                and actual['api']['version'] == reviewed['api']['version'],
                'CMS module manifest version is incompatible')
        require(actual == reviewed, 'CMS module declaration differs from the reviewed manifest version')
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
        runtime_hashes = []
        for relative, expected in sorted(runtime_files.items()):
            require(isinstance(relative, str) and isinstance(expected, str)
                    and bool(re.fullmatch(r'[0-9a-f]{64}', expected)),
                    'Invalid reviewed CMS source hash')
            target = root / relative
            require(target.is_file() and target.resolve().is_relative_to(root),
                    'Reviewed CMS runtime file is unavailable')
            require(hashlib.sha256(target.read_bytes()).hexdigest() == expected,
                    'CMS module runtime differs from reviewed content')
            runtime_hashes.append(expected)
        runtime_revision = hashlib.sha256('\n'.join(runtime_hashes).encode()).hexdigest()
        return root, actual['module_version'], runtime_revision

    def _module_status(self):
        discovered = self._discover()
        modules = []
        selected = None
        for root, manifest in discovered:
            item = {'module_id': manifest['module_id'], 'display_name': manifest['display_name'],
                    'module_version': manifest['module_version'], 'present': True,
                    'enabled': False, 'compatible': False}
            if manifest['module_id'] == MODULE_ID:
                selected = (root, manifest)
                try:
                    self._verify(root, manifest)
                    item['compatible'] = True
                    item['message'] = 'Modul je přítomný a jeho verze je kompatibilní.'
                except (ValueError, OSError) as exc:
                    item['message'] = str(exc)
            else:
                item['message'] = 'Workspace pro tuto verzi modulu nemá reviewovaný adapter.'
            modules.append(item)
        return modules, selected

    def configure(self, request):
        require(isinstance(request, dict) and set(request) == {'module_id', 'enabled'}
                and request['module_id'] == MODULE_ID and type(request['enabled']) is bool,
                'Invalid CMS module binding request')
        with self._writer():
            with self._database() as db:
                pending = db.execute("SELECT 1 FROM operations WHERE state='prepared' LIMIT 1").fetchone()
            require(not pending, 'Finish CMS recovery before changing the module binding')
            if request['enabled']:
                modules, discovered = self._module_status()
                module = next((item for item in modules if item['module_id'] == MODULE_ID), None)
                require(discovered is not None and module is not None and module['compatible'],
                        'Compatible CMS module is not present')
                root, manifest = discovered
                self._verify(root, manifest)
                binding = {'module_id': MODULE_ID,
                           'module_version': manifest['module_version'], 'enabled': True}
                _atomic_write(self.binding_path, _canonical(binding))
            elif self.binding_path.exists():
                self.binding_path.unlink()
        return self.status()

    def _config(self, root):
        path = self.config_path if self.config_path.exists() else root / 'data' / 'sites.json'
        value = self._load_json(path)
        if isinstance(value, dict) and value.get('schema_version') == 1:
            value = json.loads(json.dumps(value))
            for site in value.get('sites', []):
                variant = site.pop('variant', None)
                site['presentation'] = ('proof-of-idea' if variant == 'proof-of-idea'
                                        else 'standard')
                site['sections'] = ({'proof-of-idea': ['profile'],
                                     'profile': ['profile', 'cv'],
                                     'timeline': ['timeline']}.get(variant, []))
                for field in ('contacts', 'links', 'cv', 'timeline'):
                    site.setdefault(field, [])
            value['schema_version'] = 2
        return value

    def _digest(self, config, module_version, runtime_revision):
        raw = _canonical(config)
        require(len(raw) <= MAX_CONFIG, 'CMS config exceeds size limit')
        identity = f'{MODULE_ID}\0{module_version}\0{runtime_revision}'.encode()
        return hashlib.sha256(identity + b'\0' + raw).hexdigest(), raw

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

    def _complete(self, db, operation_id, request, root, module_version, runtime_revision):
        digest, raw = self._digest(request['config'], module_version, runtime_revision)
        require(digest == request['preview_sha256'], 'CMS preview is stale or belongs to another module version')
        output = root / 'dist' / 'sites'
        self._run(root, raw, output)
        hostnames = sorted(item['hostname'] for item in request['config']['sites'])
        for child in output.iterdir():
            if child.name not in hostnames:
                require(child.is_dir() and not child.is_symlink(),
                        'Unexpected file in derived CMS output')
                shutil.rmtree(child)
        self.checkpoint('output-generated')
        _atomic_write(self.config_path, raw)
        self.checkpoint('config-saved')
        receipt = {'operation_id': operation_id, 'state': 'completed',
                   'preview_sha256': digest, 'module_version': module_version,
                   'generated_hostnames': hostnames, 'output': 'dist/sites'}
        db.execute("UPDATE operations SET state='completed',receipt_json=? "
                   "WHERE operation_id=? AND state='prepared'",
                   (json.dumps(receipt, ensure_ascii=False, sort_keys=True), operation_id))
        db.commit()
        return receipt

    def _recover(self, root, module_version, runtime_revision):
        with self._database() as db:
            rows = db.execute("SELECT operation_id,request_json FROM operations "
                              "WHERE state='prepared' ORDER BY rowid").fetchall()
            for operation_id, raw in rows:
                self._complete(db, operation_id, json.loads(raw), root,
                               module_version, runtime_revision)

    def _enabled_module(self):
        binding = self._load_binding()
        modules, discovered = self._module_status()
        require(discovered is not None, 'Enabled CMS module is no longer present')
        root, manifest = discovered
        require(binding['module_version'] == manifest['module_version'],
                'Enabled CMS module version changed; enable it again after review')
        root, module_version, runtime_revision = self._verify(root, manifest)
        next(item for item in modules if item['module_id'] == MODULE_ID)['enabled'] = True
        return binding, modules, root, module_version, runtime_revision

    def status(self):
        try:
            modules, _ = self._module_status()
            try:
                binding, modules, root, module_version, runtime_revision = self._enabled_module()
            except FileNotFoundError:
                cms_present = any(item['module_id'] == MODULE_ID for item in modules)
                return {'binding': None, 'modules': modules, 'compatible': False, 'config': None,
                        'message': ('Publikační CMS modul je dostupný, ale není povolený.' if cms_present else
                                    'Publikační CMS modul nebyl nalezen.')}
            with self._writer():
                self._recover(root, module_version, runtime_revision)
            return {'binding': binding, 'modules': modules, 'compatible': True,
                    'config': self._config(root),
                    'message': f'Publikační CMS modul {module_version} je povolený a připravený.'}
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
            return {'binding': locals().get('binding'), 'modules': locals().get('modules', []),
                    'compatible': False, 'config': None,
                    'message': str(exc)}

    def preview(self, request):
        require(isinstance(request, dict) and set(request) == {'config', 'hostname'},
                'Invalid CMS preview request')
        _, _, root, module_version, runtime_revision = self._enabled_module()
        digest, raw = self._digest(request['config'], module_version, runtime_revision)
        with tempfile.TemporaryDirectory(prefix='publication-preview-', dir=self._root()) as temp:
            output = Path(temp) / 'sites'
            self._run(root, raw, output)
            target = output / request['hostname'] / 'index.html'
            require(target.is_file() and target.parent.parent == output,
                    'Requested CMS hostname is not present in the preview')
            html = target.read_bytes()
            require(len(html) <= MAX_HTML, 'CMS preview exceeds size limit')
        return {'hostname': request['hostname'], 'html': html.decode('utf-8'),
                'preview_sha256': digest, 'module_version': module_version}

    def generate(self, request):
        required = {'operation_id', 'preview_sha256', 'approved', 'config'}
        require(isinstance(request, dict) and set(request) == required
                and request['approved'] is True, 'Invalid or unconfirmed CMS generation request')
        uuid(request['operation_id'])
        _, _, root, module_version, runtime_revision = self._enabled_module()
        digest, _ = self._digest(request['config'], module_version, runtime_revision)
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
            return self._complete(db, request['operation_id'], request, root,
                                  module_version, runtime_revision)

    def _deployment_release(self):
        _, _, root, module_version, runtime_revision = self._enabled_module()
        require(self.config_path.is_file(),
                'Generate the publication release before checking deployment')
        config = self._config(root)
        digest, _ = self._digest(config, module_version, runtime_revision)
        hostnames = sorted(item['hostname'] for item in config['sites'])
        output = root / 'dist' / 'sites'
        require(output.is_dir() and not output.is_symlink(),
                'Generated publication output is unavailable')
        return digest, hostnames, output

    def deployment_configure(self, request):
        return self.deployment.configure(request)

    def deployment_status(self):
        return self.deployment.status()

    def deployment_preview(self, request):
        return self.deployment.preview(request)

    def deployment_confirm(self, request):
        return self.deployment.deploy(request)
