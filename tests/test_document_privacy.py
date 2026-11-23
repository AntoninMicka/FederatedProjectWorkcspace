# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import subprocess
import sys
import unittest
from uuid import uuid4

from spikes.metadata import validate_snapshot
from tests import test_artifacts as fixtures


class DocumentPrivacyTests(unittest.TestCase):
    setUp = fixtures.ArtifactTests.setUp
    request = fixtures.ArtifactTests.request

    def test_classification_preserved_and_relaxation_requires_bound_authorization(self):
        request = self.request() | {'privacy': 'confidential'}
        self.service.save(request, str(uuid4()))
        update = self.request(id_=request['artifact_id'], new=False, body='Edited')
        self.service.save(update, str(uuid4()))
        head = self.git.head()
        self.assertEqual(validate_snapshot(self.git.snapshot(head))[request['artifact_id']]['privacy'], 'confidential')
        relaxed = update | {'base_head': head, 'privacy': 'project'}
        with self.assertRaisesRegex(ValueError, 'výslovné potvrzení'):
            self.service.save(relaxed, str(uuid4()))
        self.assertEqual(head, self.git.head())
        relaxed['authorize_privacy_relaxation'] = True
        operation = str(uuid4()); result = self.service.save(relaxed, operation)
        self.assertEqual(result, self.service.save(relaxed, operation))
        with self.assertRaises(ValueError):
            self.service.save(relaxed | {'authorize_privacy_relaxation': False}, operation)
        self.assertEqual(validate_snapshot(self.git.snapshot(self.git.head()))[request['artifact_id']]['privacy'], 'project')
        self.assertIn('privacy confidential -> project', self.git.run('log', '-1', '--format=%B').stdout)

    def test_authorized_content_and_metadata_recover_together_across_process_crashes(self):
        for stage in ['prepared', 'files-applied', 'ref-updated', 'indexed']:
            with self.subTest(stage=stage):
                request = self.request() | {'privacy': 'confidential'}
                self.service.save(request, str(uuid4()))
                update = self.request(id_=request['artifact_id'], new=False, body='Reviewed content') | {
                    'privacy':'public', 'authorize_privacy_relaxation':True}
                operation = str(uuid4())
                script = '''import json,os,sys
from spikes.artifacts import Artifacts
def checkpoint(stage):
 if stage==sys.argv[4]:os._exit(79)
Artifacts(sys.argv[1]).save(json.loads(sys.argv[2]),sys.argv[3],checkpoint=checkpoint)
'''
                result = subprocess.run([sys.executable, '-c', script, str(self.node), json.dumps(update), operation, stage])
                self.assertEqual(result.returncode, 79)
                self.service.open(self.id)
                receipt = self.service.save(update, operation)
                files = self.git.snapshot(self.git.head())
                self.assertEqual(receipt['commit_id'], self.git.head())
                self.assertEqual(validate_snapshot(files)[request['artifact_id']]['privacy'], 'public')
                self.assertEqual(files[f'artifacts/{request["artifact_id"]}/content.md'], b'Reviewed content')
                self.assertFalse(self.git.run('status', '--porcelain').stdout)

    def test_network_cannot_create_local_only_file(self):
        from spikes.artifact_actions import ArtifactActions
        with self.assertRaisesRegex(ValueError, 'desktop'):
            ArtifactActions(self.node, network=True).save(self.request() | {'privacy':'local-only'}, str(uuid4()))

