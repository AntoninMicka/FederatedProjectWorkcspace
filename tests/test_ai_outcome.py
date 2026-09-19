# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import unittest
from uuid import uuid4

from spikes.ai_outcome import AITaskOutcome


class AITaskOutcomeTests(unittest.TestCase):
    def test_three_closed_variants_round_trip_long_content(self):
        message_id, artifact_id = str(uuid4()), str(uuid4())
        values = [
            {'schema_version': 1, 'kind': 'direct-answer',
             'content': 'odpověď'},
            {'schema_version': 1, 'kind': 'artifact-draft',
             'artifact_kind': 'document', 'title': 'Návrh',
             'content': 'x' * 100000},
            {'schema_version': 1, 'kind': 'external-request',
             'purpose': 'Aktuální rešerše', 'query': 'q' * 100000,
             'message_ids': [message_id], 'artifact_ids': [artifact_id]},
        ]
        for value in values:
            with self.subTest(kind=value['kind']):
                parsed = AITaskOutcome.parse(value)
                self.assertEqual(parsed.serialize(), value)
                self.assertEqual(AITaskOutcome.parse(
                    __import__('json').loads(parsed.canonical())).serialize(), value)

    def test_unknown_fields_kinds_and_unsafe_references_fail_closed(self):
        valid = {'schema_version': 1, 'kind': 'external-request',
                 'purpose': 'Rešerše', 'query': 'Najdi zdroje',
                 'message_ids': [str(uuid4())], 'artifact_ids': []}
        invalid = [dict(valid, provider='openai'), dict(valid, kind='tool-call'),
                   dict(valid, message_ids=['not-a-uuid']),
                   dict(valid, message_ids=valid['message_ids'] * 2),
                   {'schema_version': 1, 'kind': 'artifact-draft',
                    'artifact_kind': 'executable', 'title': 'X', 'content': 'Y'},
                   {'schema_version': 1, 'kind': 'direct-answer', 'content': ''}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                AITaskOutcome.parse(value)


if __name__ == '__main__':
    unittest.main()
