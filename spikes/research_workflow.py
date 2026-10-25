# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Closed nested schemas and reviewed policies for dynamic research workflows."""
import hashlib
import json
from pathlib import Path
import re
import stat

from spikes.metadata import parse_json, require, uuid
from spikes.public_source import PublicSourceBinding, normalize_url, url_origin


MAX_LIST = 32
MAX_TEXT_BYTES = 65536
HASH = re.compile(r'[0-9a-f]{64}')
HEAD = re.compile(r'[0-9a-f]{40,64}')
PRIVACY = {'public', 'project', 'confidential'}
RESEARCH_ACTIONS = {
    'source.fetch-public', 'research.verify-evidence',
    'research.select-relevant', 'research.analyze',
    'research.compose-report', 'research.plan-next',
}
PROFILE_ACTIONS = RESEARCH_ACTIONS | {'search.iterative-query'}
PROFILE_ACTION_SETS = {
    'quick-search-v1': {'search.iterative-query', 'research.select-relevant',
                        'research.compose-report', 'research.plan-next'},
    'read-and-verify-v1': {'search.iterative-query', 'source.fetch-public',
        'research.verify-evidence', 'research.select-relevant',
        'research.compose-report', 'research.plan-next'},
    'deep-research-v1': PROFILE_ACTIONS,
}
REVIEWED_PROFILES = (Path(__file__).resolve().parents[1]
                     / 'modules' / 'research-profiles')


def _canonical(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':')).encode()
    require(len(raw) <= 1024 * 1024, 'Research value exceeds 1 MiB')
    return raw


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _exact(value, fields, name):
    require(isinstance(value, dict) and set(value) == set(fields),
            f'Unknown or missing research {name} field')


def _text(value, name, maximum=MAX_TEXT_BYTES, *, nullable=False):
    if nullable and value is None:
        return
    require(isinstance(value, str) and value.strip() == value
            and 0 < len(value.encode()) <= maximum and '\0' not in value,
            f'Invalid research {name}')


def _uuid(value, name):
    try:
        uuid(value)
    except ValueError:
        require(False, f'Invalid research {name}')


def _hash(value, name, *, nullable=False):
    require((nullable and value is None)
            or (isinstance(value, str) and HASH.fullmatch(value)),
            f'Invalid research {name}')


def _strings(value, name, *, maximum=MAX_LIST, allow_empty=False):
    require(isinstance(value, list) and len(value) <= maximum
            and (allow_empty or bool(value)), f'Invalid research {name}')
    for item in value:
        _text(item, name, 1024)
    require(len(value) == len(set(value)), f'Duplicate research {name}')


def _uuids(value, name, *, allow_empty=False):
    require(isinstance(value, list) and len(value) <= MAX_LIST
            and (allow_empty or bool(value)), f'Invalid research {name}')
    for item in value:
        _uuid(item, name)
    require(len(value) == len(set(value)), f'Duplicate research {name}')


def _source_ref(value):
    fields = {'task_id', 'search_id', 'source_id', 'run_id', 'adapter',
              'binding_revision', 'url', 'origin', 'raw_sha256', 'text_sha256',
              'projection_sha256'}
    _exact(value, fields, 'source reference')
    for key in ('task_id', 'search_id', 'run_id'):
        _uuid(value[key], key)
    for key in ('source_id', 'adapter', 'binding_revision'):
        _text(value[key], key, 256)
    url = normalize_url(value['url'])
    require(url == value['url'] and url_origin(url) == value['origin'],
            'Research source URL and origin differ')
    for key in ('raw_sha256', 'text_sha256'):
        _hash(value[key], key)
    _hash(value['projection_sha256'], 'projection digest', nullable=True)


def _source_refs(value, *, allow_empty=False):
    require(isinstance(value, list) and len(value) <= MAX_LIST
            and (allow_empty or bool(value)), 'Invalid research source references')
    for item in value:
        _source_ref(item)
    identities = [(item['run_id'], item['source_id']) for item in value]
    require(len(identities) == len(set(identities)),
            'Duplicate research source reference')


def _evidence(value):
    _exact(value, {'sources', 'relations', 'warnings'}, 'evidence')
    _source_refs(value['sources'])
    require(isinstance(value['relations'], list)
            and len(value['relations']) <= 128,
            'Invalid research evidence relations')
    known = {item['run_id'] for item in value['sources']}
    for relation in value['relations']:
        _exact(relation, {'kind', 'source_run_ids', 'observation'},
               'evidence relation')
        require(relation['kind'] in {'same-origin', 'links-to', 'same-content'},
                'Unsupported research evidence relation')
        _uuids(relation['source_run_ids'], 'relation source run ID')
        require(2 <= len(relation['source_run_ids']) <= 2
                and set(relation['source_run_ids']) <= known,
                'Research evidence relation references an unknown source')
        _text(relation['observation'], 'evidence observation', 4096)
    _strings(value['warnings'], 'evidence warning', maximum=32, allow_empty=True)


def _selection(value):
    _exact(value, {'selected_source_run_ids', 'rejected', 'limitations'},
           'selection')
    _uuids(value['selected_source_run_ids'], 'selected source run ID')
    require(isinstance(value['rejected'], list) and len(value['rejected']) <= MAX_LIST,
            'Invalid research rejected sources')
    rejected_ids = []
    for item in value['rejected']:
        _exact(item, {'source_run_id', 'reason'}, 'rejected source')
        _uuid(item['source_run_id'], 'rejected source run ID')
        _text(item['reason'], 'rejection reason', 4096)
        rejected_ids.append(item['source_run_id'])
    require(len(rejected_ids) == len(set(rejected_ids))
            and not set(rejected_ids) & set(value['selected_source_run_ids']),
            'Research selection contains duplicate source decisions')
    _strings(value['limitations'], 'selection limitation', maximum=32,
             allow_empty=True)


def _claims(value):
    require(isinstance(value, list) and len(value) <= 64,
            'Invalid research analysis claims')
    for item in value:
        _exact(item, {'claim', 'source_run_ids', 'confidence'}, 'analysis claim')
        _text(item['claim'], 'analysis claim', 8192)
        _uuids(item['source_run_ids'], 'claim source run ID')
        require(item['confidence'] in {'low', 'medium', 'high'},
                'Invalid research claim confidence')


def _ledger(value):
    require(isinstance(value, list) and len(value) <= 32,
            'Invalid research ledger')
    seen = set()
    for item in value:
        _exact(item, {'step_id', 'action_id', 'state', 'result_sha256'},
               'ledger item')
        _uuid(item['step_id'], 'ledger step ID')
        require(item['step_id'] not in seen, 'Duplicate research ledger step')
        seen.add(item['step_id'])
        require(item['action_id'] in PROFILE_ACTIONS,
                'Unsupported research ledger action')
        require(item['state'] in {'completed', 'failed', 'unknown', 'cancelled'},
                'Invalid research ledger state')
        _hash(item['result_sha256'], 'ledger result digest', nullable=True)


def _planner_candidates(value):
    require(isinstance(value, list) and len(value) <= MAX_LIST,
            'Invalid research planner candidates')
    seen = set()
    for item in value:
        _exact(item, {'candidate_id', 'candidate'}, 'planner candidate option')
        _hash(item['candidate_id'], 'planner candidate ID')
        candidate = item['candidate']
        _exact(candidate, {'action', 'privacy', 'cost_units', 'input'},
               'planner candidate')
        _exact(candidate['action'], {'id', 'version'}, 'candidate action')
        action_id = candidate['action']['id']
        require(action_id in PROFILE_ACTIONS - {'research.plan-next'}
                and candidate['action']['version'] == '1.0'
                and candidate['privacy'] in PRIVACY
                and type(candidate['cost_units']) is int
                and 0 <= candidate['cost_units'] <= 1_000_000,
                'Invalid research planner candidate')
        INPUT_VALIDATORS[action_id](candidate['input'])
        require(item['candidate_id'] == _digest(candidate),
                'Research planner candidate digest differs')
        require(item['candidate_id'] not in seen,
                'Duplicate research planner candidate')
        seen.add(item['candidate_id'])


def _budget(value, name, *, allow_zero=True):
    _exact(value, {'max_steps', 'max_cost_units', 'max_seconds'}, name)
    minimum = 0 if allow_zero else 1
    require(type(value['max_steps']) is int
            and minimum <= value['max_steps'] <= 32,
            f'Invalid research {name} steps')
    require(type(value['max_cost_units']) is int
            and 0 <= value['max_cost_units'] <= 10_000_000,
            f'Invalid research {name} cost')
    require(type(value['max_seconds']) is int
            and 0 <= value['max_seconds'] <= 86_400,
            f'Invalid research {name} time')


def _fetch_input(value):
    _exact(value, {'request', 'preview', 'preview_sha256'}, 'fetch input')
    request = value['request']; preview = value['preview']
    _exact(request, {'task_id', 'search_id', 'source_id', 'run_id'},
           'fetch request')
    for key in ('task_id', 'search_id', 'run_id'):
        _uuid(request[key], key)
    _text(request['source_id'], 'source ID', 256)
    fields = {'schema_version', 'task_id', 'search_id', 'source_id', 'run_id',
              'project_id', 'privacy', 'expected_head', 'title', 'url', 'origin',
              'adapter', 'binding', 'effects', 'limits', 'warning',
              'search_provenance'}
    _exact(preview, fields, 'fetch preview')
    require(preview['schema_version'] == 1
            and all(preview[key] == request[key] for key in request),
            'Research fetch preview differs from request')
    _uuid(preview['project_id'], 'project ID')
    require(preview['privacy'] in PRIVACY, 'Invalid research fetch privacy')
    require(isinstance(preview['expected_head'], str)
            and HEAD.fullmatch(preview['expected_head']),
            'Invalid research fetch expected HEAD')
    _text(preview['title'], 'source title', 4096)
    url = normalize_url(preview['url'])
    require(url == preview['url'] and url_origin(url) == preview['origin'],
            'Research fetch URL and origin differ')
    _text(preview['adapter'], 'reader adapter', 256)
    binding = PublicSourceBinding.parse(preview['binding'])
    require(binding.adapter_id == preview['adapter']
            and preview['origin'] in binding.origins,
            'Research fetch preview differs from reader binding')
    require(isinstance(preview['effects'], list) and len(preview['effects']) == 2,
            'Research fetch preview must contain two bounded effects')
    expected_urls = [preview['origin'] + '/robots.txt', preview['url']]
    for index, effect in enumerate(preview['effects']):
        _exact(effect, {'method', 'url', 'purpose'}, 'fetch effect')
        require(effect['method'] == 'GET' and effect['url'] == expected_urls[index],
                'Research fetch effect differs from preview')
        _text(effect['purpose'], 'fetch purpose', 1024)
    _exact(preview['limits'], {'wire_bytes', 'decoded_bytes', 'text_chars',
        'compression_ratio', 'seconds', 'redirects'}, 'fetch limits')
    limits = preview['limits']
    expected_limits = {'wire_bytes': binding.max_wire_bytes,
        'decoded_bytes': binding.max_decoded_bytes,
        'text_chars': binding.max_text_chars,
        'compression_ratio': binding.max_compression_ratio,
        'seconds': binding.timeout_seconds, 'redirects': 0}
    require(limits == expected_limits, 'Research fetch limits differ from binding')
    _text(preview['warning'], 'fetch warning', 4096)
    _exact(preview['search_provenance'],
           {'search_id', 'round_index', 'source_id'}, 'search provenance')
    provenance = preview['search_provenance']
    require(provenance['search_id'] == request['search_id']
            and provenance['source_id'] == request['source_id']
            and type(provenance['round_index']) is int
            and 1 <= provenance['round_index'] <= 32,
            'Research fetch provenance differs from request')
    _hash(value['preview_sha256'], 'fetch preview digest')
    require(value['preview_sha256'] == _digest(preview),
            'Research fetch preview digest differs')


def _fetch_output(value):
    _exact(value, {'schema_version', 'kind', 'task_id', 'search_id', 'source_id',
        'run_id', 'state', 'raw_sha256', 'text_sha256', 'projection_sha256',
        'final_url'}, 'fetch output')
    require(value['schema_version'] == 1 and value['kind'] == 'public-source-reference',
            'Unsupported research fetch output')
    for key in ('task_id', 'search_id', 'run_id'):
        _uuid(value[key], key)
    _text(value['source_id'], 'source ID', 256)
    require(value['state'] == 'succeeded', 'Research fetch output is not successful')
    for key in ('raw_sha256', 'text_sha256'):
        _hash(value[key], key)
    _hash(value['projection_sha256'], 'projection digest', nullable=True)
    require(normalize_url(value['final_url']) == value['final_url'],
            'Invalid research final URL')


def _verify_input(value):
    _exact(value, {'research_id', 'source_refs', 'ledger_sha256'},
           'verification input')
    _uuid(value['research_id'], 'research ID')
    _source_refs(value['source_refs'])
    _hash(value['ledger_sha256'], 'source ledger digest')
    require(value['ledger_sha256'] == _digest(value['source_refs']),
            'Research source ledger digest differs')


def _verify_output(value):
    _exact(value, {'schema_version', 'kind', 'research_id', 'evidence',
                   'evidence_sha256'}, 'verification output')
    require(value['schema_version'] == 1 and value['kind'] == 'research-evidence',
            'Unsupported research verification output')
    _uuid(value['research_id'], 'research ID')
    _evidence(value['evidence'])
    _hash(value['evidence_sha256'], 'evidence digest')
    require(value['evidence_sha256'] == _digest(value['evidence']),
            'Research evidence digest differs')


def _model_base(value, fields, name):
    _exact(value, fields | {'research_id', 'goal', 'goal_sha256',
                            'run_id', 'manifest_id'}, name)
    for key in ('research_id', 'run_id', 'manifest_id'):
        _uuid(value[key], key)
    _text(value['goal'], 'goal', 16384)
    _hash(value['goal_sha256'], 'goal digest')
    require(value['goal_sha256'] == hashlib.sha256(value['goal'].encode()).hexdigest(),
            'Research goal digest differs')


def _select_input(value):
    _model_base(value, {'evidence', 'evidence_sha256'}, 'selection input')
    _evidence(value['evidence'])
    _hash(value['evidence_sha256'], 'evidence digest')
    require(value['evidence_sha256'] == _digest(value['evidence']),
            'Research selection evidence digest differs')


def _select_output(value):
    _exact(value, {'schema_version', 'kind', 'research_id', 'run_id',
        'manifest_id', 'selection', 'selection_sha256'}, 'selection output')
    require(value['schema_version'] == 1 and value['kind'] == 'research-selection',
            'Unsupported research selection output')
    for key in ('research_id', 'run_id', 'manifest_id'):
        _uuid(value[key], key)
    _selection(value['selection'])
    _hash(value['selection_sha256'], 'selection digest')
    require(value['selection_sha256'] == _digest(value['selection']),
            'Research selection digest differs')


def _analysis_input(value):
    _model_base(value, {'selection', 'selection_sha256'}, 'analysis input')
    _selection(value['selection'])
    _hash(value['selection_sha256'], 'selection digest')
    require(value['selection_sha256'] == _digest(value['selection']),
            'Research analysis selection digest differs')


def _analysis_output(value):
    _exact(value, {'schema_version', 'kind', 'research_id', 'run_id',
        'manifest_id', 'claims', 'limitations', 'analysis_sha256'},
        'analysis output')
    require(value['schema_version'] == 1 and value['kind'] == 'research-analysis',
            'Unsupported research analysis output')
    for key in ('research_id', 'run_id', 'manifest_id'):
        _uuid(value[key], key)
    _claims(value['claims'])
    _strings(value['limitations'], 'analysis limitation', maximum=32,
             allow_empty=True)
    content = {'claims': value['claims'], 'limitations': value['limitations']}
    _hash(value['analysis_sha256'], 'analysis digest')
    require(value['analysis_sha256'] == _digest(content),
            'Research analysis digest differs')


def _compose_input(value):
    _model_base(value, {'selected_source_run_ids', 'selection_sha256',
        'analysis_run_id', 'analysis_sha256', 'task_id'}, 'report input')
    _uuids(value['selected_source_run_ids'], 'selected source run ID')
    _hash(value['selection_sha256'], 'selection digest')
    _uuid(value['task_id'], 'task ID')
    if value['analysis_run_id'] is None:
        require(value['analysis_sha256'] is None,
                'Research report analysis reference is incomplete')
    else:
        _uuid(value['analysis_run_id'], 'analysis run ID')
        _hash(value['analysis_sha256'], 'analysis digest')


def _compose_output(value):
    _exact(value, {'schema_version', 'kind', 'research_id', 'task_id', 'run_id',
        'manifest_id', 'state', 'draft_sha256'}, 'report output')
    require(value['schema_version'] == 1 and value['kind'] == 'research-report-draft'
            and value['state'] == 'draft', 'Unsupported research report output')
    for key in ('research_id', 'task_id', 'run_id', 'manifest_id'):
        _uuid(value[key], key)
    _hash(value['draft_sha256'], 'report draft digest')


def _planner_input(value):
    _model_base(value, {'profile_id', 'profile_version', 'plan_revision',
        'ledger', 'ledger_sha256', 'remaining_budget', 'available_candidates'},
        'planner input')
    require(value['profile_id'] in {
        'quick-search-v1', 'read-and-verify-v1', 'deep-research-v1'},
        'Unsupported research profile ID')
    require(value['profile_version'] == '1.0',
            'Unsupported research profile version')
    require(type(value['plan_revision']) is int and value['plan_revision'] > 0,
            'Invalid research plan revision')
    _ledger(value['ledger'])
    _hash(value['ledger_sha256'], 'planner ledger digest')
    require(value['ledger_sha256'] == _digest(value['ledger']),
            'Research planner ledger digest differs')
    _budget(value['remaining_budget'], 'remaining budget')
    _planner_candidates(value['available_candidates'])


def _planner_output(value):
    _exact(value, {'schema_version', 'kind', 'research_id', 'run_id',
        'manifest_id', 'decision', 'reason', 'target_action', 'candidate',
        'repeat_step_id', 'finish_reason', 'proposal_sha256'}, 'planner output')
    require(value['schema_version'] == 1 and value['kind'] == 'research-next-step',
            'Unsupported research planner output')
    for key in ('research_id', 'run_id', 'manifest_id'):
        _uuid(value[key], key)
    require(value['decision'] in {'append', 'repeat', 'finish'},
            'Unsupported research planner decision')
    _text(value['reason'], 'planner reason', 4096)
    if value['decision'] == 'finish':
        require(value['target_action'] is None and value['candidate'] is None
                and value['repeat_step_id'] is None
                and value['finish_reason'] in {'completed', 'insufficient',
                    'budget-exhausted', 'cancelled-by-user'},
                'Invalid research finish proposal')
    else:
        require(value['finish_reason'] is None
                and isinstance(value['target_action'], str)
                and value['target_action'] in PROFILE_ACTIONS,
                'Invalid research action proposal')
        candidate = value['candidate']
        _exact(candidate, {'action', 'privacy', 'cost_units', 'input'},
               'planner candidate')
        _exact(candidate['action'], {'id', 'version'}, 'candidate action')
        require(candidate['action'] == {'id': value['target_action'], 'version': '1.0'}
                and candidate['privacy'] in PRIVACY
                and type(candidate['cost_units']) is int
                and 0 <= candidate['cost_units'] <= 1_000_000
                and isinstance(candidate['input'], dict),
                'Invalid research planner candidate')
        _canonical(candidate['input'])
        if value['decision'] == 'repeat':
            _uuid(value['repeat_step_id'], 'repeat step ID')
        else:
            require(value['repeat_step_id'] is None,
                    'Append proposal cannot repeat a step')
    _hash(value['proposal_sha256'], 'planner proposal digest')
    proposal = {key: value[key] for key in ('decision', 'reason', 'target_action',
        'candidate', 'repeat_step_id', 'finish_reason')}
    require(value['proposal_sha256'] == _digest(proposal),
            'Research planner proposal digest differs')


INPUT_VALIDATORS = {
    'source.fetch-public': _fetch_input,
    'research.verify-evidence': _verify_input,
    'research.select-relevant': _select_input,
    'research.analyze': _analysis_input,
    'research.compose-report': _compose_input,
    'research.plan-next': _planner_input,
}
OUTPUT_VALIDATORS = {
    'source.fetch-public': _fetch_output,
    'research.verify-evidence': _verify_output,
    'research.select-relevant': _select_output,
    'research.analyze': _analysis_output,
    'research.compose-report': _compose_output,
    'research.plan-next': _planner_output,
}


def validate_research_input(action_id, value):
    validator = INPUT_VALIDATORS.get(action_id)
    if validator is not None:
        validator(value)


def validate_research_output(action_id, value):
    validator = OUTPUT_VALIDATORS.get(action_id)
    if validator is not None:
        validator(value)


def parse_research_profile(data, registry):
    value = parse_json(data)
    fields = {'schema_version', 'profile_id', 'version', 'display_name', 'actions',
              'permissions', 'privacy', 'execution_boundaries', 'bindings',
              'default_budget', 'maximum_budget', 'start_action',
              'finish_reasons'}
    _exact(value, fields, 'profile')
    require(value['schema_version'] == 1
            and value['profile_id'] in {'quick-search-v1', 'read-and-verify-v1',
                                        'deep-research-v1'}
            and value['version'] == '1.0', 'Unsupported research profile')
    _text(value['display_name'], 'profile display name', 128)
    require(isinstance(value['actions'], list) and 1 <= len(value['actions']) <= 7,
            'Invalid research profile actions')
    action_keys = []
    descriptors = []
    for action in value['actions']:
        _exact(action, {'id', 'version'}, 'profile action')
        require(action['id'] in PROFILE_ACTIONS and action['version'] == '1.0',
                'Unsupported research profile action')
        key = (action['id'], action['version'])
        require(key not in action_keys, 'Duplicate research profile action')
        action_keys.append(key)
        descriptor = registry.resolve(*key)
        require(descriptor['schema_version'] == 2
                and descriptor['automatable']
                and descriptor['effect'] != 'local-content-create',
                'Research profile action is not safely automatable')
        descriptors.append(descriptor)
    action_ids = {item[0] for item in action_keys}
    require(action_ids == PROFILE_ACTION_SETS[value['profile_id']],
            'Research profile action policy differs from reviewed profile')
    _strings(value['permissions'], 'profile permission', allow_empty=True)
    require(set(value['permissions'])
            == set().union(*(set(item['permissions']) for item in descriptors)),
            'Research profile permissions differ from action requirements')
    _strings(value['privacy'], 'profile privacy')
    require(set(value['privacy']) <= PRIVACY
            and all(set(value['privacy']) <= set(item['privacy'])
                    for item in descriptors),
            'Research profile privacy exceeds an action')
    _strings(value['execution_boundaries'], 'profile execution boundary')
    require(set(value['execution_boundaries'])
            == set(item['execution_boundary'] for item in descriptors),
            'Research profile boundaries differ from action requirements')
    _exact(value['bindings'], {'search', 'reader', 'llm'}, 'profile bindings')
    require(value['bindings']['search'] == 'searxng'
            and value['bindings']['reader'] == 'static-html-v1'
            and value['bindings']['llm'] == 'ollama',
            'Unsupported research profile binding')
    _budget(value['default_budget'], 'default budget', allow_zero=False)
    _budget(value['maximum_budget'], 'maximum budget', allow_zero=False)
    require(all(value['default_budget'][key] <= value['maximum_budget'][key]
                for key in value['default_budget']),
            'Research default budget exceeds profile maximum')
    require(isinstance(value['start_action'], dict),
            'Invalid research profile start action')
    _exact(value['start_action'], {'id', 'version'}, 'profile start action')
    require((value['start_action']['id'], value['start_action']['version'])
            in action_keys, 'Research start action is outside profile')
    require(value['finish_reasons'] == ['completed', 'insufficient',
        'budget-exhausted', 'cancelled-by-user'],
        'Unsupported research finish reasons')
    for descriptor in descriptors:
        if descriptor['action_id'] == 'research.plan-next':
            continue
        require(any(item['action']['id'] == 'research.plan-next'
                    for item in descriptor['successors']),
                'Research action cannot return to planner')
    planner = registry.resolve('research.plan-next', '1.0')
    planner_targets = {item['action']['id'] for item in planner['successors']}
    require(action_ids - {'research.plan-next'} <= planner_targets,
            'Research planner cannot propose every profile action')
    return value


def load_research_profiles(registry, directory=REVIEWED_PROFILES):
    root = Path(directory)
    require(root.is_dir() and not root.is_symlink(),
            'Research profiles must be a regular directory')
    profiles = {}
    entries = sorted(root.iterdir(), key=lambda item: item.name)
    require(0 < len(entries) <= 16, 'Invalid research profile catalog')
    for path in entries:
        require(path.name.endswith('.profile.json'),
                'Unexpected research profile entry')
        require(stat.S_ISREG(path.lstat().st_mode),
                'Research profile must be a regular file')
        profile = parse_research_profile(path.read_bytes(), registry)
        key = (profile['profile_id'], profile['version'])
        require(key not in profiles, 'Duplicate research profile')
        profiles[key] = profile
    require(set(profiles) == {('quick-search-v1', '1.0'),
        ('read-and-verify-v1', '1.0'), ('deep-research-v1', '1.0')},
        'Reviewed research profile catalog is incomplete')
    return profiles
