# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only registered-project diagnostics for the Check & Repair workflow."""
from contextlib import closing, contextmanager
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import time

from spikes.configuration import parse_node, parse_project, read_config
from spikes.journal import Journal, snapshot
from spikes.metadata import MAX_METADATA, require, safe_path, uuid, validate_snapshot
from spikes.storage import Git, Index, projection
from spikes.workspace import Workspace


SCHEMA_VERSION = 1
STATUS_PRIORITY = {'healthy': 0, 'repairable': 1, 'manual': 2, 'retry': 3}
GIT_ENV = {'GIT_OPTIONAL_LOCKS': '0'}
GIT_OPERATION_MARKERS = ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD',
                         'rebase-merge', 'rebase-apply', 'sequencer',
                         'BISECT_START')
JOURNAL_COLUMNS = {
    'owner': ['root'],
    'pending': ['path', 'before', 'after'],
    'operations': ['id', 'record', 'done'],
}
INDEX_COLUMNS = {
    'state': ['singleton', 'commit_id'],
    'entities': list(Index.FIELDS) + ['path', 'metadata'],
    'imports': ['entity_id', *Index.IMPORT_FIELDS, 'importer_name', 'importer_version'],
    'tags': ['entity_id', 'ordinal', 'tag'],
    'relations': ['source_id', 'ordinal', 'type', 'target_id'],
}
INDEX_V1_COLUMNS = {
    'state': ['singleton', 'commit_id'],
    'entities': ['id', 'title', 'kind', 'privacy', 'provenance', 'author_id',
                 'created_at', 'description', 'source_url', 'status', 'body',
                 'path', 'metadata'],
    'tags': ['entity_id', 'ordinal', 'tag'],
    'relations': ['source_id', 'ordinal', 'type', 'target_id'],
}
INDEX_V2_COLUMNS = {
    **INDEX_V1_COLUMNS,
    'imports': ['entity_id', 'imported_at', 'imported_by', 'content_sha256',
                'source_author', 'source_created_at', 'source_revision',
                'importer_name', 'importer_version'],
}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _file_digest(path):
    result = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        while block := handle.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def _stat(path, *, content=False):
    """Return token-only evidence without following a final symlink."""
    try:
        info = path.lstat()
        value = [info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                 info.st_nlink, info.st_size, info.st_mtime_ns]
        if content and stat.S_ISREG(info.st_mode):
            value.append(_file_digest(path))
        return value
    except (OSError, ValueError) as exc:
        return ['error', type(exc).__name__, getattr(exc, 'errno', None)]


@contextmanager
def _readonly_database(path):
    """Open existing SQLite bytes without creating a database, WAL or SHM."""
    uri = path.resolve(strict=True).as_uri() + '?mode=ro&immutable=1'
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        yield db


def _columns(db, table):
    return [row[1] for row in db.execute('PRAGMA table_info(' + table + ')')]


class ProjectDiagnostics:
    """Inspect one registration without initializing or repairing any layer."""

    def __init__(self, node_path, *, timeout=30):
        self.node_path = Path(node_path).absolute()
        self.timeout = timeout

    @staticmethod
    def _finding(code, component, message, *, action='manual', severity='error'):
        return {'code': code, 'component': component, 'severity': severity,
                'message': message, 'action': action}

    def _git(self, root, deadline):
        return Git(root, deadline=deadline)

    @staticmethod
    def _run(git, *args, **kwargs):
        extra = dict(GIT_ENV)
        extra.update(kwargs.pop('env_extra', {}) or {})
        return git.run(*args, env_extra=extra, **kwargs)

    def _fingerprint(self, binding=None):
        evidence = {'node': _stat(self.node_path, content=True)}
        if not binding:
            return evidence
        root, state = Path(binding['root']), Path(binding['state_dir'])
        evidence['binding'] = dict(binding)
        evidence['root'] = _stat(root)
        evidence['git'] = _stat(root / '.git')
        evidence['project'] = _stat(root / 'project.json', content=True)
        evidence['state'] = _stat(state)
        try:
            evidence['state_entries'] = {
                item.name: _stat(item, content=stat.S_ISREG(item.lstat().st_mode))
                for item in sorted(state.iterdir(), key=lambda value: value.name)
            }
        except OSError as exc:
            evidence['state_entries'] = ['error', type(exc).__name__, exc.errno]
        try:
            root_info = root.lstat()
            git_info = (root / '.git').lstat()
            if stat.S_ISDIR(root_info.st_mode) and stat.S_ISDIR(git_info.st_mode):
                git = Git(root, deadline=time.monotonic() + self.timeout)
                outputs = []
                for args in (('rev-parse', 'HEAD'), ('symbolic-ref', '-q', 'HEAD'),
                             ('status', '--porcelain=v1', '--untracked-files=all')):
                    result = self._run(git, *args, check=False)
                    outputs.append([result.returncode, result.stdout, result.stderr])
                evidence['git_state'] = outputs
        except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
            evidence['git_state'] = ['error', type(exc).__name__]
        return evidence

    @staticmethod
    def _safe_directory(path, *, private=False):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            return False
        if path.absolute() != path.resolve(strict=True):
            return False
        mode = stat.S_IMODE(info.st_mode)
        return mode == 0o700 if private else not mode & 0o022

    @staticmethod
    def _safe_state_file(path):
        info = path.lstat()
        return (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600)

    @staticmethod
    def _same_filesystem(root, state):
        return root.stat().st_dev == state.stat().st_dev

    @staticmethod
    def _writer_busy(path):
        if not os.path.lexists(path):
            return False
        if not ProjectDiagnostics._safe_state_file(path):
            raise ValueError('unsafe writer lock')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            finally:
                try:
                    fcntl.flock(handle, fcntl.LOCK_UN)
                except OSError:
                    pass
        return False

    def _inspect_journal(self, root, state, add):
        path = state / 'journal.sqlite'
        if not os.path.lexists(path):
            add('journal-missing', 'journal',
                'Lokální journal projektu chybí; automaticky se nevytvořil.')
            return False, None
        if not self._safe_state_file(path):
            add('journal-invalid', 'journal',
                'Journal nemá bezpečný typ, vlastníka nebo práva.')
            return False, None
        try:
            with _readonly_database(path) as db:
                if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
                    raise ValueError('integrity')
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if tables != set(JOURNAL_COLUMNS) or any(
                        _columns(db, table) != columns
                        for table, columns in JOURNAL_COLUMNS.items()):
                    raise ValueError('schema')
                owners = db.execute('SELECT root FROM owner').fetchall()
                if owners != [(str(root),)]:
                    add('journal-owner-mismatch', 'journal',
                        'Journal je svázaný s jiným kořenem projektu.')
                    return False, None
                pending = db.execute(
                    'SELECT path,before,after FROM pending ORDER BY path').fetchall()
                active = db.execute(
                    'SELECT id,record FROM operations WHERE done=0 ORDER BY id').fetchall()
                if len(active) > 1:
                    raise ValueError('multiple active operations')
                for relative, before, after in pending:
                    parts = safe_path(relative)
                    if len(parts) != 3 or parts[0] not in {'artifacts', 'registries'}:
                        raise ValueError('pending path')
                    if before is not None and not isinstance(before, bytes):
                        raise ValueError('pending before')
                    if after is not None and not isinstance(after, bytes):
                        raise ValueError('pending after')
                current = snapshot(root)
                recovery_conflict = any(
                    current.get(relative) not in (before, after)
                    for relative, before, after in pending)
                active_id = None
                if active:
                    active_id, raw = active[0]
                    uuid(active_id)
                    record = json.loads(raw)
                    if not isinstance(record, dict) or record.get('operation_id') != active_id:
                        raise ValueError('active record')
                    if record.get('kind') == 'external-replication':
                        add('journal-external-replication', 'journal',
                            'Projekt čeká na dokončení externí replikace; '
                            'opakujte stejnou synchronizační operaci.')
                        active_id = None
                    elif not recovery_conflict:
                        add('journal-operation-active', 'journal',
                            'Projekt má nedokončenou Workspace operaci.',
                            action='resume-operation')
                elif pending and not recovery_conflict:
                    add('journal-pending', 'journal',
                        'Projekt má samostatný nedokončený journalový zápis.',
                        action='resume-operation')
                if recovery_conflict:
                    add('journal-recovery-conflict', 'journal',
                        'Journal narazil na cizí změnu; intent zůstal zachovaný '
                        'pro ruční kontrolu.')
                intent = {'operation_id': active_id,
                          'pending_sha256': _digest([
                              [name,
                               hashlib.sha256(before).hexdigest() if before is not None else None,
                               hashlib.sha256(after).hexdigest() if after is not None else None]
                              for name, before, after in pending])}
                return True, intent
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError,
                json.JSONDecodeError):
            add('journal-invalid', 'journal',
                'Journal má poškozené nebo nepodporované schéma či obsah.')
            return False, None

    @staticmethod
    def _expected_index(files, entities, head):
        view = projection(files, entities, head)
        entity_rows = [tuple(item['metadata'].get(key) for key in Index.FIELDS) +
                       (item['path'], json.dumps(item['metadata'], ensure_ascii=False,
                                                sort_keys=True))
                       for item in view['entities'].values()]
        imports = []
        for id_, meta in sorted(entities.items()):
            if 'import' not in meta:
                continue
            imported = meta['import']; importer = imported['importer']
            imports.append((id_, *(imported.get(key) for key in Index.IMPORT_FIELDS),
                            importer['name'], importer.get('version')))
        tags = [(id_, ordinal, tag) for id_, meta in sorted(entities.items())
                for ordinal, tag in enumerate(meta.get('tags', []))]
        relations = [(edge['source_id'], edge['ordinal'], edge['type'], edge['target_id'])
                     for edge in view['relations']]
        return entity_rows, imports, tags, relations

    @staticmethod
    def _legacy_index_valid(db, version, tables):
        if version == 0:
            if not tables <= {'state', 'entities'}:
                return False
            expected = {'state': ['singleton', 'commit_id'],
                        'entities': ['id', 'title']}
            return all(table not in tables or _columns(db, table) == columns
                       for table, columns in expected.items())
        expected = INDEX_V1_COLUMNS if version == 1 else INDEX_V2_COLUMNS
        return tables == set(expected) and all(
            _columns(db, table) == columns for table, columns in expected.items())

    def _inspect_index(self, state, head, files, entities, add):
        path = state / 'index.sqlite'
        if not os.path.lexists(path):
            add('index-missing', 'index',
                'Odvozený index chybí a lze jej znovu sestavit.',
                action='rebuild-index')
            return
        if not self._safe_state_file(path):
            add('index-invalid', 'index',
                'Index nemá bezpečný typ, vlastníka nebo práva.')
            return
        try:
            with _readonly_database(path) as db:
                if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
                    raise ValueError('integrity')
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version not in {0, 1, 2, Index.VERSION}:
                    add('index-unsupported', 'index',
                        'Index používá nepodporovanou budoucí verzi schématu.')
                    return
                if version != Index.VERSION:
                    tables = {row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")}
                    if not self._legacy_index_valid(db, version, tables):
                        raise ValueError('legacy schema')
                    add('index-legacy', 'index',
                        'Index používá podporovanou starší verzi a lze jej přestavět.',
                        action='rebuild-index')
                    return
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if tables != set(INDEX_COLUMNS) or any(
                        _columns(db, table) != columns
                        for table, columns in INDEX_COLUMNS.items()):
                    raise ValueError('schema')
                state_rows = db.execute(
                    'SELECT singleton,commit_id FROM state ORDER BY singleton').fetchall()
                if state_rows != [(1, head)]:
                    add('index-stale', 'index',
                        'Index neodpovídá aktuálnímu validovanému commitu.',
                        action='rebuild-index')
                    return
                expected = self._expected_index(files, entities, head)
                actual = (
                    db.execute('SELECT ' + ','.join(INDEX_COLUMNS['entities']) +
                               ' FROM entities ORDER BY id').fetchall(),
                    db.execute('SELECT ' + ','.join(INDEX_COLUMNS['imports']) +
                               ' FROM imports ORDER BY entity_id').fetchall(),
                    db.execute('SELECT entity_id,ordinal,tag FROM tags '
                               'ORDER BY entity_id,ordinal').fetchall(),
                    db.execute('SELECT source_id,ordinal,type,target_id FROM relations '
                               'ORDER BY source_id,ordinal').fetchall(),
                )
                if actual != expected:
                    add('index-diverged', 'index',
                        'Index se liší od validovaného commitu a vyžaduje ruční kontrolu.')
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError,
                json.JSONDecodeError):
            add('index-invalid', 'index',
                'Index má poškozené nebo nerozpoznané schéma či obsah.')

    def _check(self, project_id, *, lock_held=False):
        uuid(project_id)
        findings = []

        def add(code, component, message, *, action='manual', severity='error'):
            if not any(item['code'] == code for item in findings):
                findings.append(self._finding(code, component, message,
                                              action=action, severity=severity))

        binding = None
        try:
            raw = read_config(self.node_path)
            node = parse_node(raw, location=self.node_path)
            matches = [row for row in node['projects'] if row['project_id'] == project_id]
            if len(matches) != 1:
                add('registration-missing', 'registration',
                    'Projekt není v tomto uzlu jednoznačně registrovaný.')
            else:
                binding = matches[0]
        except (OSError, ValueError) as exc:
            duplicate = str(exc) == 'Duplicate registered project ID'
            add('registration-duplicate' if duplicate else 'registration-invalid',
                'registration', 'Registrace obsahuje duplicitní ID projektu.' if duplicate
                else 'Registrace projektů je neplatná nebo ji nelze bezpečně přečíst.')

        before = self._fingerprint(binding)
        head = files = entities = intent = None
        root_ok = state_ok = git_ok = project_ok = journal_ok = False
        writer_busy = False
        if binding is not None:
            root, state = Path(binding['root']), Path(binding['state_dir'])
            try:
                if not self._safe_directory(root):
                    add('root-unsafe', 'filesystem',
                        'Kořen projektu nemá bezpečný typ, vlastníka, práva nebo cestu.')
                else:
                    root_ok = True
            except (FileNotFoundError, NotADirectoryError):
                add('root-missing', 'filesystem', 'Registrovaný kořen projektu chybí.',
                    action='repair-location')
            except (OSError, ValueError):
                add('root-unsafe', 'filesystem',
                    'Kořen projektu nelze bezpečně ověřit.')
            try:
                if not self._safe_directory(state, private=True):
                    add('state-unsafe', 'filesystem',
                        'Lokální stav projektu nemá bezpečný typ, vlastníka, práva nebo cestu.')
                else:
                    state_ok = True
            except (FileNotFoundError, NotADirectoryError):
                add('state-missing', 'filesystem',
                    'Registrovaný lokální stav projektu chybí.')
            except (OSError, ValueError):
                add('state-unsafe', 'filesystem',
                    'Lokální stav projektu nelze bezpečně ověřit.')
            if root_ok and state_ok and not self._same_filesystem(root, state):
                add('state-filesystem-mismatch', 'filesystem',
                    'Projekt a jeho lokální stav nejsou na stejném filesystemu.')
                state_ok = False
            if state_ok:
                try:
                    lock_path = state / 'writer.lock'
                    if not os.path.lexists(lock_path):
                        add('state-unsafe', 'filesystem',
                            'Lokální stav neobsahuje existující bezpečný writer lock.')
                        state_ok = False
                    elif not self._safe_state_file(lock_path):
                        raise ValueError('unsafe writer lock')
                    elif not lock_held:
                        writer_busy = self._writer_busy(lock_path)
                        if writer_busy:
                            add('writer-busy', 'consistency',
                                'Projekt právě používá jiná zapisující operace.',
                                action='none')
                except (OSError, ValueError):
                    add('state-unsafe', 'filesystem',
                        'Writer lock projektu nemá bezpečný typ, vlastníka nebo práva.')
                    state_ok = False
            if state_ok and not writer_busy:
                try:
                    if any(not self._safe_state_file(item) for item in state.iterdir()):
                        add('state-unsafe', 'filesystem',
                            'Lokální stav obsahuje nebezpečný typ souboru, vlastníka nebo práva.')
                        state_ok = False
                except (OSError, ValueError):
                    add('state-unsafe', 'filesystem',
                        'Obsah lokálního stavu nelze bezpečně ověřit.')
                    state_ok = False

            deadline = time.monotonic() + self.timeout
            if root_ok:
                try:
                    git_path = root / '.git'
                    if not stat.S_ISDIR(git_path.lstat().st_mode):
                        raise ValueError('git directory')
                    git = self._git(root, deadline)
                    if self._run(git, 'rev-parse', '--is-bare-repository').stdout.strip() != 'false':
                        add('git-bare', 'git', 'Projekt nesmí být bare Git repository.')
                    else:
                        top = self._run(git, 'rev-parse', '--show-toplevel').stdout.strip()
                        if Path(top) != root:
                            raise ValueError('git root')
                        try:
                            head = self._run(git, 'rev-parse', 'HEAD').stdout.strip()
                            if len(head) not in {40, 64}:
                                raise ValueError('head')
                            git_ok = True
                        except (subprocess.SubprocessError, ValueError):
                            add('git-head-missing', 'git',
                                'Git repository nemá čitelný výchozí commit.')
                        branch = self._run(git, 'symbolic-ref', '-q', 'HEAD', check=False)
                        if branch.returncode:
                            add('git-detached', 'git',
                                'Projekt nemá aktivní podporovanou Git větev.')
                        if any((git_path / marker).exists()
                               for marker in GIT_OPERATION_MARKERS):
                            add('git-operation-active', 'git',
                                'V repository právě probíhá jiná Git operace.')
                        if self._run(git, 'ls-files', '-u').stdout:
                            add('git-operation-active', 'git',
                                'Git repository obsahuje nevyřešený konflikt.')
                        dirty = self._run(git, 'status', '--porcelain=v1',
                                          '--untracked-files=all').stdout
                        if dirty:
                            add('git-dirty', 'git',
                                'Pracovní strom obsahuje necommitnuté změny.',
                                severity='warning')
                except (OSError, ValueError, subprocess.SubprocessError, TimeoutError):
                    add('git-invalid-root', 'git',
                        'Registrované umístění není podporovaný kořen Git repository.')

            if git_ok:
                try:
                    entry = self._run(git, 'ls-tree', head, '--', 'project.json').stdout.strip()
                    if not entry:
                        add('project-config-missing', 'project',
                            'V commitu chybí projektová konfigurace.')
                    else:
                        info, name = entry.split('\t', 1)
                        mode, kind, oid = info.split()
                        if (name != 'project.json' or mode not in {'100644', '100755'}
                                or kind != 'blob'):
                            raise ValueError('project blob')
                        if int(self._run(git, 'cat-file', '-s', oid).stdout) > MAX_METADATA:
                            raise ValueError('project size')
                        committed = self._run(git, 'cat-file', 'blob', oid,
                                              binary=True).stdout
                        metadata = parse_project(committed)
                        if metadata['id'] != project_id:
                            add('project-id-mismatch', 'project',
                                'ID v projektové konfiguraci neodpovídá registraci.')
                        else:
                            try:
                                if read_config(root / 'project.json') != committed:
                                    add('project-worktree-mismatch', 'project',
                                        'Pracovní project.json se liší od vybraného commitu.')
                            except (OSError, ValueError):
                                add('project-worktree-mismatch', 'project',
                                    'Pracovní project.json nelze bezpečně přečíst nebo se liší.')
                            try:
                                files = git.snapshot(head)
                                entities = validate_snapshot(files)
                                project_ok = True
                            except (OSError, ValueError, subprocess.SubprocessError, TimeoutError):
                                add('project-snapshot-invalid', 'project',
                                    'Projektový snapshot je neplatný nebo překračuje limity.')
                except (OSError, ValueError, subprocess.SubprocessError, TimeoutError):
                    add('project-config-invalid', 'project',
                        'Committed projektová konfigurace je neplatná nebo ji nelze přečíst.')

            if state_ok and not writer_busy:
                journal_ok, intent = self._inspect_journal(root, state, add)
                if journal_ok and project_ok and intent is not None \
                        and intent['operation_id'] is None \
                        and intent['pending_sha256'] == _digest([]):
                    self._inspect_index(state, head, files, entities, add)

        after = self._fingerprint(binding)
        if before != after:
            findings = [self._finding('state-changed', 'consistency',
                'Projekt se během kontroly změnil; načtěte stav znovu.',
                action='none')]
        token = _digest({'schema_version': SCHEMA_VERSION,
                         'project_id': project_id, 'evidence': after})
        status = 'healthy'
        for item in findings:
            candidate = ('retry' if item['code'] in {'writer-busy', 'state-changed'}
                         else 'repairable' if item['action'] in {
                             'rebuild-index', 'resume-operation', 'repair-location'}
                         else 'manual')
            if STATUS_PRIORITY[candidate] > STATUS_PRIORITY[status]:
                status = candidate
        summary = {
            'healthy': 'Projekt je v kontrolovaném rozsahu v pořádku.',
            'repairable': 'Projekt má stav s dostupnou bezpečnou opravou.',
            'manual': 'Projekt vyžaduje ruční kontrolu; automatická oprava není povolená.',
            'retry': 'Stav není stabilní; kontrolu zopakujte po dokončení jiné operace.',
        }[status]
        report = {'schema_version': SCHEMA_VERSION, 'project_id': project_id,
                  'status': status, 'summary': summary,
                  'findings': findings, 'check_token': token}
        return report, {'binding': binding, 'head': head, 'intent': intent}

    def check(self, project_id):
        report, _ = self._check(project_id)
        return report


class ProjectRepairActions:
    """Preview and confirm the two bounded repairs accepted by ADR 0035."""

    ACTIONS = {'rebuild-index', 'resume-operation'}

    def __init__(self, node_path, *, timeout=30):
        self.diagnostics = ProjectDiagnostics(node_path, timeout=timeout)
        self._previews = {}

    @staticmethod
    def _allowed(report, action):
        return (report['status'] == 'repairable'
                and len(report['findings']) == 1
                and report['findings'][0]['action'] == action)

    @staticmethod
    def _plan_digest(plan):
        return _digest({key: value for key, value in plan.items()
                        if key != 'preview_sha256'})

    def preview(self, request):
        require(isinstance(request, dict) and set(request) == {
            'project_id', 'action', 'operation_id', 'check_token'},
            'Invalid project repair preview request')
        project_id, action = request['project_id'], request['action']
        operation_id, check_token = request['operation_id'], request['check_token']
        uuid(project_id); uuid(operation_id)
        require(action in self.ACTIONS, 'Unsupported project repair action')
        require(isinstance(check_token, str) and len(check_token) == 64
                and all(char in '0123456789abcdef' for char in check_token),
                'Invalid project repair token')
        report, context = self.diagnostics._check(project_id)
        require(hmac.compare_digest(report['check_token'], check_token),
                'Project changed; run the check again')
        require(self._allowed(report, action),
                'The checked project does not permit this repair')
        intent = context['intent'] or {'operation_id': None,
                                       'pending_sha256': _digest([])}
        require(operation_id != intent['operation_id'],
                'Repair operation ID must differ from the recovered operation')
        descriptions = {
            'rebuild-index': (
                'index',
                'Atomicky znovu sestaví pouze odvozený index z validovaného HEAD.',
                'Pád ponechá starou nebo novou celou SQLite transakci; opakování '
                'ověří výsledek proti stejnému commitu.'),
            'resume-operation': (
                'journal',
                'Pokračuje pouze v přesném nedokončeném intentu stávajícího journalu.',
                'Původní Workspace nebo Journal recovery zachová intent při konfliktu; '
                'opakování načte trvalý receipt.'),
        }
        layer, effect, recovery = descriptions[action]
        plan = {
            'schema_version': 1,
            'project_id': project_id,
            'action': action,
            'operation_id': operation_id,
            'check_token': check_token,
            'expected_head': context['head'],
            'intent_operation_id': intent['operation_id'],
            'pending_sha256': intent['pending_sha256'],
            'layer': layer,
            'effect': effect,
            'preconditions': [
                'Registrace a bezpečnost cest se nezměnily.',
                'HEAD, pracovní strom, journal a index odpovídají kontrole.',
                'Writer lock je volný a stále patří tomuto projektu.',
            ],
            'recovery': recovery,
        }
        plan['preview_sha256'] = self._plan_digest(plan)
        self._previews[operation_id] = dict(plan)
        return plan

    @staticmethod
    def _existing(db, operation_id, request_digest):
        row = db.execute('SELECT record,done FROM operations WHERE id=?',
                         (operation_id,)).fetchone()
        if row is None:
            return None
        record = json.loads(row[0])
        require(row[1] == 1 and record.get('kind') == 'project-repair'
                and record.get('request_digest') == request_digest,
                'Operation ID belongs to another operation')
        return record

    @staticmethod
    def _store(db, receipt):
        db.execute('INSERT INTO operations(id,record,done) VALUES (?,?,1)',
                   (receipt['operation_id'], _canonical(receipt)))

    def receipt(self, project_id, operation_id):
        """Return one durable repair receipt without replaying its effect."""
        uuid(project_id); uuid(operation_id)
        _, context = self.diagnostics._check(project_id)
        binding = context['binding']
        require(binding is not None, 'Project registration changed')
        journal = Journal.attach(binding['root'], binding['state_dir'], blocking=False)
        with journal.lock(), journal.connect() as db:
            row = db.execute('SELECT record,done FROM operations WHERE id=?',
                             (operation_id,)).fetchone()
            if row is None:
                return None
            record = json.loads(row[0])
            require(row[1] == 1 and record.get('kind') == 'project-repair'
                    and record.get('project_id') == project_id,
                    'Operation ID does not identify a repair receipt')
            return record

    @staticmethod
    def _receipt(plan, commit_id, *, reconciled=False):
        return {
            'schema_version': 1,
            'kind': 'project-repair',
            'operation_id': plan['operation_id'],
            'project_id': plan['project_id'],
            'action': plan['action'],
            'request_digest': plan['preview_sha256'],
            'check_token': plan['check_token'],
            'commit_id': commit_id,
            'intent_operation_id': plan['intent_operation_id'],
            'pending_sha256': plan['pending_sha256'],
            'reconciled': reconciled,
            'state': 'completed',
        }

    @staticmethod
    def _intent_completed(db, operation_id):
        if operation_id is None:
            return False
        row = db.execute('SELECT record,done FROM operations WHERE id=?',
                         (operation_id,)).fetchone()
        if row is None or row[1] != 1:
            return False
        try:
            record = json.loads(row[0])
            return record.get('operation_id') == operation_id
        except (TypeError, ValueError, json.JSONDecodeError):
            return False

    def _reconciled(self, db, plan, report, context):
        """Recognize an effect completed before its wrapper receipt was stored."""
        intent = context['intent'] or {}
        empty = intent.get('operation_id') is None \
            and intent.get('pending_sha256') == _digest([])
        if plan['action'] == 'rebuild-index':
            completed = (report['status'] == 'healthy'
                         and context['head'] == plan['expected_head'] and empty)
        else:
            completed = (plan['intent_operation_id'] is not None
                         and self._intent_completed(db, plan['intent_operation_id'])
                         and empty)
        if not completed:
            return None
        receipt = self._receipt(plan, context['head'], reconciled=True)
        self._store(db, receipt)
        db.commit()
        return receipt

    def confirm(self, plan, *, checkpoint=lambda stage: None):
        require(isinstance(plan, dict) and set(plan) == {
            'schema_version', 'project_id', 'action', 'operation_id', 'check_token',
            'expected_head', 'intent_operation_id', 'pending_sha256', 'layer',
            'effect', 'preconditions', 'recovery', 'preview_sha256'},
            'Invalid project repair plan')
        issued = self._previews.get(plan.get('operation_id'))
        require(issued is not None and issued == plan
                and hmac.compare_digest(plan['preview_sha256'],
                                        self._plan_digest(plan)),
                'Repair preview was not issued by this backend or changed')

        # Resolve the existing lock from a stable read; the same token is checked
        # again after acquiring it, before any repair object may initialize state.
        report, context = self.diagnostics._check(plan['project_id'])
        binding = context['binding']
        require(binding is not None, 'Project registration changed')
        journal = Journal.attach(binding['root'], binding['state_dir'], blocking=False)
        with journal.lock(), journal.connect() as db:
            existing = self._existing(db, plan['operation_id'],
                                      plan['preview_sha256'])
            if existing is not None:
                final = self.diagnostics._check(plan['project_id'], lock_held=True)[0]
                return {'receipt': existing, 'report': final}

            current, locked = self.diagnostics._check(plan['project_id'],
                                                       lock_held=True)
            if not hmac.compare_digest(current['check_token'], plan['check_token']):
                receipt = self._reconciled(db, plan, current, locked)
                require(receipt is not None,
                        'Project changed after preview; run the check again')
                final = self.diagnostics._check(plan['project_id'],
                                                 lock_held=True)[0]
                return {'receipt': receipt, 'report': final}
            require(self._allowed(current, plan['action'])
                    and locked['head'] == plan['expected_head'],
                    'Repair preconditions changed; run the check again')

            if plan['action'] == 'rebuild-index':
                workspace = Workspace.attach(binding['root'], binding['state_dir'],
                                             blocking=False,
                                             deadline=time.monotonic() + self.diagnostics.timeout,
                                             index=True)
                commit = workspace.index.rebuild(workspace.git, checkpoint=checkpoint)
                require(commit == plan['expected_head'],
                        'Project changed during index rebuild')
                checkpoint('effect-completed')
                receipt = self._receipt(plan, commit)
                self._store(db, receipt)
                db.commit()
            elif plan['intent_operation_id'] is not None:
                workspace = Workspace.attach(binding['root'], binding['state_dir'],
                                             blocking=False,
                                             deadline=time.monotonic() + self.diagnostics.timeout,
                                             index=True)
                row = db.execute('SELECT record FROM operations WHERE id=? AND done=0',
                                 (plan['intent_operation_id'],)).fetchone()
                require(row is not None, 'Workspace recovery intent changed')
                workspace_receipt = workspace._recover(db, json.loads(row[0]), checkpoint)
                receipt = self._receipt(plan, workspace_receipt['commit_id'])
                self._store(db, receipt)
                db.commit()
            else:
                receipt = self._receipt(plan, locked['head'])

                def complete(connection):
                    self._store(connection, receipt)

                journal._recover(db, checkpoint, complete=complete)

            final = self.diagnostics._check(plan['project_id'], lock_held=True)[0]
            return {'receipt': receipt, 'report': final}
