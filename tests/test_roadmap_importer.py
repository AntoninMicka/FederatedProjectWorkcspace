# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Reviewed roadmap imports use native receipts and recover at both boundaries."""
from copy import deepcopy
from pathlib import Path
import unittest

from spikes.projects import Projects
from spikes.roadmap_bundle import digest, project_files, write_bundle
from spikes.roadmap_importer import RoadmapImporter
from spikes.roadmap_migration import canonical
from tests.test_roadmap_mapping import MappingFixture
from tests import test_roadmap_validation as validation_tests


class RoadmapImporterTests(MappingFixture, unittest.TestCase):
    def import_fixture(self):
        operation, blobs, _, node, _, roots, module, base = validation_tests.RoadmapValidationTests.reviewed_fixture(self)
        operation = deepcopy(operation)
        module = next(project for project in operation['projects'] if project['mode'] == 'create-seeded-project')
        module['target_location'] = str(base/'imported-module')
        module['location_resolution'] = 'explicit'
        operation['bundle_sha256'] = digest(canonical({key:value for key,value in operation.items()
                                                       if key != 'bundle_sha256'}))
        bundle = base/'import-bundle'; write_bundle(bundle, operation, blobs)
        review = validation_tests.RoadmapValidationTests.source_review(self, operation, blobs)
        host = next(project for project in operation['projects'] if project['mode'] == 'replace-test-plan')
        return operation, blobs, bundle, node, roots, module, host, review, base

    def test_applies_module_then_host_once_and_replays_both_receipts(self):
        operation, blobs, bundle, node, roots, module, host, review, _ = self.import_fixture()
        importer = RoadmapImporter(node)
        first = importer.apply(bundle, review, operation['bundle_sha256'], source_roots=roots.values())
        second = importer.apply(bundle, review, operation['bundle_sha256'], source_roots=roots.values())
        self.assertEqual(first, second)
        module_git = Projects(node).repository(module['project_id'])
        self.assertEqual(module_git.snapshot(module_git.head()), project_files(module, blobs))
        host_git = Projects(node).repository(host['project_id'])
        self.assertNotEqual(host_git.head(), host['expected_head'])
        self.assertEqual(host_git.run('rev-list', '--count', host['expected_head']+'..HEAD').stdout.strip(), '1')

    def test_retry_continues_after_completed_module_without_second_creation(self):
        operation, _, bundle, node, roots, module, host, review, _ = self.import_fixture()
        importer = RoadmapImporter(node)
        with self.assertRaisesRegex(RuntimeError, 'between projects'):
            importer.apply(bundle, review, operation['bundle_sha256'], source_roots=roots.values(),
                           checkpoint=lambda scope, stage: (_ for _ in ()).throw(RuntimeError('between projects'))
                           if scope == 'orchestrator' and stage == 'completed:'+module['operation_id'] else None)
        self.assertEqual(Projects(node).repository(host['project_id']).head(), host['expected_head'])
        receipt = importer.apply(bundle, review, operation['bundle_sha256'], source_roots=roots.values())
        self.assertTrue(receipt['completed'])

    def test_retry_recovers_pending_host_workspace_transaction(self):
        operation, _, bundle, node, roots, _, host, review, _ = self.import_fixture()
        importer = RoadmapImporter(node)
        with self.assertRaisesRegex(RuntimeError, 'host crash'):
            importer.apply(bundle, review, operation['bundle_sha256'], source_roots=roots.values(),
                           checkpoint=lambda scope, stage: (_ for _ in ()).throw(RuntimeError('host crash'))
                           if scope == host['repository_id'] and stage == 'prepared' else None)
        receipt = importer.apply(bundle, review, operation['bundle_sha256'], source_roots=roots.values())
        self.assertTrue(receipt['completed'])
        self.assertNotEqual(Projects(node).repository(host['project_id']).head(), host['expected_head'])

    def test_exact_bundle_confirmation_is_required_before_any_write(self):
        operation, _, bundle, node, roots, module, host, review, _ = self.import_fixture()
        with self.assertRaisesRegex(ValueError, 'confirmation differs'):
            RoadmapImporter(node).apply(bundle, review, '0'*64, source_roots=roots.values())
        self.assertFalse(Path(module['target_location']).exists())
        self.assertEqual(Projects(node).repository(host['project_id']).head(), host['expected_head'])


if __name__ == '__main__':
    unittest.main()
