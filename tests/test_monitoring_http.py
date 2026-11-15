# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Monitoring uses the shared authenticated HTTP/RBAC boundary."""
import json
import unittest
from uuid import uuid4
from tests import test_web_server as fixtures
from spikes.monitoring import PROFILES

class MonitoringHTTPTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WebTests('test_dns_hostname_validation_is_fail_closed')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        code,body,_=self.f.create_project('Monitoring HTTP')
        self.assertEqual(code,200,body);self.pid=json.loads(body)['id']

    def call(self,action,body,headers=None):
        return self.f.request(path='/v1/monitoring/'+action,body=json.dumps(dict(project_id=self.pid,**body)),headers=headers)

    def test_current_view_returns_one_catalog_without_loading_legacy_view(self):
        from unittest.mock import patch
        with patch.object(self.f.server.monitoring,'view',side_effect=AssertionError('legacy view')), \
             patch.object(self.f.server.monitoring,'_data',side_effect=AssertionError('duplicate snapshot')):
            code,raw,_=self.call('view',dict(mode='blocks'))
        self.assertEqual(code,200,raw)
        view=json.loads(raw)
        self.assertEqual(view['commit_id'],view['block_catalog']['commit_id'])
        self.assertEqual(view['can_manage'],view['block_catalog']['can_manage'])
        self.assertTrue(any(n['id']==view['node_id'] and n['local'] for n in view['execution_nodes']['nodes']))
        self.assertNotIn('watches',view);self.assertNotIn('definitions',view)

    def test_stale_current_view_is_a_retryable_read_response(self):
        from unittest.mock import patch
        from spikes.storage import StaleIndex
        with patch.object(self.f.server.monitoring,'current_view',side_effect=StaleIndex):
            code,raw,_=self.call('view',dict(mode='blocks'))
        self.assertEqual(code,503,raw)
        self.assertEqual(json.loads(raw)['retry'],'read-again')

    def test_composable_blocks_pool_and_review_use_authenticated_http(self):
        from tests.test_monitoring_blocks import blocks, response
        from spikes.reporting_schema import encoded
        from pathlib import Path
        node=self.f.root/'node.json'
        specs=blocks(node)
        code,raw,_=self.call('blocks',{});self.assertEqual(code,200,raw);view=json.loads(raw)
        code,raw,_=self.call('blocks-save',dict(base_head=view['commit_id'],blocks=specs,operation_id=str(uuid4())))
        self.assertEqual(code,200,raw)
        self.f.server.monitoring.composable.fetcher=lambda *a,**kw:response()
        code,raw,_=self.call('block-configure',dict(block_id=specs[0]['id'],enabled=True,confirm=True))
        self.assertEqual(code,200,raw)
        self.assertEqual(self.call('block-tick',{})[0],200)
        code,raw,_=self.call('pool-view',dict(pool_id=specs[1]['id']));self.assertEqual(code,200,raw)
        self.assertEqual(len(json.loads(raw)['messages']),1)
        code,raw,_=self.call('block-task-run',dict(block_id=specs[4]['id'],run_id=str(uuid4())))
        self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw)['state'],'completed')
        self.assertEqual(self.call('blocks',{}, {'Authorization':'Bearer invalid'})[0],401)

    def test_confirmed_block_deletion_uses_native_writer_and_refuses_reader(self):
        from tests.test_monitoring_blocks import blocks
        node=self.f.root/'node.json'
        code,raw,_=self.call('blocks',{});self.assertEqual(code,200,raw)
        specs=blocks(node)
        code,raw,_=self.call('blocks-save',dict(base_head=json.loads(raw)['commit_id'],blocks=specs,operation_id=str(uuid4())))
        self.assertEqual(code,200,raw)
        catalog=json.loads(self.call('blocks',{})[1]);row=next(b for b in catalog['blocks'] if b['id']==specs[4]['id'])
        request=dict(base_head=catalog['commit_id'],block=dict(id=row['id'],previous=[row['ref']],privacy=row['privacy'],value=dict(row['value'],deleted=True)),operation_id=str(uuid4()),confirm=False)
        self.assertEqual(self.call('block-delete',request)[0],422)
        state=json.loads(self.f.request(path='/v1/administration',body=json.dumps({'action':'list'}))[1])
        state=json.loads(self.f.request(path='/v1/administration',body=json.dumps(dict(action='create-user',expected_commit=state['commit_id'],name='Deletion reader',node_role='member')))[1])
        self.assertEqual(self.call('block-delete',dict(request,confirm=True),{'Authorization':'Bearer '+state['access_key']})[0],403)
        code,raw,_=self.call('block-delete',dict(request,confirm=True));self.assertEqual(code,200,raw)
        self.assertNotIn(row['id'],{b['id'] for b in json.loads(self.call('blocks',{})[1])['blocks']})
        self.assertEqual(self.call('block-delete',dict(request,confirm=True))[0],200)

    def test_legacy_deletion_preview_confirmation_and_replay(self):
        from tests.test_monitoring_workflow import workflow
        head=json.loads(self.call('view',{})[1])['commit_id']
        request=workflow(self.pid,head);request.pop('project_id');request['operation_id']=str(uuid4())
        self.assertEqual(self.call('workflow-save',request)[0],200)
        code,raw,_=self.call('legacy-delete-preview',dict(kind='definition',id=request['processing']['watch_id']))
        self.assertEqual(code,200,raw);preview=json.loads(raw);self.assertFalse(preview['blockers'])
        body=dict(base_head=preview['base_head'],sources=preview['sources'],operation_id=str(uuid4()),confirm=False)
        self.assertEqual(self.call('legacy-delete',body)[0],422)
        self.assertEqual(self.call('legacy-delete',dict(body,confirm=True),{'Authorization':'Bearer invalid'})[0],401)
        self.assertEqual(self.call('legacy-delete',dict(body,confirm=True))[0],200)
        self.assertEqual(self.call('legacy-delete',dict(body,confirm=True))[0],200)
        self.assertEqual(len(json.loads(self.call('definitions',{})[1])['definitions']),1)

    def test_concrete_output_content_is_head_bound_and_readable_without_write_permission(self):
        from tests.test_monitoring_blocks import blocks
        node=self.f.root/'node.json';specs=blocks(node)
        head=json.loads(self.call('blocks',{})[1])['commit_id']
        self.assertEqual(self.call('blocks-save',dict(base_head=head,blocks=specs,operation_id=str(uuid4())))[0],200)
        code,raw,_=self.call('block-process',dict(block_id=specs[3]['id'],run_id=str(uuid4())))
        self.assertEqual(code,200,raw);run=json.loads(raw)
        publication=dict(run_id=run['id'],approval_digest=run['result']['approval_digest'],confirm=True)
        self.assertEqual(self.call('block-publish',publication)[0],422)
        runtime=self.f.server.monitoring.composable
        instant=runtime.clock()+3600
        runtime.clock=runtime.pools.clock=lambda:instant
        runtime.tick(self.pid,lane='processing')
        self.assertEqual(self.call('block-publish',dict(run_id=run['id'],approval_digest=run['result']['approval_digest'],confirm=True))[0],200)
        view=json.loads(self.call('view',{})[1]);summary=view['outputs'][0]
        self.assertNotIn('markdown',summary)
        state=json.loads(self.f.request(path='/v1/administration',body=json.dumps({'action':'list'}))[1])
        state=json.loads(self.f.request(path='/v1/administration',body=json.dumps(dict(action='create-user',expected_commit=state['commit_id'],name='Output reader',node_role='member')))[1])
        user=state['users'][-1];key=state['access_key']
        state=json.loads(self.f.request(path='/v1/administration',body=json.dumps(dict(action='update-user',expected_commit=state['commit_id'],user_id=user['id'],active=True,node_role='member',memberships={self.pid:'reader'})))[1])
        headers={'Authorization':'Bearer '+key}
        from unittest.mock import patch
        with patch.object(self.f.server.monitoring,'execution_nodes',side_effect=AssertionError('reader node inventory')):
            code,raw,_=self.call('view',dict(mode='blocks'),headers)
        self.assertEqual(code,200,raw);self.assertNotIn('execution_nodes',json.loads(raw))
        with patch.object(self.f.server.monitoring,'_data',wraps=self.f.server.monitoring._data) as reads:
            code,raw,_=self.call('output',dict(output_id=summary['id'],expected_head=view['commit_id']),headers)
        self.assertEqual(reads.call_count,1)
        self.assertEqual(code,200,raw);self.assertIn('markdown',json.loads(raw))
        self.assertEqual(self.call('output',dict(output_id=summary['id'],expected_head='0'*40),headers)[0],422)
        self.assertEqual(self.call('output',dict(output_id=summary['id'],expected_head=view['commit_id']),{'Authorization':'Bearer invalid'})[0],401)
        presentation=dict(output_id=summary['id'],expected_head=view['commit_id'],confirm=True)
        self.assertEqual(self.call('block-reprocess',dict(source_run_id=run['id'],run_id=str(uuid4()),confirm=True),headers)[0],403)
        self.assertEqual(self.call('presentation',presentation,headers)[0],403)
        self.assertEqual(self.call('presentation',dict(presentation,confirm=False))[0],422)
        code,raw,_=self.call('presentation',presentation)
        self.assertEqual(code,200,raw);created=json.loads(raw)
        code,raw,_=self.call('presentation',presentation)
        self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw),created)

    def test_manual_reprocessing_requires_elapsed_protection_and_replays_same_request(self):
        from tests.test_monitoring_blocks import blocks
        specs=blocks(self.f.root/'node.json')
        head=json.loads(self.call('blocks',{})[1])['commit_id']
        self.assertEqual(self.call('blocks-save',dict(base_head=head,blocks=specs,operation_id=str(uuid4())))[0],200)
        code,raw,_=self.call('block-process',dict(block_id=specs[3]['id'],run_id=str(uuid4())))
        self.assertEqual(code,200,raw);first=json.loads(raw)
        request=dict(source_run_id=first['id'],run_id=str(uuid4()),confirm=True)
        self.assertEqual(self.call('block-reprocess',request)[0],422)
        runtime=self.f.server.monitoring.composable
        instant=first['result']['protection']['until'];runtime.clock=runtime.pools.clock=lambda:instant
        self.assertEqual(self.call('block-reprocess',dict(request,confirm=False))[0],422)
        code,raw,_=self.call('block-reprocess',request)
        self.assertEqual(code,200,raw);new=json.loads(raw)
        self.assertEqual(new['state'],'review');self.assertTrue(new['result']['protection']['finalized'])
        code,raw,_=self.call('block-reprocess',request)
        self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw),new)
        self.assertEqual(self.call('block-publish',dict(run_id=new['id'],approval_digest=new['result']['approval_digest'],confirm=True))[0],200)

    def test_one_time_migration_has_readable_preview_and_admin_only_apply(self):
        from tests.test_monitoring_workflow import workflow
        view=json.loads(self.call('view',{})[1])
        request=workflow(self.pid,view['commit_id']);request.pop('project_id');request['operation_id']=str(uuid4())
        code,raw,_=self.call('workflow-save',request);self.assertEqual(code,200,raw)
        saved=json.loads(raw);ids=[r['watch_id'] for r in saved['stages'].values()]
        options=dict(watch_ids=ids,retention_days=30,processing_node_id=view['node_id'])
        code,raw,_=self.call('migration-preview',options);self.assertEqual(code,200,raw)
        plan=json.loads(raw);self.assertEqual(plan['issues'],[])
        apply=dict(options,preview_sha256=plan['preview_sha256'],operation_id=str(uuid4()),confirm=True)
        def admin(body):
            code,raw,_=self.f.request(path='/v1/administration',body=json.dumps(body));self.assertEqual(code,200,raw);return json.loads(raw)
        state=admin({'action':'list'});state=admin({'action':'create-user','expected_commit':state['commit_id'],'name':'Migration reader','node_role':'member'})
        key=state['access_key'];user=state['users'][0]
        admin({'action':'update-user','expected_commit':state['commit_id'],'user_id':user['id'],'active':True,'node_role':'member','memberships':{self.pid:'reader'}})
        headers={'Authorization':'Bearer '+key}
        self.assertEqual(self.call('migration-inventory',{},headers)[0],200)
        self.assertEqual(self.call('migration-preview',options,headers)[0],200)
        self.assertEqual(self.call('migration-apply',apply,headers)[0],403)
        code,raw,_=self.call('migration-apply',apply);self.assertEqual(code,200,raw);result=json.loads(raw)
        code,raw,_=self.call('migration-apply',apply);self.assertEqual(code,200,raw);self.assertEqual(result,json.loads(raw))
        inventory=json.loads(self.call('migration-inventory',{})[1]);self.assertTrue(all(r['converted'] for r in inventory['items']))

    def test_workflow_saves_two_definitions_and_run_waits_for_stored_inputs(self):
        from tests.test_monitoring_workflow import workflow
        code,raw,_=self.call('view',{});self.assertEqual(code,200,raw);view=json.loads(raw)
        self.assertTrue(view['execution_nodes']['nodes'][0]['local'])
        request=workflow(self.pid,view['commit_id']);request.pop('project_id');request['operation_id']=str(uuid4())
        code,raw,_=self.call('workflow-save',request);self.assertEqual(code,200,raw);saved=json.loads(raw)
        code,raw,_=self.call('workflow-save',request);self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw),saved)
        pin=saved['stages']['processing']['definition_ref']
        code,raw,_=self.call('workflow-run',dict(definition_ref=pin,period_start='2026-10-05'))
        self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw)['state'],'waiting-inputs')
        self.assertEqual(self.call('workflow-save',request,{'Authorization':'Bearer invalid'})[0],401)

    def test_synthesis_review_publish_trace_and_missing_inputs_use_shared_http(self):
        from tests.test_monitoring_definitions import definition
        from spikes.reporting_scheduler import calendar_period
        value=definition('HTTP synthesis','weekly');value['report'].update(mode='deterministic',formats=['markdown'],required_sections=['# Přehled','## Omezení'])
        value['inputs'][0]['policy']=dict(window='ending-in-period',approval='captured',missing='allow-incomplete')
        view=json.loads(self.call('definitions',{})[1])
        code,raw,_=self.call('definition-save',dict(operation_id=str(uuid4()),base_head=view['commit_id'],watch_id=str(uuid4()),previous=[],privacy='project',definition=value))
        self.assertEqual(code,200,raw);saved=json.loads(raw)
        request=dict(definition_ref=saved['definition_ref'],period=calendar_period('2026-10-05T00:00:00+02:00','weekly','Europe/Prague','iso-calendar-v1'))
        code,raw,_=self.call('synthesis-run',request);self.assertEqual(code,200,raw)
        result=json.loads(raw);self.assertEqual(result['state'],'review');self.assertFalse(result['complete'])
        code,raw,_=self.call('view',{});self.assertEqual(code,200,raw)
        row=next(r for r in json.loads(raw)['reports'] if r['id']==result['run']['run_id'])
        code,raw,_=self.call('publish',dict(run_id=row['id'],approval_digest=row['approval_digest'],confirm=True));self.assertEqual(code,200,raw)
        issued=json.loads(raw)['workspace_receipt']['snapshot']
        code,raw,_=self.call('synthesis-trace',dict(report_ref=issued));self.assertEqual(code,200,raw);self.assertTrue(json.loads(raw)['nodes'])
        code,raw,_=self.call('synthesis-freshness',dict(report_ref=issued));self.assertEqual(code,200,raw);self.assertFalse(json.loads(raw)['potentially_stale'])
        self.assertEqual(self.call('synthesis-run',request,{'Authorization':'Bearer invalid'})[0],401)

    def test_admin_can_create_and_read_watch_editor_cannot_activate_it(self):
        code,raw,_=self.call('view',{});self.assertEqual(code,200,raw);view=json.loads(raw)
        cfg=dict(id=str(uuid4()),name='HTTP watch',goal='Evidence',active=False,privacy='project',timezone='Europe/Prague',
            start='2026-03-23',inputs=[],urls=[],access_note='',periods={'weekly':PROFILES['weekly']},presentation=False,mode='deterministic',binding=None,tags=[])
        code,raw,_=self.call('save',dict(operation_id=str(uuid4()),base_head=view['commit_id'],watch=cfg,new=True))
        self.assertEqual(code,200,raw)
        def admin(body):
            code,raw,_=self.f.request(path='/v1/administration',body=json.dumps(body));self.assertEqual(code,200,raw);return json.loads(raw)
        state=admin({'action':'list'})
        state=admin({'action':'create-user','expected_commit':state['commit_id'],'name':'Editor','node_role':'member'})
        key=state['access_key'];user=state['users'][0]
        admin({'action':'update-user','expected_commit':state['commit_id'],'user_id':user['id'],'active':True,'node_role':'member','memberships':{self.pid:'editor'}})
        headers={'Authorization':'Bearer '+key}
        code,raw,_=self.call('view',{},headers);self.assertEqual(code,200,raw);self.assertFalse(json.loads(raw)['can_manage'])
        self.assertNotIn('execution_nodes',json.loads(raw))
        from tests.test_monitoring_workflow import workflow
        request=workflow(self.pid,json.loads(raw)['commit_id']);request.pop('project_id');request['operation_id']=str(uuid4())
        self.assertEqual(self.call('workflow-save',request,headers)[0],403)
        self.assertEqual(self.call('workflow-run',dict(definition_ref={},period_start='2026-10-05'),headers)[0],403)
        code,_,_=self.call('run',{'watch_id':cfg['id'],'kind':'weekly'},headers);self.assertEqual(code,403)
        code,_,_=self.call('view',{}, {'Authorization':'Bearer invalid'});self.assertEqual(code,401)

    def test_independent_definitions_share_read_permissions_and_admin_write_boundary(self):
        from tests.test_monitoring_definitions import definition
        watch_id=str(uuid4())
        code,raw,_=self.call('definitions',{});self.assertEqual(code,200,raw)
        view=json.loads(raw)
        request=dict(operation_id=str(uuid4()),base_head=view['commit_id'],watch_id=watch_id,
                     previous=[],privacy='project',definition=definition())
        code,raw,_=self.call('definition-save',request);self.assertEqual(code,200,raw)
        saved=json.loads(raw)
        rss_request=dict(watch_id=watch_id,input_id=request['definition']['inputs'][0]['id'],
            definition_ref=saved['definition_ref'],enabled=True,mode='queue-all',confirm=True)
        self.assertEqual(self.call('rss-configure',dict(rss_request,confirm=False))[0],422)
        code,raw,_=self.call('rss-configure',rss_request);self.assertEqual(code,200,raw)
        from tests.test_rss_pilot import rss
        self.f.server.monitoring.rss_runtime.fetcher=lambda *a,**kw:dict(status=200,raw=rss(),validators={'if-none-match':'"test"'})
        code,raw,_=self.call('rss-tick',{});self.assertEqual(code,200,raw)
        self.assertEqual(len(json.loads(raw)['findings']),1)
        self.assertNotIn('validators',json.loads(raw)['bindings'][0])
        code,raw,_=self.call('definitions',{});self.assertEqual(code,200,raw)
        self.assertEqual(json.loads(raw)['definitions'][0]['watch_id'],watch_id)
        def admin(body):
            code,raw,_=self.f.request(path='/v1/administration',body=json.dumps(body))
            self.assertEqual(code,200,raw);return json.loads(raw)
        state=admin({'action':'list'})
        state=admin({'action':'create-user','expected_commit':state['commit_id'],'name':'Definition reader','node_role':'member'})
        key=state['access_key'];user=state['users'][0]
        admin({'action':'update-user','expected_commit':state['commit_id'],'user_id':user['id'],
               'active':True,'node_role':'member','memberships':{self.pid:'reader'}})
        headers={'Authorization':'Bearer '+key}
        code,raw,_=self.call('definitions',{},headers);self.assertEqual(code,200,raw)
        self.assertFalse(json.loads(raw)['can_manage'])
        self.assertEqual(self.call('definition-save',request,headers)[0],403)
        self.assertEqual(self.call('legacy-delete',dict(base_head=view['commit_id'],sources=[],operation_id=str(uuid4()),confirm=True),headers)[0],403)
        self.assertEqual(self.call('rss-status',{},headers)[0],200)
        from tests.test_monitoring_filters import pipeline,source
        head=json.loads(self.call('definitions',{},headers)[1])['commit_id']
        code,raw,_=self.call('filter-preview',dict(pipeline=pipeline(),items=[source()]),headers)
        self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw)['results'][0]['decision'],'selected')
        self.assertEqual(json.loads(self.call('definitions',{},headers)[1])['commit_id'],head)
        self.assertEqual(self.call('filter-preview',dict(pipeline=pipeline(),items=[]),{'Authorization':'Bearer invalid'})[0],401)
        self.assertEqual(self.call('rss-configure',rss_request,headers)[0],403)
        self.assertEqual(self.call('rss-tick',{},headers)[0],403)
        self.assertEqual(self.call('definitions',{}, {'Authorization':'Bearer invalid'})[0],401)
