# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""SQLite contention follows the existing request-local ownership contract."""
from contextlib import contextmanager
import sqlite3

from spikes.request_ownership import ProjectBusy, bounded_project_wait


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
            raise ProjectBusy(resource + ' is busy') from exc
        raise
    finally:
        if db is not None:
            db.close()
