# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Semantic source validation for transferable Git history."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.git_transfer import validate_history
from spikes.project_creation import ProjectCreation
from spikes.source_import import Sources, request_from_file
from spikes.storage import Git


class GitTransferHistoryTests(unittest.TestCase):
    def test_linear_history_reads_each_snapshot_once_per_validation(self):
        commits = self.git.run('rev-list', self.git.head()).stdout.splitlines()
        with patch.object(self.git, 'snapshot', wraps=self.git.snapshot) as read:
            self.assertEqual(validate_history(self.git, self.git.head(), self.project_id), len(commits))
        self.assertEqual([call.args[0] for call in read.call_args_list], commits)
        # A later transfer must read and validate again, not trust an old cache.
        with patch.object(self.git, 'snapshot', wraps=self.git.snapshot) as read:
            validate_history(self.git, self.git.head(), self.project_id)
        self.assertEqual([call.args[0] for call in read.call_args_list], commits)

    def test_history_cannot_return_success_after_semantic_validation_expires(self):
        import time
        from spikes.git_budget import GitDeadlineExceeded
        from spikes.reporting_schema import validate_git
        clock = [time.monotonic()]
        original_head = self.git.head()
        def delayed_validation(*args, **kwargs):
            result = validate_git(*args, **kwargs)
            clock[0] += 61
            return result
        with patch('spikes.git_budget.time.monotonic', side_effect=lambda: clock[0]), \
             patch('spikes.reporting_schema.validate_git', side_effect=delayed_validation):
            with self.assertRaises(GitDeadlineExceeded):
                validate_history(self.git, original_head, self.project_id)
        self.assertEqual(self.git.head(), original_head)
        self.assertGreaterEqual(validate_history(self.git, original_head, self.project_id), 2)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.node, self.root = base / 'node.json', base / 'project'
        created = ProjectCreation(self.node).create('Transfer', str(self.root), str(uuid4()))
        self.project_id = created['id']; self.git = Git(self.root)
        source = base / 'public.pdf'; source.write_bytes(b'%PDF-1.7\noriginal\n')
        request = request_from_file(self.project_id, self.git.head(), str(source), 'Public', '', [], 'public')
        Sources(self.node).import_source(request, str(uuid4()))
        self.artifact_id, self.filename = request['artifact_id'], request['filename']

    def test_transfer_history_rejects_immutable_source_rewrite(self):
        self.assertGreaterEqual(validate_history(self.git, self.git.head(), self.project_id), 2)
        path = self.root / 'artifacts' / self.artifact_id / self.filename
        path.write_bytes(b'%PDF-1.7\nrewritten\n')
        metadata = self.root / 'artifacts' / self.artifact_id / 'metadata.json'
        value = json.loads(metadata.read_text())
        import hashlib
        value['import']['content_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        metadata.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
        self.git.commit('Bypass application invariant')
        with self.assertRaisesRegex(ValueError, 'Immutable source'):
            validate_history(self.git, self.git.head(), self.project_id)


if __name__ == '__main__':
    unittest.main()
