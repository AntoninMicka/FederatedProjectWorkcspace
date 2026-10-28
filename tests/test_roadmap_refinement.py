# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.markdown_documents import main_todo_id
from spikes.ollama_backend import OllamaAdapter, OllamaBinding, OllamaBindings
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.roadmap_refinement import RoadmapRefinement
from spikes.storage import Git


class RoadmapRefinementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name); self.node = self.base/'node.json'
        created = ProjectCreation(self.node).create('Project', str(self.base/'project'), str(uuid4()))
        self.project_id = created['id']; self.git = Git(self.base/'project'); self.docs = Artifacts(self.node)
        self.document_id = str(uuid4()); self.target_id = 'MILESTONE-M1'
        detached_path = f'artifacts/{self.document_id}/content.md'
        self.docs.save(dict(project_id=self.project_id, artifact_id=self.document_id,
            base_head=self.git.head(), title='Detached evidence', body='# Evidence\n\nBelongs to M1.\n', new=True), str(uuid4()))
        body = ('<!-- fpw-plan-profile: software-development/v1 -->\n\n# Roadmapa\n\n'
                '## Samostatné podklady bez jednoznačného přiřazení\n\n'
                f'- [Detached evidence]({detached_path})\n\n'
                f'- [ ] [{self.target_id}] First milestone\n  - type: milestone\n'
                '  - [ ] [BATCH-01] Feature\n    - type: batch\n'
                '    - [ ] [TASK-01] Work\n      - type: task\n')
        self.docs.save(dict(project_id=self.project_id, artifact_id=main_todo_id(self.project_id),
            base_head=self.git.head(), title='Roadmap', body=body, new=True), str(uuid4()))
        self.head = self.git.head(); self.state = self.base/'refinement'; self.chat = self.node.parent/('.'+self.node.name+'.chat')
        self.chat.mkdir(mode=0o700)
        self.binding = dict(schema_version=1, binding_id=str(uuid4()), revision='one', adapter='ollama',
            boundary='same-node', endpoint='http://127.0.0.1:11434', model='fixture', target_id='local-process')
        OllamaBindings(self.chat).save(OllamaBinding.parse(self.binding))
        self.response = dict(schema='fpw-roadmap-refinement-proposal-v1', decision='attach',
            document_id=self.document_id, target_id=self.target_id, confidence='high', reason='Clear M1 evidence.')
        def factory(runs):
            return OllamaAdapter(runs, transport=lambda binding, raw:
                {'model':binding.model, 'response':json.dumps(self.response)})
        self.service = RoadmapRefinement(self.node, self.project_id, state_dir=self.state,
                                         adapter_factory=factory)

    def test_scan_is_durable_proposal_only_and_repeated_scan_does_not_loop(self):
        first = self.service.scan(limit=4)
        self.assertEqual(len(first['created']), 1)
        self.assertEqual(first['created'][0]['state'], 'pending')
        context = self.service.review_context(first['created'][0])
        self.assertEqual(context['project_title'], 'Project')
        self.assertEqual(context['source_title'], 'Detached evidence')
        self.assertEqual(context['target']['id'], self.target_id)
        self.assertIn('Belongs to M1', context['source_excerpt'])
        self.assertEqual(self.git.head(), self.head)
        second = self.service.scan(limit=4)
        self.assertEqual(second['created'], [])
        self.assertFalse(second['converged'])  # Pending human review remains.

    def test_reviewed_attachment_applies_one_workspace_transaction(self):
        proposal = self.service.scan()['created'][0]
        self.service.decide(proposal['proposal_id'], 'accept')
        result = self.service.apply(str(uuid4()))
        self.assertEqual(result['applied_proposals'], [proposal['proposal_id']])
        view = Projects(self.node).open(self.project_id); files = self.git.snapshot(view['commit_id'])
        body = files[f'artifacts/{main_todo_id(self.project_id)}/content.md'].decode()
        self.assertNotIn('## Samostatné podklady bez jednoznačného přiřazení\n\n- [Detached', body)
        self.assertIn('  - Podklad: [Detached evidence]', body)
        self.assertEqual(self.service.get(proposal['proposal_id'])['state'], 'applied')

    def test_reject_is_terminal_for_unchanged_evidence(self):
        proposal = self.service.scan()['created'][0]
        self.service.decide(proposal['proposal_id'], 'reject')
        result = self.service.scan()
        self.assertEqual(result['created'], [])
        self.assertTrue(result['converged'])
        self.assertEqual(self.git.head(), self.head)

    def test_model_cannot_select_unknown_target_or_change_document_identity(self):
        self.response['target_id'] = 'MADE-UP'
        result = self.service.scan()
        self.assertEqual(result['created'][0]['state'], 'failed')
        self.assertIn('target is unavailable', result['created'][0]['proposal']['error'])
        self.assertIn('MADE-UP', result['created'][0]['proposal']['raw_response'])
        # The same evidence/catalog fingerprint is terminal until explicitly
        # handled; repeated scans do not silently ask the model again.
        self.response['target_id'] = self.target_id
        self.assertEqual(self.service.scan()['created'], [])

    def test_shared_local_queue_is_strictly_scoped_to_project(self):
        proposal = self.service.scan()['created'][0]
        other_root = self.base/'other-project'
        other = ProjectCreation(self.node).create('Other', str(other_root), str(uuid4()))
        other_service = RoadmapRefinement(
            self.node, other['id'], state_dir=self.state,
            adapter_factory=self.service.adapter_factory)
        self.assertEqual(other_service.list(), [])
        with self.assertRaisesRegex(ValueError, 'not pending review'):
            other_service.decide(proposal['proposal_id'], 'reject')
        self.assertEqual(self.service.get(proposal['proposal_id'])['state'], 'pending')

    def test_deep_check_freezes_source_clusters_into_the_same_proposal_queue(self):
        source_id = str(uuid4())
        self.docs.save(dict(project_id=self.project_id, artifact_id=source_id,
            base_head=self.git.head(), title='Legacy TODO.md',
            body='- [ ] **TASK-01 — Work** Legacy planned definition.\n', new=True,
            metadata={'tags': ['roadmap-import', 'original-source']}), str(uuid4()))
        deep_head = self.git.head()
        self.response = dict(
            schema='fpw-roadmap-deep-check-proposal-v1', action='keep-canonical',
            cluster_id='id:TASK-01', source_ids=[source_id], target_ids=['TASK-01'],
            confidence='high', summary='Kanonický task odpovídá zdroji.',
            reason='ID i význam jsou shodné.', changes=[])
        first = self.service.scan(limit=10, deep_check=True)
        self.assertEqual(first['mode'], 'deep-check')
        self.assertEqual(first['total'], 1)
        self.assertEqual(first['created'][0]['state'], 'pending')
        self.assertEqual(first['created'][0]['mode'], 'deep-check')
        self.assertEqual(first['created'][0]['proposal']['action'], 'keep-canonical')
        self.assertTrue(any(item['artifact_id'] == main_todo_id(self.project_id)
                            for item in first['created'][0]['input']['current_occurrences']))
        self.assertEqual(self.git.head(), deep_head)
        second = self.service.scan(limit=10, deep_check=True)
        self.assertEqual(second['created'], [])
        self.assertTrue(second['converged'])
        proposal = first['created'][0]
        self.service.decide(proposal['proposal_id'], 'accept')
        with self.assertRaisesRegex(ValueError, 'future structured reconciliation apply'):
            self.service.apply(str(uuid4()))

    def test_deep_check_rejects_unknown_structured_targets_without_retry(self):
        source_id = str(uuid4())
        self.docs.save(dict(project_id=self.project_id, artifact_id=source_id,
            base_head=self.git.head(), title='Legacy backlog',
            body='- [ ] **TASK-01 — Work** Legacy definition.\n', new=True,
            metadata={'tags': ['original-source']}), str(uuid4()))
        self.response = dict(
            schema='fpw-roadmap-deep-check-proposal-v1', action='add-dependency',
            cluster_id='id:TASK-01', source_ids=[source_id], target_ids=['TASK-01'],
            confidence='medium', summary='Navrhovana hrana.', reason='Legacy text.',
            changes=[dict(kind='add-dependency', node_id='TASK-01', target_id='MADE-UP',
                          title=None, node_type=None, parent_id=None, checked=None,
                          reason='Neexistujici cil.')])
        first = self.service.scan(limit=10, deep_check=True)
        self.assertEqual(first['created'][0]['state'], 'failed')
        self.assertIn('structured change', first['created'][0]['proposal']['error'])
        self.assertEqual(self.service.scan(limit=10, deep_check=True)['created'], [])


if __name__ == '__main__':
    unittest.main()
