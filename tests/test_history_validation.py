# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from spikes.git_budget import GitDeadlineExceeded, git_budget
from spikes.history_validation import validate_histories, _capacity, _validate
from spikes.request_ownership import ProjectBusy
from tests import test_git_transfer as transfer_tests


class HistoryValidationTests(unittest.TestCase):
    def setUp(self):
        fixture = transfer_tests.GitTransferHistoryTests('test_transfer_history_rejects_immutable_source_rewrite')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.git, self.project = fixture.git, fixture.project_id

    def validate(self):
        return validate_histories(self.git, [self.git.head()], self.project, {'public'})

    def test_real_worker_validates_again_and_rejects_unclassified_history(self):
        self.validate()
        (self.git.root / 'unclassified.txt').write_text('Not transferable')
        self.git.commit('Unexpected file')
        with self.assertRaisesRegex(ValueError, 'Unclassified historical file'):
            self.validate()

    def test_capacity_rejects_without_waiting_and_is_reusable(self):
        self.assertTrue(_capacity.acquire(blocking=False))
        try:
            with self.assertRaises(ProjectBusy) as error:
                self.validate()
            self.assertEqual(error.exception.busy_resource, 'history-validation')
        finally:
            _capacity.release()
        self.validate()

    def test_timeout_reaps_worker_and_git_children_and_releases_capacity(self):
        pidfile = self.fixture.root.parent / 'grandchild.pid'
        code = ('import subprocess,sys,time;from pathlib import Path;'
                'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);'
                f'Path({str(pidfile)!r}).write_text(str(child.pid));time.sleep(30)')
        native = subprocess.Popen
        children = []
        def launch(command, **kwargs):
            process = native([sys.executable, '-c', code], **kwargs)
            children.append(process)
            return process
        with patch('spikes.history_validation._popen', side_effect=launch):
            with self.assertRaises(GitDeadlineExceeded):
                with git_budget(.5):
                    self.validate()
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(pidfile.exists())
        path = Path('/proc') / pidfile.read_text() / 'stat'
        try:
            state = path.read_text().rsplit(')', 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            state = None  # The kernel may reap it during the /proc read.
        self.assertIn(state, (None, 'Z'))
        self.validate()

    def test_malformed_reply_is_transient_not_a_validation_success(self):
        native = subprocess.Popen
        def launch(command, **kwargs):
            return native([sys.executable, '-c', 'print("{}")'], **kwargs)
        with patch('spikes.history_validation._popen', side_effect=launch):
            with self.assertRaises(ProjectBusy) as error:
                self.validate()
        self.assertEqual(error.exception.busy_resource, 'history-validation')
        self.validate()

    def test_failure_to_start_worker_is_transient_and_releases_capacity(self):
        with patch('spikes.history_validation._popen', side_effect=OSError('Unavailable')):
            with self.assertRaises(ProjectBusy) as error:
                self.validate()
        self.assertEqual(error.exception.busy_resource, 'history-validation')
        self.validate()

    def test_all_heads_share_one_absolute_worker_deadline(self):
        now = time.monotonic(); clock = [now]
        def validation(*args):
            clock[0] += 35
        request = dict(repo=str(self.git.root), heads=[self.git.head()] * 2,
                       project_id=self.project, privacy=['public'], deadline=now + 60)
        with patch('spikes.git_budget.time.monotonic', side_effect=lambda: clock[0]), \
             patch('spikes.git_transfer.validate_history', side_effect=validation) as native:
            with self.assertRaises(GitDeadlineExceeded):
                _validate(request)
        self.assertEqual(native.call_count, 2)

    def test_cpu_worker_leaves_project_and_node_http_requests_available(self):
        from spikes.desktop_management import DesktopManagementHandler
        from spikes.local_api import running_api
        from spikes.projects import Projects
        from tests.test_project_http_ownership import ProjectHTTPOwnershipTests
        ready = self.fixture.root.parent / 'ready'
        release = self.fixture.root.parent / 'release'
        code = ('import os,time;from pathlib import Path;os.nice(10);'
                f'Path({str(ready)!r}).touch();finish=Path({str(release)!r});'
                'deadline=time.monotonic()+15\n'
                'while not finish.exists() and time.monotonic()<deadline:\n'
                ' for i in range(10000): x=i*i\n'
                'print(\'{"outcome":"ok","message":""}\')')
        native = subprocess.Popen
        errors = []
        def launch(command, **kwargs):
            return native([sys.executable, '-c', code], **kwargs)
        def validate():
            try: self.validate()
            except Exception as exc: errors.append(exc)
        projects = Projects(self.fixture.node)
        with running_api('http', handler=DesktopManagementHandler, projects=projects) as server:
            with patch('spikes.history_validation._popen', side_effect=launch):
                thread = threading.Thread(target=validate); thread.start()
                try:
                    deadline = time.monotonic() + 3
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(ready.exists())
                    # Actual native project read through the authenticated HTTP
                    # adapter while a separate process is actively burning CPU.
                    code_, view, _ = ProjectHTTPOwnershipTests.post(
                        self, server, '/v1/projects/open', {'project_id': self.project})
                    self.assertEqual(code_, 200, view)
                    self.assertEqual(ProjectHTTPOwnershipTests.post(
                        self, server, '/v1/counter', {'action': 'increment'})[0], 200)
                    self.assertTrue(thread.is_alive())
                    self.assertFalse(release.exists())
                finally:
                    release.touch(); thread.join(5)
        self.assertFalse(thread.is_alive()); self.assertEqual(errors, [])
