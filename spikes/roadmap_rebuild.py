# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Source-first local-LLM roadmap reconstruction without Workspace writes."""
from base64 import b64encode
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import NAMESPACE_URL, uuid4, uuid5

from spikes.backend_contract import ROLES
from spikes.context_builder import DispatchHandoff
from spikes.metadata import pairs, require
from spikes.ollama_backend import OllamaAdapter, OllamaBindings, OllamaRuns
from spikes.roadmap_migration import (HEADING, PinnedRepository, canonical,
                                      inventory)

SCHEMA = 'fpw-roadmap-source-rebuild-v1'
CATALOG_SCHEMA = 'fpw-roadmap-source-catalog-v1'
EXTRACTION_SCHEMA = 'fpw-roadmap-source-extraction-v1'
AUDIT_SCHEMA = 'fpw-roadmap-source-audit-v1'
REVISION = 'source-first-v1'
MAX_BLOCK = 96 * 1024
KINDS = {'milestone', 'batch', 'task', 'checklist', 'history', 'description'}
STATUSES = {'planned', 'in-progress', 'completed', 'blocked', 'unknown'}
VERDICTS = {'correct', 'equivalent', 'misplaced', 'distorted', 'missing',
            'duplicated', 'unsupported-target', 'ambiguous'}
STABLE_ID = re.compile(r'[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+')

SOURCE_POLICY = '''The source documents are sequential project records, not a normalized database.
TODO contains one current feature batch. A closed whole batch, including completed subtasks and evidence, moves to WORK_LOG. BACKLOG contains future batches and deferred or implemented-but-unverified work. The Master Checklist is a strategic catalog and may describe the same capability at a broader granularity. A later occurrence wins only when it contains actual evidence. History is not a new open task; free prose is not automatically executable work. Preserve uncertainty instead of inventing hierarchy, completion, IDs, or dependencies.'''

EXTRACTION_INSTRUCTION = SOURCE_POLICY + '''
Extract the supplied complete logical source block without using any existing imported target.
Return exactly one JSON object:
{"schema":"fpw-roadmap-source-extraction-v1","block_id":"exact block ID","entities":[{"kind":"milestone|batch|task|checklist|history|description","stable_id":"explicit source ID or null","title":"text","status":"planned|in-progress|completed|blocked|unknown","parent_id":"explicit source parent ID or null","depends_on":["explicit source ID"],"line_start":1,"line_end":1,"summary":"Czech meaning preserved from source"}],"ambiguities":[{"line_start":1,"line_end":1,"reason":"Czech explanation"}],"summary":"Czech block summary"}.
Line numbers are absolute original-document numbers from block.line_start through block.line_end, not block-relative numbers. Copy only IDs explicitly present in the block or its heading path. Use null when the source has no stable ID. Do not invent a parent, dependency, completion, implementation evidence, or new ID. Preserve descriptions and history as non-executable entities. Return JSON only.'''

AUDIT_INSTRUCTION = SOURCE_POLICY + '''
Audit whether the candidate records faithfully represent the supplied original source block. Source evidence has priority; do not merely judge whether the candidate sounds reasonable.
Return exactly one JSON object:
{"schema":"fpw-roadmap-source-audit-v1","block_id":"exact block ID","verdict":"correct|equivalent|misplaced|distorted|missing|duplicated|unsupported-target|ambiguous","scores":{"coverage":0,"hierarchy":0,"status":0,"provenance":0,"dependencies":0},"findings":[{"line_start":1,"line_end":1,"candidate_id":"ID or null","kind":"missing|misplaced|distorted|duplicated|unsupported-target|ambiguous","reason":"Czech evidence-based explanation"}],"summary":"Czech audit summary"}.
Every score is an integer 0..100 and must be justified by the findings and absolute original-document line numbers from source_block.line_start through source_block.line_end. A different representation can be equivalent, but missing or changed meaning must not be excused. Return JSON only.'''


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _atomic_json(path, value):
    path = Path(path); temporary = path.with_name('.' + path.name + '.' + str(uuid4()) + '.tmp')
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b'\n'
    try:
        with open(temporary, 'xb') as stream:
            os.chmod(temporary, 0o600); stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _secure_directory(path, *, create=False):
    path = Path(path).absolute()
    if create:
        path.mkdir(mode=0o700)
    info = path.lstat()
    require(path == path.resolve() and stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            'Rebuild run directory requires owned mode 0700')
    return path


def _sections(raw):
    """Split on H2 logical units; oversized units recursively split on H3+ headings."""
    text = raw.decode('utf-8'); lines = text.splitlines(keepends=True)
    offsets, total = [], 0
    for line in lines:
        offsets.append(total); total += len(line.encode())
    headings = []
    for index, line in enumerate(lines):
        match = HEADING.match(line.rstrip('\r\n'))
        if match:
            headings.append((index, len(match.group(1)), match.group(2)))
    starts = [item for item in headings if item[1] == 2]
    if not starts:
        starts = [(0, 1, headings[0][2] if headings else 'Dokument')]
    elif starts[0][0] > 0:
        starts.insert(0, (0, 1, headings[0][2] if headings else 'Úvod'))

    def emit(start, end, title, level):
        begin = offsets[start]; finish = offsets[end] if end < len(lines) else len(raw)
        if finish - begin <= MAX_BLOCK:
            return [(start, end, title)]
        children = [item for item in headings if start < item[0] < end and item[1] == level + 1]
        if not children:
            raise ValueError('Logical source block exceeds local-LLM context limit: ' + title)
        boundaries = [(start, level, title)] + children
        result = []
        for index, child in enumerate(boundaries):
            child_end = boundaries[index + 1][0] if index + 1 < len(boundaries) else end
            result.extend(emit(child[0], child_end, child[2], child[1]))
        return result

    result = []
    for index, item in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
        result.extend(emit(item[0], end, item[2], item[1]))
    return [(start + 1, end, title, ''.join(lines[start:end])) for start, end, title in result]


def source_catalog(host_root, *, revision='HEAD', modules=()):
    selected = tuple(modules)
    base = inventory(host_root, revision=revision, modules=selected)
    repositories = {'federated-workspace': PinnedRepository(host_root, 'federated-workspace', revision)}
    for module_id, root, module_revision in selected:
        repositories[module_id] = PinnedRepository(root, module_id, module_revision)
    sources, blocks = [], []
    for source in base['sources']:
        if source['role'] not in {'requirements', 'active', 'backlog', 'history'} \
                or not source['path'].endswith('.md'):
            continue
        raw = repositories[source['repository_id']].read(source['path'])
        source_row = dict(source)
        source_row['sequence_policy'] = source['role']
        sources.append(source_row)
        sections = _sections(raw)
        for index, (line_start, line_end, title, body) in enumerate(sections):
            digest = hashlib.sha256((source['key'] + '\0' + str(line_start) + '\0' + body).encode()).hexdigest()
            block_id = str(uuid5(NAMESPACE_URL, 'roadmap-source-block:' + digest))
            blocks.append(dict(block_id=block_id, source=source['key'], role=source['role'],
                               order=index, title=title, line_start=line_start,
                               line_end=line_end, sha256=hashlib.sha256(body.encode()).hexdigest(),
                               text=body))
    by_source = {}
    for block in blocks:
        by_source.setdefault(block['source'], []).append(block)
    for rows in by_source.values():
        for index, block in enumerate(rows):
            block['previous'] = rows[index - 1]['block_id'] if index else None
            block['next'] = rows[index + 1]['block_id'] if index + 1 < len(rows) else None
    value = dict(schema=CATALOG_SCHEMA, revision=REVISION,
                 inventory_sha256=base['inventory_sha256'], sources=sources, blocks=blocks,
                 summary=dict(source_files=len(sources), blocks=len(blocks),
                              source_bytes=sum(item['size'] for item in sources)))
    value['catalog_sha256'] = hashlib.sha256(canonical(value)).hexdigest()
    return value


def _strict_json(raw, schema, fields):
    require(isinstance(raw, str) and len(raw.encode()) <= 256 * 1024,
            'Local-LLM response is invalid or oversized')
    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, RecursionError) as exc:
        raise ValueError('Local-LLM response is not strict JSON') from exc
    require(isinstance(value, dict) and set(value) == fields and value['schema'] == schema,
            'Local-LLM response fields differ')
    return value


def validate_extraction(raw, block):
    value = _strict_json(raw, EXTRACTION_SCHEMA,
        {'schema', 'block_id', 'entities', 'ambiguities', 'summary'})
    require(value['block_id'] == block['block_id'] and isinstance(value['summary'], str)
            and isinstance(value['entities'], list) and len(value['entities']) <= 512
            and isinstance(value['ambiguities'], list) and len(value['ambiguities']) <= 128,
            'Invalid source extraction identity')
    for entity in value['entities']:
        require(isinstance(entity, dict) and set(entity) == {'kind', 'stable_id', 'title',
                'status', 'parent_id', 'depends_on', 'line_start', 'line_end', 'summary'},
                'Invalid extracted entity fields')
        require(entity['kind'] in KINDS and entity['status'] in STATUSES
                and isinstance(entity['title'], str) and bool(entity['title'].strip())
                and isinstance(entity['summary'], str) and isinstance(entity['depends_on'], list)
                and all(isinstance(item, str) and STABLE_ID.fullmatch(item)
                        for item in entity['depends_on'])
                and (entity['stable_id'] is None or STABLE_ID.fullmatch(entity['stable_id'])),
                'Invalid extracted entity')
        require(entity['parent_id'] is None or STABLE_ID.fullmatch(entity['parent_id']),
                'Invalid extracted parent')
        require(type(entity['line_start']) is int and type(entity['line_end']) is int
                and block['line_start'] <= entity['line_start'] <= entity['line_end'] <= block['line_end'],
                'Extracted entity cites lines outside source block')
        source_ids = set(STABLE_ID.findall(block['text']))
        require(entity['stable_id'] is None or entity['stable_id'] in source_ids,
                'Extracted ID is absent from source block')
        require(entity['parent_id'] is None or entity['parent_id'] in source_ids,
                'Extracted parent is absent from source block')
        require(set(entity['depends_on']) <= source_ids,
                'Extracted dependency is absent from source block')
    for item in value['ambiguities']:
        require(isinstance(item, dict) and set(item) == {'line_start', 'line_end', 'reason'}
                and type(item['line_start']) is int and type(item['line_end']) is int
                and block['line_start'] <= item['line_start'] <= item['line_end'] <= block['line_end']
                and isinstance(item['reason'], str) and bool(item['reason'].strip()),
                'Invalid extraction ambiguity')
    return value


def validate_audit(raw, block):
    value = _strict_json(raw, AUDIT_SCHEMA,
        {'schema', 'block_id', 'verdict', 'scores', 'findings', 'summary'})
    require(value['block_id'] == block['block_id'] and value['verdict'] in VERDICTS
            and isinstance(value['summary'], str) and isinstance(value['findings'], list),
            'Invalid source audit identity')
    require(isinstance(value['scores'], dict) and set(value['scores']) == {
        'coverage', 'hierarchy', 'status', 'provenance', 'dependencies'}
        and all(type(score) is int and 0 <= score <= 100 for score in value['scores'].values()),
        'Invalid audit scores')
    for item in value['findings']:
        require(isinstance(item, dict) and set(item) == {'line_start', 'line_end',
                'candidate_id', 'kind', 'reason'} and item['kind'] in VERDICTS - {'correct', 'equivalent'}
                and (item['candidate_id'] is None or isinstance(item['candidate_id'], str))
                and type(item['line_start']) is int and type(item['line_end']) is int
                and block['line_start'] <= item['line_start'] <= item['line_end'] <= block['line_end']
                and isinstance(item['reason'], str) and bool(item['reason'].strip()),
                'Invalid audit finding')
    return value


def build_candidate(catalog, extractions):
    nodes, support, conflicts, used = {}, [], [], set()
    block_by_id = {item['block_id']: item for item in catalog['blocks']}
    for extraction in extractions:
        block = block_by_id[extraction['block_id']]
        for index, entity in enumerate(extraction['entities']):
            row = dict(entity)
            if entity['stable_id'] is None:
                digest = hashlib.sha256((block['block_id'] + ':' + str(index)).encode()).hexdigest()[:12].upper()
                row['candidate_id'] = ('MIG-' + entity['kind'].upper() + '-' + digest
                                       if entity['kind'] in {'milestone', 'batch', 'task'} else None)
            else:
                row['candidate_id'] = entity['stable_id']
            row['provenance'] = dict(block_id=block['block_id'], source=block['source'],
                                     line_start=entity['line_start'], line_end=entity['line_end'])
            if entity['kind'] not in {'milestone', 'batch', 'task'}:
                support.append(row); continue
            node_id = row['candidate_id']
            if node_id in used:
                existing = nodes[node_id]
                comparable = ('kind', 'title', 'status', 'parent_id', 'depends_on', 'summary')
                if all(existing[key] == row[key] for key in comparable):
                    existing['provenance_all'].append(row['provenance'])
                else:
                    conflicts.append({'kind': 'conflicting-id', 'id': node_id,
                                      'first': existing['provenance'],
                                      'other': row['provenance']})
                continue
            row['provenance_all'] = [row['provenance']]
            used.add(node_id); nodes[node_id] = row
    issues = list(conflicts)
    allowed = {'milestone': {None}, 'batch': {'milestone'}, 'task': {'batch'}}
    for node_id, node in nodes.items():
        parent = nodes.get(node['parent_id']) if node['parent_id'] else None
        parent_kind = parent['kind'] if parent else None
        if parent_kind not in allowed[node['kind']]:
            issues.append({'kind': 'invalid-parent', 'id': node_id,
                           'parent_id': node['parent_id']})
        for dependency in node['depends_on']:
            if dependency not in nodes or dependency == node_id:
                issues.append({'kind': 'invalid-dependency', 'id': node_id,
                               'dependency': dependency})
    ordered = sorted(nodes.values(), key=lambda item: (
        item['provenance']['source'], item['provenance']['line_start'], item['candidate_id']))
    candidate = dict(schema='fpw-roadmap-rebuild-candidate-v1', nodes=ordered,
                     supporting_records=support, issues=issues,
                     ready=not issues and bool(ordered))
    candidate['candidate_sha256'] = hashlib.sha256(canonical(candidate)).hexdigest()
    return candidate


def render_candidate(candidate):
    lines = ['# Source-first roadmap candidate', '',
             f'Ready: {str(candidate["ready"]).lower()}', '']
    children = {}
    for node in candidate['nodes']:
        children.setdefault(node['parent_id'], []).append(node)
    def add(parent, indent=0):
        for node in children.get(parent, []):
            checked = 'x' if node['status'] == 'completed' else ' '
            lines.append(' ' * indent + f'- [{checked}] [{node["candidate_id"]}] {node["title"]}')
            lines.append(' ' * (indent + 2) + '- type: ' + node['kind'])
            if node['depends_on']:
                lines.append(' ' * (indent + 2) + '- depends_on: ' + ', '.join(node['depends_on']))
            add(node['candidate_id'], indent + 2)
    add(None)
    lines += ['', '## Nezařazené popisy a historie', '']
    for item in candidate['supporting_records']:
        lines += [f'- **{item["kind"]}: {item["title"]}**',
                  f'  - {item["summary"]}',
                  f'  - source: {item["provenance"]["source"]}:{item["line_start"]}', '']
    if candidate['issues']:
        lines += ['## Blokátory kandidáta', '', '```json',
                  json.dumps(candidate['issues'], ensure_ascii=False, indent=2), '```', '']
    return '\n'.join(lines)


class RoadmapRebuild:
    def __init__(self, node, run_dir, *, adapter_factory=None):
        self.node = Path(node).absolute(); self.root = Path(run_dir).absolute()
        self.adapter_factory = adapter_factory

    @classmethod
    def prepare(cls, node, run_dir, host_root, *, revision='HEAD', modules=()):
        root = Path(run_dir).absolute()
        require(not root.exists(), 'Rebuild run directory already exists')
        catalog = source_catalog(host_root, revision=revision, modules=modules)
        binding = OllamaBindings(Path(node).absolute().parent / ('.' + Path(node).name + '.chat')).load()
        require(binding.boundary == 'same-node', 'Source rebuild requires same-node Ollama')
        manifest = dict(schema=SCHEMA, revision=REVISION, created_at=_now(),
                        catalog_sha256=catalog['catalog_sha256'],
                        binding=dict(adapter='ollama', binding_id=binding.binding_id,
                                     revision=binding.revision, boundary=binding.boundary,
                                     target_id=binding.target_id, model=binding.model),
                        prompts=dict(extraction_sha256=hashlib.sha256(EXTRACTION_INSTRUCTION.encode()).hexdigest(),
                                     audit_sha256=hashlib.sha256(AUDIT_INSTRUCTION.encode()).hexdigest()),
                        state='prepared')
        root = _secure_directory(root, create=True)
        _atomic_json(root/'catalog.json', catalog); _atomic_json(root/'manifest.json', manifest)
        (root/'results').mkdir(mode=0o700); (root/'raw').mkdir(mode=0o700)
        (root/'ollama-runs').mkdir(mode=0o700)
        return cls(node, root)

    def _load(self, name):
        _secure_directory(self.root)
        return json.loads((self.root/name).read_text(encoding='utf-8'))

    def _binding(self):
        binding = OllamaBindings(self.node.parent / ('.' + self.node.name + '.chat')).load()
        manifest = self._load('manifest.json')['binding']
        require(dict(adapter='ollama', binding_id=binding.binding_id, revision=binding.revision,
                     boundary=binding.boundary, target_id=binding.target_id,
                     model=binding.model) == manifest, 'Local-LLM binding changed after prepare')
        return binding

    def _dispatch(self, stage, item_id, instruction, value):
        binding = self._binding(); target = binding.target()
        payload = canonical({'inputs': [{'input_id': item_id,
                                         'content_b64': b64encode(canonical(value)).decode()}],
                             'task': {'role_id': 'extractor', 'role_revision': 'extractor-v1',
                                      'instruction': instruction, 'focus_input_id': item_id}})
        run_id = str(uuid5(NAMESPACE_URL, f'roadmap-rebuild:{self._load("manifest.json")["catalog_sha256"]}:{stage}:{item_id}'))
        manifest_id = str(uuid5(NAMESPACE_URL, 'roadmap-rebuild-manifest:' + run_id))
        digest = hashlib.sha256(canonical({'stage': stage, 'item_id': item_id,
                                           'binding': self._load('manifest.json')['binding'],
                                           'payload_sha256': hashlib.sha256(payload).hexdigest()})).hexdigest()
        handoff = DispatchHandoff(run_id, manifest_id, digest, target, payload)
        runs = OllamaRuns(self.root/'ollama-runs')
        adapter = self.adapter_factory(runs) if self.adapter_factory else OllamaAdapter(runs)
        role = ROLES.resolve('extractor', 'extractor-v1')
        adapter.prepare(handoff, binding, role, 'json')
        return adapter.dispatch(handoff, binding, role, 'json')['response']

    def run(self, *, limit=1):
        require(type(limit) is int and 1 <= limit <= 100000, 'Run limit must be 1..100000')
        manifest = self._load('manifest.json')
        require(manifest['prompts'] == {
            'extraction_sha256': hashlib.sha256(EXTRACTION_INSTRUCTION.encode()).hexdigest(),
            'audit_sha256': hashlib.sha256(AUDIT_INSTRUCTION.encode()).hexdigest()},
            'Rebuild prompt changed after prepare; create a new run')
        catalog = self._load('catalog.json')
        frozen = dict(catalog); catalog_sha256 = frozen.pop('catalog_sha256')
        require(hashlib.sha256(canonical(frozen)).hexdigest() == catalog_sha256
                and manifest['catalog_sha256'] == catalog_sha256,
                'Rebuild source catalog changed after prepare')
        calls = 0
        if self.adapter_factory is None:
            binding = self._binding()
            availability = OllamaAdapter.probe(binding)
            require(availability['model_available'],
                    'Pinned local-LLM model is unavailable: ' + binding.model)
        extractions = []
        for block in catalog['blocks']:
            path = self.root/'results'/('extract-' + block['block_id'] + '.json')
            failure = self.root/'results'/('extract-' + block['block_id'] + '.failed.json')
            if path.exists():
                value = validate_extraction(path.read_text(encoding='utf-8'), block)
            elif failure.exists():
                continue
            else:
                if calls >= limit:
                    continue
                focused = dict(schema='fpw-roadmap-source-block-v1', policy=SOURCE_POLICY,
                               block=block,
                               previous_title=next((item['title'] for item in catalog['blocks']
                                   if item['block_id'] == block['previous']), None),
                               next_title=next((item['title'] for item in catalog['blocks']
                                   if item['block_id'] == block['next']), None))
                raw = None
                try:
                    raw = self._dispatch('extract', block['block_id'], EXTRACTION_INSTRUCTION, focused)
                    (self.root/'raw'/('extract-' + block['block_id'] + '.json')).write_text(raw, encoding='utf-8')
                    value = validate_extraction(raw, block); _atomic_json(path, value)
                except Exception as exc:
                    _atomic_json(failure, {'stage': 'extract', 'block_id': block['block_id'],
                                           'error': str(exc), 'failed_at': _now()})
                    calls += 1; continue
                calls += 1
            extractions.append(value)
        if len(extractions) != len(catalog['blocks']):
            return self.status() | {'processed': calls}
        candidate = build_candidate(catalog, extractions)
        _atomic_json(self.root/'candidate.json', candidate)
        (self.root/'candidate.md').write_text(render_candidate(candidate), encoding='utf-8')
        audits = []
        for block in catalog['blocks']:
            path = self.root/'results'/('audit-' + block['block_id'] + '.json')
            failure = self.root/'results'/('audit-' + block['block_id'] + '.failed.json')
            if path.exists():
                value = validate_audit(path.read_text(encoding='utf-8'), block)
            elif failure.exists():
                continue
            else:
                if calls >= limit:
                    continue
                records = [item for item in candidate['nodes'] + candidate['supporting_records']
                           if item['provenance']['block_id'] == block['block_id']]
                raw = None
                try:
                    raw = self._dispatch('audit', block['block_id'], AUDIT_INSTRUCTION,
                                         {'source_block': block, 'candidate_records': records})
                    (self.root/'raw'/('audit-' + block['block_id'] + '.json')).write_text(raw, encoding='utf-8')
                    value = validate_audit(raw, block); _atomic_json(path, value)
                except Exception as exc:
                    _atomic_json(failure, {'stage': 'audit', 'block_id': block['block_id'],
                                           'error': str(exc), 'failed_at': _now()})
                    calls += 1; continue
                calls += 1
            audits.append(value)
        if len(audits) == len(catalog['blocks']):
            dimensions = {key: round(sum(item['scores'][key] for item in audits) / len(audits), 2)
                          for key in ('coverage', 'hierarchy', 'status', 'provenance', 'dependencies')}
            report = dict(schema='fpw-roadmap-rebuild-report-v1', catalog_sha256=catalog['catalog_sha256'],
                          candidate_sha256=candidate['candidate_sha256'], blocks=len(audits),
                          verdicts=dict(Counter(item['verdict'] for item in audits)),
                          scores=dimensions, fidelity=round(sum(dimensions.values()) / len(dimensions), 2),
                          candidate_ready=candidate['ready'], candidate_issues=candidate['issues'],
                          import_ready=candidate['ready'] and all(item['verdict'] in {'correct', 'equivalent'}
                                                                 for item in audits))
            _atomic_json(self.root/'report.json', report)
            lines = ['# Source-first roadmap rebuild report', '',
                     f'- blocks: {report["blocks"]}',
                     f'- candidate_ready: {str(report["candidate_ready"]).lower()}',
                     f'- import_ready: {str(report["import_ready"]).lower()}',
                     f'- fidelity: {report["fidelity"]} %', '',
                     '## Fidelity dimensions', '']
            lines += [f'- {key}: {value} %' for key, value in report['scores'].items()]
            lines += ['', '## Verdicts', '']
            lines += [f'- {key}: {value}' for key, value in sorted(report['verdicts'].items())]
            lines += ['', '## Candidate blockers', '', '```json',
                      json.dumps(report['candidate_issues'], ensure_ascii=False, indent=2), '```', '']
            (self.root/'report.md').write_text('\n'.join(lines), encoding='utf-8')
        return self.status() | {'processed': calls}

    def status(self):
        catalog = self._load('catalog.json'); result_dir = self.root/'results'
        extracted = sum((result_dir/('extract-' + item['block_id'] + '.json')).exists()
                        for item in catalog['blocks'])
        audited = sum((result_dir/('audit-' + item['block_id'] + '.json')).exists()
                      for item in catalog['blocks'])
        failed_extractions = sum((result_dir/('extract-' + item['block_id'] + '.failed.json')).exists()
                                 for item in catalog['blocks'])
        failed_audits = sum((result_dir/('audit-' + item['block_id'] + '.failed.json')).exists()
                            for item in catalog['blocks'])
        report = self._load('report.json') if (self.root/'report.json').exists() else None
        return dict(run_dir=str(self.root), blocks=len(catalog['blocks']), extracted=extracted,
                    failed_extractions=failed_extractions, audited=audited,
                    failed_audits=failed_audits, candidate=(self.root/'candidate.json').exists(),
                    complete=report is not None, report=report)
