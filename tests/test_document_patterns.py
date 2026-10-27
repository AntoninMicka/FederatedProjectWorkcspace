# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import copy
import unittest

from spikes.document_patterns import DocumentPatterns, MAX_TEXT
from spikes.desktop_ui import CSS, HTML, JS, DesktopHandler


class DocumentPatternTests(unittest.TestCase):
    def setUp(self):
        self.service = DocumentPatterns()
        self.catalog = self.service.catalog()

    def test_catalog_is_stable_closed_and_returns_copies(self):
        self.assertEqual('fpw-document-pattern-catalog-v1', self.catalog['schema'])
        self.assertEqual(64, len(self.catalog['revision']))
        self.assertEqual({'markdown', 'task-plan', 'presentation', 'julia'},
                         {item['id'] for item in self.catalog['adapters']})
        self.assertEqual(len(self.catalog['patterns']),
                         len({item['id'] for item in self.catalog['patterns']}))
        self.assertEqual(len(self.catalog['coverage']),
                         len({item['id'] for item in self.catalog['coverage']}))
        for adapter in self.catalog['adapters']:
            self.assertEqual(set(adapter['formats']), set(adapter['format_help']))
            self.assertEqual(set(adapter['formats']),
                             set(adapter['format_examples']))
            self.assertTrue(all(value.strip()
                                for value in adapter['format_help'].values()))
            self.assertTrue(all(value.strip()
                                for value in adapter['format_examples'].values()))
        self.assertTrue(all(item['example'].strip()
                            for item in self.catalog['patterns']))
        changed = copy.deepcopy(self.catalog)
        changed['patterns'][0]['text'] = 'changed'
        self.assertNotEqual(changed['patterns'][0]['text'],
                            self.service.catalog()['patterns'][0]['text'])

    def test_patterns_only_target_declared_adapter_formats(self):
        adapters = {item['id']: item for item in self.catalog['adapters']}
        for pattern in self.catalog['patterns']:
            for adapter_id in pattern['adapter_ids']:
                self.assertIn(pattern['id'], adapters[adapter_id]['pattern_ids'])
                self.assertLessEqual(set(pattern['formats']),
                                     set(adapters[adapter_id]['formats']))
        json_pattern = next(item for item in self.catalog['patterns']
                            if item['id'] == 'julia.computation-json')
        self.assertNotIn('//', json_pattern['text'])
        self.assertNotIn('# DOPLNIT', json_pattern['text'])

    def test_reviewed_coverage_maps_every_non_task_pattern_once(self):
        patterns = {item['id']: item for item in self.catalog['patterns']}
        covered = {item['pattern_id'] for item in self.catalog['coverage']}
        expected = {item['id'] for item in self.catalog['patterns']
                    if item['adapter_ids'] != ['task-plan']}
        self.assertEqual(expected, covered)
        self.assertEqual(len(covered), len(self.catalog['coverage']))
        for item in self.catalog['coverage']:
            pattern = patterns[item['pattern_id']]
            self.assertIn(item['adapter_id'], pattern['adapter_ids'])
            self.assertIn(item['format'], pattern['formats'])
            self.assertEqual(pattern['insertion'], item['operation'])

    def test_all_builtin_patterns_validate_in_their_declared_formats(self):
        for pattern in self.catalog['patterns']:
            for adapter_id in pattern['adapter_ids']:
                for format_ in pattern['formats']:
                    result = self.service.validate(adapter_id, format_,
                                                   pattern['text'])
                    self.assertTrue(result['valid'], pattern['id'])
                    self.assertTrue(result['lossless'], pattern['id'])
        computation = next(item for item in self.catalog['patterns']
                           if item['id'] == 'julia.computation-json')
        self.assertIn('execution_policy', computation['text'])
        self.assertIn('julia_compat', computation['text'])
        self.assertIn('fpw-julia-result-v1', next(
            item for item in self.catalog['patterns']
            if item['id'] == 'julia.runner-entrypoint')['text'])

    def test_task_editor_operations_have_stable_catalog_patterns(self):
        adapter = next(item for item in self.catalog['adapters']
                       if item['id'] == 'task-plan')
        required = {'task-plan.document', 'task-plan.external-document',
                    'task-plan.milestone', 'task-plan.batch-inline',
                    'task-plan.batch-file', 'task-plan.task',
                    'task-plan.dependency'}
        self.assertEqual(required, set(adapter['pattern_ids']))
        patterns = {item['id']: item for item in self.catalog['patterns']}
        self.assertIn('fpw-plan-profile: software-development/v1',
                      patterns['task-plan.document']['text'])
        self.assertIn('fpw-plan-document: definitions/v1',
                      patterns['task-plan.external-document']['text'])
        self.assertIn('](artifacts/', patterns['task-plan.batch-file']['text'])
        for pattern_id in required:
            result = self.service.validate('task-plan', 'text/markdown',
                                           patterns[pattern_id]['text'])
            self.assertTrue(result['valid'])
            self.assertTrue(result['lossless'])

    def test_presentation_pattern_and_round_trip_use_real_domain_format(self):
        pattern = next(item for item in self.catalog['patterns']
                       if item['id'] == 'presentation.document')
        result = self.service.validate(
            'presentation', 'application/x-fpw-presentation-markdown',
            pattern['text'])
        self.assertTrue(result['valid'])
        self.assertTrue(result['lossless'])
        self.assertEqual('DOPLNIT: název prezentace', result['value']['title'])
        serialized = self.service.serialize(
            'presentation', 'application/x-fpw-presentation-markdown',
            result['value'])
        self.assertEqual(pattern['text'], serialized['normalized_content'])

    def test_validation_rejects_unknown_format_oversize_and_invalid_deck(self):
        with self.assertRaisesRegex(ValueError, 'Neznámý'):
            self.service.validate('unknown', 'text/markdown', '')
        with self.assertRaisesRegex(ValueError, 'Neznámý'):
            self.service.validate('julia', 'text/markdown', '')
        with self.assertRaisesRegex(ValueError, '1 MiB'):
            self.service.validate('markdown', 'text/markdown', 'x' * (MAX_TEXT + 1))
        with self.assertRaises(ValueError):
            self.service.validate('presentation',
                                  'application/x-fpw-presentation-markdown',
                                  '<script>alert(1)</script>')
        with self.assertRaisesRegex(ValueError, 'JSON'):
            self.service.validate('julia', 'application/json', '{broken')
        with self.assertRaisesRegex(ValueError, 'TOML'):
            self.service.validate('julia', 'application/toml', 'name = [')

    def test_insertion_is_catalog_data_and_has_no_execution_or_save_callback(self):
        forbidden = {'callback', 'endpoint', 'script', 'save', 'execute'}
        for pattern in self.catalog['patterns']:
            self.assertFalse(forbidden & set(pattern))
            self.assertIn(pattern['insertion'], {'document', 'block', 'cursor'})

    def test_shared_widget_is_wired_to_document_and_presentation_without_save_endpoint(self):
        self.assertEqual(2, HTML.count('class="raw-editor-widget"'))
        self.assertIn('id="artifact-raw-widget"', HTML)
        self.assertIn('id="presentation-raw-widget"', HTML)
        self.assertIn('id="presentation-editor-mode-raw"', HTML)
        self.assertIn('function createRawEditorWidget(', JS)
        widget = JS[JS.index('function createRawEditorWidget('):
                    JS.index("const artifactEditorForm=")]
        self.assertNotIn('innerHTML', widget)
        self.assertIn('replaceChildren', widget)
        self.assertIn("helpTitle.textContent=pattern?.name||'Nápověda k souboru'", widget)
        self.assertIn('helpBody.textContent=pattern?.help||adapter?.format_help?.[format]',
                      widget)
        self.assertIn('helpExample.textContent=pattern?.example||adapter?.format_examples?.[format]',
                      widget)
        self.assertIn("patterns.length?'Vyberte vzor…'", widget)
        self.assertEqual(2, HTML.count('class="raw-editor-help-panel"'))
        self.assertEqual(2, HTML.count('data-raw-help-title'))
        self.assertEqual(2, HTML.count('data-raw-help-example'))
        self.assertIn('.raw-editor-layout{display:grid', CSS)
        self.assertIn('grid-template-columns:minmax(0,820px) minmax(260px,320px)',
                      CSS)
        self.assertIn('#artifact-raw-widget{width:min(1174px,calc(100vw - 388px))',
                      CSS)
        self.assertIn('.raw-editor-help-panel{', CSS)
        self.assertIn("projectRequest('/v1/document-patterns'", JS)
        self.assertIn("if(presentationEditorMode==='raw'&&!await applyPresentationRaw())return", JS)
        self.assertIn('presentationEditorDirty||presentationEditorAttempt', JS)
        self.assertIn('@media(max-width:700px)', CSS)
        self.assertIn('.raw-editor-layout{grid-template-columns:1fr}', CSS)
        self.assertIn('.raw-editor-widget textarea{font-size:16px}', CSS)
        self.assertIn('/v1/document-patterns', DesktopHandler.post_paths)
        self.assertNotIn('/v1/document-patterns/save', DesktopHandler.post_paths)


if __name__ == '__main__':
    unittest.main()
