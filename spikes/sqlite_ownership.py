# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""SQLite contention follows the existing request-local ownership contract."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from spikes.request_ownership import ProjectBusy, bounded_project_wait, busy_resource_for

# Inside an HTTP request SQLite waits this long for a concurrent writer before
# reporting typed busy. Local transactions are short; a zero wait turned every
# background write into a failed request (ADR 0050, addendum AUDIT-B7-T1).
BOUNDED_SQLITE_WAIT = 2


@contextmanager
def sqlite_connection(database, *, resource, timeout=5, **options):
    """Wait at most BOUNDED_SQLITE_WAIT in HTTP workers; preserve native transactions.

    Only SQLite BUSY/LOCKED become typed busy outcomes. Rollback/close precede
    translation; completed commits and earlier journal stages remain durable.
    No retries, migrations, schema changes or connection pooling are introduced.
    """
    bounded = bounded_project_wait.get()
    db = None
    try:
        db = sqlite3.connect(database, timeout=min(timeout, BOUNDED_SQLITE_WAIT) if bounded else timeout,
                             **options)
        with db:
            yield db
    except sqlite3.OperationalError as exc:
        code = getattr(exc, 'sqlite_errorcode', 0) & 0xff
        if bounded and code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise ProjectBusy(resource + ' is busy', resource=busy_resource_for(resource, 'sqlite')) from exc
        raise
    finally:
        if db is not None:
            db.close()


def store_connection(path, unsafe_message, *, readonly=False, timeout=30):
    """Open a private local SQLite store; readers never create or migrate it.

    The writer path keeps its O_CREAT bootstrap. A reader returns None for an
    absent store and opens an existing one with mode=ro, so the caller's own
    schema validation runs without a writer transaction (AUDIT-B2-T1).
    """
    import os
    import stat
    from spikes.metadata import require
    path = Path(path)
    if readonly:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return None
    else:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and info.st_nlink == 1 and not info.st_mode & 0o077, unsafe_message)
    if readonly:
        return bounded_connect(path.absolute().as_uri() + '?mode=ro', uri=True, timeout=timeout,
                               resource=unsafe_message.removeprefix('Unsafe '))
    return bounded_connect(path, timeout=timeout, resource=unsafe_message.removeprefix('Unsafe '))


def readonly_refused(exc):
    """A read-only open met initialization or migration work: use the writer path."""
    return (isinstance(exc, sqlite3.OperationalError)
            and getattr(exc, 'sqlite_errorcode', 0) & 0xff == sqlite3.SQLITE_READONLY)


def _translated(connection, call, *args):
    try:
        return call(*args)
    except sqlite3.OperationalError as exc:
        code = getattr(exc, 'sqlite_errorcode', 0) & 0xff
        if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise ProjectBusy(connection.fpw_resource + ' is busy',
                              resource=busy_resource_for(connection.fpw_resource, 'sqlite')) from exc
        raise


class _BoundedCursor(sqlite3.Cursor):
    def execute(self, *args):
        return _translated(self.connection, super().execute, *args)

    def executemany(self, *args):
        return _translated(self.connection, super().executemany, *args)

    def executescript(self, *args):
        return _translated(self.connection, super().executescript, *args)


class _BoundedConnection(sqlite3.Connection):
    """HTTP-bounded connection: no SQLite wait, BUSY/LOCKED as typed ProjectBusy.

    The native transaction is unchanged: an interrupted statement or commit is
    rolled back by SQLite or by the caller's own transaction handling.
    """
    fpw_resource = 'Local SQLite store'

    def cursor(self, factory=_BoundedCursor):
        return super().cursor(factory)

    def execute(self, *args):
        return _translated(self, super().execute, *args)

    def executemany(self, *args):
        return _translated(self, super().executemany, *args)

    def executescript(self, *args):
        return _translated(self, super().executescript, *args)

    def commit(self):
        return _translated(self, super().commit)

    def __exit__(self, *exc):
        return _translated(self, super().__exit__, *exc)


def bounded_connect(database, *, resource='Local SQLite store', timeout=5, **options):
    """Direct sqlite3.connect under the request-local bounded wait (AUDIT-B2-T2, A09).

    Outside HTTP requests the connection and its timeout are unchanged. Inside a
    bounded request SQLite waits at most BOUNDED_SQLITE_WAIT, and BUSY/LOCKED
    become ProjectBusy instead of parking the worker for up to the native timeout.
    """
    if not bounded_project_wait.get():
        return sqlite3.connect(database, timeout=timeout, **options)
    if 'factory' in options:
        raise ValueError('Bounded SQLite connection cannot take a custom factory')
    db = sqlite3.connect(database, timeout=min(timeout, BOUNDED_SQLITE_WAIT),
                         factory=_BoundedConnection, **options)
    db.fpw_resource = resource
    return db
