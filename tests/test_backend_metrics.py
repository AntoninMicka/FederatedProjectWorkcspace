# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from spikes.backend_metrics import MetricTransportError, OpenAIAccountMetrics, run_usage


class BackendMetricTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'state'; self.root.mkdir(mode=0o700)

    def test_run_usage_distinguishes_supported_zero_and_missing(self):
        report = run_usage('ollama', 'binding', 'run', {
            'prompt_eval_count': 0, 'eval_count': 4, 'total_duration': 10},
            '2026-09-20T10:00:00Z')
        self.assertEqual(report['status'], 'available')
        self.assertEqual([(item['name'], item['value']) for item in report['metrics']],
                         [('input_tokens', 0), ('output_tokens', 4),
                          ('total_duration', 10)])
        missing = run_usage('openai-responses', 'binding', 'run', {},
                            '2026-09-20T10:00:00Z')
        self.assertEqual((missing['status'], missing['metrics']), ('unsupported', []))

    def test_account_refresh_aggregates_pages_and_uses_admin_secret(self):
        calls = []
        def transport(path, secret):
            calls.append((path, secret)); parsed = urlsplit(path); query = parse_qs(parsed.query)
            self.assertEqual(query['start_time'], ['100'])
            if parsed.path.endswith('/usage/completions'):
                if 'page' not in query:
                    return {'data': [{'results': [{'input_tokens': 2,
                        'output_tokens': 3, 'num_model_requests': 1}]}],
                        'has_more': True, 'next_page': 'next'}
                return {'data': [{'results': [{'input_tokens': 5,
                    'output_tokens': 7, 'num_model_requests': 2}]}], 'has_more': False}
            return {'data': [{'results': [{'amount': {'value': 1.25,
                'currency': 'usd'}}]}], 'has_more': False}
        metrics = OpenAIAccountMetrics(self.root, transport)
        status = metrics.configure('sk-admin-' + 'x' * 32)
        self.assertTrue(status['credential']['available'])
        self.assertNotIn('sk-admin', metrics.path.read_text())
        report = metrics.refresh(100, 200)
        values = {item['name']: item['value'] for part in report['reports']
                  for item in part['metrics']}
        self.assertEqual(values, {'input_tokens': 7, 'output_tokens': 10,
                                  'model_requests': 3, 'cost': 1.25})
        self.assertEqual(len(calls), 3)

    def test_refresh_failure_returns_stale_cache_or_unavailable(self):
        good = OpenAIAccountMetrics(self.root, lambda *_:
            {'data': [{'results': []}], 'has_more': False})
        good.configure('sk-admin-' + 'x' * 32)
        self.assertEqual(good.refresh(100, 200)['status'], 'available')
        stale = OpenAIAccountMetrics(self.root, lambda *_:
            (_ for _ in ()).throw(MetricTransportError('timeout')))
        self.assertEqual(stale.refresh(100, 200)['status'], 'stale')

        other = Path(self.temp.name) / 'other'; other.mkdir(mode=0o700)
        failing = OpenAIAccountMetrics(other, lambda *_:
            (_ for _ in ()).throw(MetricTransportError('forbidden', forbidden=True)))
        failing.configure('sk-admin-' + 'y' * 32)
        self.assertEqual(failing.refresh(100, 200)['status'], 'forbidden')

    def test_period_and_pagination_are_bounded(self):
        metrics = OpenAIAccountMetrics(self.root, lambda *_: {'data': [], 'has_more': False})
        metrics.configure('sk-admin-' + 'x' * 32)
        with self.assertRaisesRegex(ValueError, 'period'):
            metrics.refresh(200, 100)
        looping = OpenAIAccountMetrics(self.root, lambda *_:
            {'data': [], 'has_more': True, 'next_page': 'same'})
        with self.assertRaisesRegex(ValueError, 'pagination'):
            looping.refresh(100, 200)
