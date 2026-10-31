# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Accepted rebuilds adapt to native bundles without writing live projects."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.markdown_documents import main_todo_id
from spikes.project_creation import ProjectCreation
from spikes.roadmap_migration import canonical, inventory
from spikes.roadmap_rebuild_bundle import (accepted_rebuild, assemble_rebuild_bundle,
                                           local_author_id, rebind_source_review)
from spikes.roadmap_import_evidence import audit_import_evidence
from spikes.roadmap_importer import RoadmapImporter
from spikes.roadmap_validation import load_bundle, validate_bundle
from tests.fixtures import AUTHOR
from tests.test_roadmap_mapping import MappingFixture
from tests import test_roadmap_validation as validation_tests


class RoadmapRebuildBundleTests(MappingFixture, unittest.TestCase):
    def fixture_run(self):
        source = self.fixture(); value = inventory(source.root)
        roadmap = next(item for item in value['sources']
                       if item['path'].endswith('základní roadmapa.md'))
        block_id = str(uuid4())
        catalog = {'schema': 'fpw-roadmap-source-catalog-v1',
                   'revision': 'source-first-v2',
                   'inventory_sha256': value['inventory_sha256'],
                   'sources': [item for item in value['sources']
                               if item['role'] in {'requirements', 'active', 'backlog', 'history'}
                               and item['path'].endswith('.md')],
                   'blocks': [{'block_id': block_id, 'source': roadmap['key'],
                               'repository_id': 'federated-workspace', 'role': 'requirements',
                               'order': 0, 'title': 'Roadmap', 'line_start': 1, 'line_end': 10,
                               'sha256': '0'*64, 'allowed_source_ids': [],
                               'reference_source_ids': [], 'text': '# Roadmap',
                               'previous': None, 'next': None}],
                   'summary': {'source_files': 4, 'blocks': 1, 'source_bytes': 1}}
        catalog['catalog_sha256'] = hashlib.sha256(canonical(catalog)).hexdigest()
        provenance = {'block_id': block_id, 'source': roadmap['key'], 'role': 'requirements',
                      'order': 0, 'line_start': 1, 'line_end': 1}
        nodes = [
            dict(entity_key='e1', kind='milestone', source_ids=['M1'], title='Milník',
                 status='planned', maturity='designed', line_start=1, line_end=1,
                 summary='Milník.', candidate_id='MILESTONE-M1',
                 repository_id='federated-workspace', parent_id=None, depends_on=[],
                 provenance=provenance, provenance_all=[provenance], variants=[]),
            dict(entity_key='e2', kind='batch', source_ids=['DEV-01'], title='Dávka',
                 status='completed', maturity='implemented', line_start=2, line_end=2,
                 summary='Dávka.', candidate_id='DEV-01',
                 repository_id='federated-workspace', parent_id='MILESTONE-M1', depends_on=[],
                 provenance=provenance, provenance_all=[provenance], variants=[]),
            dict(entity_key='e3', kind='task', source_ids=['DEV-01-A'], title='Úkol',
                 status='planned', maturity='designed', line_start=3, line_end=3,
                 summary='Úkol.', candidate_id='DEV-01-A',
                 repository_id='federated-workspace', parent_id='DEV-01', depends_on=[],
                 provenance=provenance, provenance_all=[provenance], variants=[])]
        support = [dict(entity_key='e4', kind='description', source_ids=[], title='Kontext',
                        status='unknown', maturity='unknown', line_start=4, line_end=4,
                        summary='Zachovaný volný popis.', candidate_id=None,
                        repository_id='federated-workspace', parent_id='DEV-01', depends_on=[],
                        provenance=provenance),
                   dict(entity_key='e5', kind='history', source_ids=[], title='Volná historie',
                        status='unknown', maturity='unknown', line_start=5, line_end=5,
                        summary='Samostatný [historický](TODO.md) podklad.', candidate_id=None,
                        repository_id='federated-workspace', parent_id=None, depends_on=[],
                        provenance=provenance)]
        candidate = {'schema': 'fpw-roadmap-rebuild-candidate-v1', 'nodes': nodes,
                     'supporting_records': support, 'normalizations': [],
                     'resolution_warnings': [], 'issues': [], 'ready': True}
        candidate['candidate_sha256'] = hashlib.sha256(canonical(candidate)).hexdigest()
        report = {'schema': 'fpw-roadmap-rebuild-report-v1', 'blocks': 1,
                  'catalog_sha256': catalog['catalog_sha256'],
                  'candidate_sha256': candidate['candidate_sha256'],
                  'candidate_ready': True, 'candidate_issues': [], 'import_ready': True,
                  'fidelity': 100.0, 'scores': {}, 'verdicts': {'correct': 1},
                  'audit_overrides': []}
        manifest = {'schema': 'fpw-roadmap-source-rebuild-v1',
                    'catalog_sha256': catalog['catalog_sha256']}
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        base = Path(temporary.name); run = base/'run'; run.mkdir()
        for name, content in [('catalog.json', catalog), ('candidate.json', candidate),
                              ('report.json', report), ('manifest.json', manifest)]:
            (run/name).write_text(json.dumps(content), encoding='utf-8')
        node = base/'node.json'
        created = ProjectCreation(node).create('Target', str(base/'target'), AUTHOR)
        project_id = created['id']
        saved = Artifacts(node).save(dict(project_id=project_id,
            artifact_id=main_todo_id(project_id), base_head=created['commit_id'],
            title='Test', body='TEST ROADMAP\n', new=True, metadata={}), AUTHOR)
        return source, run, node, project_id, saved['commit_id'], base

    def test_accepted_rebuild_becomes_native_unapplied_bundle(self):
        source, run, node, project_id, head, base = self.fixture_run()
        output = base/'bundle'
        operation, mapping = assemble_rebuild_bundle(run,
            {'federated-workspace': source.root}, node, project_id,
            author_id=AUTHOR, privacy='project', output=output,
            created_at='2026-10-30T12:00:00Z')
        loaded, blobs = load_bundle(output)
        self.assertEqual(operation, loaded)
        self.assertEqual(mapping['rebuild']['candidate_sha256'],
                         json.loads((run/'candidate.json').read_text())['candidate_sha256'])
        self.assertFalse(operation['project_write_performed'])
        self.assertFalse(operation['import_ready'])
        self.assertEqual(Artifacts(node).open(project_id)['commit_id'], head)
        project = operation['projects'][0]
        self.assertEqual(project['mode'], 'replace-test-plan')
        self.assertEqual(project['expected_head'], head)
        self.assertEqual(project['summary']['node_types'],
                         {'batch': 1, 'milestone': 1, 'task': 1})
        self.assertTrue(any(entry['artifact_role'] == 'free-description'
                            for entry in project['files']))
        self.assertTrue(blobs)

    def test_candidate_tampering_is_rejected_before_bundle_output(self):
        _, run, *_ = self.fixture_run()
        candidate = json.loads((run/'candidate.json').read_text())
        candidate['nodes'][0]['title'] = 'Tampered'
        (run/'candidate.json').write_text(json.dumps(candidate), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'digest differs'):
            accepted_rebuild(run)

    def test_review_rebind_requires_explicit_decision_for_changed_source(self):
        source, run, node, project_id, _, base = self.fixture_run()
        output = base/'bundle-review'
        operation, _ = assemble_rebuild_bundle(run, {'federated-workspace': source.root},
            node, project_id, author_id=AUTHOR, privacy='project', output=output,
            created_at='2026-10-30T12:00:00Z')
        project = operation['projects'][0]
        manifest_path = next(entry['path'] for entry in project['files']
                             if entry['path'].endswith('/sources.json'))
        manifest = json.loads((output/project['payload_directory']/manifest_path).read_text())
        rows = [dict(key=item['key'], sha256=item['sha256'], privacy='project',
                     rationale='Reviewed fixture source.') for item in manifest['sources']]
        changed = rows[0]; changed['sha256'] = '0'*64
        prior = base/'prior-review.json'
        prior.write_text(json.dumps({'schema': 'fpw-roadmap-source-review-v1',
            'bundle_sha256': '0'*64, 'reviewed_at': '2026-10-29T00:00:00Z',
            'source_classifications': rows, 'external_links': []}))
        with self.assertRaisesRegex(ValueError, 'Changed source requires'):
            rebind_source_review(output, prior, [])
        review = rebind_source_review(output, prior, [
            (changed['key'], 'project', 'Changed fixture was reviewed.')],
            reviewed_at='2026-10-30T13:00:00Z')
        self.assertEqual(operation['bundle_sha256'], review['bundle_sha256'])
        self.assertEqual(len(manifest['sources']), len(review['source_classifications']))

    def test_read_only_evidence_audit_proves_applied_candidate_coverage(self):
        source, run, node, project_id, _, base = self.fixture_run()
        output = base/'bundle-evidence'
        operation, _ = assemble_rebuild_bundle(run, {'federated-workspace': source.root},
            node, project_id, author_id=local_author_id(node), privacy='project', output=output,
            created_at='2026-10-30T12:00:00Z')
        _, blobs = load_bundle(output)
        review = validation_tests.RoadmapValidationTests.source_review(self, operation, blobs)
        validation = validate_bundle(output, node, source_roots=[source.root],
                                     source_review=review)
        self.assertTrue(validation['prewrite_checks_passed'], validation)
        receipt = RoadmapImporter(node).apply(output, review, operation['bundle_sha256'],
                                              source_roots=[source.root])
        receipt_path = base/'receipt.json'
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
        report = audit_import_evidence(run, output, receipt_path, node)
        self.assertTrue(report['complete'])
        self.assertEqual(report['verdict'], 'complete-no-loss-detected')
        self.assertEqual(report['counts']['source_blocks'], 1)
        self.assertEqual(report['counts']['nodes'], 3)
        self.assertEqual(report['counts']['supporting_records'], 2)


if __name__ == '__main__':
    unittest.main()
