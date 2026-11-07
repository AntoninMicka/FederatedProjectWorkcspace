# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import unittest

from spikes.metadata import ValidationError
from spikes.source_connectors import (SourceContext, RSSConnector, DocumentConnector, SearchConnector,
    WorkspaceOutputConnector, PlatformConnector, connector_catalog, validate_item, batch)
from spikes.reporting_schema import digest, encoded
from spikes.rss_sources import RSSSources
from tests.test_rss_pilot import rss
from tests import test_reporting as fixtures

NOW = '2026-11-06T17:00:00Z'
URL = 'https://example.test/feed'


def context(**changes):
    return SourceContext(**(dict(source_id='source-one', locator=URL, discovered_at=NOW,
        privacy='public', retention='test-memory-only', channel='Example') | changes))


class ConnectorContractTests(unittest.TestCase):
    def test_rss_read_uses_exact_source_and_link_identity_when_guid_is_empty(self):
        calls=[]
        def fetcher(url):
            calls.append(url);return rss(identifier='')
        result=RSSConnector(fetcher=fetcher).read(dict(url=URL),context())
        self.assertEqual(calls,[URL])
        self.assertIsNone(result['items'][0]['original_id'])
        self.assertEqual(result['items'][0]['url'],'https://example.test/article')
        validate_item(result['items'][0])

    def test_rss_document_and_search_share_one_item_and_batch_contract(self):
        ctx = context()
        batches = [RSSConnector().normalize(dict(raw=rss(), url=URL), ctx),
                   DocumentConnector().normalize(dict(raw=b'<title>Document</title><p>Body</p>', content_type='text/html', url=URL), ctx),
                   SearchConnector().normalize([dict(title='Result', url='https://example.test/article', snippet='Text')], ctx)]
        for result in batches:
            self.assertEqual(result['schema'], 'fpw-source-batch-v1')
            self.assertIsNone(result['continuation'])
            for item in result['items']:
                validate_item(item)
                self.assertEqual(item['schema'], 'fpw-source-item-v1')
                self.assertEqual(item['discovered_at'], NOW)
                self.assertIsNone(item['imported_at'])
                self.assertIsNone(item['published_at'])
                self.assertEqual(item['content_sha256'], digest(item['content'].encode()))
                self.assertEqual(item['privacy'], 'public')
                self.assertTrue(item['provenance']['untrusted'])

    def test_dates_are_separate_and_rss_unknown_author_is_not_fabricated(self):
        imported = '2026-11-06T18:00:00Z'
        item = RSSConnector().normalize(dict(raw=rss(date='Fri, 06 Nov 2026 16:00:00 +0100'),url=URL),
                                        context(imported_at=imported))['items'][0]
        self.assertEqual(item['published_at'], '2026-11-06T15:00:00Z')
        self.assertEqual(item['discovered_at'], NOW)
        self.assertEqual(item['imported_at'], imported)
        self.assertIsNone(item['author'])
        self.assertEqual(item['original_id'], 'one')

    def test_content_change_preserves_native_identity_and_changes_content_hash(self):
        first = RSSConnector().normalize(dict(raw=rss(),url=URL),context())['items'][0]
        raw = rss().replace(b'inert', b'corrected')
        second = RSSConnector().normalize(dict(raw=raw,url=URL),context())['items'][0]
        self.assertEqual(first['id'], second['id'])
        self.assertNotEqual(first['content_sha256'], second['content_sha256'])
        self.assertNotEqual(first['provenance']['raw_sha256'], second['provenance']['raw_sha256'])

    def test_no_event_confirmation_or_credentials_can_be_injected(self):
        item = RSSConnector().normalize(dict(raw=rss(),url=URL),context())['items'][0]
        for key in ['confirmed', 'event', 'progress', 'breakthrough', 'credentials']:
            malformed = dict(item, **{key: True})
            with self.subTest(key=key), self.assertRaises(ValidationError): validate_item(malformed)
        calls = []
        reader = RSSConnector(fetcher=lambda url: calls.append(url))
        with self.assertRaises(ValidationError):
            reader.read(dict(url=URL, api_token='not-a-real-secret'),context())
        self.assertEqual(calls, [])

    def test_item_hash_and_reference_must_match_exact_bytes(self):
        item = RSSConnector().normalize(dict(raw=rss(),url=URL),context())['items'][0]
        item['content_sha256'] = '0'*64
        with self.assertRaisesRegex(ValidationError, 'hash mismatch'): validate_item(item)

    def test_unsupported_continuation_and_local_only_fail_before_network(self):
        reader = RSSConnector(fetcher=lambda url: self.fail('unexpected network'))
        with self.assertRaisesRegex(ValidationError, 'continuation'):
            reader.read(dict(url=URL),context(),continuation='cursor')
        with self.assertRaisesRegex(ValidationError, 'Local-only'):
            reader.read(dict(url=URL),context(privacy='local-only'))
        private='http://127.0.0.1/feed'
        with self.assertRaises(ValidationError):
            reader.read(dict(url=private),context(locator=private))

    def test_catalog_declares_availability_permissions_and_node_local_credentials(self):
        catalog = {row['id']:row for row in connector_catalog()}
        self.assertEqual(set(catalog), {'rss-atom','static-text','web-search','platform-channel','workspace-output'})
        self.assertEqual(catalog['rss-atom']['availability']['state'], 'ready')
        self.assertEqual(catalog['web-search']['availability']['state'], 'not-configured')
        self.assertEqual(catalog['platform-channel']['availability']['state'], 'unavailable')
        self.assertEqual(catalog['workspace-output']['availability']['state'], 'not-configured')
        for row in catalog.values():
            self.assertFalse(row['config_schema']['additionalProperties'])
            self.assertEqual(row['continuation']['kind'], 'http-validators' if row['id']=='rss-atom' else 'none')
            self.assertEqual(row['credential_storage'], 'node-local')
            self.assertNotIn('api-token', row['config_fields'])
            self.assertIn('max_items', row['limits'])
        with self.assertRaisesRegex(ValueError, 'dostupné'):
            PlatformConnector().read({},context())

    def test_unavailable_channel_does_not_fall_back_to_rss(self):
        channels=[dict(id='platform',name='Platform',url=URL,connector='platform-channel')]
        service = RSSSources(channels=channels,fetcher=lambda url:self.fail('unexpected RSS fallback'))
        self.assertEqual(service.view()['channels'][0]['state'],'unavailable')
        result = service.refresh('all')
        self.assertEqual(result['items'],[])
        self.assertEqual(result['channels'][0]['state'],'unavailable')

    def test_rss_view_exposes_normalized_items_with_original_capture_provenance(self):
        now=[0]; raw=[rss()]
        service = RSSSources(channels=[dict(id='rss',name='RSS',url=URL)],
                             fetcher=lambda url:raw[0],clock=lambda:now[0])
        initial=service.refresh('all')
        first = initial['items'][0]
        self.assertNotIn('schema',initial['entries'][0])
        now[0]=31
        raw[0]=b'<rss version="2.0"><channel><title>Empty</title></channel></rss>'
        second = service.refresh('all')['items'][0]
        self.assertEqual(first['provenance']['raw_sha256'],second['provenance']['raw_sha256'])
        self.assertEqual(first['discovered_at'],second['discovered_at'])
        self.assertIsNone(second['imported_at'])
        validate_item(second)

    def test_connector_output_rejects_wrong_mime_oversized_text_and_identity_mismatch(self):
        for payload in [dict(raw=b'%PDF',content_type='application/pdf',url=URL),
                        dict(raw=b'x'*600000,content_type='text/plain',url=URL),
                        dict(raw=b'x',content_type='text/plain',url='https://other.test/')]:
            with self.subTest(payload=payload['content_type']), self.assertRaises((ValueError,RuntimeError)):
                DocumentConnector().normalize(payload,context())
        with self.assertRaises(ValidationError):
            SearchConnector().normalize([dict(title='Unsafe',url='javascript:alert(1)',snippet='Text')],context())


class WorkspaceOutputConnectorTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ReportingTests('test_manual_event_multiple_sources_and_read_projection')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.pin=self.f.store('ReportSnapshot',self.f.publication(),confirm=True,
                              markdown='# Přehled\n\nNebyla doložena významná změna.\n')
        self.reader=WorkspaceOutputConnector(self.f.node)

    def test_pinned_report_uses_same_normalized_contract_without_project_write(self):
        head=self.f.git.head()
        result=self.reader.read(dict(project_id=self.f.project,report_ref=self.pin),context(privacy='project'))
        item=result['items'][0];validate_item(item)
        self.assertEqual(item['connector'],'workspace-output')
        self.assertEqual(item['original_id'],self.pin['artifact_id'])
        self.assertEqual(item['provenance']['input_ref'],self.pin)
        self.assertEqual(item['content_sha256'],item['content_ref']['sha256'])
        self.assertEqual(item['content'],'# Přehled\n\nNebyla doložena významná změna.\n')
        self.assertIsNone(item['imported_at'])
        self.assertEqual(self.f.git.head(),head)
        self.assertEqual(self.f.git.run('status','--porcelain').stdout,'')

    def test_privacy_cross_project_hash_and_unissued_input_fail_closed(self):
        with self.assertRaisesRegex(ValidationError,'project read permission'):
            WorkspaceOutputConnector(self.f.node,network=True).read(
                dict(project_id=self.f.project,report_ref=self.pin),context(privacy='project'))
        for config, ctx in [
            (dict(project_id=self.f.project,report_ref=self.pin),context()),
            (dict(project_id=self.f.project,report_ref=dict(self.pin,sha256='0'*64)),context(privacy='project')),
            (dict(project_id=self.f.project,report_ref=self.f.task),context(privacy='project')),
        ]:
            with self.subTest(config=config),self.assertRaises(ValidationError): self.reader.read(config,ctx)
        other=dict(self.pin,project_id='00000000-0000-4000-8000-000000000001')
        with self.assertRaisesRegex(ValidationError,'authorized'):
            self.reader.read(dict(project_id=self.f.project,report_ref=other),context(privacy='project'))
