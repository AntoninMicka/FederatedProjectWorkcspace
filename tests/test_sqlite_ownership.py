# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from spikes.request_ownership import ProjectBusy, bounded_project_requests
from spikes.sqlite_ownership import sqlite_connection


class SQLiteOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'state.sqlite'
        with sqlite_connection(self.path, resource='Test') as db:
            db.execute('CREATE TABLE entries (value TEXT)')

    def test_request_context_preserves_native_policy_after_exit(self):
        for bounded, expected in ((False, 2000), (True, 0), (False, 2000)):
            def inspect():
                with sqlite_connection(self.path, resource='Test', timeout=2) as db:
                    self.assertEqual(db.execute('PRAGMA busy_timeout').fetchone()[0], expected)
            if bounded:
                with bounded_project_requests():
                    inspect()
            else:
                inspect()

    def test_exclusive_reader_collision_is_busy_and_connection_is_released(self):
        with closing(sqlite3.connect(self.path)) as owner:
            owner.execute('BEGIN EXCLUSIVE')
            started = time.monotonic()
            with bounded_project_requests(), self.assertRaises(ProjectBusy) as caught:
                with sqlite_connection(self.path, resource='Test') as db:
                    db.execute('SELECT * FROM entries').fetchall()
            self.assertLess(time.monotonic() - started, .5)
            self.assertEqual(caught.exception.outcome, 'unknown')
            owner.rollback()
        with sqlite_connection(self.path, resource='Test') as db:
            db.execute('BEGIN EXCLUSIVE')

    def test_extended_shared_cache_locked_code_is_busy(self):
        uri = self.path.as_uri() + '?cache=shared'
        with closing(sqlite3.connect(uri, uri=True)) as owner:
            owner.execute('BEGIN IMMEDIATE')
            owner.execute("INSERT INTO entries VALUES ('locked')")
            with bounded_project_requests(), self.assertRaises(ProjectBusy) as caught:
                with sqlite_connection(uri, uri=True, resource='Test') as db:
                    db.execute('SELECT * FROM entries').fetchall()
            self.assertEqual(caught.exception.__cause__.sqlite_errorcode & 0xff,
                             sqlite3.SQLITE_LOCKED)
            owner.rollback()

    def test_busy_commit_rolls_back_unpublished_rows(self):
        with closing(sqlite3.connect(self.path)) as reader:
            reader.execute('BEGIN')
            reader.execute('SELECT * FROM entries').fetchall()
            with bounded_project_requests(), self.assertRaises(ProjectBusy):
                with sqlite_connection(self.path, resource='Test') as db:
                    db.execute("INSERT INTO entries VALUES ('unpublished')")
            reader.rollback()
        with sqlite_connection(self.path, resource='Test') as db:
            self.assertEqual(db.execute('SELECT * FROM entries').fetchall(), [])
            db.execute("INSERT INTO entries VALUES ('next')")

    def test_non_contention_sql_errors_are_not_busy(self):
        with bounded_project_requests(), self.assertRaises(sqlite3.OperationalError):
            with sqlite_connection(self.path, resource='Test') as db:
                db.execute('SELECT * FROM missing_table')

    def test_native_contention_preserves_sqlite_exception_and_timeout(self):
        with closing(sqlite3.connect(self.path)) as owner:
            owner.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(sqlite3.OperationalError):
                with sqlite_connection(self.path, resource='Test', timeout=.01) as db:
                    db.execute('SELECT * FROM entries')

    def test_rollback_and_close_on_application_failure(self):
        with self.assertRaises(ValueError):
            with sqlite_connection(self.path, resource='Test') as db:
                db.execute("INSERT INTO entries VALUES ('rollback')")
                raise ValueError('Abort')
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')
        with sqlite_connection(self.path, resource='Test') as reopened:
            self.assertEqual(reopened.execute('SELECT * FROM entries').fetchall(), [])
