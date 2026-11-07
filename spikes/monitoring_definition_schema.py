# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Closed declarative watch model; no connector, worker, provider or writer."""
from copy import deepcopy
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import urlsplit

from spikes.metadata import require, uuid, ValidationError
from spikes.public_source import normalize_url
from spikes.reporting_schema import PRIVACY, choice, encoded, fields, scope, sequence, text

WATCH_FIELDS = 'title goal scope active schedule inputs selection evaluation report placement'
KINDS = {'daily', 'weekly', 'monthly', 'quarterly', 'annual'}


def normalize_definition(value):
    """Only documented safe defaults: upstream reports are published-only."""
    result = deepcopy(value)
    if isinstance(result, dict) and isinstance(result.get('inputs'), list):
        for item in result['inputs']:
            if isinstance(item, dict) and item.get('kind') == 'watch':
                item.setdefault('take', 'reports')
                item.setdefault('include_drafts', False)
    return result


def validate_definition(value):
    fields(value, 'schema ' + WATCH_FIELDS)
    require(value['schema'] == 'fpw-reporting-watch-v1', 'Unknown watch definition version')
    for key in ('title', 'goal'):
        text(value[key]); require(len(value[key]) <= 2000, 'Watch text exceeds limit')
    require(len(value['title']) <= 150, 'Watch title exceeds limit')
    scope(value['scope'])
    require(type(value['active']) is bool, 'Invalid watch active flag')
    schedule = value['schedule']
    fields(schedule, 'kind timezone start'+(' trigger' if 'trigger' in schedule else ''))
    if 'trigger' in schedule:
        choice(schedule['trigger'], {'manual', 'scheduled'})
    choice(schedule['kind'], KINDS)
    text(schedule['timezone']); text(schedule['start'])
    try:
        ZoneInfo(schedule['timezone'])
        start = date.fromisoformat(schedule['start'])
        require(start.isoformat() == schedule['start'], 'Expected canonical watch start date')
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValidationError('Invalid watch calendar') from exc

    def input_(item):
        require(isinstance(item, dict), 'Expected watch input')
        choice(item.get('kind'), {'external', 'watch'})
        if item['kind'] == 'external':
            fields(item, 'id kind connector locator poll access' + (' policy' if 'policy' in item else ''))
            choice(item['connector'], {'rss-atom', 'static-text', 'web-search', 'platform-channel'})
            require(item['locator'] == normalize_url(item['locator']), 'Expected canonical source URL')
            require(not urlsplit(item['locator']).query, 'Source query/credentials are outside the watch definition')
            fields(item['poll'], 'seconds')
            require(type(item['poll']['seconds']) is int and 60 <= item['poll']['seconds'] <= 604800,
                    'Source polling interval must be 60..604800 seconds')
            fields(item['access'], 'reviewed capture_allowed terms retention')
            require(item['access']['reviewed'] is True and item['access']['capture_allowed'] is True,
                    'External source requires explicit access/capture review')
            text(item['access']['terms']); text(item['access']['retention'])
        else:
            fields(item, 'id kind watch_id take include_drafts' + (' policy' if 'policy' in item else ''))
            uuid(item['watch_id'])
            choice(item['take'], {'findings', 'processed-items', 'reports'})
            require(type(item['include_drafts']) is bool, 'Invalid draft input flag')
            require(not item['include_drafts'] or item['take'] == 'reports',
                    'Draft permission applies only to report inputs')
            if 'policy' in item:
                policy=item['policy'];fields(policy,'window approval missing')
                choice(policy['window'],{'ending-in-period','overlap'})
                choice(policy['missing'],{'wait','allow-incomplete'})
                allowed={'reports':{'issued'},'findings':{'captured','selected','processed'},'processed-items':{'processed'}}
                choice(policy['approval'],allowed[item['take']])
        if item['kind']=='external' and 'policy' in item:
            policy=item['policy'];fields(policy,'window approval missing')
            choice(policy['window'],{'ending-in-period','overlap'})
            choice(policy['approval'],{'captured','selected','processed'} if item['connector']=='rss-atom' else {'captured'})
            choice(policy['missing'],{'wait','allow-incomplete'})
        uuid(item['id'])
    sequence(value['inputs'], input_, minimum=1)
    require(len({item['id'] for item in value['inputs']}) == len(value['inputs']), 'Duplicate watch input identity')
    for key in ('selection', 'evaluation'):
        names = 'revision instructions'
        if key == 'selection' and isinstance(value[key], dict) and 'pipeline' in value[key]:
            from spikes.monitoring_filters import validate_pipeline
            validate_pipeline(value[key]['pipeline'])
            names += ' pipeline'
        fields(value[key], names)
        text(value[key]['revision']); text(value[key]['instructions'])
        require(len(value[key]['revision']) <= 100 and len(value[key]['instructions']) <= 8000,
                'Watch rules exceed limit')
    report = value['report']
    fields(report, 'mode instructions formats language required_sections'+(' analysis' if 'analysis' in report else ''))
    if 'analysis' in report:
        from spikes.reporting_schema import ref
        analysis=report['analysis'];fields(analysis,'revision input_level case_studies target')
        text(analysis['revision']);require(len(analysis['revision'])<=100,'Analysis revision exceeds limit')
        choice(analysis['input_level'],{'weekly','monthly','mixed'})
        def case(item):
            fields(item,'ref status note');ref(item['ref']);text(item['note'])
            choice(item['status'],{'ongoing','stalled','abandoned','completed','unknown'})
            require(len(item['note'])<=2000,'Case study note exceeds limit')
        sequence(analysis['case_studies'],case)
        if analysis['target'] is not None:
            from spikes.context_builder import Target
            fields(analysis['target'],'binding_id binding_revision boundary target_id model');Target(**analysis['target']).validate()
        require((analysis['target'] is not None)==(report['mode']=='llm'),'Analytical target requires explicit LLM mode')
    choice(report['mode'], {'collect-only', 'deterministic', 'llm'})
    text(report['instructions']); text(report['language'])
    require(len(report['instructions']) <= 8000 and len(report['language']) <= 50, 'Report instructions exceed limit')
    sequence(report['formats'], lambda item: choice(item, {'findings', 'markdown', 'presentation'}), minimum=1)
    sequence(report['required_sections'], text)
    if report['mode'] == 'collect-only':
        require(report['formats'] == ['findings'] and not report['required_sections'],
                'Collection-only output consists of findings, without a report')
    else:
        require('markdown' in report['formats'] and 'findings' not in report['formats'] and report['required_sections'],
                'Synthesis requires Markdown and report sections')
    placement = value['placement']
    fields(placement, 'mode node_id capabilities')
    choice(placement['mode'], {'local', 'node', 'capability'})
    sequence(placement['capabilities'], text)
    if placement['mode'] == 'node':
        uuid(placement['node_id']); require(not placement['capabilities'], 'Node placement cannot select capabilities')
    else:
        require(placement['node_id'] is None, 'Unexpected placement node')
        require(bool(placement['capabilities']) == (placement['mode'] == 'capability'), 'Invalid placement capabilities')
    require(len(encoded(value)) <= 48 * 1024, 'Watch definition exceeds limit')
    return value


def validate_graph(records):
    """Validate current stable-identity links, even when they were edited via raw APIs."""
    watches = {key: row for key, row in records.items() if row['type'] == 'WatchDefinition'}
    parents = {pin['artifact_id'] for row in watches.values() for pin in row['previous']}
    tips = {row['entity_id']: row for key, row in watches.items() if key not in parents}
    edges = {}
    for identity, row in tips.items():
        targets = []
        for item in row['value']['inputs']:
            if item['kind'] == 'external':
                require(row['privacy'] != 'local-only', 'Local-only watch cannot access external sources')
                continue
            target = item['watch_id']
            require(target != identity, 'Watch cannot depend on itself')
            require(target in tips, 'Watch input target is missing')
            require(PRIVACY[row['privacy']] >= PRIVACY[tips[target]['privacy']], 'Watch input would relax privacy')
            targets.append(target)
        edges[identity] = targets
    visited, active = set(), set()
    for root in edges:
        stack = [(root, False)]
        while stack:
            identity, leaving = stack.pop()
            if leaving:
                active.remove(identity); visited.add(identity)
            elif identity not in visited:
                require(identity not in active, 'Cyclic watch input graph')
                active.add(identity); stack.append((identity, True))
                stack.extend((target, False) for target in edges[identity])
    return tips
