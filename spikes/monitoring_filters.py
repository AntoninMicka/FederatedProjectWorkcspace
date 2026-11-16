# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Versioned, bounded selection. No network, project writes or implicit LLM calls."""
from copy import deepcopy
import json
import subprocess
import sys

from spikes.metadata import require
from spikes.reporting_schema import digest, encoded, fields, sequence, text
from spikes.source_connectors import validate_item

SCHEMA = 'fpw-monitoring-pipeline-v1'
ENGINE = 'monitoring-filters-v1'
SEARCH_FIELDS = {'title', 'content', 'author', 'url', 'channel'}
CHEAP = {'restrict', 'keywords', 'regex', 'dedup'}
ROLES = {'classifier': 'monitoring-classifier-v1',
         'extractor': 'monitoring-extractor-v1',
         'evidence-evaluator': 'monitoring-evaluator-v1'}

# Limits are installed inside the child, never in preexec_fn in a threaded server.
# One child handles the entire regex stage, so 500 pathological items cannot
# multiply the timeout by 500. communicate(timeout) kills and reaps the child.
REGEX_CHILD = '''
import json,re,resource,sys
resource.setrlimit(resource.RLIMIT_CPU,(1,1))
resource.setrlimit(resource.RLIMIT_AS,(192*1024*1024,192*1024*1024))
v=json.load(sys.stdin)
try:
 p=re.compile(v['pattern'],sum(getattr(re,f) for f in v['flags']))
 fn=p.search if v['match']=='search' else p.fullmatch
 print(json.dumps({'matches':[any(fn(t) is not None for t in row) for row in v['texts']]}))
except (re.error,MemoryError,RecursionError):
 print(json.dumps({'error':'Invalid or excessive regular expression'}))
'''


def strings(values, *, maximum=64):
    sequence(values, text)
    require(len(values) <= maximum and all(len(v) <= 512 for v in values), 'Filter values exceed limit')


def validate_pipeline(value):
    fields(value, 'schema revision steps')
    require(value['schema'] == SCHEMA, 'Unknown selection pipeline')
    text(value['revision']); require(len(value['revision']) <= 100, 'Pipeline revision exceeds limit')
    require(isinstance(value['steps'], list) and 1 <= len(value['steps']) <= 16, 'Expected 1..16 filter steps')
    seen = set(); semantic = False; terminal = False; regexes = 0
    for step in value['steps']:
        require(isinstance(step, dict), 'Expected filter step')
        kind = step.get('kind'); name = step.get('id'); text(name)
        require(len(name) <= 100 and name not in seen and not terminal, 'Duplicate step or step after handoff')
        seen.add(name)
        require(kind in CHEAP | {'llm', 'assessment', 'handoff'}, 'Unknown filter kind')
        require(not semantic or kind not in CHEAP, 'Cheap filters must precede LLM and assessment')
        if kind == 'restrict':
            fields(step, 'id kind channels languages required_fields')
            strings(step['channels']); strings(step['languages']); strings(step['required_fields'])
            require(set(step['required_fields']) <= SEARCH_FIELDS, 'Unknown required source field')
        elif kind == 'keywords':
            fields(step, 'id kind fields all any none case_sensitive')
            for key in ('all', 'any', 'none'): strings(step[key])
            require(step['all'] or step['any'] or step['none'], 'Empty keyword rule')
        elif kind == 'regex':
            fields(step, 'id kind fields pattern flags match negate')
            text(step['pattern']); require(len(step['pattern']) <= 512, 'Regex exceeds limit')
            require(isinstance(step['flags'], list) and set(step['flags']) <= {'IGNORECASE', 'MULTILINE', 'DOTALL', 'ASCII'}
                    and len(step['flags']) == len(set(step['flags'])), 'Invalid regex flags')
            require(step['match'] in {'search', 'fullmatch'} and type(step['negate']) is bool, 'Invalid regex comparison')
            regexes += 1; require(regexes <= 4, 'At most four regex stages')
        elif kind == 'dedup':
            fields(step, 'id kind field'); require(step['field'] in {'content_sha256', 'url', 'title'}, 'Invalid duplicate field')
        elif kind == 'llm':
            fields(step, 'id kind role instructions target')
            require(not semantic and any(s['kind'] in CHEAP for s in value['steps'][:len(seen)-1]),
                    'LLM requires a preceding cheap filter and only one LLM step')
            require(step['role'] in ROLES, 'Unsupported monitoring role')
            text(step['instructions']); require(len(step['instructions']) <= 8000, 'LLM instructions exceed limit')
            from spikes.context_builder import Target
            fields(step['target'], 'binding_id binding_revision boundary target_id model')
            Target(**step['target']).validate(); semantic = True
        elif kind == 'assessment':
            fields(step, 'id kind'); require(semantic, 'Assessment requires explicit LLM result'); semantic = True
        else:
            fields(step, 'id kind'); terminal = True
        if kind in {'keywords', 'regex'}:
            strings(step['fields']); require(step['fields'] and set(step['fields']) <= SEARCH_FIELDS, 'Unknown search fields')
        if kind == 'keywords': require(type(step['case_sensitive']) is bool, 'Invalid keyword case option')
    require(len(encoded(value)) <= 24 * 1024, 'Pipeline exceeds limit')
    return value


def regex_matches(step, rows):
    try:
        result = subprocess.run([sys.executable, '-I', '-c', REGEX_CHILD], input=encoded(dict(
            pattern=step['pattern'], flags=step['flags'], match=step['match'], texts=rows)),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=.75, check=False)
        if result.returncode != 0: return None, 'Regex resource limit or child failure'
        value = json.loads(result.stdout)
        if 'error' in value: return None, value['error']
        return value['matches'], None
    except subprocess.TimeoutExpired:
        return None, 'Regex time limit exceeded'


def evaluate(pipeline, items, *, previous=(), languages=None):
    """Pure preview; missing semantic results remain waiting, never selected."""
    validate_pipeline(pipeline)
    require(isinstance(items, list) and len(items) <= 500, 'Expected at most 500 items')
    require(len(encoded(items)) <= 4 * 1024 * 1024, 'Filter input exceeds limit')
    for item in items: validate_item(item)
    require(len({i['id'] for i in items}) == len(items), 'Duplicate preview item identity')
    require(isinstance(previous, (list, tuple)) and len(previous) <= 5000, 'Duplicate history exceeds limit')
    for item in previous: validate_item(item)
    languages = languages or {}
    require(isinstance(languages, dict) and set(languages) <= {i['id'] for i in items}, 'Unknown language input')
    for language in languages.values(): text(language)
    results = [dict(item_id=i['id'], decision='selected', reason='All configured rules passed',
                    steps=[], assessment=None, handoff=False) for i in items]
    for step in pipeline['steps']:
        active = [n for n, r in enumerate(results) if r['decision'] == 'selected']
        if not active: break
        kind = step['kind']; matches = None; error = None
        if kind == 'regex':
            matches, error = regex_matches(step, [[items[n].get(f) or '' for f in step['fields']] for n in active])
        seen = {i[step['field']] for i in previous if i['id'] not in {items[n]['id'] for n in active}} if kind == 'dedup' else set()
        for index, n in enumerate(active):
            item = items[n]; result = results[n]; passed = True; detail = 'Rule passed'
            if kind == 'restrict':
                passed = ((not step['channels'] or item['channel'] in step['channels']) and
                    (not step['languages'] or languages.get(item['id']) in step['languages']) and
                    all(item.get(f) for f in step['required_fields']))
                detail = 'Channel, declared language and required fields matched' if passed else 'Restriction failed (missing language is unknown)'
            elif kind == 'keywords':
                values = [item.get(f) or '' for f in step['fields']]
                fold = (lambda s: s) if step['case_sensitive'] else str.casefold
                contains = lambda term: any(fold(term) in fold(v) for v in values)
                passed = (all(contains(t) for t in step['all']) and (not step['any'] or any(contains(t) for t in step['any']))
                          and not any(contains(t) for t in step['none']))
                detail = 'ALL/ANY/NONE matched' if passed else 'ALL/ANY/NONE rejected'
            elif kind == 'regex':
                passed = bool(matches[index]) != step['negate'] if not error else False
                detail = error or ('Regex matched' if passed else 'Regex rejected')
            elif kind == 'dedup':
                key = item[step['field']]; passed = key is None or key not in seen
                if key is not None: seen.add(key)
                detail = 'Unique item' if passed else 'Duplicate ' + step['field']
            elif kind == 'llm':
                result['decision'] = 'waiting'; detail = 'Explicit pinned LLM execution required'
            elif kind == 'handoff':
                result['handoff'] = True; detail = 'Candidate for reporting; no publication or confirmation'
            else:
                result['decision'] = 'waiting'; detail = 'Explicit evidence assessment required'
            if error: result['decision'] = 'error'
            elif not passed: result['decision'] = 'discarded'
            result['steps'].append(dict(id=step['id'], kind=kind, outcome=result['decision'], reason=detail))
            if result['decision'] != 'selected': result['reason'] = step['id'] + ': ' + detail
    return dict(schema='fpw-monitoring-preview-v1', engine=ENGINE, pipeline=deepcopy(pipeline),
                pipeline_sha256=digest(encoded(pipeline)), items_sha256=digest(encoded(items)),
                languages=deepcopy(languages), previous_sha256=digest(encoded(list(previous))), results=results)


class FilterPreviews:
    """Application API for samples or immutable stored findings; never publishes."""
    def __init__(self, node):
        from spikes.reporting import Reporting
        self.reporting = Reporting(node)

    def preview(self, project_id, pipeline, *, items=None, finding_refs=None, languages=None):
        from spikes.source_collector import SourceCollector
        from spikes.metadata import validate_snapshot
        ws = self.reporting.artifacts.workspace(project_id); ws.recover()
        head = ws.git.head(); files = ws.git.snapshot(head); entities = validate_snapshot(files)
        require((items is None) != (finding_refs is None), 'Choose samples or stored findings')
        if finding_refs is not None:
            require(isinstance(finding_refs, list) and len(finding_refs) <= 500, 'Too many preview references')
            items = []
            for pin in finding_refs:
                raw, _ = SourceCollector.resolve(ws, project_id, pin, files, entities)
                row = json.loads(raw); require(row['type'] == 'SourceFinding', 'Expected stored finding')
                items.append(row['value']['item'])
        result = evaluate(pipeline, items, languages=languages)
        result.update(project_id=project_id, head=head, finding_refs=deepcopy(finding_refs))
        return result
