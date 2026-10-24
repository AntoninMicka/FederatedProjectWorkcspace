# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Closed research action schemas and reviewed profile policies."""
from copy import deepcopy
import hashlib
import json
import tempfile
from pathlib import Path
import unittest
from uuid import uuid4

from spikes.action_autonomy import digest, load_action_registry
from spikes.metadata import ValidationError
from spikes.research_workflow import (load_research_profiles,
                                      parse_research_profile)


def sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


class ResearchWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.registry = load_action_registry()
        self.research_id = str(uuid4())
        self.task_id = str(uuid4())
        self.search_id = str(uuid4())
        self.run_id = str(uuid4())
        self.manifest_id = str(uuid4())
        self.source_id = 'source-' + 'a' * 32
        self.goal = 'Find the supported answer.'
        self.binding = {'schema_version': 1, 'binding_id': str(uuid4()),
            'revision': 'reader-r1', 'adapter': 'static-html-v1',
            'origins': ['https://example.test'], 'user_agent': 'Workspace/1.0',
            'auth': 'none', 'max_wire_bytes': 1024,
            'max_decoded_bytes': 2048, 'max_text_chars': 4096,
            'max_compression_ratio': 10, 'timeout_seconds': 15}
        self.preview = {'schema_version': 1, 'task_id': self.task_id,
            'search_id': self.search_id, 'source_id': self.source_id,
            'run_id': self.run_id, 'project_id': str(uuid4()),
            'privacy': 'project', 'expected_head': 'a' * 40,
            'title': 'Evidence', 'url': 'https://example.test/evidence',
            'origin': 'https://example.test', 'adapter': 'static-html-v1',
            'binding': self.binding,
            'effects': [
                {'method': 'GET', 'url': 'https://example.test/robots.txt',
                 'purpose': 'RFC 9309 preflight'},
                {'method': 'GET', 'url': 'https://example.test/evidence',
                 'purpose': 'selected public document when robots allows'}],
            'limits': {'wire_bytes': 1024, 'decoded_bytes': 2048,
                'text_chars': 4096, 'compression_ratio': 10, 'seconds': 15,
                'redirects': 0},
            'warning': 'Remote content is untrusted data.',
            'search_provenance': {'search_id': self.search_id,
                'round_index': 1, 'source_id': self.source_id}}
        self.source_ref = {'task_id': self.task_id, 'search_id': self.search_id,
            'source_id': self.source_id, 'run_id': self.run_id,
            'adapter': 'static-html-v1', 'binding_revision': 'reader-r1',
            'url': 'https://example.test/evidence',
            'origin': 'https://example.test', 'raw_sha256': '1' * 64,
            'text_sha256': '2' * 64, 'projection_sha256': '3' * 64}
        self.evidence = {'sources': [self.source_ref], 'relations': [],
                         'warnings': []}
        self.selection = {'selected_source_run_ids': [self.run_id],
                           'rejected': [], 'limitations': []}

    def validate(self, action_id, value, output=False):
        descriptor = self.registry.resolve(action_id, '1.0')
        method = (self.registry.validate_output if output
                  else self.registry.validate_input)
        method(descriptor, value)

    def model_base(self):
        return {'research_id': self.research_id, 'goal': self.goal,
            'goal_sha256': hashlib.sha256(self.goal.encode()).hexdigest(),
            'run_id': self.run_id, 'manifest_id': self.manifest_id}

    def test_reviewed_profiles_are_policy_allowlists_with_bounded_budgets(self):
        profiles = load_research_profiles(self.registry)
        self.assertEqual(set(profiles), {('quick-search-v1', '1.0'),
            ('read-and-verify-v1', '1.0'), ('deep-research-v1', '1.0')})
        quick = profiles[('quick-search-v1', '1.0')]
        deep = profiles[('deep-research-v1', '1.0')]
        self.assertEqual(quick['start_action']['id'], 'search.iterative-query')
        self.assertNotIn('artifact.create-local',
                         {item['id'] for item in deep['actions']})
        self.assertLess(quick['default_budget']['max_steps'],
                        deep['maximum_budget']['max_steps'])
        self.assertIn('research.analyze', {item['id'] for item in deep['actions']})

        excessive = deepcopy(quick)
        excessive['default_budget']['max_steps'] = 13
        with self.assertRaisesRegex(ValidationError, 'exceeds profile maximum'):
            parse_research_profile(json.dumps(excessive).encode(), self.registry)
        missing_permission = deepcopy(quick)
        missing_permission['permissions'].remove('external-dispatch')
        with self.assertRaisesRegex(ValidationError, 'permissions differ'):
            parse_research_profile(json.dumps(missing_permission).encode(), self.registry)
        unknown = deepcopy(quick); unknown['pipeline'] = ['fixed']
        with self.assertRaisesRegex(ValidationError, 'profile field'):
            parse_research_profile(json.dumps(unknown).encode(), self.registry)

    def test_profile_loader_rejects_unreviewed_files_and_incomplete_catalog(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = load_research_profiles(self.registry)[
                ('quick-search-v1', '1.0')]
            (root / 'quick-search-v1.profile.json').write_text(
                json.dumps(profile), encoding='utf-8')
            with self.assertRaisesRegex(ValidationError, 'incomplete'):
                load_research_profiles(self.registry, root)
            (root / 'README').write_text('not reviewed', encoding='utf-8')
            with self.assertRaisesRegex(ValidationError, 'Unexpected'):
                load_research_profiles(self.registry, root)

    def test_fetch_schema_binds_exact_preview_and_returns_only_reference(self):
        request = {'task_id': self.task_id, 'search_id': self.search_id,
                   'source_id': self.source_id, 'run_id': self.run_id}
        value = {'request': request, 'preview': self.preview,
                 'preview_sha256': digest(self.preview)}
        self.validate('source.fetch-public', value)
        output = {'schema_version': 1, 'kind': 'public-source-reference',
            **request, 'state': 'succeeded', 'raw_sha256': '1' * 64,
            'text_sha256': '2' * 64, 'projection_sha256': '3' * 64,
            'final_url': 'https://example.test/evidence'}
        self.validate('source.fetch-public', output, output=True)

        changed = deepcopy(value); changed['preview']['limits']['seconds'] = 14
        changed['preview_sha256'] = digest(changed['preview'])
        with self.assertRaisesRegex(ValidationError, 'limits differ'):
            self.validate('source.fetch-public', changed)
        injected = deepcopy(value); injected['preview']['effects'][1]['headers'] = {}
        injected['preview_sha256'] = digest(injected['preview'])
        with self.assertRaisesRegex(ValidationError, 'fetch effect field'):
            self.validate('source.fetch-public', injected)
        leaked = dict(output, text='full page')
        with self.assertRaisesRegex(ValidationError, 'output fields differ'):
            self.validate('source.fetch-public', leaked, output=True)

    def test_verification_selection_analysis_and_report_are_digest_bound(self):
        verify = {'research_id': self.research_id,
            'source_refs': [self.source_ref],
            'ledger_sha256': sha([self.source_ref])}
        self.validate('research.verify-evidence', verify)
        invalid_identity = deepcopy(verify)
        invalid_identity['source_refs'][0]['run_id'] = 'not-a-uuid'
        invalid_identity['ledger_sha256'] = sha(invalid_identity['source_refs'])
        with self.assertRaisesRegex(ValidationError, 'Invalid research run_id'):
            self.validate('research.verify-evidence', invalid_identity)
        verified = {'schema_version': 1, 'kind': 'research-evidence',
            'research_id': self.research_id, 'evidence': self.evidence,
            'evidence_sha256': sha(self.evidence)}
        self.validate('research.verify-evidence', verified, output=True)

        select = {**self.model_base(), 'evidence': self.evidence,
                  'evidence_sha256': sha(self.evidence)}
        self.validate('research.select-relevant', select)
        selected = {'schema_version': 1, 'kind': 'research-selection',
            'research_id': self.research_id, 'run_id': self.run_id,
            'manifest_id': self.manifest_id, 'selection': self.selection,
            'selection_sha256': sha(self.selection)}
        self.validate('research.select-relevant', selected, output=True)

        analysis = {**self.model_base(), 'selection': self.selection,
                    'selection_sha256': sha(self.selection)}
        self.validate('research.analyze', analysis)
        content = {'claims': [{'claim': 'Supported by the selected source.',
            'source_run_ids': [self.run_id], 'confidence': 'medium'}],
            'limitations': ['Single source.']}
        analyzed = {'schema_version': 1, 'kind': 'research-analysis',
            'research_id': self.research_id, 'run_id': self.run_id,
            'manifest_id': self.manifest_id, **content,
            'analysis_sha256': sha(content)}
        self.validate('research.analyze', analyzed, output=True)

        report = {**self.model_base(),
            'selected_source_run_ids': [self.run_id],
            'selection_sha256': sha(self.selection),
            'analysis_run_id': self.run_id,
            'analysis_sha256': analyzed['analysis_sha256'],
            'task_id': self.task_id}
        self.validate('research.compose-report', report)
        draft = {'schema_version': 1, 'kind': 'research-report-draft',
            'research_id': self.research_id, 'task_id': self.task_id,
            'run_id': self.run_id, 'manifest_id': self.manifest_id,
            'state': 'draft', 'draft_sha256': '4' * 64}
        self.validate('research.compose-report', draft, output=True)

        stale = deepcopy(select); stale['evidence']['warnings'] = ['changed']
        with self.assertRaisesRegex(ValidationError, 'evidence digest differs'):
            self.validate('research.select-relevant', stale)
        invented = deepcopy(selected)
        invented['selection']['unexpected'] = True
        invented['selection_sha256'] = sha(invented['selection'])
        with self.assertRaisesRegex(ValidationError, 'selection field'):
            self.validate('research.select-relevant', invented, output=True)

    def test_planner_has_closed_decisions_and_cannot_change_policy_or_budget(self):
        ledger = [{'step_id': str(uuid4()), 'action_id': 'research.analyze',
                   'state': 'completed', 'result_sha256': '5' * 64}]
        planner = {**self.model_base(), 'profile_id': 'deep-research-v1',
            'profile_version': '1.0', 'plan_revision': 2, 'ledger': ledger,
            'ledger_sha256': sha(ledger), 'remaining_budget': {
                'max_steps': 4, 'max_cost_units': 10, 'max_seconds': 300}}
        self.validate('research.plan-next', planner)
        proposal = {'decision': 'finish', 'reason': 'Enough evidence.',
            'target_action': None, 'candidate': None, 'repeat_step_id': None,
            'finish_reason': 'completed'}
        output = {'schema_version': 1, 'kind': 'research-next-step',
            'research_id': self.research_id, 'run_id': self.run_id,
            'manifest_id': self.manifest_id, **proposal,
            'proposal_sha256': sha(proposal)}
        self.validate('research.plan-next', output, output=True)

        report_input = {**self.model_base(),
            'selected_source_run_ids': [self.run_id],
            'selection_sha256': sha(self.selection), 'analysis_run_id': None,
            'analysis_sha256': None, 'task_id': self.task_id}
        candidate = {'action': {'id': 'research.compose-report', 'version': '1.0'},
            'privacy': 'project', 'cost_units': 8, 'input': report_input}
        append = {'decision': 'append', 'reason': 'Compose the bounded draft.',
            'target_action': 'research.compose-report', 'candidate': candidate,
            'repeat_step_id': None, 'finish_reason': None}
        appended = {**output, **append, 'proposal_sha256': sha(append)}
        self.validate('research.plan-next', appended, output=True)
        malformed = deepcopy(appended)
        malformed['candidate']['input']['model_may_publish'] = True
        malformed_proposal = {key: malformed[key] for key in ('decision', 'reason',
            'target_action', 'candidate', 'repeat_step_id', 'finish_reason')}
        malformed['proposal_sha256'] = sha(malformed_proposal)
        with self.assertRaisesRegex(ValidationError, 'input fields differ'):
            self.validate('research.plan-next', malformed, output=True)

        escalation = deepcopy(output)
        escalation['budget'] = {'max_steps': 99}
        with self.assertRaisesRegex(ValidationError, 'output fields differ'):
            self.validate('research.plan-next', escalation, output=True)
        bad = deepcopy(output); bad['target_action'] = 'research.analyze'
        with self.assertRaisesRegex(ValidationError, 'finish proposal'):
            self.validate('research.plan-next', bad, output=True)


if __name__ == '__main__':
    unittest.main()
