"""Single-writer Linux M0 file journal; caller commits/indexes after successful recovery."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import sqlite3
import stat

from spikes.metadata import MAX_FILE, MAX_SNAPSHOT, require, safe_path, validate_snapshot


class RecoveryConflict(RuntimeError):
    pass


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def snapshot(root):
    files = {}
    total = 0
    for section in ('artifacts', 'registries'):
        folder = root / section
        require(not folder.is_symlink(), 'Symlink section')
        if not folder.exists():
            continue
        for parent, directories, names in os.walk(folder, followlinks=False):
            for name in directories + names:
                path = Path(parent) / name
                require(not path.is_symlink(), 'Symlinks are forbidden')
                if path.is_dir():
                    continue
                require(stat.S_ISREG(path.stat().st_mode), 'Non-regular file')
                require(path.stat().st_size <= MAX_FILE, 'File exceeds limit')
                data = path.read_bytes()
                total += len(data)
                require(total <= MAX_SNAPSHOT and len(files) < 10000, 'Snapshot exceeds limit')
                files[path.relative_to(root).as_posix()] = data
    return files


class Journal:
    def __init__(self, root, state):
        self.root = Path(root).resolve(strict=True)
        self.state = Path(state).resolve()
        require(not self.state.is_relative_to(self.root) and not self.root.is_relative_to(self.state),
                'Journal directory must be outside project')
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(self.state.stat().st_dev == self.root.stat().st_dev, 'Journal must be on same filesystem')
        self.database = self.state / 'journal.sqlite'
        with self.lock(), self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS owner (root TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pending (path TEXT PRIMARY KEY, before BLOB, after BLOB);
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, record TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_operation ON operations(done) WHERE done=0;
            ''')
            owner = db.execute('SELECT root FROM owner').fetchone()
            if owner is None:
                db.execute('INSERT INTO owner VALUES (?)', (str(self.root),))
            else:
                require(owner[0] == str(self.root), 'Journal belongs to another project')
        os.chmod(self.database, 0o600)
        sync_dir(self.state)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def lock(self):
        fd = os.open(self.state / 'writer.lock', os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, 'a+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def target(self, relative):
        parts = safe_path(relative)
        require(len(parts) == 3 and parts[0] in {'artifacts', 'registries'}, 'Invalid journal path')
        path = self.root
        for part in parts:
            path = path / part
            require(not path.is_symlink(), 'Symlink target')
        return path

    def apply(self, changes, checkpoint=lambda stage: None):
        """Validate whole resulting projection, persist intent, then roll forward."""
        with self.lock(), self.connect() as db:
            require(not db.execute('SELECT 1 FROM pending LIMIT 1').fetchone(), 'Recovery required')
            require(not db.execute('SELECT 1 FROM operations WHERE done=0').fetchone(),
                    'Workspace recovery required')
            self._prepare(db, changes)
            db.commit()
            checkpoint('prepared')
            self._recover(db, checkpoint)

    def _prepare(self, db, changes):
        before = snapshot(self.root)
        after = dict(before)
        rows = []
        for path, data in sorted(changes.items()):
            self.target(path)
            require(data is None or isinstance(data, bytes), 'Expected bytes or deletion')
            if data is None:
                after.pop(path, None)
            else:
                after[path] = data
            if before.get(path) != data:
                rows.append((path, before.get(path), data))
        validate_snapshot(after)
        db.executemany('INSERT INTO pending VALUES (?, ?, ?)', rows)
        return [row[0] for row in rows]

    def recover(self, checkpoint=lambda stage: None):
        with self.lock(), self.connect() as db:
            require(not db.execute('SELECT 1 FROM operations WHERE done=0').fetchone(),
                    'Workspace recovery required')
            return self._recover(db, checkpoint)

    def _recover(self, db, checkpoint, *, clear=True):
        rows = db.execute('SELECT path, before, after FROM pending ORDER BY path').fetchall()
        if not rows:
            return False
        current = snapshot(self.root)
        final = dict(current)
        # Check every target before modifying any: never overwrite an intervening edit.
        for path, before, after in rows:
            self.target(path)
            if current.get(path) not in (before, after):
                raise RecoveryConflict(f'Intervening edit at {path}; pending operation retained')
            if after is None:
                final.pop(path, None)
            else:
                final[path] = after
        validate_snapshot(final)
        for index, (path, before, after) in enumerate(rows):
            target = self.target(path)
            if after is None:
                target.unlink(missing_ok=True)
                if target.parent.exists():
                    sync_dir(target.parent)
            else:
                for parent in (target.parent.parent, target.parent):
                    parent.mkdir(exist_ok=True)
                    sync_dir(parent.parent)
                temporary = self.state / 'payload.tmp'
                with temporary.open('wb') as handle:
                    os.chmod(temporary, 0o600)
                    handle.write(after)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
                sync_dir(target.parent)
                sync_dir(self.state)
            checkpoint(f'file:{index}')
        validate_snapshot(snapshot(self.root))
        checkpoint('applied')
        if clear:
            db.execute('DELETE FROM pending')
            db.commit()
            checkpoint('completed')
        return True
