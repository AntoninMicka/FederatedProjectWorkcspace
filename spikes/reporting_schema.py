# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Closed reporting v1 records, immutable revisions and local pinned references.

No provider, network, scheduler or policy interpreter lives here. JSON policies
are evidence of the local user's decision, never executable instructions.
"""
from datetime import date, datetime, timedelta
import hashlib
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from spikes.metadata import parse_json, require, safe_path, timestamp, uuid, ValidationError

SCHEMA = 'fpw-reporting-record-v1'
PRIVACY = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}
DIMENSIONS = ('maturity', 'relevance', 'novelty', 'impact', 'confidence')
PERIODS = {'daily', 'weekly', 'monthly', 'quarterly', 'annual', 'custom'}
TYPES = {
    'SourceFinding': ('finding', 'definition_ref input_id item aliases entry_sha256 stage selection change_reason raw_ref'),
    'WatchDefinition': ('watch', 'title goal scope active schedule inputs selection evaluation report placement'),
    'ReportingTask': ('task', 'title goal scope source_policy calendar selection_policy scale_ref outputs execution retention_policy'),
    'EvaluationScale': ('scale', 'title dimensions comparison_policy'),
    'Source': ('source', 'task_ref title locator declared_author source_role publication_date imported_at retrieved_at capture_state raw_ref availability license'),
    'Event': ('event', 'task_ref title summary event_date detected_at imported_at categories entities geographies tags sources claims assessments correction_reason'),
    'EvidenceAssessment': ('assessment', 'task_ref subject scale_ref ratings evidence limitations review'),
    'Story': ('story', 'task_ref title summary events decisions'),
    'ReportSnapshot': ('snapshot', 'task_ref rules_ref scale_refs period knowledge_cutoff input_head baseline_snapshot events sources stories assessments selection query methodology_changes markdown generation approval limitations reproducibility corrects correction_reason'),
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def moment(value):
    timestamp(value)
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def fields(value, names):
    require(isinstance(value, dict) and value.keys() == set(names.split()),
            'Invalid reporting fields: ' + names)


def text(value, nullable=False):
    if nullable and value is None:
        return
    require(isinstance(value, str) and bool(value.strip()) and '\0' not in value,
            'Expected non-empty reporting text')


def choice(value, choices):
    require(isinstance(value, str) and value in choices, 'Unknown reporting value')


def hex_id(value, commit=False):
    require(isinstance(value, str) and re.fullmatch(
        r'(?:[0-9a-f]{40}|[0-9a-f]{64})' if commit else r'[0-9a-f]{64}', value),
        'Expected full commit ID' if commit else 'Expected SHA-256')


def sequence(value, validator, *, minimum=0, unique=True):
    require(isinstance(value, list) and minimum <= len(value) <= 128, 'Invalid reporting list')
    for item in value:
        validator(item)
    if unique:
        require(len({encoded(item) for item in value}) == len(value), 'Duplicate reporting entry')


def ref(value, batch=False):
    require(isinstance(value, dict), 'Expected reporting reference')
    if 'at' in value:
        require(batch, 'Pinned reference required')
        fields(value, 'artifact_id path sha256 at')
        require(value['at'] == 'same-commit', 'Invalid batch reference')
    else:
        fields(value, 'project_id artifact_id commit_id path sha256')
        uuid(value['project_id'])
        hex_id(value['commit_id'], True)
    uuid(value['artifact_id'])
    require(safe_path(value['path'])[:2] == ['artifacts', value['artifact_id']]
            and len(safe_path(value['path'])) == 3 and not value['path'].endswith('/metadata.json'),
            'Reference must select artifact content')
    hex_id(value['sha256'])


def references(value):
    """Walk only explicit Ref shapes; free text never selects a path."""
    if isinstance(value, dict):
        if {'artifact_id', 'path', 'sha256'} <= value.keys():
            yield value
        else:
            for item in value.values():
                yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


def scope(value):
    fields(value, 'entities categories geographies tags')
    for item in value.values():
        sequence(item, text)


def date_value(value):
    fields(value, 'precision start end basis')
    choice(value['precision'], {'unknown', 'day', 'month', 'year', 'range'})
    sequence(value['basis'], ref)
    if value['precision'] == 'unknown':
        require(value['start'] is None and value['end'] is None, 'Unknown date has no boundaries')
        return
    try:
        require(all(isinstance(value[k], str) and re.fullmatch(r'\d{4}-\d\d-\d\d', value[k])
                    for k in ('start', 'end')), 'Expected ISO dates')
        start, end = date.fromisoformat(value['start']), date.fromisoformat(value['end'])
        require(start < end, 'Empty date interval')
        precision = value['precision']
        if precision == 'day':
            require(end == start + timedelta(days=1), 'Invalid day interval')
        elif precision == 'month':
            require(start.day == 1 and end.day == 1 and
                    (end.year * 12 + end.month) == start.year * 12 + start.month + 1,
                    'Invalid month interval')
        elif precision == 'year':
            require(start.month == start.day == end.month == end.day == 1
                    and end.year == start.year + 1, 'Invalid year interval')
    except (ValueError, OverflowError) as exc:
        raise ValidationError('Invalid reporting calendar date') from exc
    require(bool(value['basis']), 'Known date needs evidence')


def period(value):
    fields(value, 'kind timezone calendar_revision start_local end_local start_utc end_utc')
    choice(value['kind'], PERIODS)
    text(value['calendar_revision'])
    try:
        text(value['timezone'])
        zone = ZoneInfo(value['timezone'])
        local = []
        for name in ('start', 'end'):
            timestamp(value[name + '_utc'])
            text(value[name + '_local'])
            dt = datetime.fromisoformat(value[name + '_local'])
            utc = datetime.fromisoformat(value[name + '_utc'].replace('Z', '+00:00'))
            require(dt.tzinfo is not None and dt == utc and
                    dt.isoformat() == utc.astimezone(zone).isoformat(), 'Period offset/timezone mismatch')
            local.append(dt)
        start, end = local
        require(start < end, 'Empty reporting period')
        if value['kind'] != 'custom':
            require(start.time() == end.time() == datetime.min.time(), 'Calendar boundaries must be midnight')
            if value['kind'] == 'daily':
                require((end.date() - start.date()).days == 1, 'Daily interval spans one local day')
            elif value['kind'] == 'weekly':
                require(start.weekday() == 0 and (end.date() - start.date()).days == 7,
                        'Weekly interval starts Monday and spans seven local days')
            else:
                months = {'monthly': 1, 'quarterly': 3, 'annual': 12}[value['kind']]
                require(start.day == end.day == 1 and
                        end.year * 12 + end.month == start.year * 12 + start.month + months,
                        'Invalid calendar month interval')
                if months == 3:
                    require(start.month in {1, 4, 7, 10}, 'Invalid quarter')
                if months == 12:
                    require(start.month == 1, 'Invalid annual interval')
    except (ValueError, ZoneInfoNotFoundError, OverflowError) as exc:
        raise ValidationError('Invalid reporting period') from exc


def review(value, nullable=False):
    if nullable and value is None:
        return
    fields(value, 'decision actor_id at policy_revision note')
    choice(value['decision'], {'confirmed', 'disputed', 'retracted'})
    uuid(value['actor_id'])
    timestamp(value['at'])
    ref(value['policy_revision'])
    text(value['note'])


def locator(value):
    text(value)
    # Manual references are either opaque IDs or public, credential-free URLs.
    if value.startswith('local:'):
        require(re.fullmatch(r'local:[A-Za-z0-9._-]{1,200}', value), 'Expected opaque local locator')
        return
    parsed = urlsplit(value)
    require(parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username
            and not parsed.password and not parsed.query and not parsed.fragment
            and not any(c.isspace() for c in value), 'Expected sanitized URL or opaque local locator')


def validate_record(record):
    fields(record, 'schema type entity_id revision_id previous recorded_at recorded_by privacy provenance value')
    require(record['schema'] == SCHEMA, 'Unknown reporting record version')
    choice(record['type'], TYPES)
    uuid(record['entity_id']); uuid(record['revision_id']); uuid(record['recorded_by'])
    timestamp(record['recorded_at'])
    choice(record['privacy'], PRIVACY)
    sequence(record['previous'], ref)
    require(len(record['previous']) <= 2, 'At most two revision parents')
    provenance = record['provenance']
    fields(provenance, 'method inputs run_refs')
    choice(provenance['method'], {'user', 'import', 'derived', 'migration'})
    sequence(provenance['inputs'], ref)
    def run_ref(item):
        fields(item, 'run_id manifest_sha256 result_sha256')
        uuid(item['run_id']); hex_id(item['manifest_sha256']); hex_id(item['result_sha256'])
    sequence(provenance['run_refs'], run_ref)
    kind = record['type']
    suffix, names = TYPES[kind]
    v = record['value']
    fields(v, 'schema ' + names)
    require(v['schema'] == 'fpw-reporting-' + suffix + '-v1', 'Unknown reporting value version')
    for key in ('title', 'goal', 'summary', 'correction_reason', 'declared_author'):
        if key in v:
            text(v[key], nullable=key in {'correction_reason', 'declared_author'})
    for key in ('task_ref', 'scale_ref', 'rules_ref'):
        if key in v:
            ref(v[key])
    for key in ('categories', 'entities', 'geographies', 'tags', 'limitations'):
        if key in v:
            sequence(v[key], text)
    if kind == 'SourceFinding':
        from spikes.rss_finding_schema import validate_finding
        validate_finding(v)
    elif kind == 'WatchDefinition':
        from spikes.monitoring_definition_schema import validate_definition
        validate_definition(v)
    elif kind == 'ReportingTask':
        scope(v['scope'])
        for key in ('source_policy', 'selection_policy', 'retention_policy'):
            ref(v[key])
        fields(v['calendar'], 'timezone calendar_revision periods')
        text(v['calendar']['timezone']); text(v['calendar']['calendar_revision'])
        try:
            ZoneInfo(v['calendar']['timezone'])
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationError('Unknown task timezone') from exc
        sequence(v['calendar']['periods'], lambda x: choice(x, PERIODS), minimum=1)
        fields(v['outputs'], 'formats language required_sections')
        require(v['outputs']['formats'] == ['markdown'], 'Manual v1 supports Markdown only')
        text(v['outputs']['language']); sequence(v['outputs']['required_sections'], text, minimum=1)
        fields(v['execution'], 'llm context_policy publication_policy')
        choice(v['execution']['llm'], {'disabled', 'optional'})
        ref(v['execution']['context_policy']); ref(v['execution']['publication_policy'])
    elif kind == 'EvaluationScale':
        fields(v['dimensions'], ' '.join(DIMENSIONS))
        for dimension, levels in v['dimensions'].items():
            def level(item):
                fields(item, 'value label criteria'); text(item['label']); text(item['criteria'])
                if dimension == 'confidence':
                    choice(item['value'], {'insufficient', 'low', 'medium', 'high'})
                else:
                    require(type(item['value']) is int and 0 <= item['value'] <= 5, 'Invalid rating level')
            sequence(levels, level, minimum=1)
            expected = {'insufficient', 'low', 'medium', 'high'} if dimension == 'confidence' else set(range(6))
            require(len(levels) == len(expected) and {x['value'] for x in levels} == expected,
                    'Incomplete evaluation scale')
        choice(v['comparison_policy'], {'same-revision-only', 'explicit-crosswalk'})
    elif kind == 'Source':
        locator(v['locator']); date_value(v['publication_date'])
        choice(v['source_role'], {'primary', 'secondary', 'community', 'unknown'})
        timestamp(v['imported_at'])
        if v['retrieved_at'] is not None:
            timestamp(v['retrieved_at'])
        choice(v['capture_state'], {'captured', 'reference-only'})
        choice(v['availability'], {'available', 'changed', 'withdrawn', 'unavailable', 'unknown'})
        fields(v['license'], 'identifier terms_ref capture_allowed retention_policy')
        text(v['license']['identifier'], True)
        require(type(v['license']['capture_allowed']) is bool, 'Expected capture permission')
        ref(v['license']['retention_policy'])
        if v['license']['terms_ref'] is not None:
            ref(v['license']['terms_ref'])
        if v['capture_state'] == 'captured':
            ref(v['raw_ref'], batch=True)
            require(v['license']['capture_allowed'] and v['license']['terms_ref'] is not None,
                    'Capture requires documented permission')
        else:
            require(v['raw_ref'] is None, 'Reference-only source cannot claim raw bytes')
    elif kind == 'Event':
        date_value(v['event_date']); timestamp(v['imported_at'])
        if v['detected_at'] is not None:
            timestamp(v['detected_at'])
        sequence(v['sources'], ref, minimum=1); sequence(v['assessments'], ref)
        def claim(item):
            fields(item, 'claim_id text scope stage'); uuid(item['claim_id']); text(item['text']); text(item['scope'])
            choice(item['stage'], {'announcement', 'demonstration', 'lab-result', 'controlled-demo',
                                   'pilot', 'limited-production', 'verified-operation', 'unknown'})
        sequence(v['claims'], claim, minimum=1)
        require(len({c['claim_id'] for c in v['claims']}) == len(v['claims']), 'Duplicate claim ID')
        require(not record['previous'] or v['correction_reason'], 'Event revision needs correction reason')
    elif kind == 'EvidenceAssessment':
        fields(v['subject'], 'event_id claim_id claim_sha256')
        uuid(v['subject']['event_id']); uuid(v['subject']['claim_id']); hex_id(v['subject']['claim_sha256'])
        fields(v['ratings'], ' '.join(DIMENSIONS))
        for key, rating in v['ratings'].items():
            if rating is not None:
                if key == 'confidence':
                    choice(rating, {'insufficient', 'low', 'medium', 'high'})
                else:
                    require(type(rating) is int and 0 <= rating <= 5, 'Invalid evidence rating')
        def evidence(item):
            fields(item, 'source_ref locator relation independence_group rationale')
            ref(item['source_ref']); text(item['locator'], True); text(item['independence_group'], True)
            choice(item['relation'], {'supports', 'contradicts', 'context'}); text(item['rationale'])
        sequence(v['evidence'], evidence, minimum=1); review(v['review'], True)
    elif kind == 'Story':
        sequence(v['events'], ref, minimum=1)
        ids = set()
        def decision(item):
            fields(item, 'decision_id kind event_ids canonical_event_id reverses reason review')
            uuid(item['decision_id']); require(item['decision_id'] not in ids, 'Duplicate story decision')
            ids.add(item['decision_id'])
            choice(item['kind'], {'link', 'duplicate', 'retract'})
            sequence(item['event_ids'], uuid, minimum=1); text(item['reason']); review(item['review'])
            require(item['review']['decision'] == 'confirmed', 'Story decision needs confirmation')
            if item['kind'] == 'duplicate':
                require(len(item['event_ids']) >= 2 and item['canonical_event_id'] in item['event_ids']
                        and item['reverses'] is None, 'Invalid duplicate decision')
            elif item['kind'] == 'link':
                require(item['canonical_event_id'] is None and item['reverses'] is None, 'Invalid link')
            else:
                require(item['canonical_event_id'] is None, 'Invalid retraction')
                uuid(item['reverses'])
        sequence(v['decisions'], decision)
    elif kind == 'ReportSnapshot':
        require(not record['previous'], 'Report corrections must create new identities')
        period(v['period']); timestamp(v['knowledge_cutoff']); hex_id(v['input_head'], True)
        for key in ('scale_refs', 'events', 'sources', 'stories', 'assessments', 'methodology_changes'):
            sequence(v[key], ref)
        for key in ('baseline_snapshot', 'corrects'):
            if v[key] is not None:
                ref(v[key])
        require((v['corrects'] is None) == (v['correction_reason'] is None), 'Correction needs reference and reason')
        def selection(item):
            fields(item, 'event_ref reason'); ref(item['event_ref'])
            choice(item['reason'], {'new', 'changed', 'late-discovery', 'late-import', 'context'})
        sequence(v['selection'], selection)
        fields(v['query'], 'selection_policy_ref scope include_unknown_dates include_late')
        ref(v['query']['selection_policy_ref']); scope(v['query']['scope'])
        require(all(type(v['query'][k]) is bool for k in ('include_unknown_dates', 'include_late')),
                'Expected selection booleans')
        ref(v['markdown'], batch=True)
        fields(v['generation'], 'mode run_id context_manifest_ref result_sha256')
        choice(v['generation']['mode'], {'manual', 'assisted'}); uuid(v['generation']['run_id'])
        hex_id(v['generation']['result_sha256'])
        if v['generation']['context_manifest_ref'] is not None:
            ref(v['generation']['context_manifest_ref'])
        require(v['generation']['mode'] == 'manual' or v['generation']['context_manifest_ref'] is not None,
                'Assisted generation needs provenance')
        review(v['approval']); require(v['approval']['decision'] == 'confirmed', 'Publication requires approval')
        choice(v['reproducibility'], {'exact-inputs', 'limited-inputs'})
    return record


def canonical_events(story):
    """Project confirmed dedup decisions without changing either event's bytes."""
    active = {d['decision_id']: d for d in story['value']['decisions'] if d['kind'] != 'retract'}
    for decision in story['value']['decisions']:
        if decision['kind'] == 'retract':
            active.pop(decision['reverses'], None)
    mapping = {}
    for decision in active.values():
        if decision['kind'] == 'duplicate':
            for event_id in decision['event_ids']:
                if event_id != decision['canonical_event_id']:
                    require(event_id not in mapping or mapping[event_id] == decision['canonical_event_id'],
                            'Conflicting active deduplication decisions')
                    mapping[event_id] = decision['canonical_event_id']
    for event_id in mapping:
        seen, current = set(), event_id
        while current in mapping:
            require(current not in seen, 'Cyclic deduplication decisions')
            seen.add(current); current = mapping[current]
    return mapping



def records(files, entities):
    result = {}
    for id_, meta in entities.items():
        # Raw sources remain opaque even when the captured filename is
        # record.json. Capturing a reporting export is not importing its claims.
        if meta['kind'] == 'source' or not meta.get('file', '').endswith('.json'):
            continue
        data = files[f'artifacts/{id_}/' + meta['file']]
        tagged = SCHEMA in meta.get('tags', [])
        if not tagged and meta['file'] != 'record.json' and b'fpw-reporting-record-' not in data:
            continue
        try:
            payload = parse_json(data, maximum=16 * 1024 * 1024)
        except ValidationError:
            require(not tagged and b'fpw-reporting-record-' not in data, 'Malformed reporting JSON')
            continue
        declared = isinstance(payload, dict) and isinstance(payload.get('schema'), str) and payload['schema'].startswith('fpw-reporting-record-')
        if not tagged and not declared:
            continue
        require(meta['file'] == 'record.json', 'Reporting record requires record.json')
        path = f'artifacts/{id_}/record.json'
        if meta['file'] == 'record.json':
            record = validate_record(parse_json(files[path], maximum=1024 * 1024))
            require(files[path] == encoded(record), 'Reporting JSON must use canonical serialization')
            require(record['revision_id'] == id_ and record['recorded_at'] == meta['created_at']
                    and record['recorded_by'] == meta['author_id'] and record['privacy'] == meta['privacy'],
                    'Reporting envelope differs from metadata')
            require(meta['kind'] == ('snapshot' if record['type'] == 'ReportSnapshot' else 'document'),
                    'Invalid reporting artifact kind')
            if record['type']=='SourceFinding':
                require(meta['provenance']=='external','Finding metadata must remain external source data')
            result[id_] = record
    identities = {}
    parents = set()
    for id_, record in result.items():
        identity = record['entity_id']
        require(identity not in entities, 'Reporting identity collides with artifact ID')
        identities.setdefault(identity, []).append(id_)
        for parent in record['previous']:
            before = result.get(parent['artifact_id'])
            require(before is not None and before['entity_id'] == identity and before['type'] == record['type']
                    and before['revision_id'] != id_, 'Invalid revision predecessor')
            require(moment(before['recorded_at']) <= moment(record['recorded_at']), 'Revision precedes its parent')
            parents.add(before['revision_id'])
            if record['type'] in {'Event', 'Source'}:
                require(before['value']['imported_at'] == record['value']['imported_at'], 'Import time is immutable')
            if record['type']=='SourceFinding':
                prior=before['value'];current=record['value']
                require(current['input_id']==prior['input_id'] and all(current['item'][k]==prior['item'][k] for k in ('source_id','source_locator')), 'Finding identity changed')
                require(set(prior['aliases'])<=set(current['aliases']),'Finding aliases are append-only')
                require(all(current['item'][k]==prior['item'][k] for k in ('discovered_at','imported_at')),'Finding first-seen/import times are immutable')
            if record['type'] == 'Story':
                old, new = before['value']['decisions'], record['value']['decisions']
                require(new[:len(old)] == old, 'Story decisions are append-only')
        for reference in references(record):
            if 'at' in reference:
                require(reference['path'] in files and digest(files[reference['path']]) == reference['sha256'],
                        'Batch reference content mismatch')
    for identity, revisions in identities.items():
        require(len([id_ for id_ in revisions if id_ not in parents]) == 1, 'Conflicting reporting revision tips')
        require(len({result[id_]['type'] for id_ in revisions}) == 1, 'Identity changes reporting type')
        require(sum(not result[id_]['previous'] for id_ in revisions) == 1, 'Identity needs one genesis')
        if result[revisions[0]]['type'] == 'ReportSnapshot':
            require(len(revisions) == 1, 'Snapshot identity cannot be reused')
        # Every revision must reach genesis; reject cycles even at equal timestamps.
        visited, active = set(), set()
        for root in revisions:
            stack = [(root, False)]
            while stack:
                id_, leaving = stack.pop()
                if leaving:
                    active.remove(id_); visited.add(id_)
                elif id_ not in visited:
                    require(id_ not in active, 'Cyclic reporting revisions')
                    active.add(id_); stack.append((id_, True))
                    stack.extend((p['artifact_id'], False) for p in result[id_]['previous'])
    from spikes.monitoring_definition_schema import validate_graph
    validate_graph(result)
    publications = set()
    corrections = set()
    for record in result.values():
        if record['type'] != 'ReportSnapshot':
            continue
        v = record['value']
        if v['corrects'] is None:
            # Pinning the same immutable revision in a later containing commit
            # must not create a new reservation for the same period.
            key = encoded([[v['task_ref']['artifact_id'], v['task_ref']['sha256']], v['period'],
                           [v['rules_ref']['artifact_id'], v['rules_ref']['sha256']]])
            require(key not in publications, 'Period already has a base publication; issue a correction')
            publications.add(key)
        else:
            key = v['corrects']['artifact_id']
            require(key not in corrections, 'Conflicting report corrections')
            corrections.add(key)
    return result


def immutable_transition(base_files, candidate_files, base_entities, candidate_entities):
    before = records(base_files, base_entities)
    after = records(candidate_files, candidate_entities)
    require(not (set(after) - set(before)) & set(base_entities),
            'Reporting revision must use a new artifact ID')
    for id_ in before:
        prefix = f'artifacts/{id_}/'
        require({p: b for p, b in base_files.items() if p.startswith(prefix)} ==
                {p: b for p, b in candidate_files.items() if p.startswith(prefix)},
                'Reporting revisions are immutable; create a successor')


def validate_git(git, files, entities, base_files=None, *, head='HEAD'):
    """Resolve all local references against exact commits before journal/CAS.

    Cross-project refs fail closed in MON-01: their authorization belongs to
    XREF-01, rather than treating a known project UUID as a grant.
    """
    from spikes.configuration import committed_project, parse_project
    from spikes.metadata import validate_snapshot
    all_records = records(files, entities)
    if not all_records:
        return
    if head != 'HEAD':
        hex_id(head, commit=True)
        require(git.run('rev-parse','--verify',head+'^{commit}').stdout.strip()==head,
                'Reporting validation needs an exact commit')
    project = parse_project(git.run('show', head+':project.json', binary=True).stdout)['id']
    cache = {}
    def resolve(reference, expected=None):
        ref(reference, batch=True)
        if 'at' in reference:
            selected, metas = files, entities
            if base_files is not None:
                require(not any(p.startswith(f"artifacts/{reference['artifact_id']}/") for p in base_files),
                        'Batch reference must be a new sibling')
        else:
            require(reference['project_id'] == project, 'Cross-project reporting refs require authorized handoff')
            commit = reference['commit_id']
            if commit not in cache:
                pinned_commit=git.run('rev-parse','--verify',commit+'^{commit}',check=False)
                require(pinned_commit.returncode==0 and pinned_commit.stdout.strip() == commit,
                        'Reference must pin a commit')
                committed_project(git, commit, project, check_worktree=False)
                selected = git.snapshot(commit)
                cache[commit] = selected, validate_snapshot(selected)
            selected, metas = cache[commit]
        require(reference['path'] in selected and digest(selected[reference['path']]) == reference['sha256'],
                'Pinned reporting bytes mismatch')
        meta = metas.get(reference['artifact_id'])
        require(meta is not None and meta.get('file') == reference['path'].split('/')[-1], 'Invalid content reference')
        payload = None
        if meta['kind'] != 'source' and meta.get('file') == 'record.json':
            payload = records(selected, metas).get(meta['id'])
        if expected:
            require(payload is not None and payload['type'] == expected, 'Wrong reporting reference type')
        return meta, payload

    # Existing batch refs are interpreted in their original commit. Only new
    # records need candidate validation; old bytes already passed this gate.
    for id_, record in all_records.items():
        if base_files is not None and f'artifacts/{id_}/record.json' in base_files:
            continue
        v = record['value']; kind = record['type']
        for reference in references(record):
            meta, _ = resolve(reference)
            require(PRIVACY[record['privacy']] >= PRIVACY[meta['privacy']], 'Reporting privacy would be relaxed')
        for parent in record['previous']:
            _, old = resolve(parent, kind)
            require(old['entity_id'] == record['entity_id'], 'Predecessor identity mismatch')
        task = None
        if 'task_ref' in v:
            _, task = resolve(v['task_ref'], 'ReportingTask')
        if 'scale_ref' in v:
            resolve(v['scale_ref'], 'EvaluationScale')
        if kind == 'Source' and v['raw_ref'] is not None:
            meta, _ = resolve(v['raw_ref'])
            require(meta['kind'] == 'source', 'Captured bytes must be immutable source')
        if kind=='SourceFinding':
            _,definition=resolve(v['definition_ref'],'WatchDefinition')
            inputs=[i for i in definition['value']['inputs'] if i['id']==v['input_id']]
            require(len(inputs)==1 and inputs[0]['kind']=='external' and inputs[0]['connector']=='rss-atom','Finding input is not an RSS source')
            require(inputs[0]['locator']==v['item']['source_locator'] and v['item']['source_id']==v['input_id'],'Finding source differs from definition')
            require(v['item']['privacy']==record['privacy'],'Finding privacy differs from envelope')
            meta,_=resolve(v['raw_ref']);require(meta['kind']=='source','Finding raw capture must be a source')
        if kind == 'Event':
            for source in v['sources']:
                _, source_record = resolve(source, 'Source')
                require(source_record['value']['task_ref'] == v['task_ref'], 'Event/source task mismatch')
            for assessment in v['assessments']:
                _, assessment_record = resolve(assessment, 'EvidenceAssessment')
                subject = assessment_record['value']['subject']
                require(subject['event_id'] == record['entity_id'] and any(
                    c['claim_id'] == subject['claim_id'] and digest(encoded(c)) == subject['claim_sha256']
                    for c in v['claims']), 'Assessment does not match current claim')
        if kind == 'Story':
            event_ids = set()
            for event in v['events']:
                _, event_record = resolve(event, 'Event')
                require(event_record['value']['task_ref'] == v['task_ref'], 'Story/event task mismatch')
                event_ids.add(event_record['entity_id'])
            decisions, retracted = {}, set()
            for d in v['decisions']:
                require(set(d['event_ids']) <= event_ids, 'Story decision names absent event')
                if d['kind'] == 'retract':
                    original = decisions.get(d['reverses'])
                    require(original is not None and original['kind'] != 'retract'
                            and d['reverses'] not in retracted and d['event_ids'] == original['event_ids'],
                            'Retraction must reverse an earlier active decision')
                    retracted.add(d['reverses'])
                decisions[d['decision_id']] = d
            canonical_events(record)
        if kind == 'EvidenceAssessment':
            require(v['scale_ref'] == task['value']['scale_ref'], 'Assessment uses a different task scale')
            for evidence in v['evidence']:
                _, source = resolve(evidence['source_ref'], 'Source')
                require(source['value']['task_ref'] == v['task_ref'], 'Assessment/source task mismatch')
        if kind == 'ReportSnapshot':
            _snapshot(v, task['value'], resolve)
            require(moment(v['knowledge_cutoff']) <= moment(record['recorded_at']),
                    'Knowledge cutoff cannot be in the future')
            require(git.run('rev-parse', '--verify', v['input_head'] + '^{commit}').stdout.strip() == v['input_head'],
                    'Report input_head must be a commit')
            require(git.run('merge-base', '--is-ancestor', v['input_head'], head, check=False).returncode == 0,
                    'Report input_head must belong to project history')
            for key in ('events', 'sources', 'stories', 'assessments', 'scale_refs'):
                for reference in v[key]:
                    require(git.run('merge-base', '--is-ancestor', reference['commit_id'], v['input_head'],
                                    check=False).returncode == 0, 'Report input is newer than input_head')
                    _, item = resolve(reference)
                    require(moment(item['recorded_at']) <= moment(v['knowledge_cutoff']), 'Input is beyond knowledge cutoff')
            markdown_bytes = (files if 'at' in v['markdown'] else
                              cache[v['markdown']['commit_id']][0])[v['markdown']['path']]
            try:
                markdown = markdown_bytes.decode('utf-8')
            except UnicodeError as exc:
                raise ValidationError('Report Markdown must be UTF-8') from exc
            require(all(section in markdown for section in task['value']['outputs']['required_sections']),
                    'Report omits required sections')
            require(v['events'] or 'Nebyla doložena významná změna.' in markdown,
                    'Empty report must explicitly state no demonstrated significant change')


def _snapshot(v, task, resolve):
    require(v['query']['selection_policy_ref'] == task['selection_policy'] == v['rules_ref'],
            'Report selection policy differs from task')
    require(v['query']['scope'] == task['scope'], 'Manual report must use task scope')
    require(v['period']['timezone'] == task['calendar']['timezone'] and
            v['period']['calendar_revision'] == task['calendar']['calendar_revision'] and
            v['period']['kind'] in task['calendar']['periods'], 'Report calendar differs from task')
    require(v['approval']['policy_revision'] == task['execution']['publication_policy'],
            'Report approval policy differs from task')
    require(task['scale_ref'] in v['scale_refs'], 'Report must pin task scale')
    for scale in v['scale_refs']:
        resolve(scale, 'EvaluationScale')
    for key in ('baseline_snapshot', 'corrects'):
        if v[key] is not None:
            _, prior = resolve(v[key], 'ReportSnapshot')
            require(prior['value']['task_ref'] == v['task_ref'], 'Report predecessor task mismatch')
            if key == 'corrects':
                require(prior['value']['period'] == v['period'], 'Correction must preserve report period')
    selected = [s['event_ref'] for s in v['selection']]
    require(len(selected) == len(v['events']) and {encoded(r) for r in selected} ==
            {encoded(r) for r in v['events']}, 'Selection must explain every event exactly once')
    selected_sources = {encoded(r) for r in v['sources']}
    selected_assessments = {encoded(r) for r in v['assessments']}
    for key, expected in [('sources', 'Source'), ('stories', 'Story'), ('assessments', 'EvidenceAssessment')]:
        for reference in v[key]:
            _, item = resolve(reference, expected)
            require(item['value']['task_ref'] == v['task_ref'], 'Report input task mismatch')
            if key == 'sources' and item['value']['capture_state'] == 'reference-only':
                require(v['reproducibility'] == 'limited-inputs' and v['limitations'],
                        'Reference-only source requires explicit reproduction limits')
            if key == 'assessments':
                require(item['value']['scale_ref'] in v['scale_refs'], 'Report omits assessment scale')
                require({encoded(e['source_ref']) for e in item['value']['evidence']} <= selected_sources,
                        'Report omits assessment evidence')
    for reference in v['events']:
        _, event = resolve(reference, 'Event'); e = event['value']
        require(e['task_ref'] == v['task_ref'], 'Report event task mismatch')
        require(moment(e['imported_at']) <= moment(v['knowledge_cutoff']) and
                moment(event['recorded_at']) <= moment(v['knowledge_cutoff']),
                'Event is beyond knowledge cutoff')
        require({encoded(r) for r in e['sources']} <= selected_sources and
                {encoded(r) for r in e['assessments']} <= selected_assessments, 'Report omits event evidence')
        if e['event_date']['precision'] == 'unknown':
            require(v['query']['include_unknown_dates'] and v['limitations'], 'Unknown date needs explicit category/limitation')
        if e['detected_at'] is None:
            require(v['limitations'], 'Unknown detection time needs explicit limitation')
        for source_ref in e['sources']:
            _, source = resolve(source_ref, 'Source')
            require(moment(source['value']['imported_at']) <= moment(v['knowledge_cutoff']),
                    'Source is beyond knowledge cutoff')
        for claim in e['claims']:
            if claim['stage'] == 'verified-operation':
                confirmed = False
                for reference in e['assessments']:
                    _, assessment = resolve(reference, 'EvidenceAssessment'); a = assessment['value']
                    if a['subject']['claim_sha256'] != digest(encoded(claim)):
                        continue
                    confirmed |= bool(a['review'] and a['review']['decision'] == 'confirmed' and any(
                        ev['relation'] == 'supports' and
                        (resolve(ev['source_ref'], 'Source')[1]['value']['source_role'] == 'primary'
                         or ev['independence_group']) for ev in a['evidence']))
                require(confirmed, 'Verified operation lacks confirmed independent/primary evidence')
    markdown_meta, _ = resolve(v['markdown'])
    require(markdown_meta['kind'] == 'snapshot' and markdown_meta['file'].endswith('.md'),
            'Published Markdown must be an immutable Markdown snapshot')
    require(v['generation']['result_sha256'] == v['markdown']['sha256'], 'Markdown digest differs from generation')
