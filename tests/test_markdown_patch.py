# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import copy
import json
import unittest
from uuid import uuid4

from spikes.ai_outcome import AITaskOutcome
from spikes.markdown_patch import apply, context, digest, scan, KIND, SCHEMA
from spikes.ollama_backend import OllamaAdapter
from tests import test_task_file_edit as fixtures
from tests.fixtures import ENTITY


def proposal(text, *ops):
    return dict(schema_version=1, kind=KIND, title='Title', document_hash=digest(text), changes=list(ops))


def compact(value):
    """The v3 model answer: IDs and content only; hashes are filled in by the application."""
    return dict(kind=value['kind'], changes=[dict(block_id=op['block_id'], action=op['action'],
        destination_id=op['destination_id'], content=op['content']) for op in value['changes']])


def operation(text, content, action='replace', *, match=None, destination=None):
    scope = context(text)
    block = next(b for b in scope['blocks'] if match is None or match(b))
    dest = next((b for b in scope['blocks'] if b['block_id'] == destination), None)
    return dict(block_id=block['block_id'], expected_hash=block['expected_hash'],
                action=action, content=content, destination_id=destination,
                destination_hash=dest['expected_hash'] if dest else None)


class MarkdownPatchTests(unittest.TestCase):
    def test_lossless_offsets_duplicate_headings_setext_and_fenced_code(self):
        text = '<!-- unknown -->\r\n# Úvod\r\n\r\nStejné\r\n\r\nStejné\r\n\r\n```md\r\n# Fake\r\n- item\r\n```\r\n\r\nKonec\r\n-----\r\n'
        blocks = scan(text)
        self.assertEqual(text, ''.join(text[b.start:b.end] for b in blocks))
        self.assertEqual(['Úvod', 'Konec'], [b.title for b in blocks if b.kind == 'heading'])
        copies = [b for b in context(text)['blocks'] if b['content'] == 'Stejné\r\n']
        self.assertEqual(2, len(copies))
        change = operation(text, 'Jiné\r\n', match=lambda b: b['block_id'] == copies[1]['block_id'])
        expected = text[:text.rfind('Stejné')] + text[text.rfind('Stejné'):].replace('Stejné', 'Jiné', 1)
        self.assertEqual(expected.encode(), apply(text, proposal(text, change)).encode())

    def test_insert_delete_empty_and_no_final_newline(self):
        for text, content, action, expected in [('', '# Nový\n', 'insert_after', '# Nový\n'),
                ('A', '\nB', 'insert_after', 'A\nB'), ('A\n', 'B\n', 'insert_before', 'B\nA\n'),
                ('A', None, 'delete', '')]:
            with self.subTest(action=action, text=text):
                self.assertEqual(expected, apply(text, proposal(text, operation(text, content, action))))

    def test_section_scope_copies_only_selected_text_and_rejects_escape(self):
        text = '# Root\n\n## One\nA\n\n## Two\nB\n'
        records = context(text)['blocks'];one = next(b for b in records if b.get('title') == 'One')
        two = next(b for b in records if b.get('title') == 'Two')
        scoped = context(text, [one['block_id']])
        self.assertNotIn('B\n', [b['content'] for b in scoped['blocks']])
        change = operation(text, 'AA\n', match=lambda b: b['content'] == 'A\n')
        self.assertEqual(text.replace('A\n', 'AA\n'), apply(text, proposal(text, change), selected_ids=[one['block_id']]))
        for op in [operation(text, 'BB\n', match=lambda b: b['content'] == 'B\n'),
                   operation(text, None, 'move_section', match=lambda b: b['block_id'] == one['block_id'], destination=two['block_id'])]:
            with self.assertRaisesRegex(ValueError, 'mimo vybraný rozsah'):
                apply(text, proposal(text, op), selected_ids=[one['block_id']])

    def test_move_retains_exact_section_bytes_and_descendants(self):
        text = '# Root\r\n## One\r\nž  \r\n### Child\r\n~~~py\r\nx=1\r\n~~~\r\n## Two\r\nB\r\n'
        records = context(text)['blocks']
        two = next(b for b in records if b.get('title') == 'Two')
        op = operation(text, None, 'move_section', match=lambda b: b.get('title') == 'One', destination=two['block_id'])
        expected = '# Root\r\n## Two\r\nB\r\n## One\r\nž  \r\n### Child\r\n~~~py\r\nx=1\r\n~~~\r\n'
        self.assertEqual(expected.encode(), apply(text, proposal(text, op)).encode())
        child = next(b for b in records if b.get('title') == 'Child')
        op['destination_id'], op['destination_hash'] = child['block_id'], child['expected_hash']
        with self.assertRaises(ValueError): apply(text, proposal(text, op))

    def test_section_operations_and_heading_rename_preserve_surroundings(self):
        text = '## Old ##\r\nA\r\n## Other\r\nB\r\n'
        match = lambda b: b.get('title') == 'Old'
        for action, content, expected in [
                ('rename_heading', 'New', text.replace('Old', 'New')),
                ('append_section', 'C\r\n', text.replace('A\r\n', 'A\r\nC\r\n')),
                ('replace_section', '## New\r\nD\r\n', '## New\r\nD\r\n## Other\r\nB\r\n')]:
            with self.subTest(action=action):
                self.assertEqual(expected, apply(text, proposal(text, operation(text, content, action, match=match))))
        text = 'Old\n===\nbody\n'
        self.assertEqual('New\n===\nbody\n', apply(text, proposal(text, operation(text, 'New', 'rename_heading'))))

    def test_rejects_stale_hashes_unknown_ids_extra_fields_and_noops(self):
        text = 'A\n\nB\n'
        valid = proposal(text, operation(text, 'C\n'))
        for mutate in [lambda p: p.update(document_hash=digest('new')),
                lambda p: p['changes'][0].update(expected_hash=digest('wrong')),
                lambda p: p['changes'][0].update(block_id='b99999'),
                lambda p: p['changes'][0].update(path='/tmp/file'),
                lambda p: p['changes'][0].update(content='A\n'),
                lambda p: p['changes'][0].update(action='shell')]:
            value = copy.deepcopy(valid);mutate(value)
            with self.assertRaises(ValueError): apply(text, value)
        with self.assertRaises(ValueError): apply(text + 'new', valid)

    def test_rejects_overlaps_and_invalid_fences_atomically(self):
        text = '# A\nbody\n'
        op = operation(text, '# New\n', 'replace_section')
        child = operation(text, 'changed\n', match=lambda b: b['kind'] == 'paragraph')
        with self.assertRaisesRegex(ValueError, 'Overlapping'): apply(text, proposal(text, child, op))
        with self.assertRaisesRegex(ValueError, 'Unclosed'): apply(text, proposal(text, operation(text, '```\n')))
        self.assertEqual('# A\nbody\n', text)

    def test_section_replacement_cannot_change_sibling_heading_levels(self):
        text = '# Root\n## One\nA\n## Two\nB\n'
        match = lambda b: b.get('title') == 'One'
        for action, content in [('append_section', '## Escaped\n'),
                                ('replace_section', '# Wrong level\n'),
                                ('replace_section', '## One\n## Escaped\n')]:
            with self.subTest(action=action), self.assertRaises(ValueError):
                apply(text, proposal(text, operation(text, content, action, match=match)))

    def test_outcome_roundtrip_and_plan_scope_digest(self):
        value = proposal('A', operation('A', 'B'))
        self.assertEqual(value, AITaskOutcome.parse(value).serialize())
        parsed = AITaskOutcome.parse(value);value['changes'][0]['content'] = 'tampered'
        self.assertEqual('B', parsed.serialize()['changes'][0]['content'])

    def test_schema_restricts_existing_ids_and_keeps_legacy_schema_unchanged(self):
        from spikes.markdown_patch import output_schema
        scope = context('# Chapter\nBody\n')
        schema = output_schema(scope)
        self.assertEqual([digest('# Chapter\nBody\n')], schema['properties']['document_hash']['enum'])
        for variant in schema['properties']['changes']['items']['anyOf']:
            self.assertEqual(scope['allowed_block_ids'], variant['properties']['block_id']['enum'])
            if variant['properties']['action']['enum'] == ['move_section']:
                self.assertEqual(scope['allowed_block_ids'], variant['properties']['destination_id']['enum'])
        legacy = output_schema()
        self.assertEqual({'type':'string'}, legacy['properties']['document_hash'])
        for variant in legacy['properties']['changes']['items']['anyOf']:
            self.assertEqual({'type':'string'}, variant['properties']['block_id'])

    def test_invented_future_id_has_distinct_diagnostic_from_unapproved_existing_id(self):
        text = '# Chapter\nA\n## Other\nB\n'
        value = proposal(text, operation(text, 'New\n', 'insert_after'))
        value['changes'][0]['block_id'] = 'b99999'
        with self.assertRaisesRegex(ValueError, 'neexistující blok b99999'):
            apply(text, value)
        value = proposal(text, operation(text, 'New\n', 'insert_after', match=lambda b: b['content']=='B\n'))
        with self.assertRaisesRegex(ValueError, 'mimo vybraný rozsah'):
            apply(text, value, selected_ids=['b00002'])


class CompactProposalTests(unittest.TestCase):
    """v3: the model sends IDs and Markdown; the application owns hashes and block separation."""

    def test_v2_projection_has_no_hashes_or_whitespace_blocks_and_legacy_v1_is_unchanged(self):
        from spikes.markdown_patch import SCHEMA_V1, render_prompt
        text = '# A\n\nPara one.\n\n- [ ] task\n'
        legacy = context(text)
        self.assertEqual(SCHEMA_V1, legacy['schema'])
        self.assertTrue(all('expected_hash' in b for b in legacy['blocks']))
        scope = context(text, schema=SCHEMA)
        self.assertEqual(['heading', 'paragraph', 'list-item'], [b['kind'] for b in scope['blocks']])
        self.assertTrue(all('expected_hash' not in b for b in scope['blocks']))
        self.assertEqual(legacy['allowed_block_ids'], scope['allowed_block_ids'])
        rendered = render_prompt(scope)
        self.assertNotIn('sha256', rendered)
        self.assertIn('<<b00001 heading level 1>>\n# A\n<<b00003 paragraph>>\nPara one.', rendered)

    def test_projection_is_much_smaller_on_a_large_document(self):
        text = ''.join(f'## Kapitola {i}\n\nOdstavec {i} s českým textem.\n\n- [ ] úkol {i}\n\n' for i in range(300))
        old = json.dumps(context(text), ensure_ascii=False)
        new = json.dumps(context(text, schema=SCHEMA), ensure_ascii=False)
        self.assertLess(len(new), len(old) * 0.6)

    def test_complete_fills_hashes_and_null_content_for_delete(self):
        from spikes.markdown_patch import complete
        text = '# A\n\nOld\n\nGone\n'
        value = dict(kind=KIND, changes=[
            dict(block_id='b00003', action='replace', destination_id=None, content='New\n'),
            dict(block_id='b00005', action='delete', destination_id='b00001', content='')])
        full = complete(value, text)
        self.assertEqual(digest(text), full['document_hash'])
        self.assertEqual(digest('Old\n'), full['changes'][0]['expected_hash'])
        self.assertEqual((None, None, None), (full['changes'][1]['content'], full['changes'][1]['destination_id'],
                                              full['changes'][1]['destination_hash']))
        self.assertEqual('# A\n\nNew\n\n', apply(text, full))

    def test_complete_keeps_invented_id_diagnostic_and_rejects_extra_fields(self):
        from spikes.markdown_patch import complete
        text = '# A\nBody\n'
        value = dict(kind=KIND, changes=[dict(block_id='b99999', action='insert_after', destination_id=None, content='x\n')])
        with self.assertRaisesRegex(ValueError, 'neexistující blok b99999'):
            apply(text, complete(value, text))
        value['changes'][0]['expected_hash'] = digest('')
        with self.assertRaisesRegex(ValueError, 'Unknown Markdown operation field'):
            complete(value, text)

    def test_complete_repairs_missing_newlines_and_paragraph_separation(self):
        from spikes.markdown_patch import complete
        text = '# A\n\n- [ ] one\n- [ ] two\n\nPara text.\n\n## B\n'
        def run(block_id, action, content):
            value = dict(kind=KIND, changes=[dict(block_id=block_id, action=action, destination_id=None, content=content)])
            return apply(text, complete(value, text))
        self.assertIn('- [ ] one\n- [ ] new\n- [ ] two\n', run('b00003', 'insert_after', '- [ ] new'))
        self.assertIn('Para text.\n\nNew para.\n\n## B', run('b00006', 'insert_after', 'New para.\n'))
        self.assertIn('- [ ] two\n\nAfter list.\n', run('b00004', 'insert_after', 'After list.'))
        self.assertIn('Before.\n\nPara text.\n', run('b00006', 'insert_before', 'Before.'))
        self.assertIn('\nChanged.\n\n## B', run('b00006', 'replace', 'Changed.'))
        crlf = '# A\r\n\r\nBody\r\n'
        value = dict(kind=KIND, changes=[dict(block_id='b00003', action='replace', destination_id=None, content='New')])
        self.assertEqual('# A\r\n\r\nNew\r\n', apply(crlf, complete(value, crlf)))

    def test_list_item_followed_by_rule_is_not_a_setext_heading(self):
        self.assertEqual([], [b for b in scan('- item\n---\n') if b.kind == 'heading'])
        self.assertEqual(['Title'], [b.title for b in scan('Title\n---\n') if b.kind == 'heading'])

    def test_milestone_scope_shows_child_structure_without_descriptions_or_siblings(self):
        from spikes.markdown_patch import render_prompt
        text = ('- [ ] [M1] Milestone\n  - type: milestone\n  - [ ] [B1] Batch\n    - type: batch\n'
                '    Popis dávky SECRET-DESCRIPTION\n    - [ ] [T1] Task\n      - type: task\n'
                '- [ ] [M2] Other SIBLING\n  - type: milestone\n')
        ids = [b.id for b in scan(text)][:2]
        scope = context(text, ids, schema=SCHEMA)
        self.assertEqual(ids, scope['addressable_block_ids'])
        self.assertIn('  - [ ] [B1] Batch\n    - type: batch\n', scope['following_context'])
        rendered = render_prompt(scope)
        self.assertNotIn('SECRET-DESCRIPTION', rendered)
        self.assertNotIn('SIBLING', rendered)
        self.assertEqual('', context('# A\nx\n## B\ny\n', ['b00001'], schema=SCHEMA)['following_context'])

    def test_output_schema_has_one_operation_shape_and_heading_only_destinations(self):
        from spikes.markdown_patch import output_schema_v3
        scope = context('# A\n\nBody\n\n# B\n', schema=SCHEMA)
        schema = output_schema_v3(scope)
        item = schema['properties']['changes']['items']
        self.assertNotIn('anyOf', item)
        self.assertEqual(['b00001', 'b00003', 'b00005'], item['properties']['block_id']['enum'])
        self.assertEqual(['b00001', 'b00005'], item['properties']['destination_id']['anyOf'][1]['enum'])
        self.assertEqual({'kind', 'changes'}, set(schema['properties']))

    def test_context_window_is_explicit_and_bounded(self):
        from spikes.markdown_patch import context_window, NUM_PREDICT
        window = context_window('x' * 10000, 'y' * 1000)
        self.assertEqual(0, window % 2048)
        self.assertGreaterEqual(window, 11000 * 2 // 5 + NUM_PREDICT)
        self.assertIsNone(context_window('x' * 400000, ''))


class MarkdownTaskTests(unittest.TestCase):
    setUp = fixtures.FileEditTests.setUp
    request = fixtures.FileEditTests.request
    pin_run_choice = fixtures.FileEditTests.pin_run_choice
    route_request = fixtures.FileEditTests.route_request
    create_document = fixtures.FileEditTests.create_document
    generate = fixtures.FileEditTests.generate
    confirmation = fixtures.FileEditTests.confirmation

    def routed(self, *, invalid=False, selected=True):
        text = '# Root\r\n## Selected\r\nOriginal ž  \r\n## Secret\r\nDO_NOT_SEND\r\n'
        target = self.create_document(text)
        service, request, calls = self.generate(target)
        request['task_plan']['edit_format'] = 'blocks'
        if selected:
            request['task_plan']['edit_block_ids'] = [next(b.id for b in scan(text) if b.title == 'Selected')]
        def transport(binding, raw):
            wire = json.loads(raw);calls.append(wire)
            op = operation(text, 'Changed ž  \r\n', match=lambda b: b['content'] == 'Original ž  \r\n')
            if invalid:
                op = operation(text, 'Bad\r\n', match=lambda b: b['content'] == 'DO_NOT_SEND\r\n')
            return dict(model=binding.model, response=json.dumps(compact(proposal(text, op))))
        service.adapter_factory = lambda runs: OllamaAdapter(runs, transport=transport)
        return service, request, calls, text

    def test_scope_manifest_schema_preview_native_save_and_idempotent_retry(self):
        service, request, calls, original = self.routed();head = self.git.head()
        result = service.task_route(request)
        self.assertEqual(head, self.git.head())
        self.assertEqual([KIND], calls[0]['format']['properties']['kind']['enum'])
        from spikes.markdown_patch import ROLE
        self.assertEqual('task-output-markdown-patch-v3', ROLE)
        scope = context(original, request['task_plan']['edit_block_ids'], schema=SCHEMA)
        item = calls[0]['format']['properties']['changes']['items']
        self.assertEqual(scope['addressable_block_ids'], item['properties']['block_id']['enum'])
        self.assertNotIn('document_hash', calls[0]['format']['properties'])
        self.assertNotIn('expected_hash', item['properties'])
        self.assertNotIn('sha256:', calls[0]['prompt'])
        self.assertIn('<<' + scope['addressable_block_ids'][0] + ' heading level 2>>', calls[0]['prompt'])
        self.assertEqual(False, calls[0]['think'])
        self.assertGreaterEqual(calls[0]['options']['num_ctx'], 4096 + 512)
        self.assertNotIn('DO_NOT_SEND', calls[0]['prompt'])
        self.assertIn('User edit request', calls[0]['prompt'])
        self.assertEqual(SCHEMA, result['projection']['file_edit_context']['schema'])
        self.assertEqual(1, len(calls))
        preview = service.task_preview_file_edit(dict(project_id=ENTITY, task_id=request['task_id']))
        expected = original.replace('Original ž', 'Changed ž')
        self.assertEqual(expected, preview['body'])
        self.assertIn('-Original ž', preview['diff'])
        confirmed = self.confirmation(preview)
        saved = service.task_confirm_file_edit(confirmed)
        self.assertEqual(saved, service.task_confirm_file_edit(confirmed))
        self.assertEqual(expected.encode(), self.git.snapshot(self.git.head())[preview['document']['path']])
        self.assertEqual('1', self.git.run('rev-list', '--count', head+'..HEAD').stdout.strip())

    def test_invalid_model_scope_has_no_outcome_no_write_no_retry(self):
        service, request, calls, _ = self.routed(invalid=True);head = self.git.head()
        with self.assertRaisesRegex(ValueError, 'mimo vybraný rozsah'):service.task_route(request)
        self.assertEqual(head, self.git.head())
        self.assertEqual([], service.task_outcomes(project_id=ENTITY))
        self.assertEqual(1, len(calls))

    def test_unknown_scope_is_rejected_before_dispatch(self):
        service, request, calls, _ = self.routed()
        request['task_plan']['edit_block_ids'] = ['b99999']
        with self.assertRaisesRegex(ValueError, 'scope block'):service.task_route(request)
        self.assertEqual([], calls)

    def test_invalid_roadmap_is_a_rejected_proposal_not_an_unknown_run(self):
        from spikes.artifacts import Artifacts
        from spikes.markdown_documents import main_todo_id
        from spikes.markdown_patch import MarkdownPatchError
        text = ('<!-- fpw-plan-profile: software-development/v1 -->\n'
                '- [ ] [M] Milestone\n  - type: milestone\n')
        target = main_todo_id(ENTITY)
        Artifacts(self.node_path).save(dict(project_id=ENTITY, artifact_id=target, new=True,
            title='Roadmap', body=text, base_head=self.git.head()), str(uuid4()))
        service, request, calls = self.generate(target)
        request['task_plan']['edit_format'] = 'blocks'
        def transport(binding, raw):
            calls.append(json.loads(raw))
            op = operation(text, '  - [ ] [BROKEN] Task without type\n', 'insert_after',
                           match=lambda b: 'type: milestone' in b['content'])
            return dict(model=binding.model, response=json.dumps(compact(proposal(text, op))))
        service.adapter_factory = lambda runs: OllamaAdapter(runs, transport=transport)
        head = self.git.head()
        with self.assertRaisesRegex(MarkdownPatchError, 'neplatnou roadmapu'):service.task_route(request)
        from spikes.ollama_backend import OllamaRuns
        self.assertEqual('succeeded', OllamaRuns(self.chat_state).get(request['run_id'])['state'])
        self.assertEqual([], service.task_outcomes(project_id=ENTITY))
        self.assertEqual(head, self.git.head())
        self.assertEqual(1, len(calls))

    def test_whole_document_and_cancel(self):
        service, request, calls, _ = self.routed(selected=False);head = self.git.head()
        service.task_route(request)
        self.assertIn('DO_NOT_SEND', calls[0]['prompt'])
        service.task_cancel(dict(task_id=request['task_id']))
        self.assertEqual(head, self.git.head())

    def test_recovery_after_native_commit_uses_approved_body_without_model_replay(self):
        service, request, calls, _ = self.routed();service.task_route(request);head = self.git.head()
        preview = service.task_preview_file_edit(dict(project_id=ENTITY, task_id=request['task_id']))
        confirmation = self.confirmation(preview)
        from spikes.task_file_edit import confirm
        def checkpoint(stage):
            if stage == 'file-edit-before-outcome':raise RuntimeError('lost response')
        with self.assertRaisesRegex(RuntimeError, 'lost response'):confirm(service, confirmation, checkpoint=checkpoint)
        self.assertNotEqual(head, self.git.head())
        service.task_confirm_file_edit(confirmation)
        self.assertEqual(1, len(calls))
        self.assertEqual('1', self.git.run('rev-list', '--count', head+'..HEAD').stdout.strip())

    def test_oversized_context_is_rejected_before_any_dispatch(self):
        from unittest import mock
        service, request, calls, _ = self.routed()
        with mock.patch('spikes.markdown_patch.MAX_CONTEXT_WINDOW', 2048):
            with self.assertRaisesRegex(ValueError, 'příliš velký'):service.task_route(request)
        self.assertEqual([], calls)
        self.assertEqual([], service.task_outcomes(project_id=ENTITY))

    def test_truncated_prompt_evidence_rejects_the_proposal(self):
        service, request, calls, text = self.routed()
        def transport(binding, raw):
            wire = json.loads(raw);calls.append(wire)
            op = operation(text, 'Changed\r\n', match=lambda b: b['content'] == 'Original ž  \r\n')
            return dict(model=binding.model, response=json.dumps(compact(proposal(text, op))),
                        prompt_eval_count=wire['options']['num_ctx'])
        service.adapter_factory = lambda runs: OllamaAdapter(runs, transport=transport)
        with self.assertRaisesRegex(ValueError, 'neviděl celé zadání'):service.task_route(request)
        self.assertEqual([], service.task_outcomes(project_id=ENTITY))
        self.assertEqual(1, len(calls))
