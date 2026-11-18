# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""SQLite contention follows the existing request-local ownership contract."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from spikes.request_ownership import ProjectBusy, bounded_project_wait, busy_resource_for


@contextmanager
def sqlite_connection(database, *, resource, timeout=5, **options):
    """Do not park HTTP workers on SQLite locks; preserve native transactions.

    Only SQLite BUSY/LOCKED become typed busy outcomes. Rollback/close precede
    translation; completed commits and earlier journal stages remain durable.
    No retries, migrations, schema changes or connection pooling are introduced.
    """
    bounded = bounded_project_wait.get()
    db = None
    try:
        db = sqlite3.connect(database, timeout=0 if bounded else timeout, **options)
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
        return sqlite3.connect(path.absolute().as_uri() + '?mode=ro', uri=True, timeout=timeout)
    return sqlite3.connect(path, timeout=timeout)


def readonly_refused(exc):
    """A read-only open met initialization or migration work: use the writer path."""
    return (isinstance(exc, sqlite3.OperationalError)
            and getattr(exc, 'sqlite_errorcode', 0) & 0xff == sqlite3.SQLITE_READONLY)
