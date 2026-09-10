"""Coordinated Linux M0 operations in controlled, initialized Git repositories."""
import hashlib
import json
from pathlib import Path
import tempfile
import uuid

from spikes.configuration import committed_project
from spikes.markdown_documents import main_todo_view
from spikes.journal import Journal, RecoveryConflict, snapshot
from spikes.metadata import require, validate_snapshot
from spikes.storage import Git, Index, StaleIndex


class PendingOperation(RuntimeError):
    pass


class Workspace:
    def __init__(self, root, state, *, blocking=True, deadline=None):
        self.journal = Journal(root, state, blocking=blocking)
        self.git = Git(self.journal.root, deadline=deadline)
        self.index = Index(self.journal.state / 'index.sqlite')

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
            return self._apply_locked(db, changes, author_name, author_email, message, checkpoint)

    def transact(self, operation_id, request, prepare, *, expected_head=None, checkpoint=lambda stage: None):
        """Bind a native request to one durable operation, including lost-response retries.

        prepare runs under the writer lock, only for a new request, and returns
        (changes, author_name, author_email, message) after checking its base HEAD.
        """
        from spikes.metadata import uuid as validate_uuid
        validate_uuid(operation_id)
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.journal.lock(), self.journal.connect() as db:
            row = db.execute('SELECT record, done FROM operations WHERE id=?', (operation_id,)).fetchone()
            if row:
                record = json.loads(row[0])
                require(record.get('request_digest') == digest, 'Operation ID belongs to a different request')
                return record if row[1] else self._recover(db, record, checkpoint)
            if self._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
                raise PendingOperation('Recover the pending operation first')
            changes, name, email, message = prepare(self)
            return self._apply_locked(db, changes, name, email, message, checkpoint,
                                      operation_id=operation_id, request_digest=digest, expected_head=expected_head)

    def _apply_locked(self, db, changes, author_name, author_email, message, checkpoint,
                      *, operation_id=None, request_digest=None, expected_head=None):
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
        require(not self.git.run('status', '--porcelain', '--untracked-files=all').stdout,
                'Clean worktree and staging index required')
        require(snapshot(self.git.root) == self.git.snapshot(base),
                'Working projection differs from HEAD (including ignored files)')
        paths = self.journal._prepare(db, changes)
        require(bool(paths), 'Operation has no changes')
        record = dict(operation_id=operation_id or str(uuid.uuid4()), base_head=base, branch=branch,
                      paths=paths, author_name=author_name, author_email=author_email,
                      message=message, state='prepared', commit_id=None, request_digest=request_digest)
        db.execute('INSERT INTO operations(id, record) VALUES (?, ?)',
                   (record['operation_id'], json.dumps(record)))
        db.commit()
        checkpoint('prepared')
        return self._recover(db, record, checkpoint)

    def recover(self, checkpoint=lambda stage: None):
        with self.journal.lock(), self.journal.connect() as db:
            record = self._active(db)
            if record is None:
                if db.execute('SELECT 1 FROM pending').fetchone():
                    raise PendingOperation('Standalone Journal recovery required')
                return None
            return self._recover(db, record, checkpoint)

    def read(self):
        """Only expose a validated HEAD projection with no unfinished operation."""
        with self.journal.lock(), self.journal.connect() as db:
            return self._read_locked(db)

    def _read_locked(self, db):
        if self._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
            raise PendingOperation('Project has an unfinished operation')
        try:
            return self.index.read(self.git)
        except StaleIndex:
            self.index.rebuild(self.git)
            return self.index.read(self.git)

    def read_project(self, project_id):
        """Return one committed project view under the shared writer lock."""
        with self.journal.lock(), self.journal.connect() as db:
            if self._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
                raise PendingOperation('Project has an unfinished operation')
            self._branch()
            commit = self.git.head()
            require(not self.git.run('ls-files', '-u').stdout, 'Unresolved merge')
            meta = committed_project(self.git, commit, project_id)
            files = self.git.snapshot(commit)
            entities = validate_snapshot(files)
            rows = self._read_locked(db)
            require(rows == sorted((item['id'], item['title']) for item in entities.values()),
                    'Index differs from validated commit')
            todo = main_todo_view(files, entities, project_id)
            if self.git.head() != commit:
                raise StaleIndex('HEAD changed while opening project; retry')
            artifact_ids = {path.split('/')[1] for path in files if path.startswith('artifacts/')}
            return dict(id=project_id, title=meta['title'], commit_id=commit, main_todo=todo,
                        artifacts=[dict(id=id_, title=title) for id_, title in rows if id_ in artifact_ids])

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
                    self.git.run('update-index', '--add', '--cacheinfo', '100644', oid, path, env_extra=env)
            tree = self.git.run('write-tree', env_extra=env).stdout.strip()
        validate_snapshot(self.git.snapshot(tree))
        identity = {'GIT_AUTHOR_NAME': record['author_name'], 'GIT_AUTHOR_EMAIL': record['author_email'],
                    'GIT_COMMITTER_NAME': record['author_name'], 'GIT_COMMITTER_EMAIL': record['author_email']}
        commit = self.git.run('commit-tree', tree, '-p', record['base_head'],
                              input=record['message'] + '\n\nWorkspace-Operation: ' + record['operation_id'] + '\n',
                              env_extra=identity).stdout.strip()
        checkpoint('commit-created')
        record['commit_id'] = commit
        self._save(db, record, 'commit-ready')
        checkpoint('commit-ready')

    def _recover(self, db, record, checkpoint):
        self._check(record)
        if record['commit_id'] is None:
            self.journal._recover(db, checkpoint, clear=False)
            self._save(db, record, 'files-applied')
            checkpoint('files-applied')
            self._check(record)
            self._candidate(db, record, checkpoint)
        # Once a candidate exists, never roll back a subsequent edit to its payload.
        current = snapshot(self.git.root)
        if current != self.git.snapshot(record['commit_id']):
            raise RecoveryConflict('Working projection differs from candidate; operation retained')
        head = self._check(record)
        if head == record['base_head']:
            checkpoint('before-ref')
            self.git.run('update-ref', record['branch'], record['commit_id'], record['base_head'])
            checkpoint('ref-updated')
        self._save(db, record, 'committed')
        checkpoint('committed')
        self._check(record)
        self.git.run('read-tree', record['commit_id'])
        checkpoint('git-indexed')
        indexed = self.index.rebuild(self.git)
        require(indexed == record['commit_id'], 'HEAD changed during index rebuild')
        self._check(record)
        self._save(db, record, 'indexed')
        checkpoint('indexed')
        db.execute('DELETE FROM pending')
        db.execute('UPDATE operations SET done=1 WHERE id=?', (record['operation_id'],))
        db.commit()
        checkpoint('completed')
        return record
