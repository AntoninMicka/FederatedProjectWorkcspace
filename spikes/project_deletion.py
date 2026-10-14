# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Recoverable local project removal with an explicit, durable approval boundary."""
from contextlib import closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import time

from spikes.configuration import parse_node, read_config
from spikes.journal import sync_dir
from spikes.metadata import require, uuid
from spikes.project_creation import (ProjectCreation, check, directory, encoded,
                                     identity, missing)
from spikes.storage import Git


MODES = {'clear-derived', 'unregister', 'trash'}
STAGES = ('prepared', 'trash-created', 'root-trashed', 'state-trashed',
          'derived-cleared', 'root-restored', 'state-restored', 'trash-removed',
          'purged', 'node-published', 'completed')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _owned_file(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and info.st_nlink == 1 and not info.st_mode & 0o077,
            'Neplatný lokální stav projektu.')


def _read_only(path, query, values=()):
    if not os.path.lexists(path):
        return []
    _owned_file(path)
    uri = path.resolve(strict=True).as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
        return db.execute(query, values).fetchall()


class ProjectDeletion:
    """Coordinate node registration, project state and recoverable trash moves.

    Project Git remains authoritative until a separately confirmed purge of an
    already completed trash entry. Shared node-local history is inventoried and
    preserved; ambiguous external effects and active authorities are blockers.
    """

    def __init__(self, node_path, *, timeout=60):
        self.node_path = Path(node_path).absolute()
        self.creator = ProjectCreation(self.node_path, timeout=timeout)
        self.timeout = timeout

    def _binding(self, project_id):
        uuid(project_id)
        raw = read_config(self.node_path)
        node = parse_node(raw, location=self.node_path)
        binding = next((row for row in node['projects']
                        if row['project_id'] == project_id), None)
        check(binding is not None, 'Projekt není registrovaný.')
        return raw, node, binding

    def _workspace_inventory(self, binding):
        root, state = Path(binding['root']), Path(binding['state_dir'])
        directory(root); directory(root / '.git'); directory(state, private=True)
        check(root.stat().st_dev == state.stat().st_dev,
              'Projekt a jeho lokální stav nejsou na stejném filesystemu.')
        lock_path = state / 'writer.lock'
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('Projekt právě používá jiná zapisující operace.') from exc
            journal = state / 'journal.sqlite'
            rows = _read_only(journal,
                'SELECT (SELECT COUNT(*) FROM pending), '
                '(SELECT COUNT(*) FROM operations WHERE done=0)')
            pending, operations = rows[0] if rows else (0, 0)
            check(not pending and not operations,
                  'Projekt má nedokončenou Workspace operaci; nejprve ji obnovte.')
            git = Git(root, deadline=time.monotonic() + self.timeout)
            head = git.head()
            check(not git.run('ls-files', '-u').stdout, 'Projekt má nevyřešený Git konflikt.')
            dirty = bool(git.run('status', '--porcelain', '--untracked-files=all').stdout)
        return {'root': str(root), 'state_dir': str(state), 'head': head,
                'dirty_worktree': dirty, 'root_identity': identity(root),
                'state_identity': identity(state),
                'index_present': os.path.lexists(state / 'index.sqlite')}

    def _transfer_inventory(self, project_id):
        path = self.node_path.parent / ('.' + self.node_path.name + '.network') \
            / 'git-transfer-journal.sqlite'
        rows = _read_only(path, 'SELECT operation_id,context FROM transfers WHERE done=0')
        pending = []
        for operation_id, raw in rows:
            context = json.loads(raw)
            if context.get('project_id') == project_id:
                pending.append(operation_id)
        return pending

    def _administration_inventory(self, project_id):
        repo = self.node_path.parent / ('.' + self.node_path.name + '.administration') / 'registry.git'
        if not repo.exists():
            return {'memberships': 0, 'mappings': 0}
        directory(repo)
        git = Git(repo, deadline=time.monotonic() + self.timeout)
        head = git.run('rev-parse', '--verify', 'refs/heads/main', check=False)
        if head.returncode:
            return {'memberships': 0, 'mappings': 0}
        state = json.loads(git.run('show', head.stdout.strip() + ':registry.json').stdout)
        memberships = sum(project_id in user.get('memberships', {})
                          for user in state.get('users', []))
        mappings = sum(project_id in row.get('spec', {}).get('project_ids', [])
                       and row.get('revocation') is None
                       for row in state.get('mappings', []))
        return {'memberships': memberships, 'mappings': mappings}

    def _node_records(self, project_id):
        root = self.node_path.parent / ('.' + self.node_path.name + '.chat')
        if not root.exists():
            return {'records': 0, 'unknown_or_active': 0, 'details': {}}
        directory(root, private=True)
        details = {}

        def count(name, query, values=(project_id,), active_query=None):
            path = root / name
            rows = _read_only(path, query, values)
            total = int(rows[0][0]) if rows else 0
            active = 0
            if active_query:
                rows = _read_only(path, active_query, values)
                active = int(rows[0][0]) if rows else 0
            if total:
                details[name] = {'records': total, 'unknown_or_active': active}
            return total, active

        total = active = 0
        for values in (
            count('chat-threads.sqlite',
                  'SELECT COUNT(*) FROM threads WHERE project_id=?', active_query=
                  "SELECT COUNT(*) FROM turns JOIN threads USING(thread_id) "
                  "WHERE threads.project_id=? AND turns.state IN ('prepared','run-bound','unknown')"),
            count('task-outcomes.sqlite',
                  'SELECT COUNT(*) FROM outcomes WHERE project_id=?', active_query=
                  "SELECT COUNT(*) FROM outcomes WHERE project_id=? AND state='prepared'"),
            count('search-runs.sqlite',
                  'SELECT COUNT(*) FROM searches WHERE project_id=?', active_query=
                  "SELECT COUNT(*) FROM searches WHERE project_id=? "
                  "AND state IN ('prepared','dispatching','unknown')"),
            count('role-workflows.sqlite',
                  'SELECT COUNT(*) FROM workflows WHERE project_id=?', active_query=
                  "SELECT COUNT(*) FROM workflows LEFT JOIN steps USING(workflow_id) "
                  "WHERE workflows.project_id=? AND (workflows.publish_state='publishing' "
                  "OR steps.state IN ('prepared','run-bound','unknown'))"),
            count('output-executions.sqlite',
                  'SELECT COUNT(*) FROM executions WHERE project_id=?', active_query=
                  "SELECT COUNT(*) FROM executions WHERE project_id=? "
                  "AND state IN ('prepared','running','unknown')"),
        ):
            total += values[0]; active += values[1]

        # Task/approval stores bind the project in their canonical request JSON.
        for name, table, request_column, state_column in (
            ('summary-tasks.sqlite', 'tasks', 'request_json', 'state'),
            ('extraction-tasks.sqlite', 'tasks', 'request_json', 'state'),
            ('metadata-suggestion-tasks.sqlite', 'tasks', 'request_json', 'state'),
            ('media-approvals.sqlite', 'tasks', 'request_json', 'state'),
            ('external-dispatches.sqlite', 'approvals', 'request', 'state'),
        ):
            path = root / name
            rows = _read_only(path, f'SELECT {request_column},{state_column} FROM {table}')
            matched = []
            for raw, state in rows:
                request = json.loads(raw)
                if request.get('project_id') == project_id:
                    matched.append(state)
            if matched:
                uncertain = sum(state in {'prepared', 'run-bound', 'publishing',
                                          'dispatching', 'running', 'unknown'}
                                for state in matched)
                details[name] = {'records': len(matched), 'unknown_or_active': uncertain}
                total += len(matched); active += uncertain
        return {'records': total, 'unknown_or_active': active, 'details': details}

    def inventory(self, project_id):
        before, node, binding = self._binding(project_id)
        workspace = self._workspace_inventory(binding)
        administration = self._administration_inventory(project_id)
        transfers = self._transfer_inventory(project_id)
        node_records = self._node_records(project_id)
        blockers = []
        if transfers:
            blockers.append('Projekt má nedokončený odchozí Git přenos.')
        if administration['memberships'] or administration['mappings']:
            blockers.append('Projekt je stále použit v účtu nebo federačním mapování.')
        if node_records['unknown_or_active']:
            blockers.append('Projekt má aktivní nebo neurčitý AI/síťový účinek.')
        return {'project_id': project_id, **workspace,
                'transfers': transfers, 'administration': administration,
                'node_records': node_records, 'blockers': blockers,
                'shared_credentials_preserved': True,
                'remote_copies_preserved': True,
                '_before': before.decode(), '_node': node, '_binding': binding}

    def preview(self, project_id, mode):
        check(mode in MODES, 'Neplatný režim odstranění projektu.')
        item = self.inventory(project_id)
        public = {key: value for key, value in item.items() if not key.startswith('_')}
        public['mode'] = mode
        public['trash_path'] = (str(Path(item['root']).parent /
            ('.workspace-trash-' + project_id)) if mode == 'trash' else None)
        public['effect'] = {
            'clear-derived': 'Odstraní se pouze obnovitelný SQLite index; Git, journal a registrace zůstanou.',
            'unregister': 'Odstraní se pouze registrace; repozitář, stav a node-local historie zůstanou.',
            'trash': 'Repozitář a projektový stav se přesunou do obnovitelného koše a registrace se odebere.',
        }[mode]
        public['preview_sha256'] = digest(public)
        return public

    def confirm(self, preview, operation_id, *, checkpoint=lambda stage: None):
        uuid(operation_id)
        check(isinstance(preview, dict) and preview.get('mode') in MODES,
              'Neplatný potvrzený náhled odstranění.')
        deadline = time.monotonic() + self.timeout
        with self.creator._locked() as db:
            row = db.execute('SELECT record,done FROM project_deletions WHERE id=?',
                             (operation_id,)).fetchone()
            if row:
                record = json.loads(row[0])
                check(record['request_digest'] == digest(preview),
                      'ID operace už patří jinému odstranění.')
                return record['receipt'] if row[1] else self._finish(
                    db, record, deadline, checkpoint)
            expected = self.preview(preview.get('project_id'), preview.get('mode'))
            check(preview == expected, 'Projekt nebo jeho dopady se od náhledu změnily.')
            check(not expected['blockers'], 'Projekt má blokující vazby nebo operace.')
            check(not db.execute('SELECT 1 FROM creations WHERE done=0').fetchone()
                  and not db.execute('SELECT 1 FROM project_deletions WHERE done=0').fetchone(),
                  'Nejprve dokončete jinou operaci projektu.')
            current = self.inventory(preview['project_id'])
            check(not current['blockers'], 'Projekt má blokující vazby nebo operace.')
            check(all(current[key] == preview[key] for key in
                      ('root', 'state_dir', 'head', 'root_identity', 'state_identity',
                       'dirty_worktree', 'index_present', 'transfers', 'administration',
                       'node_records')), 'Projekt nebo jeho dopady se od náhledu změnily.')
            updated = dict(current['_node'], projects=[row for row in current['_node']['projects']
                if row['project_id'] != preview['project_id']])
            after = (current['_before'] if preview['mode'] == 'clear-derived'
                     else encoded(updated).decode())
            trash = (Path(current['root']).parent /
                     ('.workspace-trash-' + preview['project_id']))
            record = {'operation_id': operation_id, 'project_id': preview['project_id'],
                'mode': preview['mode'], 'request_digest': digest(preview),
                'preview': preview, 'root': current['root'], 'state': current['state_dir'],
                'head': current['head'], 'root_identity': current['root_identity'],
                'state_identity': current['state_identity'], 'before': current['_before'],
                'after': after, 'trash': str(trash), 'trash_identity': None,
                'receipt': None}
            db.execute('INSERT INTO project_deletions VALUES (?,?,0)',
                       (operation_id, canonical(record)))
            db.commit(); checkpoint('prepared')
            return self._finish(db, record, deadline, checkpoint)

    def recover(self, *, checkpoint=lambda stage: None):
        if not self.creator.database.exists():
            return None
        with self.creator._locked() as db:
            row = db.execute('SELECT record FROM project_deletions WHERE done=0').fetchone()
            return (self._finish(db, json.loads(row[0]),
                    time.monotonic() + self.timeout, checkpoint) if row else None)

    @staticmethod
    def _save(db, record, *, done=False):
        db.execute('UPDATE project_deletions SET record=?,done=? WHERE id=?',
                   (canonical(record), int(done), record['operation_id']))
        db.commit()

    def _boundary(self, deadline, checkpoint, stage):
        if time.monotonic() >= deadline:
            raise TimeoutError('Odstranění překročilo limit; operace zůstala k obnově.')
        checkpoint(stage)

    def _finish(self, db, record, deadline, checkpoint):
        mode = record['mode']
        if mode == 'restore':
            return self._finish_restore(db, record, deadline, checkpoint)
        if mode == 'purge':
            return self._finish_purge(db, record, deadline, checkpoint)
        root, state, trash = Path(record['root']), Path(record['state']), Path(record['trash'])
        before, _ = self.creator._node()
        after = record['after'].encode()
        check(before in {record['before'].encode(), after},
              'Konfigurace uzlu se mezitím změnila; cizí změny byly zachovány.')
        if mode == 'clear-derived':
            check(before == record['before'].encode(),
                  'Projekt už není registrovaný.')
            check(identity(root) == record['root_identity']
                  and identity(state) == record['state_identity'],
                  'Projekt nebo jeho stav byl nahrazen.')
            index = state / 'index.sqlite'
            if os.path.lexists(index):
                _owned_file(index); index.unlink(); sync_dir(state)
            self._boundary(deadline, checkpoint, 'derived-cleared')
        elif mode == 'unregister':
            check(identity(root) == record['root_identity']
                  and identity(state) == record['state_identity'],
                  'Projekt nebo jeho stav byl nahrazen.')
            self.creator._publish_node(record)
            self._boundary(deadline, checkpoint, 'node-published')
        else:
            if not os.path.lexists(trash):
                trash.mkdir(mode=0o700)
                sync_dir(trash.parent)
            directory(trash, private=True)
            if record['trash_identity'] is None:
                check(not list(trash.iterdir()), 'Koš operace obsahuje cizí data.')
                record['trash_identity'] = identity(trash); self._save(db, record)
            check(identity(trash) == record['trash_identity'], 'Koš operace byl nahrazen.')
            self._boundary(deadline, checkpoint, 'trash-created')
            for source, target, expected, stage in (
                (root, trash / 'repository', record['root_identity'], 'root-trashed'),
                (state, trash / 'state', record['state_identity'], 'state-trashed')):
                if os.path.lexists(source):
                    check(identity(source) == expected and not os.path.lexists(target),
                          'Zdroj nebo cíl koše se změnil.')
                    os.rename(source, target); sync_dir(source.parent); sync_dir(trash)
                check(identity(target) == expected, 'Přesunutá data v koši byla nahrazena.')
                self._boundary(deadline, checkpoint, stage)
            self.creator._publish_node(record)
            self._boundary(deadline, checkpoint, 'node-published')
        record['receipt'] = {'operation_id': record['operation_id'],
            'project_id': record['project_id'], 'mode': mode,
            'unregistered': mode in {'unregister', 'trash'},
            'trash_path': str(trash) if mode == 'trash' else None,
            'remote_copies_preserved': True, 'node_records_preserved': True}
        self._save(db, record, done=True)
        self._boundary(deadline, checkpoint, 'completed')
        return record['receipt']

    def trash(self):
        """List completed recoverable trash entries without opening project data."""
        if not self.creator.database.exists():
            return []
        with self.creator._locked() as db:
            rows = db.execute("SELECT record FROM project_deletions WHERE done=1").fetchall()
        result = []
        for row, in rows:
            record = json.loads(row)
            if record['mode'] == 'trash' and os.path.lexists(record['trash']):
                result.append({'project_id': record['project_id'],
                    'operation_id': record['operation_id'], 'trash_path': record['trash'],
                    'head': record['head'], 'dirty_worktree': record['preview']['dirty_worktree'],
                    'node_records': record['preview']['node_records']})
        return sorted(result, key=lambda item: item['project_id'])

    def restore_preview(self, deletion_operation_id):
        uuid(deletion_operation_id)
        item = next((row for row in self.trash()
                     if row['operation_id'] == deletion_operation_id), None)
        check(item is not None, 'Položka koše není dostupná.')
        preview = {**item,
            'effect': 'Repozitář a projektový stav se vrátí na původní cesty a projekt se znovu zaregistruje.'}
        preview['preview_sha256'] = digest(preview)
        return preview

    def restore(self, deletion_operation_id, operation_id, *, checkpoint=lambda stage: None):
        """Restore one unchanged trash entry and its original registration."""
        uuid(deletion_operation_id); uuid(operation_id)
        with self.creator._locked() as db:
            existing = db.execute('SELECT record,done FROM project_deletions WHERE id=?',
                                  (operation_id,)).fetchone()
            if existing:
                operation = json.loads(existing[0])
                check(operation.get('mode') == 'restore'
                      and operation.get('source_operation_id') == deletion_operation_id,
                      'ID operace už patří jiné obnově.')
                return operation['receipt'] if existing[1] else self._finish(
                    db, operation, time.monotonic() + self.timeout, checkpoint)
            row = db.execute('SELECT record,done FROM project_deletions WHERE id=?',
                             (deletion_operation_id,)).fetchone()
            check(row is not None and row[1], 'Položka koše není dokončená.')
            source = json.loads(row[0]); check(source['mode'] == 'trash', 'Nejde o položku koše.')
            trash, root, state = Path(source['trash']), Path(source['root']), Path(source['state'])
            check(identity(trash) == source['trash_identity'] and missing(root) and missing(state),
                  'Původní cíl nebo položka koše se změnily.')
            before, node = self.creator._node()
            check(node is not None and not any(p['project_id'] == source['project_id']
                  for p in node['projects']), 'Projekt je již registrovaný.')
            check(before == source['after'].encode(),
                  'Registrace uzlu se od odstranění změnila; obnovu proveďte ručně.')
            check(not db.execute('SELECT 1 FROM creations WHERE done=0').fetchone()
                  and not db.execute('SELECT 1 FROM project_deletions WHERE done=0').fetchone(),
                  'Nejprve dokončete jinou operaci projektu.')
            operation = {'operation_id': operation_id, 'mode': 'restore',
                'source_operation_id': deletion_operation_id,
                'project_id': source['project_id'], 'root': source['root'],
                'state': source['state'], 'trash': source['trash'],
                'trash_identity': source['trash_identity'],
                'root_identity': source['root_identity'],
                'state_identity': source['state_identity'], 'head': source['head'],
                'before': source['after'], 'after': source['before'], 'receipt': None}
            db.execute('INSERT INTO project_deletions VALUES (?,?,0)',
                       (operation_id, canonical(operation))); db.commit()
            checkpoint('prepared')
            return self._finish_restore(db, operation, time.monotonic() + self.timeout,
                                        checkpoint)

    def _finish_restore(self, db, record, deadline, checkpoint):
        trash, root, state = Path(record['trash']), Path(record['root']), Path(record['state'])
        before, _ = self.creator._node(); after = record['after'].encode()
        check(before in {record['before'].encode(), after},
              'Registrace uzlu se od odstranění změnila; obnova byla zastavena.')
        if os.path.lexists(trash):
            check(identity(trash) == record['trash_identity'], 'Položka koše byla nahrazena.')
        for source, target, expected, stage in (
            (trash / 'repository', root, record['root_identity'], 'root-restored'),
            (trash / 'state', state, record['state_identity'], 'state-restored')):
            if os.path.lexists(source):
                check(not os.path.lexists(target) and identity(source) == expected,
                      'Cíl obnovy nebo data v koši se změnily.')
                os.rename(source, target); sync_dir(target.parent); sync_dir(trash)
            check(identity(target) == expected, 'Obnovená data byla nahrazena.')
            self._boundary(deadline, checkpoint, stage)
        if os.path.lexists(trash):
            check(not list(trash.iterdir()), 'Koš operace obsahuje cizí data.')
            trash.rmdir(); sync_dir(trash.parent)
        self._boundary(deadline, checkpoint, 'trash-removed')
        self.creator._publish_node(record)
        self._boundary(deadline, checkpoint, 'node-published')
        record['receipt'] = {'operation_id': record['operation_id'],
            'project_id': record['project_id'], 'restored': True, 'head': record['head']}
        self._save(db, record, done=True)
        self._boundary(deadline, checkpoint, 'completed')
        return record['receipt']

    def purge_preview(self, deletion_operation_id):
        uuid(deletion_operation_id)
        if not self.creator.database.exists():
            raise ValueError('Položka koše není dostupná.')
        with self.creator._locked() as db:
            return self._purge_preview_locked(db, deletion_operation_id)

    def _purge_preview_locked(self, db, deletion_operation_id):
        row = db.execute('SELECT record,done FROM project_deletions WHERE id=?',
                         (deletion_operation_id,)).fetchone()
        check(row is not None and row[1], 'Položka koše není dostupná.')
        source = json.loads(row[0])
        check(source.get('mode') == 'trash' and os.path.lexists(source['trash']),
              'Položka koše není dostupná.')
        item = {'project_id': source['project_id'],
                'operation_id': source['operation_id'], 'trash_path': source['trash'],
                'head': source['head'], 'dirty_worktree': source['preview']['dirty_worktree'],
                'node_records': source['preview']['node_records']}
        blockers = []
        if item['node_records']['records']:
            blockers.append('Node-local historie projektu je zachovaná; nejprve ji explicitně vyřešte.')
        preview = {**item, 'blockers': blockers,
                   'effect': 'Definitivně a lokálně odstraní repozitář i projektový stav z koše. Vzdálené kopie zůstanou.'}
        preview['preview_sha256'] = digest(preview)
        return preview

    def purge(self, preview, operation_id, *, checkpoint=lambda stage: None):
        uuid(operation_id)
        with self.creator._locked() as db:
            existing = db.execute('SELECT record,done FROM project_deletions WHERE id=?',
                                  (operation_id,)).fetchone()
            if existing:
                record = json.loads(existing[0])
                check(record.get('mode') == 'purge'
                      and record.get('request_digest') == digest(preview),
                      'ID operace už patří jinému výmazu.')
                return record['receipt'] if existing[1] else self._finish(
                    db, record, time.monotonic() + self.timeout, checkpoint)
            expected = self._purge_preview_locked(db, preview.get('operation_id'))
            check(preview == expected and not expected['blockers'],
                  'Položka koše nebo její dopady se změnily.')
            check(not db.execute('SELECT 1 FROM creations WHERE done=0').fetchone()
                  and not db.execute('SELECT 1 FROM project_deletions WHERE done=0').fetchone(),
                  'Nejprve dokončete jinou operaci projektu.')
            trash = Path(preview['trash_path']); directory(trash, private=True)
            record = {'operation_id': operation_id, 'mode': 'purge',
                'source_operation_id': preview['operation_id'],
                'project_id': preview['project_id'], 'trash': str(trash),
                'trash_identity': identity(trash), 'request_digest': digest(preview),
                'receipt': None}
            db.execute('INSERT INTO project_deletions VALUES (?,?,0)',
                       (operation_id, canonical(record))); db.commit()
            checkpoint('prepared')
            return self._finish_purge(db, record, time.monotonic() + self.timeout,
                                      checkpoint)

    def _finish_purge(self, db, record, deadline, checkpoint):
        trash = Path(record['trash'])
        if os.path.lexists(trash):
            check(identity(trash) == record['trash_identity'], 'Položka koše byla nahrazena.')
            # The private parent and exact recorded inode bind the target;
            # rmtree unlinks symlinks instead of following their targets.
            shutil.rmtree(trash); sync_dir(trash.parent)
        self._boundary(deadline, checkpoint, 'purged')
        record['receipt'] = {'operation_id': record['operation_id'],
            'project_id': record['project_id'], 'purged': True,
            'remote_copies_preserved': True}
        self._save(db, record, done=True)
        self._boundary(deadline, checkpoint, 'completed')
        return record['receipt']
