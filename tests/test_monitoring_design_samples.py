# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.monitoring_design_samples import collect, read_article
from spikes.public_source import HTTPResult
from spikes.rss_reader import parse_feed
from spikes.reporting_schema import encoded
from tests import test_monitoring_blocks as block_fixtures


URL='https://example.org/attack'
RAW=('''<rss version="2.0"><channel><title>News</title><item><guid>attack</guid>
<link>'''+URL+'''</link><title>Útoky v Kyjevě</title>
<description>Na severozápadě Ukrajiny.</description><category>Svět</category>
</item></channel></rss>''').encode()


class DesignSamplesTests(unittest.TestCase):
    def setUp(self):
        self.env=block_fixtures.BlockTests('test_shared_blocks_usage_and_atomic_validation')
        self.env.setUp();self.addCleanup(self.env.doCleanups)
        self.service=self.env.service;self.pid=self.env.f.project
        self.source=next(b for b in self.service.blocks.read(self.pid)['blocks'] if b['id']==self.env.specs[0]['id'])

    def feed(self,*args,**kwargs):
        return dict(status=200,raw=RAW,validators={})

    def test_categories_and_page_context_do_not_masquerade_as_runtime_fields(self):
        pages=[]
        def article(url):pages.append(url);return dict(text='Plný text článku o válce na Ukrajině.',raw_sha256='a'*64)
        evidence,items=collect(self.source,self.feed,'2026-11-12T09:00:00Z',article_fetcher=article)
        self.assertEqual(pages,[URL]);self.assertEqual(evidence['candidates'][0]['categories'],['Svět'])
        self.assertIn('Plný text',evidence['candidates'][0]['article']['text'])
        self.assertEqual(items[0]['content'],'Na severozápadě Ukrajiny.')
        self.assertNotIn('categories',items[0])
        self.assertIn('not a historical archive',evidence['coverage'])

    def test_atom_categories_and_excessive_categories(self):
        raw=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>a</id><category term="Ukraine"/></entry></feed>'
        self.assertEqual(parse_feed(raw,'https://example.org/rss')['entries'][0]['categories'],['Ukraine'])
        raw=RAW.replace(b'<category>',b'<category>'+b'a'*513)
        with self.assertRaisesRegex(ValueError,'categories'):parse_feed(raw,'https://example.org/rss')

    def test_full_content_in_feed_is_used_before_short_description(self):
        raw=RAW.replace(b'<rss version="2.0">',b'<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">')
        raw=raw.replace(b'</description>',b'</description><content:encoded>Full article text</content:encoded>')
        self.assertEqual(parse_feed(raw,'https://example.org/rss')['entries'][0]['content'],'Full article text')

    def test_cross_origin_article_is_not_followed_and_feed_failure_is_explicit(self):
        def feed(*a,**kw):return dict(status=200,raw=RAW.replace(URL.encode(),b'https://other.example/article'),validators={})
        evidence,_=collect(self.source,feed,'2026-11-12T09:00:00Z',article_fetcher=lambda u:self.fail('Cross-origin GET'))
        self.assertEqual(evidence['candidates'][0]['article']['state'],'different-origin-or-missing-url')
        with self.assertRaisesRegex(ValueError,'full feed'):
            collect(self.source,lambda *a,**k:dict(status=304),'2026-11-12T09:00:00Z')

    def test_article_reader_obeys_robots_and_rejects_redirects(self):
        def denied(url,*a,**k):return HTTPResult(200,{'content-type':'text/plain'},b'User-agent: *\nDisallow: /',url)
        with patch('spikes.monitoring_design_samples.StaticHTMLAdapter._get',side_effect=denied):
            with self.assertRaisesRegex(ValueError,'robots'):read_article(URL)
        def redirect(url,*a,**k):
            return (HTTPResult(200,{'content-type':'text/plain'},b'User-agent: *\nAllow: /',url) if url.endswith('robots.txt') else HTTPResult(302,{},b'',url))
        with patch('spikes.monitoring_design_samples.StaticHTMLAdapter._get',side_effect=redirect):
            with self.assertRaisesRegex(ValueError,'redirect'):read_article(URL)

    def proposal(self):
        b=deepcopy(self.env.specs[2])
        b['previous']=[next(r for r in self.service.blocks.read(self.pid)['blocks'] if r['id']==b['id'])['ref']]
        b['value']['config']['pipeline']['steps']=[dict(id='topic',kind='regex',fields=['title','content'],
            pattern='ukrajin|válk|valk',flags=['IGNORECASE'],match='search',negate=False)]
        return dict(blocks=[b],explanation='Explicitní tvary pro ověřený kanál; jiná redakce není ověřena.')

    def test_filter_design_uses_manifest_samples_and_actual_engine_then_replays_without_effects(self):
        proposal=self.proposal();calls=[];gets=[]
        def transport(binding,request):
            calls.append(request);return dict(model=binding.model,response=encoded(proposal).decode(),done=True)
        self.env.model(transport)
        def fetch(*a,**kw):gets.append(a);return self.feed()
        self.service.fetcher=fetch;run=str(uuid4());head=self.env.f.git.head()
        with patch('spikes.monitoring_design_samples.read_article',return_value=dict(text='Plný článek',raw_sha256='a'*64)) as page:
            result=self.service.compose(self.pid,run,'Sledovat válku na Ukrajině',confirm=True,
                source_ids=[self.source['id']],proposal_kind='filter')
            repeated=self.service.compose(self.pid,run,'Sledovat válku na Ukrajině',confirm=True,
                source_ids=[self.source['id']],proposal_kind='filter')
        self.assertEqual(result,repeated);self.assertEqual((len(calls),len(gets),page.call_count),(1,1,1))
        self.assertIn('source_samples',str(calls))
        self.assertIn('literal substrings',str(calls))
        self.assertEqual(result['result']['calibration'][0]['results'][0]['decision'],'selected')
        self.assertNotIn('Plný článek',json.dumps(result,ensure_ascii=False))
        self.assertEqual(head,self.env.f.git.head());self.assertEqual(self.service.pools.export(self.pid),[])
        job=next(j for j in self.service.catalog(self.pid)['jobs'] if j['id']==run)
        self.assertIn('manifest',job['intent'])
        with self.assertRaisesRegex(ValueError,'another request'):
            self.service.compose(self.pid,run,'Sledovat válku na Ukrajině',confirm=True,source_ids=[],proposal_kind='filter')

    def test_failed_sampling_never_dispatches_model_or_automatically_fetches_again(self):
        self.service.fetcher=lambda *a,**k:(_ for _ in ()).throw(TimeoutError('interrupted'))
        run=str(uuid4())
        with patch.object(self.service,'_model',side_effect=AssertionError('No model effect')):
            with self.assertRaises(TimeoutError):
                self.service.compose(self.pid,run,'Topic',confirm=True,source_ids=[self.source['id']])
            result=self.service.compose(self.pid,run,'Topic',confirm=True,source_ids=[self.source['id']])
            self.assertEqual(result['state'],'unknown')

    def test_process_crash_during_sampling_recovers_unknown_without_second_get(self):
        script='''
import os,sys
from pathlib import Path
from spikes.monitoring import Monitoring
from spikes.projects import Projects
from spikes.composable_monitoring import ComposableMonitoring
node=Path(sys.argv[1]);m=Monitoring(node,Projects(node))
c=ComposableMonitoring(m,fetcher=lambda *a,**kw:os._exit(73))
c.compose(sys.argv[2],sys.argv[3],'Topic',confirm=True,source_ids=[sys.argv[4]])
'''
        run=str(uuid4())
        completed=subprocess.run([sys.executable,'-c',script,str(self.env.f.node),self.pid,run,self.source['id']],capture_output=True,text=True,timeout=15)
        self.assertEqual(completed.returncode,73,completed.stdout+completed.stderr)
        self.service.fetcher=lambda *a,**kw:self.fail('No automatic GET after process crash')
        result=self.service.compose(self.pid,run,'Topic',confirm=True,source_ids=[self.source['id']])
        self.assertEqual(result['state'],'unknown')

    def test_task_design_tests_reused_filters_and_reports_unsampled_channels(self):
        task=deepcopy(self.env.specs[4]);task['id']=str(uuid4())
        self.service.fetcher=self.feed
        def model(*a,**kw):return encoded(dict(blocks=[task],explanation='Reuse existing filters')).decode()
        with patch.object(self.service,'_model',side_effect=model),patch('spikes.monitoring_design_samples.read_article',side_effect=ValueError('unavailable')):
            result=self.service.compose(self.pid,str(uuid4()),'Topic',confirm=True,source_ids=[self.source['id']])
            reused=result['result']['calibration'][0]
            self.assertEqual(reused['filter_id'],self.env.specs[2]['id'])
            self.assertEqual(reused['results'][0]['decision'],'selected')
            self.assertEqual(result['result']['sample_coverage'][0]['articles'][0]['state'],'unavailable')
            result=self.service.compose(self.pid,str(uuid4()),'Topic',confirm=True)
            self.assertEqual(result['result']['calibration'][0]['state'],'not-sampled')

    def test_source_validation_and_confirmation_precede_network(self):
        self.service.fetcher=lambda *a,**k:self.fail('No unauthorized GET')
        for sources in ([str(uuid4())],[self.source['id']]*2,[self.source['id']]*4):
            with self.assertRaises(ValueError):self.service.compose(self.pid,str(uuid4()),'Topic',confirm=True,source_ids=sources)
        with self.assertRaises(ValueError):
            self.service.compose(self.pid,str(uuid4()),'Topic',confirm=False,source_ids=[self.source['id']])
        private=deepcopy(self.env.specs[0]);private['id']=str(uuid4());private['privacy']='local-only'
        self.service.blocks.save(self.pid,self.env.f.git.head(),[private],str(uuid4()))
        with self.assertRaisesRegex(ValueError,'local-only'):
            self.service.compose(self.pid,str(uuid4()),'Topic',confirm=True,source_ids=[private['id']])

    def test_empty_feed_never_claims_filter_effectiveness(self):
        task=deepcopy(self.env.specs[4]);task['id']=str(uuid4())
        self.service.fetcher=lambda *a,**k:dict(status=200,raw=b'<rss version="2.0"><channel><title>Empty</title></channel></rss>',validators={})
        with patch.object(self.service,'_model',return_value=encoded(dict(blocks=[task],explanation='Empty examples')).decode()):
            result=self.service.compose(self.pid,str(uuid4()),'Topic',confirm=True,source_ids=[self.source['id']])
        self.assertEqual(result['result']['calibration'][0]['state'],'empty-sample')

    def test_sampling_is_bounded_and_does_not_prefilter_with_existing_keywords(self):
        raw=('<rss version="2.0"><channel><title>Many</title>'+''.join(
            '<item><guid>'+str(i)+'</guid><link>https://example.org/'+str(i)+'</link><title>Other topic</title></item>'
            for i in range(12))+'</channel></rss>').encode()
        pages=[]
        evidence,items=collect(self.source,lambda *a,**k:dict(status=200,raw=raw,validators={}),
            '2026-11-12T09:00:00Z',article_fetcher=lambda u:(pages.append(u) or dict(text='Body')))
        self.assertEqual((evidence['feed_items'],len(items),len(pages)),(12,8,2))

    def test_changed_project_during_sampling_stops_model_dispatch(self):
        pool=deepcopy(self.env.specs[1])
        pool['previous']=[next(b for b in self.service.blocks.read(self.pid)['blocks'] if b['id']==pool['id'])['ref']]
        pool['value']['title']='Changed while fetching'
        def fetch(*a,**kw):
            self.service.blocks.save(self.pid,self.env.f.git.head(),[pool],str(uuid4()))
            return self.feed()
        self.service.fetcher=fetch
        with patch.object(self.service,'_model',side_effect=AssertionError('No dispatch')),patch('spikes.monitoring_design_samples.read_article',return_value=dict(text='Body')):
            with self.assertRaisesRegex(ValueError,'changed during source sampling'):
                self.service.compose(self.pid,str(uuid4()),'Topic',confirm=True,source_ids=[self.source['id']])
