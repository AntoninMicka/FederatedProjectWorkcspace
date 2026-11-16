# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Busy hints identify resources without exposing underlying messages."""
import fcntl
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

from spikes.request_ownership import ProjectBusy, bounded_flock, bounded_project_requests
from spikes.sqlite_ownership import sqlite_connection
from spikes.web_administration import ADMIN_JS


class BusyResourceTests(unittest.TestCase):
    def test_native_and_sqlite_contention_preserve_resource_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'owner'
            with path.open('a+b') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX)
                with path.open('a+b') as contender, bounded_project_requests(), self.assertRaises(ProjectBusy) as caught:
                    with bounded_flock(contender, fcntl.LOCK_EX, resource='Project journal'):
                        self.fail('Owner was bypassed')
                self.assertEqual(caught.exception.busy_resource, 'project-journal')
            database = Path(directory) / 'journal.sqlite'
            with sqlite3.connect(database) as owner:
                owner.execute('CREATE TABLE example (value INTEGER)')
                owner.execute('BEGIN IMMEDIATE')
                with bounded_project_requests(), self.assertRaises(ProjectBusy) as caught:
                    with sqlite_connection(database, resource='Content synchronization journal') as other:
                        other.execute('INSERT INTO example VALUES (1)')
                self.assertEqual(caught.exception.busy_resource, 'sync-journal')
                owner.rollback()
                self.assertEqual(owner.execute('SELECT COUNT(*) FROM example').fetchone()[0], 0)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
    def test_browser_busy_text_distinguishes_remote_resource_and_unknown(self):
        function = ADMIN_JS.split('function contentSyncBusyText(status){', 1)[1].split('\nfunction ', 1)[0]
        program = 'function contentSyncBusyText(status){' + function + '''
const values=[{}, {phase:'download'}, {phase:'download',busy_resource:'sync-journal'},
 {phase:'wait-lock',busy_resource:'outbound-capacity'},
 {phase:'download',busy_resource:'__proto__'}, {busy_resource:'secret-token'}];
console.log(JSON.stringify(values.map(diagnostic=>contentSyncBusyText({diagnostic}))));
'''
        result = subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True)
        values = json.loads(result.stdout)
        self.assertIn('dostupný prostředek', values[0])
        self.assertIn('protistrana přenos dočasně odmítla', values[1])
        self.assertIn('protistrana: SQLite journal synchronizace', values[2])
        self.assertIn('odchozí linka uzlu', values[3])
        self.assertNotIn('protistrana:', values[3])
        self.assertEqual(values[1], values[4])
        self.assertNotIn('secret-token', values[5])
        self.assertNotIn('projekt je zaneprázdněný', str(values))
