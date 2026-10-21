# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from spikes.web_search import (SearXNGAdapter, SearXNGBindings, SearXNGBinding,
                               SearchResponseError, SearchRuns, SearchUnknown)


class WebSearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'search'
        self.root.mkdir(mode=0o700)
        self.binding = SearXNGBinding.parse({
            'schema_version': 1, 'binding_id': str(uuid4()), 'revision': 'one',
            'adapter': 'searxng', 'boundary': 'same-node',
            'endpoint': 'http://127.0.0.1:8888', 'target_id': 'local-process',
            'result_limit': 3, 'timeout_seconds': 15})

    def tearDown(self):
        self.temporary.cleanup()

    def request(self):
        return {'task_id': str(uuid4()), 'search_id': str(uuid4()),
                'project_id': str(uuid4()), 'synthesis_run_id': str(uuid4()),
                'synthesis_manifest_id': str(uuid4()), 'query': 'current facts',
                'privacy': 'project', 'created_at': '2026-10-12T12:00:00Z'}

    def prepare(self, request=None):
        request = request or self.request()
        preview = {'schema_version': 1, 'search_id': request['search_id'],
                   'task_id': request['task_id'], 'query': request['query'],
                   'privacy': request['privacy'], 'binding': self.binding.serialize()}
        row = SearchRuns(self.root).prepare(search_id=request['search_id'],
            task_id=request['task_id'], node_id=str(uuid4()), user_id=str(uuid4()),
            project_id=request['project_id'], request=request, preview=preview,
            binding=self.binding)
        return request, row

    def test_binding_is_atomic_and_fail_closed(self):
        bindings = SearXNGBindings(self.root)
        bindings.save(self.binding)
        self.assertEqual(bindings.load(), self.binding)
        self.assertEqual((self.root / 'searxng-binding.json').stat().st_mode & 0o777, 0o600)
        bad = self.binding.serialize(); bad['endpoint'] = 'http://searxng:8080'
        with self.assertRaisesRegex(ValueError, 'numeric IP'):
            SearXNGBinding.parse(bad)
        bad = self.binding.serialize(); bad.update(
            boundary='private-network', endpoint='https://10.0.0.2:8443',
            target_id=str(uuid4()))
        with self.assertRaisesRegex(ValueError, 'certificate pin'):
            SearXNGBinding.parse(bad)

    def test_search_result_is_bounded_deduplicated_and_replayed(self):
        request, row = self.prepare()
        calls = []
        def transport(binding, query):
            calls.append((binding, query))
            return {'query': query, 'results': [
                {'title': 'One', 'url': 'https://example.test/one', 'content': 'First'},
                {'title': 'Duplicate', 'url': 'https://example.test/one', 'content': 'Ignored'},
                {'title': 'Two', 'url': 'https://example.test/two', 'content': '<script>x</script>'},
                {'title': 'Three', 'url': 'https://example.test/three', 'content': ''},
                {'title': 'Four', 'url': 'https://example.test/four', 'content': 'bounded'}]}
        adapter = SearXNGAdapter(SearchRuns(self.root), transport=transport)
        result = adapter.dispatch(request['search_id'], self.binding,
                                  preview_sha256=row['preview_sha256'],
                                  now=lambda: '2026-10-12T12:01:00Z')
        self.assertEqual([item['title'] for item in result['results']], ['One', 'Two', 'Three'])
        self.assertEqual(result['results'][1]['snippet'], '<script>x</script>')
        self.assertRegex(result['results'][0]['source_id'], r'^source-[0-9a-f]{32}$')
        self.assertEqual(result['results'][0]['source_id'],
                         adapter.dispatch(request['search_id'], self.binding,
                         preview_sha256=row['preview_sha256'])['results'][0]['source_id'])
        self.assertEqual(result['source']['binding_revision'], 'one')
        self.assertEqual(adapter.dispatch(request['search_id'], self.binding,
                         preview_sha256=row['preview_sha256']), result)
        self.assertEqual(len(calls), 1)

    def test_iterative_workflow_is_bounded_and_rounds_are_durable(self):
        runs = SearchRuns(self.root)
        task_id, node_id, user_id, project_id = (str(uuid4()) for _ in range(4))
        first_search, first_run, first_manifest = (str(uuid4()) for _ in range(3))
        request = {'task_id': task_id, 'search_id': first_search,
                   'project_id': project_id, 'query': 'first', 'privacy': 'project',
                   'created_at': '2026-10-12T12:00:00Z',
                   'synthesis_run_id': first_run,
                   'synthesis_manifest_id': first_manifest}
        runs.prepare_round(search_id=first_search, task_id=task_id,
            search_task_id=task_id, node_id=node_id, user_id=user_id,
            project_id=project_id, privacy='project', expected_head='a' * 40,
            request=request, preview={'search_id': first_search}, binding=self.binding,
            round_index=1, parent_search_id=None, synthesis_run_id=first_run,
            synthesis_manifest_id=first_manifest, now=lambda: 100.0)
        runs.transition(first_search, 'prepared', 'dispatching')
        runs.transition(first_search, 'dispatching', 'succeeded', result={
            'schema_version': 1, 'query': 'first', 'searched_at': '2026-10-12T12:00:00Z',
            'source': {}, 'results': [{'source_id': 'source-one'}]})
        evaluation = {'schema_version': 1, 'assessment': 'intermediate',
            'answer': 'Partial', 'rationale': 'Need more', 'used_source_ids': [],
            'limitations': [], 'follow_up_queries': ['second']}
        workflow = runs.record_evaluation(task_id, node_id, user_id, first_search,
                                          evaluation)
        self.assertEqual(workflow['rounds'][0]['evaluation'], evaluation)
        self.assertEqual(runs.budget_state(workflow, now=lambda: 105.0), {
            'rounds_used': 1, 'queries_used': 1, 'results_used': 1,
            'elapsed_seconds': 5})
        with self.assertRaisesRegex(ValueError, 'round exceeds budget'):
            runs.prepare_round(search_id=str(uuid4()), task_id=task_id,
                search_task_id=str(uuid4()), node_id=node_id, user_id=user_id,
                project_id=project_id, privacy='project', expected_head='a' * 40,
                request=dict(request, query='too late'), preview={}, binding=self.binding,
                round_index=4, parent_search_id=first_search,
                synthesis_run_id=str(uuid4()), synthesis_manifest_id=str(uuid4()))

    def test_invalid_response_is_failed_and_unknown_transport_is_not_retried(self):
        request, row = self.prepare()
        adapter = SearXNGAdapter(SearchRuns(self.root), transport=lambda *_: {
            'query': request['query'], 'results': [
                {'title': 'Bad', 'url': 'javascript:alert(1)', 'content': 'x'}]})
        with self.assertRaisesRegex(SearchResponseError, 'Invalid SearXNG response'):
            adapter.dispatch(request['search_id'], self.binding,
                             preview_sha256=row['preview_sha256'])
        self.assertEqual(SearchRuns(self.root).get(request['search_id'])['state'], 'failed')

        second, second_row = self.prepare()
        calls = []
        def timeout(*_):
            calls.append(1); raise TimeoutError('lost response')
        adapter = SearXNGAdapter(SearchRuns(self.root), transport=timeout)
        with self.assertRaises(SearchUnknown):
            adapter.dispatch(second['search_id'], self.binding,
                             preview_sha256=second_row['preview_sha256'])
        with self.assertRaises(SearchUnknown):
            adapter.dispatch(second['search_id'], self.binding,
                             preview_sha256=second_row['preview_sha256'])
        self.assertEqual(calls, [1])

    def test_zero_results_and_probe_use_exact_public_query(self):
        value = {'query': 'SearXNG', 'results': []}
        probe = SearXNGAdapter.probe(self.binding, transport=lambda binding, query: value)
        self.assertEqual(probe['result_count'], 0)
        self.assertEqual(SearXNGAdapter.validate_response(
            {'query': 'none', 'results': []}, self.binding, 'none',
            '2026-10-12T12:00:00Z')['results'], [])

    def test_http_transport_rejects_redirect_oversize_invalid_json_and_unavailable(self):
        class Response:
            def __init__(self, status, raw=b''):
                self.status, self.raw = status, raw
            def read(self, _limit):
                return self.raw

        class Connection:
            def __init__(self, response=None, connect_error=None):
                self.response, self.connect_error = response, connect_error
                self.sock = None; self.requests = []
            def connect(self):
                if self.connect_error: raise self.connect_error
            def request(self, *args, **kwargs): self.requests.append((args, kwargs))
            def getresponse(self): return self.response
            def close(self): pass

        parsed = urlsplit(self.binding.endpoint)
        cases = (
            (Connection(Response(302)), 'redirect'),
            (Connection(Response(200, b'x' * (2 * 1024 * 1024 + 1))), 'exceeds'),
            (Connection(Response(200, b'{bad')), 'Invalid SearXNG JSON'),
            (Connection(connect_error=ConnectionRefusedError()), 'unavailable'),
        )
        for connection, message in cases:
            with self.subTest(message=message), patch.object(
                    SearXNGAdapter, '_connection', return_value=(parsed, connection)):
                with self.assertRaisesRegex(SearchResponseError, message):
                    SearXNGAdapter._http_transport(self.binding, 'public query')
                if connection.response is not None:
                    self.assertIn('language=cs-CZ', connection.requests[0][0][1])


if __name__ == '__main__':
    unittest.main()
