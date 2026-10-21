# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Semantic source validation for transferable Git history."""
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.git_transfer import validate_history
from spikes.project_creation import ProjectCreation
from spikes.source_import import Sources, request_from_file
from spikes.storage import Git


class GitTransferHistoryTests(unittest.TestCase):
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
