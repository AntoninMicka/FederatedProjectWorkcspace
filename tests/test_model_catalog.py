# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile
import unittest

from spikes.metadata import ValidationError
from spikes.model_catalog import (ModelDiscoveryStore, ModelKnowledgeStore,
                                  collect_discovery_pages, project_catalog, validate_discovery,
                                  validate_knowledge)


NOW = '2026-10-25T12:00:00+00:00'


def capability(name, value, state, source='review:operator', revision='review-v1'):
    return {'name': name, 'value': value, 'state': state, 'source': source,
            'revision': revision, 'observed_at': NOW}


def offer(offer_id='openai:gpt-shared', provider='openai', model='gpt-shared',
          canonical='canonical:gpt-shared', capabilities=None):
    return {'offer_id': offer_id, 'provider_id': provider,
            'provider_model_id': model, 'protocol': 'openai-responses-v1',
            'canonical_model_id': canonical,
            'capabilities': capabilities or []}


def knowledge(offers=None, models=None):
    return {'schema_version': 1, 'revision': 'knowledge-v1', 'reviewed_at': NOW,
            'models': models if models is not None else [
                {'model_id': 'canonical:gpt-shared', 'display_name': 'Shared model'}],
            'offers': offers if offers is not None else [offer()]}


def discovered(offers=None, binding='binding-v1', credential=1):
    return {'schema_version': 1, 'provider_id': 'openai', 'scope_id': 'scope:one',
            'binding_revision': binding, 'credential_revision': credential,
            'fetched_at': NOW, 'offers': offers if offers is not None else [{
                'offer_id': 'openai:gpt-shared', 'provider_id': 'openai',
                'provider_model_id': 'gpt-shared',
                'protocol': 'openai-responses-v1', 'availability': 'available',
                'capabilities': []}]}


class ModelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'state'; self.root.mkdir(mode=0o700)

    def test_knowledge_separates_canonical_offer_and_same_provider_name(self):
        value = knowledge(
            models=[{'model_id': 'canonical:a', 'display_name': 'A'},
                    {'model_id': 'canonical:b', 'display_name': 'B'}],
            offers=[offer('offer:a', model='same-name', canonical='canonical:a'),
                    dict(offer('offer:b', model='same-name', canonical='canonical:b'),
                         protocol='ollama-generate-v1', provider_id='ollama')])
        normalized = validate_knowledge(value)
        self.assertEqual([item['canonical_model_id'] for item in normalized['offers']],
                         ['canonical:a', 'canonical:b'])
        duplicate = json.loads(json.dumps(value))
        duplicate['offers'][1]['provider_id'] = 'openai'
        duplicate['offers'][1]['protocol'] = 'openai-responses-v1'
        with self.assertRaisesRegex(ValidationError, 'Duplicate provider model offer'):
            validate_knowledge(duplicate)

    def test_unknown_fields_capabilities_and_dangling_model_fail_closed(self):
        cases = []
        extra = knowledge(); extra['secret'] = 'must-not-pass'; cases.append(extra)
        unknown = knowledge(); unknown['offers'][0]['capabilities'] = [
            capability('telepathy', True, 'reviewed')]; cases.append(unknown)
        dangling = knowledge(); dangling['offers'][0]['canonical_model_id'] = 'missing'
        cases.append(dangling)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_knowledge(value)

    def test_atomic_knowledge_import_preserves_previous_on_invalid_value(self):
        store = ModelKnowledgeStore(self.root)
        previous = store.save(knowledge(), expected_revision='empty-v1')
        invalid = knowledge(); invalid['offers'][0]['capabilities'] = [
            capability('generate-text', True, 'reported')]
        with self.assertRaisesRegex(ValidationError, 'state'):
            store.save(invalid)
        changed = knowledge(); changed['revision'] = 'knowledge-v2'
        with self.assertRaisesRegex(ValidationError, 'changed before import'):
            store.save(changed, expected_revision='empty-v1')
        self.assertEqual(store.load(), previous)
        self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('credential', json.dumps(store.export()))

    def test_discovery_retains_removed_offer_and_marks_revision_mismatch_stale(self):
        store = ModelDiscoveryStore(self.root, 'openai', 'scope:one')
        first = store.publish(discovered())
        self.assertEqual(first['offers'][0]['availability'], 'available')
        second = store.publish(discovered(offers=[], binding='binding-v2', credential=2))
        self.assertEqual(second['offers'][0]['availability'], 'removed')
        self.assertEqual(store.load('binding-v2', 2)['freshness'], 'fresh')
        stale = store.load('binding-v3', 2, refresh_error='rate-limited')
        self.assertEqual((stale['freshness'], stale['refresh_error']),
                         ('stale', 'rate-limited'))

    def test_discovery_is_bounded_and_provider_scoped(self):
        foreign = discovered(); foreign['offers'][0]['provider_id'] = 'ollama'
        with self.assertRaisesRegex(ValidationError, 'different provider'):
            validate_discovery(foreign)
        oversized = discovered(offers=[])
        oversized['offers'] = [dict(discovered()['offers'][0],
                                    offer_id=f'openai:model-{index}',
                                    provider_model_id=f'model-{index}')
                               for index in range(10001)]
        with self.assertRaisesRegex(ValidationError, 'discovered model offers'):
            validate_discovery(oversized)

    def test_pagination_is_bounded_nonrepeating_and_does_not_retry(self):
        calls = []
        pages = {'page-2': {'items': ['b'], 'next_cursor': None}}
        result = collect_discovery_pages({'items': ['a'], 'next_cursor': 'page-2'},
            lambda cursor: (calls.append(cursor), pages[cursor])[1])
        self.assertEqual((result, calls), (['a', 'b'], ['page-2']))
        with self.assertRaisesRegex(ValidationError, 'Repeated'):
            collect_discovery_pages({'items': [], 'next_cursor': 'repeat'},
                                    lambda _: {'items': [], 'next_cursor': 'repeat'})
        with self.assertRaisesRegex(ValueError, 'page count'):
            collect_discovery_pages({'items': [], 'next_cursor': 'next'},
                                    lambda _: {'items': [], 'next_cursor': None},
                                    max_pages=1)
        failures = []
        def rejected(cursor):
            failures.append(cursor); raise RuntimeError('rate-limited')
        with self.assertRaisesRegex(RuntimeError, 'rate-limited'):
            collect_discovery_pages({'items': [], 'next_cursor': 'next'}, rejected)
        self.assertEqual(failures, ['next'])

    def test_projection_uses_reported_then_reviewed_and_conflict_is_unsupported(self):
        reviewed = knowledge(offers=[offer(capabilities=[
            capability('generate-text', True, 'reviewed'),
            capability('json-output', True, 'reviewed')])])
        report = discovered(); report['offers'][0]['capabilities'] = [
            capability('generate-text', False, 'reported',
                       source='binding:one', revision='binding-cap-v1')]
        report = dict(validate_discovery(report), freshness='fresh', refresh_error=None)
        result = project_catalog(reviewed, [report])
        caps = {item['name']: item for item in result['offers'][0]['capabilities']}
        self.assertEqual((caps['generate-text']['state'],
                          caps['generate-text']['supported']), ('conflicting', False))
        self.assertEqual((caps['json-output']['state'],
                          caps['json-output']['supported']), ('reviewed', True))
        self.assertEqual(caps['streaming']['state'], 'unknown')

    def test_multiple_offers_can_reference_one_model_without_fallback(self):
        reviewed = knowledge(offers=[offer(),
            offer('ollama:qwen', provider='ollama', model='qwen',
                  canonical='canonical:gpt-shared')])
        report = dict(validate_discovery(discovered()), freshness='fresh',
                      refresh_error=None)
        result = project_catalog(reviewed, [report])
        self.assertEqual(len(result['offers']), 2)
        ollama = next(item for item in result['offers'] if item['provider_id'] == 'ollama')
        self.assertEqual((ollama['availability'], ollama['freshness']),
                         ('not-observed', 'stale'))
        self.assertNotIn('selected_offer_id', result)


if __name__ == '__main__':
    unittest.main()
