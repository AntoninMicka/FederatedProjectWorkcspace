# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Independent watch definitions over Reporting/Workspace immutable revisions.

Run preparation freezes the exact definitions in the existing run journal.
It performs no connector dispatch, LLM call, publication or node placement.
"""
from copy import deepcopy
import json

from spikes.metadata import require, uuid, validate_snapshot
from spikes.monitoring_definition_schema import normalize_definition, validate_definition, validate_graph
from spikes.reporting import Reporting, operation_uuid, pinned
from spikes.reporting_schema import digest, encoded, fields, records
from spikes.reporting_scheduler import ReportingScheduler
from spikes.source_collector import SourceCollector


class MonitoringDefinitions:
    def __init__(self, node):
        self.node = node
        self.reporting = Reporting(node)

    def read(self, project_id):
        data = self.reporting.read(project_id)
        definitions = validate_graph({row['revision_id']: row for row in data['records']})
        ws = self.reporting.artifacts.workspace(project_id)
        files = ws.git.snapshot(data['commit_id']); entities = validate_snapshot(files)
        result = []
        for identity, row in definitions.items():
            result.append(dict(watch_id=identity, definition_ref=pinned(project_id, data['commit_id'],
                row['revision_id'], files, entities), definition=deepcopy(row['value']), privacy=row['privacy'],
                version=digest(encoded(row['value'])), runtime_state='not-connected'))
        require(ws.git.head() == data['commit_id'], 'Project changed while reading watch definitions')
        return dict(project_id=project_id, commit_id=data['commit_id'], definitions=result)

    def save(self, request, operation_id, *, checkpoint=lambda stage: None):
        fields(request, 'project_id base_head watch_id previous privacy definition')
        uuid(request['watch_id'])
        value = validate_definition(normalize_definition(request['definition']))
        # Reporting's semantic validator also checks the full stable-identity graph
        # under the writer lock, before journal prepare, including raw editor writes.
        native = dict(project_id=request['project_id'], base_head=request['base_head'], records=[
            dict(type='WatchDefinition', entity_id=request['watch_id'], previous=request['previous'],
                 privacy=request['privacy'], value=value)])
        receipt = self.reporting.apply(native, operation_id, checkpoint=checkpoint)
        revision = operation_uuid(operation_id, 'record:0')
        return dict(receipt=receipt, watch_id=request['watch_id'],
                    definition_ref=self.reporting.pin(request['project_id'], revision, receipt['commit_id']))

    def prepare_run(self, project_id, definition_ref, period, run_id):
        """Prepare a reporting intent only; execution is a later connector/runtime boundary."""
        # Import lazily: the old UI/worker remains a v1 compatibility reader.
        from spikes.monitoring import Monitoring, ident
        uuid(run_id)
        ws = self.reporting.artifacts.workspace(project_id)
        ws.recover()
        ws._writable()
        head = ws.git.head(); files = ws.git.snapshot(head); entities = validate_snapshot(files)
        raw, _ = SourceCollector.resolve(ws, project_id, definition_ref, files, entities)
        row = json.loads(raw)
        require(row.get('type') == 'WatchDefinition', 'Expected an independent watch definition')
        scheduler = ReportingScheduler(self.node)
        with scheduler.db() as db:
            saved = db.execute('SELECT document FROM runs WHERE run_id=?', (run_id,)).fetchone()
        existing = json.loads(saved[0]) if saved else None
        if existing is not None:
            rules_raw, _ = SourceCollector.resolve(ws, project_id, existing['rules_ref'], files, entities)
            old_definition = json.loads(rules_raw)['definition_ref']
            require(existing['project_id'] == project_id and existing['period'] == period and
                    old_definition['artifact_id'] == definition_ref['artifact_id'] and
                    old_definition['sha256'] == definition_ref['sha256'], 'Run ID belongs to another watch intent')
            intent = {key: existing[key] for key in ('project_id', 'task_ref', 'period', 'rules_ref',
                      'input_head', 'knowledge_cutoff', 'baseline_snapshot')}
            return scheduler.enqueue(dict(intent, delivery_required=False), run_id)
        tips = validate_graph(records(files, entities))
        require(tips[row['entity_id']]['revision_id'] == row['revision_id'], 'Watch definition has been superseded')
        value = row['value']
        require(value['active'], 'Watch is paused')
        require(value['placement']['mode'] == 'local', 'Remote watch placement is not connected')
        require(value['report']['mode'] != 'collect-only', 'Collection-only runs require the connector runtime')
        require(period['kind'] == value['schedule']['kind'] and
                period['timezone'] == value['schedule']['timezone'], 'Run period differs from watch schedule')
        require(period['start_local'][:10] >= value['schedule']['start'], 'Run precedes watch start')
        # Validate a closed, canonical period before materializing any definitions.
        from datetime import datetime, timezone
        from spikes.reporting_schema import moment, period as validate_period
        from spikes.reporting_scheduler import utc
        validate_period(period)
        require(period['calendar_revision'] == 'iso-calendar-v1', 'Unknown watch calendar revision')
        for edge in ('start', 'end'):
            require(period[edge+'_utc'] == utc(moment(period[edge+'_utc'])), 'Run period needs canonical timestamps')
        require(moment(period['end_utc']) <= datetime.now(timezone.utc), 'Reporting period has not closed')
        inputs = []
        def original_pin(revision):
            path = 'artifacts/'+revision+'/record.json'
            commit = ws.git.run('log', '-1', '--format=%H', '--diff-filter=A', head, '--', path).stdout.strip()
            require(commit, 'Watch revision has no committed origin')
            return self.reporting.pin(project_id, revision, commit)
        definition_ref = original_pin(row['revision_id'])
        for item in value['inputs']:
            if item['kind'] == 'watch':
                upstream = tips[item['watch_id']]
                inputs.append(dict(input_id=item['id'], take=item['take'], include_drafts=item['include_drafts'],
                    definition_ref=original_pin(upstream['revision_id'])))
        rules = dict(schema='fpw-monitoring-run-rules-v1', definition_ref=definition_ref,
                     input_definitions=inputs)
        namespace = ident(row['revision_id'], digest(encoded(rules)))
        monitoring = Monitoring(self.node, self.reporting.artifacts.projects)
        rules_ref = monitoring._doc(project_id, ident(namespace, 'rules'), 'Sledování — připnutá pravidla běhu',
            encoded(rules).decode(), ident(namespace, 'rules-op'), row['privacy'])
        scale = monitoring._scale(project_id, row['entity_id'], row['privacy'], 'definition-scale-op')
        task_entity = ident(row['entity_id'], 'definition-task-entity')
        data = self.reporting.read(project_id)
        prior = [record for record in data['records'] if record['type'] == 'ReportingTask'
                 and record['entity_id'] == task_entity and record['revision_id'] in data['tips']]
        previous = [self.reporting.pin(project_id, record['revision_id'], data['commit_id']) for record in prior]
        task = monitoring._record(project_id, 'ReportingTask', dict(schema='fpw-reporting-task-v1',
            title=value['title'], goal=value['goal'], scope=value['scope'], source_policy=rules_ref,
            calendar=dict(timezone=value['schedule']['timezone'], calendar_revision='iso-calendar-v1',
                          periods=[value['schedule']['kind']]), selection_policy=rules_ref, scale_ref=scale,
            outputs=dict(formats=['markdown'], language=value['report']['language'],
                         required_sections=value['report']['required_sections']),
            execution=dict(llm='optional' if value['report']['mode'] == 'llm' else 'disabled',
                           context_policy=rules_ref, publication_policy=rules_ref), retention_policy=rules_ref),
            ident(namespace, 'task-op'), row['privacy'], entity=task_entity, previous=previous)
        # Rules/scale/task publication may span several receipts. None dispatches
        # work; the final intent pins their exact Git state in the original journal.
        return scheduler.enqueue(dict(project_id=project_id, task_ref=task, period=period, rules_ref=rules_ref,
            input_head=ws.git.head(), knowledge_cutoff=scheduler.stamp(), baseline_snapshot=None,
            delivery_required=False), run_id)
