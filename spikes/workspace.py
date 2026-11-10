# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Coordinated Linux M0 operations in controlled, initialized Git repositories."""
import hashlib
import base64
from collections import OrderedDict
import json
from pathlib import Path
import re
import tempfile
import threading
import uuid

from spikes.configuration import committed_project, parse_project
from spikes.markdown_documents import main_todo_id, main_todo_view
from spikes.task_graph import project_task_graph
from spikes.journal import Journal, RecoveryConflict, snapshot
from spikes.metadata import MAX_METADATA, require, validate_snapshot, validate_transition
from spikes.storage import Git, Index, StaleIndex, projection


class PendingOperation(RuntimeError):
    pass


MAX_PROJECT_HISTORY = 20
_PROJECT_VIEWS = OrderedDict()
_PROJECT_VIEWS_LOCK = threading.Lock()
_PROJECT_VIEWS_BYTES = 16 * 1024 * 1024


def _project_view_get(key):
    with _PROJECT_VIEWS_LOCK:
        value = _PROJECT_VIEWS.get(key)
        if value is not None:
            _PROJECT_VIEWS.move_to_end(key)
        return value


def _project_view_put(key, result, validated_projection):
    # Immutable bytes prevent callers from changing another request's result.
    value = (json.dumps(result, ensure_ascii=False).encode(),
             json.dumps(validated_projection, ensure_ascii=False).encode())
    if sum(map(len, value)) > _PROJECT_VIEWS_BYTES:
        return
    with _PROJECT_VIEWS_LOCK:
        _PROJECT_VIEWS[key] = value; _PROJECT_VIEWS.move_to_end(key)
        while (len(_PROJECT_VIEWS) > 8 or
               sum(len(a) + len(b) for a, b in _PROJECT_VIEWS.values()) > _PROJECT_VIEWS_BYTES):
            _PROJECT_VIEWS.popitem(last=False)


class Workspace:
    def __init__(self, root, state, *, blocking=True, deadline=None,
                 write_guard=None):
        self.journal = Journal(root, state, blocking=blocking)
        self.git = Git(self.journal.root, deadline=deadline)
        self.index = Index(self.journal.state / 'index.sqlite')
        self.write_guard = write_guard

    @classmethod
    def attach(cls, root, state, *, blocking=True, deadline=None, index=False):
        """Attach to existing state without running journal initialization."""
        workspace = cls.__new__(cls)
        workspace.journal = Journal.attach(root, state, blocking=blocking)
        workspace.git = Git(workspace.journal.root, deadline=deadline)
        workspace.index = (Index(workspace.journal.state / 'index.sqlite')
                           if index else None)
        workspace.write_guard = None
        return workspace

    @classmethod
    def open_for_read(cls, root, state, *, blocking=True, deadline=None, write_guard=None):
        """Reuse initialized state without repeating journal bootstrap/fsync.

        Reads still own the journal, refuse pending writes and may rebuild the
        index. Missing state uses native bootstrap; errors never trigger reset.
        """
        if not (Path(state) / 'journal.sqlite').exists():
            return cls(root, state, blocking=blocking, deadline=deadline,
                       write_guard=write_guard)
        workspace = cls.attach(root, state, blocking=blocking, deadline=deadline)
        with workspace.journal.lock(), workspace.journal.connect() as db:
            owners = db.execute('SELECT root FROM owner').fetchall()
            require(owners == [(str(workspace.journal.root),)],
                    'Journal belongs to another project or is not initialized')
            index_path = workspace.journal.state / 'index.sqlite'
            workspace.index = (Index.attach(index_path) if index_path.exists()
                               else Index(index_path))
        workspace.write_guard = write_guard
        return workspace

    def _writable(self):
        if self.write_guard is not None:
            self.write_guard()

    def _active(self, db):
        row = db.execute('SELECT record FROM operations WHERE done=0').fetchone()
        return json.loads(row[0]) if row else None

    def _save(self, db, record, state):
        record['state'] = state
        db.execute('UPDATE operations SET record=? WHERE id=?',
                   (json.dumps(record), record['operation_id']))
        db.commit()

    def _branch(self):
        result = self.git.run('symbolic-ref', '-q', 'HEAD', check=False)
        require(result.returncode == 0, 'An initialized branch is required')
        # Linked worktrees and in-progress Git operations are outside this PoC.
        require((self.git.root / '.git').is_dir(), 'Linked worktrees are unsupported')
        for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge',
                     'rebase-apply', 'sequencer', 'BISECT_START'):
            require(not (self.git.root / '.git' / name).exists(), 'Git operation in progress')
        return result.stdout.strip()

    def apply(self, changes, *, author_name, author_email, message, checkpoint=lambda stage: None):
        """Refuse dirty inputs; return a durable receipt after commit and index publication."""
        with self.journal.lock(), self.journal.connect() as db:
            self._writable()
            return self._apply_locked(db, changes, author_name, author_email, message, checkpoint)

    def transact(self, operation_id, request, prepare, *, expected_head=None,
                 allow_privacy_relaxation=False, additional_parents=(), adopt_staged=False,
                 checkpoint=lambda stage: None):
        """Bind a native request to one durable operation, including lost-response retries.

        prepare runs under the writer lock, only for a new request, and returns
        (changes, author_name, author_email, message) after checking its base HEAD.
        """
        from spikes.metadata import uuid as validate_uuid
        validate_uuid(operation_id)
        require(isinstance(additional_parents, (list, tuple))
                and len(additional_parents) <= 1,
                'At most one additional parent is supported')
        additional_parents = list(additional_parents)
        for parent in additional_parents:
            require(isinstance(parent, str)
                    and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', parent),
                    'Expected full additional parent commit ID')
        require(type(adopt_staged) is bool, 'Invalid staged adoption mode')
        if adopt_staged:request=dict(request, workspace_mode='adopt-staged-v1')
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.journal.lock(), self.journal.connect() as db:
            self._writable()
            row = db.execute('SELECT record, done FROM operations WHERE id=?', (operation_id,)).fetchone()
            if row:
                record = json.loads(row[0])
                require(record.get('request_digest') == digest, 'Operation ID belongs to a different request')
                return record if row[1] else self._recover(db, record, checkpoint)
            if self._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
                raise PendingOperation('Recover the pending operation first')
            changes, name, email, message = prepare(self)
            return self._apply_locked(db, changes, name, email, message, checkpoint,
                                      operation_id=operation_id, request_digest=digest, expected_head=expected_head,
                                      allow_privacy_relaxation=allow_privacy_relaxation,
                                      additional_parents=additional_parents, adopt_staged=adopt_staged)

    def _apply_locked(self, db, changes, author_name, author_email, message, checkpoint,
                      *, operation_id=None, request_digest=None, expected_head=None,
                      allow_privacy_relaxation=False, additional_parents=(), adopt_staged=False):
        for value in (author_name, author_email):
            require(isinstance(value, str) and value.strip() == value and bool(value)
                    and not any(c in value for c in '\n\r\0<>'), 'Explicit Git identity required')
        require(isinstance(message, str) and bool(message.strip()) and '\0' not in message,
                'Commit message required')
        if self._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
            raise PendingOperation('Recover the pending operation first')
        branch = self._branch()
        base = self.git.head()
        require(expected_head is None or base == expected_head, 'Project changed before preparation')
        for parent in additional_parents:
            resolved = self.git.run('rev-parse', '--verify', parent + '^{commit}').stdout.strip()
            require(resolved == parent and parent != base, 'Invalid additional parent')
        index_tree = None
        if adopt_staged:
            require(len(changes)==1 and not additional_parents,'A file commit adopts exactly one staged file')
            index_tree=self.git.run('write-tree').stdout.strip()
            for path,data in changes.items():
                self.journal.target(path)
                require(path.startswith('artifacts/') and isinstance(data,bytes),'Expected tracked artifact bytes')
                require(self.git.run('show',':'+path,binary=True).stdout==data,'Staged file changed; review again')
        else:
            require(not self.git.run('status', '--porcelain', '--untracked-files=all').stdout,
                    'Clean worktree and staging index required')
            require(snapshot(self.git.root) == self.git.snapshot(base),
                    'Working projection differs from HEAD (including ignored files)')
        base_files = self.git.snapshot(base)
        candidate_files = dict(base_files)
        for path, data in changes.items():
            if not path.startswith(('artifacts/', 'registries/')):
                continue
            if data is None:
                candidate_files.pop(path, None)
            else:
                candidate_files[path] = data
        entities = validate_transition(base_files, candidate_files,
                                       allow_privacy_relaxation=allow_privacy_relaxation)
        from spikes.reporting_schema import validate_git
        validate_git(self.git, candidate_files, entities, base_files)
        if adopt_staged:
            pid=parse_project(self.git.run('show',base+':project.json',binary=True).stdout)['id']
            plan=project_task_graph(candidate_files,entities,pid,base)
            require(plan['status'] in {'ready','missing'},plan.get('error','Invalid project plan'))
        if adopt_staged:
            paths=[]
            for path,data in changes.items():
                require(path in base_files and base_files[path]!=data,'Selected file has no staged changes')
                db.execute('INSERT INTO pending VALUES(?,?,?)',(path,base_files[path],data));paths.append(path)
        else:paths = self.journal._prepare(db, changes)
        # A merge that explicitly keeps the complete first-parent tree is still
        # meaningful: its additional parent records the reconciled history.
        require(bool(paths) or additional_parents, 'Operation has no changes')
        record = dict(operation_id=operation_id or str(uuid.uuid4()), base_head=base, branch=branch,
                      paths=paths, author_name=author_name, author_email=author_email,
                      message=message, state='prepared', commit_id=None, request_digest=request_digest,
                      allow_privacy_relaxation=allow_privacy_relaxation,
                      additional_parents=list(additional_parents))
        if adopt_staged:record.update(kind='staged-artifact-commit',index_tree=index_tree,file_modes={path:self.git.run('ls-tree',index_tree,'--',path).stdout.split()[0] for path in paths})
        db.execute('INSERT INTO operations(id, record) VALUES (?, ?)',
                   (record['operation_id'], json.dumps(record)))
        db.commit()
        checkpoint('prepared')
        return self._recover(db, record, checkpoint)

    def stage_artifact(self, operation_id, request, prepare, *, checkpoint=lambda stage: None):
        """Freeze one file in the real Git index, using the shared operation journal."""
        from spikes.metadata import uuid as validate_uuid
        validate_uuid(operation_id)
        digest=hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.journal.lock(),self.journal.connect() as db:
            self._writable()
            row=db.execute('SELECT record,done FROM operations WHERE id=?',(operation_id,)).fetchone()
            if row:
                record=json.loads(row[0]);require(record.get('request_digest')==digest,'Operation ID belongs to a different request')
                return record if row[1] else self._recover_stage(db,record,checkpoint)
            if self._active(db) or db.execute('SELECT 1 FROM pending').fetchone():raise PendingOperation('Recover pending operation first')
            path,raw=prepare(self);self.journal.target(path)
            branch=self._branch();head=self.git.head();before=self.git.run('write-tree').stdout.strip()
            mode=self.git.run('ls-tree',head,'--',path).stdout.split()[0]
            require(mode in {'100644','100755'},'Expected tracked regular file')
            oid=self.git.run('hash-object','-w','--stdin',input=raw,binary=True).stdout.decode().strip()
            with tempfile.TemporaryDirectory(dir=self.journal.state) as temporary:
                env={'GIT_INDEX_FILE':str(Path(temporary)/'index')}
                self.git.run('read-tree',before,env_extra=env)
                self.git.run('update-index','--add','--cacheinfo',mode,oid,path,env_extra=env)
                after=self.git.run('write-tree',env_extra=env).stdout.strip()
            record=dict(kind='artifact-stage',operation_id=operation_id,request_digest=digest,base_head=head,
                        branch=branch,paths=[path],blob_oid=oid,file_mode=mode,before_index=before,after_index=after,
                        state='stage-prepared',commit_id=None)
            db.execute('INSERT INTO operations(id,record) VALUES(?,?)',(operation_id,json.dumps(record)));db.commit()
            checkpoint('stage-prepared')
            return self._recover_stage(db,record,checkpoint)

    def restore_working_artifact(self, operation_id, request, prepare, *, checkpoint=lambda stage: None):
        """Restore one reviewed working file; preserve its original bytes in this journal."""
        from spikes.metadata import uuid as validate_uuid
        validate_uuid(operation_id)
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.journal.lock(), self.journal.connect() as db:
            self._writable()
            row = db.execute('SELECT record,done FROM operations WHERE id=?', (operation_id,)).fetchone()
            if row:
                record = json.loads(row[0])
                require(record.get('kind') == 'artifact-working-restore'
                        and record.get('request_digest') == digest,
                        'Operation ID belongs to a different request')
                return record if row[1] else self._recover_working_restore(db, record, checkpoint)
            if self._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
                raise PendingOperation('Recover pending operation first')
            path, before, after, head = prepare(self)
            require(path.startswith('artifacts/') and isinstance(before, bytes) and isinstance(after, bytes),
                    'Expected tracked artifact bytes')
            branch = self._branch()
            require(self.git.head() == head, 'Project changed before working restore')
            require(after == self.git.run('show', head + ':' + path, binary=True).stdout,
                    'Working restore must use the selected committed bytes')
            require(self.journal._prepare(db, {path: after}) == [path], 'Working file has no change to restore')
            require(db.execute('SELECT before FROM pending WHERE path=?', (path,)).fetchone() == (before,),
                    'Working file changed before restore preparation')
            record = dict(kind='artifact-working-restore', operation_id=operation_id,
                request_digest=digest, base_head=head, commit_id=head, branch=branch,
                paths=[path], index_tree=self.git.run('write-tree').stdout.strip(),
                backup_base64=base64.b64encode(before).decode('ascii'),
                backup_sha256=hashlib.sha256(before).hexdigest(), state='restore-prepared')
            db.execute('INSERT INTO operations(id,record) VALUES (?,?)', (operation_id, json.dumps(record)))
            db.commit(); checkpoint('working-restore-prepared')
            return self._recover_working_restore(db, record, checkpoint)

    def _recover_working_restore(self, db, record, checkpoint):
        self._writable()
        require(self._branch() == record['branch'] and self.git.head() == record['base_head'],
                'Working restore base changed; operation retained')
        require(self.git.run('write-tree').stdout.strip() == record['index_tree'],
                'Git staging changed; working restore retained')
        rows = db.execute('SELECT path,before,after FROM pending ORDER BY path').fetchall()
        backup = base64.b64decode(record['backup_base64'], validate=True)
        require(len(rows) == 1 and [rows[0][0]] == record['paths'] and rows[0][1] == backup
                and hashlib.sha256(backup).hexdigest() == record['backup_sha256']
                and rows[0][2] == self.git.run('show', record['base_head'] + ':' + rows[0][0], binary=True).stdout,
                'Working restore intent differs from reviewed bytes')
        self.journal._recover(db, checkpoint, clear=False)
        require(self.git.head() == record['base_head'], 'HEAD changed during working restore')
        record['state'] = 'restored'
        db.execute('DELETE FROM pending')
        db.execute('UPDATE operations SET record=?,done=1 WHERE id=?',
                   (json.dumps(record), record['operation_id']))
        db.commit(); checkpoint('working-restored')
        return record

    def _recover_stage(self,db,record,checkpoint):
        self._writable()
        require(self._branch()==record['branch'] and self.git.head()==record['base_head'],'Stage base changed; operation retained')
        current=self.git.run('write-tree').stdout.strip()
        require(current in {record['before_index'],record['after_index']},'Foreign staging changes; operation retained')
        if current!=record['after_index']:
            self.git.run('update-index','--add','--cacheinfo',record['file_mode'],record['blob_oid'],record['paths'][0])
        checkpoint('stage-indexed')
        require(self._branch()==record['branch'] and self.git.head()==record['base_head'] and
                self.git.run('write-tree').stdout.strip()==record['after_index'],'Stage outcome changed; operation retained')
        record['commit_id']=record['base_head']
        self._save(db,record,'stage-applied');db.execute('UPDATE operations SET done=1 WHERE id=?',(record['operation_id'],));db.commit()
        checkpoint('stage-completed')
        return record

    def recover(self, checkpoint=lambda stage: None):
        with self.journal.lock(), self.journal.connect() as db:
            record = self._active(db)
            if record is None:
                if db.execute('SELECT 1 FROM pending').fetchone():
                    raise PendingOperation('Standalone Journal recovery required')
                return None
            if record.get('kind') == 'external-replication':
                raise PendingOperation('External replication recovery required')
            return self._recover(db, record, checkpoint)

    def read(self):
        """Only expose a validated HEAD projection with no unfinished operation."""
        with self.journal.lock(), self.journal.connect() as db:
            return self._read_locked(db)

    def read_projection(self):
        """Expose committed metadata/relations under the same pending and writer boundary."""
        with self.journal.lock(), self.journal.connect() as db:
            return self._read_locked(db, self.index.read_projection)

    def read_relations(self, entity_id, *, direction='outgoing', relation_type=None):
        from spikes.metadata import uuid as validate_uuid
        validate_uuid(entity_id)
        with self.journal.lock(), self.journal.connect() as db:
            return self._read_locked(db, lambda git: self.index.read_relations(
                git, entity_id, direction=direction, relation_type=relation_type))

    def _read_locked(self, db, query=None, *, expected_head=None):
        if self._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
            raise PendingOperation('Project has an unfinished operation')
        query = query or self.index.read
        try:
            return query(self.git)
        except StaleIndex:
            if expected_head is not None and self.git.head() != expected_head:
                raise StaleIndex('Project changed while reading index')
            self.index.rebuild(self.git)
            return query(self.git)

    def read_project(self, project_id, *, artifact_id=None, expected_head=None, network=False, plan_only=False, dashboard_only=False):
        """Return one committed project view under the shared writer lock."""
        with self.journal.lock(), self.journal.connect() as db:
            if self._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
                raise PendingOperation('Project has an unfinished operation')
            branch = self._branch()
            commit = self.git.head()
            require(not self.git.run('ls-files', '-u').stdout, 'Unresolved merge')
            if expected_head is not None and commit != expected_head:
                raise StaleIndex('Project changed; reopen preview')
            meta = committed_project(self.git, commit, project_id)
            cache_key = None
            if (artifact_id is None and not plan_only and not dashboard_only
                    and not any((self.git.root / '.git' / name).exists()
                                for name in ('shallow', 'info/grafts'))
                    and not self.git.run('for-each-ref', '--count=1', '--format=%(refname)',
                                         'refs/replace/').stdout):
                cache_key = (str(self.git.root), str(self.journal.state), project_id, commit, network)
                cached = _project_view_get(cache_key)
                if cached is not None:
                    current = self._read_locked(db, self.index.read_projection, expected_head=commit)
                    require(current == json.loads(cached[1]), 'Index differs from validated commit')
                    if self.git.head() != commit:
                        raise StaleIndex('HEAD changed while opening cached project; retry')
                    result = json.loads(cached[0])
                    result['conflict_summary'] = self._project_conflict_hint(commit, branch)
                    return result
            files = self.git.snapshot(commit)
            entities = validate_snapshot(files)
            if network:
                require(all(item['privacy'] != 'local-only' for item in entities.values()),
                        'Project contains local-only data')
            view = self._read_locked(db, self.index.read_projection, expected_head=commit)
            if view['commit_id'] != commit:
                raise StaleIndex('Project changed while rebuilding index')
            require(view == projection(files, entities, commit),
                    'Index differs from validated commit')
            rows = [(id_, item['metadata']['title'], item['metadata']['kind'])
                    for id_, item in view['entities'].items()]
            if artifact_id is not None:
                prefix = f'artifacts/{artifact_id}/'
                entries = {p: raw for p, raw in files.items() if p.startswith(prefix)}
                require(entries and artifact_id in entities, 'Artifact is not in this project')
                metadata = entities[artifact_id]
                sidecar = prefix + 'metadata.json' in entries
                path = prefix + metadata['file'] if sidecar else next(iter(entries))
                if self.git.head() != commit:
                    raise StaleIndex('Project changed while reading preview')
                return dict(id=artifact_id, commit_id=commit, metadata=metadata,
                            path=path, raw=entries[path], sidecar=sidecar)
            if dashboard_only:
                todo = main_todo_view(files, entities, project_id)
                if self.git.head() != commit:
                    raise StaleIndex('HEAD changed while reading dashboard; retry')
                return dict(id=project_id, title=meta['title'], commit_id=commit,
                            main_todo_id=main_todo_id(project_id), main_todo=todo)
            plan = project_task_graph(files, entities, project_id, commit)
            if plan_only:
                if self.git.head() != commit:
                    raise StaleIndex('HEAD changed while reading plan; retry')
                return dict(id=project_id, title=meta['title'], commit_id=commit,
                            main_todo_id=main_todo_id(project_id), plan=plan)
            todo = main_todo_view(files, entities, project_id)
            revisions = self.git.run('rev-list', '--topo-order',
                                     f'--max-count={MAX_PROJECT_HISTORY + 1}', commit).stdout.splitlines()
            history = []
            selected = revisions[:MAX_PROJECT_HISTORY]
            for revision in selected:
                require(len(revision) in {40, 64} and all(c in '0123456789abcdef' for c in revision),
                        'Invalid commit ID')
            if selected:
                checked = self.git.run('cat-file', '--batch-check',
                    input=''.join(revision + '\n' for revision in selected)).stdout.splitlines()
                require(len(checked) == len(selected), 'Incomplete commit metadata inventory')
                for revision, row in zip(selected, checked):
                    parts = row.split()
                    require(len(parts) == 3 and parts[:2] == [revision, 'commit']
                            and parts[2].isdecimal() and int(parts[2]) <= MAX_METADATA,
                            'Commit metadata exceeds 64 KiB or differs from inventory')
                fields = self.git.run('log', '--no-walk=unsorted', '-z',
                    '--format=%H%x00%aI%x00%an%x00%s', *selected).stdout.split('\0')
                require(fields[-1] == '' and len(fields) == 4 * len(selected) + 1,
                        'Invalid commit metadata output')
                for index, revision in enumerate(selected):
                    actual, date, author, subject = fields[4 * index:4 * index + 4]
                    require(actual == revision, 'Commit history order changed')
                    history.append(dict(commit_id=revision, date=date, author=author, subject=subject))
            if self.git.head() != commit:
                raise StaleIndex('HEAD changed while opening project; retry')
            artifact_ids = {path.split('/')[1] for path in files if path.startswith('artifacts/')}
            result = dict(id=project_id, title=meta['title'],
                        description=meta.get('description', ''), commit_id=commit,
                        main_todo_id=main_todo_id(project_id), main_todo=todo, plan=plan,
                        history=dict(entries=history, truncated=len(revisions) > MAX_PROJECT_HISTORY),
                        artifacts=[dict(id=id_, title=title, kind=kind)
                                   for id_, title, kind in rows if id_ in artifact_ids])
            if cache_key is not None:
                _project_view_put(cache_key, result, view)
            result['conflict_summary'] = self._project_conflict_hint(commit, branch)
            return result

    def _project_conflict_hint(self, head, branch):
        """Cheap live hint, never a replacement for the full conflict preview."""
        dirty = bool(self.git.run('status', '--porcelain', '--untracked-files=all').stdout)
        branch_name = branch[len('refs/heads/'):]
        incoming = self.git.run('for-each-ref', '--count=101', '--no-merged=' + head,
            '--format=%(refname)', 'refs/federation/incoming/').stdout.splitlines()
        if self.git.head() != head:
            raise StaleIndex('HEAD changed while reading project conflict summary')
        return {'local_changes': dirty,
                'incoming': (101 if len(incoming) > 100 else
                    sum(len(ref.split('/', 5)) == 6 and ref.split('/', 5)[5] == branch_name for ref in incoming))}

    def receipt(self, operation_id):
        with self.journal.lock(), self.journal.connect() as db:
            row = db.execute('SELECT record FROM operations WHERE id=? AND done=1',
                             (operation_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def _check(self, record):
        if self._branch() != record['branch']:
            raise RecoveryConflict('Branch changed; operation retained')
        head = self.git.head()
        if head not in {record['base_head'], record['commit_id']}:
            raise RecoveryConflict('HEAD changed; operation retained')
        if record['state'] in {'committed', 'indexed'} and head != record['commit_id']:
            raise RecoveryConflict('Published HEAD moved backwards; operation retained')
        for parent in record.get('additional_parents', []):
            resolved = self.git.run('rev-parse', '--verify', parent + '^{commit}').stdout.strip()
            require(resolved == parent, 'Additional parent is unavailable')
        if record.get('kind')=='staged-artifact-commit':
            if self.git.run('write-tree').stdout.strip()!=record['index_tree']:
                raise RecoveryConflict('Git staging changed; operation retained')
            return head
        trees = {self.git.run('rev-parse', f"{record['base_head']}^{{tree}}").stdout.strip()}
        if record['commit_id']:
            trees.add(self.git.run('rev-parse', f"{record['commit_id']}^{{tree}}").stdout.strip())
        staged = self.git.run('write-tree').stdout.strip()
        if staged not in trees:
            raise RecoveryConflict('Foreign staging changes; operation retained')
        changed = self.git.run('diff', '--no-renames', '--name-only', '-z', record['base_head'], '--').stdout
        untracked = self.git.run('ls-files', '--others', '--exclude-standard', '-z').stdout
        if (set(filter(None, changed.split('\0'))) | set(filter(None, untracked.split('\0')))) - set(record['paths']):
            raise RecoveryConflict('Foreign working changes; operation retained')
        return head

    def _candidate(self, db, record, checkpoint):
        # Populate a private staging index from journal bytes, never Git clean filters.
        # Only paths owned by this operation differ from the base tree.
        with tempfile.TemporaryDirectory(dir=self.journal.state) as temporary:
            env = {'GIT_INDEX_FILE': str(Path(temporary) / 'index')}
            self.git.run('read-tree', record['base_head'], env_extra=env)
            for path, data in db.execute('SELECT path, after FROM pending ORDER BY path'):
                if data is None:
                    self.git.run('update-index', '--force-remove', '--', path, env_extra=env)
                else:
                    oid = self.git.run('hash-object', '-w', '--stdin', input=data, binary=True).stdout.decode().strip()
                    self.git.run('update-index', '--add', '--cacheinfo', record.get('file_modes',{}).get(path,'100644'), oid, path, env_extra=env)
            tree = self.git.run('write-tree', env_extra=env).stdout.strip()
        base_files = self.git.snapshot(record['base_head'])
        candidate_files = self.git.snapshot(tree)
        entities = validate_transition(base_files, candidate_files,
                                       allow_privacy_relaxation=record.get('allow_privacy_relaxation', False))
        from spikes.reporting_schema import validate_git
        validate_git(self.git, candidate_files, entities, base_files)
        if record.get('kind')=='staged-artifact-commit':
            pid=parse_project(self.git.run('show',record['base_head']+':project.json',binary=True).stdout)['id']
            plan=project_task_graph(candidate_files,entities,pid,record['base_head'])
            require(plan['status'] in {'ready','missing'},plan.get('error','Invalid project plan'))
        identity = {'GIT_AUTHOR_NAME': record['author_name'], 'GIT_AUTHOR_EMAIL': record['author_email'],
                    'GIT_COMMITTER_NAME': record['author_name'], 'GIT_COMMITTER_EMAIL': record['author_email']}
        parents = []
        for parent in [record['base_head'], *record.get('additional_parents', [])]:
            parents.extend(['-p', parent])
        commit = self.git.run('commit-tree', tree, *parents,
                              input=record['message'] + '\n\nWorkspace-Operation: ' + record['operation_id'] + '\n',
                              env_extra=identity).stdout.strip()
        checkpoint('commit-created')
        record['commit_id'] = commit
        self._save(db, record, 'commit-ready')
        checkpoint('commit-ready')

    def _recover(self, db, record, checkpoint):
        if record.get('kind') == 'artifact-working-restore':return self._recover_working_restore(db,record,checkpoint)
        if record.get('kind')=='artifact-stage':return self._recover_stage(db,record,checkpoint)
        adopting=record.get('kind')=='staged-artifact-commit'
        if adopting:self._writable()
        self._check(record)
        if record['commit_id'] is None:
            if not adopting:self.journal._recover(db, checkpoint, clear=False)
            self._save(db, record, 'files-applied')
            checkpoint('files-applied')
            self._check(record)
            self._candidate(db, record, checkpoint)
        # Once a candidate exists, never roll back a subsequent edit to its payload.
        current = snapshot(self.git.root) if not adopting else None
        if not adopting and current != self.git.snapshot(record['commit_id']):
            raise RecoveryConflict('Working projection differs from candidate; operation retained')
        head = self._check(record)
        if head == record['base_head']:
            checkpoint('before-ref')
            self.git.run('update-ref', record['branch'], record['commit_id'], record['base_head'])
            checkpoint('ref-updated')
        self._save(db, record, 'committed')
        checkpoint('committed')
        self._check(record)
        if not adopting:self.git.run('read-tree', record['commit_id'])
        checkpoint('git-indexed')
        indexed = self.index.rebuild(self.git, checkpoint=checkpoint)
        require(indexed == record['commit_id'], 'HEAD changed during index rebuild')
        self._check(record)
        self._save(db, record, 'indexed')
        checkpoint('indexed')
        db.execute('DELETE FROM pending')
        db.execute('UPDATE operations SET done=1 WHERE id=?', (record['operation_id'],))
        db.commit()
        checkpoint('completed')
        return record
