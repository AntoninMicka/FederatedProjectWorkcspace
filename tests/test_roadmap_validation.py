# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only roadmap review closes bundle and live-context checks."""
import tempfile
from collections import Counter
from pathlib import Path
import unittest

from spikes.roadmap_bundle import assemble_bundle, project_files, write_bundle
from spikes.roadmap_validation import _actor, _links, load_bundle, validate_bundle
from spikes.metadata import ValidationError, parse_json
from tests import test_roadmap_bundle as bundle_tests
from tests.test_roadmap_mapping import MappingFixture


class RoadmapValidationTests(MappingFixture, unittest.TestCase):
    def reviewed_fixture(self):
        _, _, value, mapping, roots, service, _, _, _ = bundle_tests.RoadmapBundleTests.fixture_bundle(self, module=True)
        operation, blobs = assemble_bundle(value, mapping, roots, author_id=_actor(service.node_path),
                                           created_at=bundle_tests.WHEN, privacy='project')
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        base = Path(temporary.name); bundle = base/'bundle'
        write_bundle(bundle, operation, blobs)
        classifications = {source['key']: 'project' for source in value['sources']}
        module = next(project for project in operation['projects'] if project['mode'] == 'create-seeded-project')
        return operation, blobs, bundle, service.node_path, classifications, roots, module, base

    def source_review(self, operation, blobs):
        sources, links = [], Counter()
        for project in operation['projects']:
            files = project_files(project, blobs)
            links.update(item['target'] for item in _links(files, project)[2])
            for path, raw in files.items():
                if path.endswith('/sources.json'):
                    sources += [dict(key=item['key'], sha256=item['sha256'], privacy='project',
                                     rationale='Test fixture contains project planning data.')
                                for item in parse_json(raw)['sources']]
        return dict(schema='fpw-roadmap-source-review-v1', bundle_sha256=operation['bundle_sha256'],
                    reviewed_at='2026-10-28T00:00:00Z', source_classifications=sources,
                    external_links=[dict(url=url, occurrences=count, status='reachable',
                                         final_url=url, evidence='Fixture URL review.')
                                    for url, count in sorted(links.items())])

    def test_complete_review_merges_live_snapshot_without_writing(self):
        operation, blobs, bundle, node, classifications, roots, module, base = self.reviewed_fixture()
        before = next(project for project in operation['projects'] if project['mode'] == 'replace-test-plan')['expected_head']
        report = validate_bundle(bundle, node,
                                 locations={module['repository_id']: base/'new-module'},
                                 source_privacy=classifications, source_roots=roots.values())
        self.assertTrue(report['prewrite_checks_passed'])
        self.assertFalse(report['import_ready']); self.assertFalse(report['project_write_performed'])
        self.assertEqual(load_bundle(bundle), (operation, blobs))
        from spikes.projects import Projects
        host = next(project for project in operation['projects'] if project['mode'] == 'replace-test-plan')
        self.assertEqual(Projects(node).repository(host['project_id']).head(), before)
        self.assertFalse((base/'new-module').exists())

    def test_missing_location_and_classification_remain_open(self):
        operation, _, bundle, node, _, roots, _, _ = self.reviewed_fixture()
        report = validate_bundle(bundle, node, source_roots=roots.values())
        statuses = {row['code']: row['status'] for row in report['checks']}
        self.assertEqual(statuses['new-project-location'], 'blocked')
        self.assertTrue(any(code.endswith(':source-privacy') and status == 'needs-review'
                            for code, status in statuses.items()))
        self.assertFalse(report['prewrite_checks_passed'])

    def test_bundle_bound_source_review_closes_privacy_and_external_links(self):
        operation, blobs, bundle, node, _, roots, module, base = self.reviewed_fixture()
        report = validate_bundle(bundle, node, locations={module['repository_id']:base/'module'},
                                 source_roots=roots.values(), source_review=self.source_review(operation, blobs))
        self.assertTrue(report['prewrite_checks_passed'])
        self.assertEqual(report['summary']['needs_review'], 0)
        wrong = self.source_review(operation, blobs); wrong['bundle_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValidationError, 'another bundle'):
            validate_bundle(bundle, node, locations={module['repository_id']:base/'module'},
                            source_roots=roots.values(), source_review=wrong)

    def test_generated_relative_link_is_not_mistaken_for_an_artifact_link(self):
        operation, blobs, *_ = self.reviewed_fixture()
        host = next(project for project in operation['projects'] if project['mode'] == 'replace-test-plan')
        files = project_files(host, blobs)
        path = next(entry['path'] for entry in host['files'] if entry['artifact_role'] == 'main-todo'
                    and entry['role'] != 'metadata')
        files[path] += b'\n[old](WORK_LOG.md)\n[missing](artifacts/00000000-0000-0000-0000-000000000000/content.md)\n'
        relative, broken, external = _links(files, host)
        self.assertEqual(relative[-1]['target'], 'WORK_LOG.md')
        self.assertEqual(broken[-1]['target'], 'artifacts/00000000-0000-0000-0000-000000000000/content.md')
        self.assertEqual(external, [])


if __name__ == '__main__':
    unittest.main()
