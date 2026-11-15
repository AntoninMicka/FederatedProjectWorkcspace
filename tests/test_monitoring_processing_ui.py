# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import shutil
import subprocess
import unittest

from spikes.monitoring_catalogs_ui import JS


@unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
class ProcessingUiTests(unittest.TestCase):
    def run_js(self, checks):
        harness="""
const assert=require('node:assert/strict');
let blockCatalog={node_id:'local',jobs:[]};
let monitoringView={execution_nodes:{nodes:[{id:'remote',name:'Omnia'}]}};
const row={id:'processing',value:{config:{pool_ids:['pool'],node_id:'remote',schedule:{kind:'weekly',time:'07:30',timezone:'Europe/Prague'}}},runtime:{enabled:true}};
const blockName=id=>id;
const job=(state,result={},extra={})=>({id:'run',state,intent:{kind:'processing',block:{id:row.id},started_at:1794160000,executor_node_id:'local',...extra},result});
"""
        result=subprocess.run(['node','-e',harness+JS+checks],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_enabled_schedule_does_not_hide_failure_or_incomplete_inputs(self):
        self.run_js(r"""
blockCatalog.jobs=[job('failed',{error:'Model není dostupný'})];
assert.match(monitoringProcessingPlan(row),/zapnutý/);
assert.match(monitoringProcessingOutcome(row),/Chyba: Model není dostupný/);
blockCatalog.jobs=[job('failed',{error:'Neúplný přenos vstupních dat: pool test'})];
assert.match(monitoringProcessingOutcome(row),/^Neúplné vstupy:/);
blockCatalog.jobs=[job('unknown',{error:'Přerušený dispatch'})];
assert.match(monitoringProcessingOutcome(row),/Unknown.*Přerušený dispatch/);
blockCatalog.jobs=[job('review',{protection:{finalized:false,until:1794163600,error:'Neúplný přenos vstupních dat: pool test'}})];
assert.match(monitoringProcessingOutcome(row),/^Neúplné vstupy:/);
""")

    def test_protection_and_historical_report_keep_their_own_state(self):
        self.run_js(r"""
const historical=job('review',{protection:{finalized:false,until:1794163600,changed:true}});
assert.match(monitoringProcessingJobOutcome(historical),/Ochranné období.*nezahrnuté vstupy/);
blockCatalog.jobs=[job('failed',{error:'Novější chyba'})];
assert.match(monitoringProcessingOutcome(row),/Novější chyba/);
assert.match(monitoringProcessingJobOutcome(historical),/Ochranné období/);
historical.result.protection={finalized:true,until:1794163600,changed:false};
assert.match(monitoringProcessingJobOutcome(historical),/čeká na posouzení/);
assert.equal(monitoringProcessingJobOutcome(job('published')),'Zpráva vydána');
assert.match(monitoringProcessingJobOutcome(job('dispatching')),/Probíhá/);
assert.match(monitoringProcessingJobOutcome(job('prepared')),/Čeká na zpracování/);
""")

    def test_visible_run_executor_is_independent_of_scheduled_node(self):
        self.run_js(r"""
assert.match(monitoringProcessingOutcome(row),/není v přehledu/);
assert.equal(monitoringProcessingExecutor(row),'Nezjištěn');
blockCatalog.jobs=[job('review',{}, {regeneration_of:'original'}),job('review',{replacement:true}),job('review',{}, {block:{id:'other'}}),job('review')];
assert.equal(monitoringProcessingExecutor(row),'Tento uzel');
const columns=Object.fromEntries(monitoringCatalogColumns('processing'));
assert.equal(columns['Plánovaný uzel'](row),'Omnia');
assert.match(columns['Rozvrh'](row),/Týdně v 07:30 \(Europe\/Prague\)/);
assert.equal(monitoringProcessingTime(row),new Date(1794160000000).toLocaleString());
blockCatalog.jobs=[job('review',{output:{built_at:'2026-11-15T10:00:00Z'}},{executor_node_id:'remote'})];
assert.equal(monitoringProcessingExecutor(row),'Omnia');
assert.equal(monitoringProcessingTime(row),new Date('2026-11-15T10:00:00Z').toLocaleString());
row.runtime={enabled:false};assert.match(monitoringProcessingPlan(row),/není aktivovaný/);
row.runtime.error='Konflikt aktivace';assert.equal(monitoringProcessingPlan(row),'Konflikt aktivace');
row.runtime=null;row.value.config.schedule.kind='manual';assert.match(monitoringProcessingPlan(row),/ruční/);
""")
