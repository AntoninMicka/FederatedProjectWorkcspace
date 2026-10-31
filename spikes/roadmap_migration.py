# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only, commit-pinned inventory for review before roadmap migration.

Occurrence locators are evidence, never stable task IDs. Nothing in this module
writes a Workspace, chooses canonical definitions, or approves an import.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from spikes.metadata import require
from spikes.module_manifest import parse_module_manifest
from spikes.roadmap_graph import _topology
from spikes.storage import Git

SCHEMA = 'fpw-roadmap-migration-inventory-v1'
MAX_FILE = 4 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
MAX_FILES = 128
HOST_SOURCES = (
    ('Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md', 'requirements'),
    ('TODO.md', 'active'), ('BACKLOG.md', 'backlog'), ('WORK_LOG.md', 'history'),
    ('docs/roadmap-graph.json', 'graph'),
    ('docs/adr/0026-module-unified-api.md', 'support'),
    ('docs/adr/0055-project-task-plan.md', 'support'),
    ('docs/adr/0059-file-plan-hierarchy-and-task-editor.md', 'support'),
    ('docs/adr/0060-local-file-ide-bridge.md', 'support'),
)
ID = r'[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+'
HEADING = re.compile(r'^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$')
CHECKBOX = re.compile(r'^(\s*)[-+*]\s+\[([ xX])\]\s*(.*)$')
EXPLICIT_ID = re.compile(r'^(?:\*\*)?(?:\[(' + ID + r')\]|(' + ID + r'))(?=[\s:*—–]|\*\*|$)')
STATUS = re.compile(r'^\[(planned|in progress|completed|blocked)\]\s*')
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
LINK = re.compile(r'\[[^\]\n]*\]\(([^)\n]+)\)')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


class PinnedRepository:
    def __init__(self, root, repository_id, revision):
        self.git = Git(Path(root).resolve())
        require(self.git.run('rev-parse', '--show-toplevel').stdout.strip() == str(self.git.root),
                'Select a repository root, not a directory in its parent repository')
        require(isinstance(repository_id, str) and re.fullmatch(r'[a-z][a-z0-9.-]{0,127}', repository_id),
                'Invalid logical repository identity')
        require(isinstance(revision, str) and revision and not revision.startswith('-'), 'Invalid revision')
        self.repository_id = repository_id
        self.commit = self.git.run('rev-parse', '--verify', '--end-of-options', revision + '^{commit}').stdout.strip()
        self.entries = {}
        for entry in self.git.run('ls-tree', '-rz', self.commit).stdout.split('\0'):
            if entry:
                info, path = entry.split('\t', 1)
                self.entries[path] = info.split()

    def read(self, path):
        require(isinstance(path, str) and path and not path.startswith('/')
                and str(PurePosixPath(path)) == path and '..' not in PurePosixPath(path).parts,
                'Invalid source path')
        require(path in self.entries, 'Missing pinned source: ' + path)
        mode, kind, oid = self.entries[path]
        require(mode in {'100644', '100755'} and kind == 'blob', 'Non-regular pinned source: ' + path)
        size = int(self.git.run('cat-file', '-s', oid).stdout)
        require(size <= MAX_FILE, 'Pinned source exceeds inventory limit')
        return self.git.run('cat-file', 'blob', oid, binary=True).stdout


def visible_markdown_lines(raw):
    """Yield source positions and visible Markdown outside comments/fenced examples."""
    text = raw.decode('utf-8')
    fence, comment = None, False
    offset = 0
    for line_no, original in enumerate(text.splitlines(keepends=True), 1):
        start, end = offset, offset + len(original.encode('utf-8'))
        offset = end
        line = original.rstrip('\r\n')
        marker = FENCE.match(line)
        if fence is not None:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= fence[1] and not marker.group(2).strip():
                fence = None
            continue
        # Remove comment regions only for recognition; raw spans remain intact.
        visible = ''
        while line:
            if comment:
                finish = line.find('-->')
                if finish < 0:
                    break
                comment, line = False, line[finish + 3:]
            else:
                begin = line.find('<!--')
                if begin < 0:
                    visible += line
                    break
                visible += line[:begin]
                comment, line = True, line[begin + 4:]
        line = visible
        marker = FENCE.match(line)
        if marker:
            fence = (marker.group(1)[0], len(marker.group(1)))
            continue
        yield line_no, start, end, line, original
    require(fence is None and not comment, 'Unclosed fenced example or HTML comment; manual source review required')


def markdown_occurrences(raw):
    """Account for checkboxes/headings outside fenced examples and HTML comments."""
    result, headings, links = [], [], []
    for line_no, start, end, line, original in visible_markdown_lines(raw):
        for target in LINK.findall(line):
            target = target.strip('<>')
            if '://' not in target and not target.startswith('#'):
                links.append({'line': line_no, 'target': target})
        heading, checkbox = HEADING.match(line), CHECKBOX.match(line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2)
            while headings and headings[-1]['level'] >= level:
                headings.pop()
            headings.append({'level': level, 'title': title})
            active = re.fullmatch(r'TODO\s+—\s+(' + ID + r')(?:\s*[:—].*)?', title)
            match = EXPLICIT_ID.match(active.group(1) if active else title)
            if not match:
                continue
            kind, body, state, declared = 'heading', title, None, None
        elif checkbox:
            kind, body = 'checkbox', checkbox.group(3)
            normalized = body.removeprefix('**')
            status = STATUS.match(normalized)
            declared = status.group(1) if status else None
            body = normalized[status.end():] if status else normalized
            match = EXPLICIT_ID.match(body)
            state = 'checked' if checkbox.group(2).lower() == 'x' else 'unchecked'
        else:
            continue
        result.append({
            'line': line_no, 'byte_start': start, 'byte_end': end,
            'kind': kind, 'id': (match.group(1) or match.group(2)) if match else None,
            'checkbox_state': state, 'declared_status': declared,
            'section': [item['title'] for item in headings],
            'text': original.rstrip('\r\n'),
        })
    return result, links


def inventory(host_root, *, revision='HEAD', modules=()):
    """Modules are explicit (module_id, local repository root, revision) triples.

    Local paths are not copied into the report. Every source remains pinned and
    byte-addressable in its Git repository. Unkeyed requirements remain review
    candidates instead of being silently manufactured into executable tasks.
    """
    host = PinnedRepository(host_root, 'federated-workspace', revision)
    sources, occurrences, references, module_reports, issues = [], [], [], [], []
    total = 0

    def add(repo, path, role):
        nonlocal total
        raw = repo.read(path)
        total += len(raw)
        require(len(sources) < MAX_FILES and total <= MAX_TOTAL, 'Inventory exceeds bounded selection')
        source_key = repo.repository_id + ':' + path
        record = dict(repository_id=repo.repository_id, commit_id=repo.commit,
                      path=path, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw),
                      role=role, privacy='pending-review', key=source_key)
        sources.append(record)
        if path.endswith('.md'):
            items, links = markdown_occurrences(raw)
            for item in items:
                item.update(source=source_key, role=role,
                            locator=f'{source_key}:{item["line"]}')
                item['classification'] = ('historical-evidence' if role == 'history' else
                                          'supporting-document' if role == 'support' else
                                          'definition-candidate' if item['id'] else 'needs-identity-and-type-review')
                occurrences.append(item)
            references.extend(dict(source=source_key, **link) for link in links)
        return raw

    for path, role in HOST_SOURCES:
        add(host, path, role)
    graph_raw = next(item for item in sources if item['role'] == 'graph')
    graph = json.loads(host.read(graph_raw['path']))
    require(graph.get('schema') == 'fpw-roadmap-graph-v1' and isinstance(graph.get('nodes'), list),
            'Unsupported source dependency graph')
    registrations = {}
    for path in sorted(host.entries):
        if path.startswith('modules/') and path.endswith('.module.json'):
            declaration = parse_module_manifest(add(host, path, 'module-registration'))
            module_id = declaration['module_id']
            require(module_id not in registrations, 'Duplicate module registration')
            registrations[module_id] = declaration
    selected = {}
    for module_id, root, module_revision in modules:
        require(module_id in registrations and module_id not in selected, 'Unknown or duplicate selected module')
        repo = PinnedRepository(root, module_id, module_revision)
        declaration = parse_module_manifest(add(repo, 'module.json', 'module-manifest'))
        require(declaration['module_id'] == module_id, 'Selected module identity differs')
        require(declaration == registrations[module_id], 'Pinned module declaration differs from host registration')
        add(repo, declaration['roadmap'], 'requirements')
        if 'TODO.md' in repo.entries:
            add(repo, 'TODO.md', 'active')
        for path, role in (('BACKLOG.md', 'backlog'), ('WORK_LOG.md', 'history')):
            if path in repo.entries:
                add(repo, path, role)
        selected[module_id] = repo.commit
    for module_id in sorted(registrations):
        included = module_id in selected
        module_reports.append(dict(module_id=module_id, included=included,
                                   commit_id=selected.get(module_id), target='linked-project-proposed'))
        if not included:
            issues.append({'kind': 'unselected-module', 'module_id': module_id})

    groups = defaultdict(list)
    anonymous = []
    for item in occurrences:
        # Supporting ADR examples/IDs are not canonical plan definitions.
        if item['role'] == 'support':
            continue
        if item['id']:
            repository_id = item['source'].split(':', 1)[0]
            groups[(repository_id, item['id'])].append(item)
        elif item['kind'] == 'checkbox':
            anonymous.append(item['locator'])
    definitions = []
    for (repository_id, stable_id), items in sorted(groups.items()):
        states = sorted({item['checkbox_state'] for item in items if item['checkbox_state']})
        # This is a review proposal, not automatic conflict resolution. Keep all
        # occurrences, including history, even when a live definition exists.
        priority = {'active': 0, 'backlog': 1, 'history': 2, 'requirements': 3}
        candidate = min(items, key=lambda item: (priority[item['role']],
                                               item['kind'] != 'heading', item['line']))
        definitions.append(dict(repository_id=repository_id, id=stable_id,
                                occurrences=[item['locator'] for item in items],
                                checkbox_states=states, needs_reconciliation=len(items) > 1,
                                proposed_definition=candidate['locator'], mapping_approved=False,
                                proposed_role=('historical-evidence' if candidate['role'] == 'history'
                                               else 'requirement' if candidate['role'] == 'requirements'
                                               else 'plan-node-type-needs-review')))
        if len(states) > 1:
            issues.append(dict(kind='different-source-states', repository_id=repository_id,
                               id=stable_id, occurrences=[item['locator'] for item in items]))
    host_ids = {key[1] for key in groups if key[0] == host.repository_id}
    nodes = graph['nodes']
    require(all(isinstance(node, dict) and isinstance(node.get('id'), str)
                and re.fullmatch(ID, node['id'])
                and isinstance(node.get('depends_on'), list)
                and all(isinstance(parent, str) and re.fullmatch(ID, parent)
                        for parent in node['depends_on']) for node in nodes), 'Invalid graph nodes')
    node_ids = {node['id'] for node in nodes}
    require(len(node_ids) == len(nodes), 'Duplicate dependency hint ID')
    require(all(len(node['depends_on']) == len(set(node['depends_on']))
                and set(node['depends_on']) <= node_ids and node['id'] not in node['depends_on']
                for node in nodes), 'Unknown, repeated or self dependency hint')
    _topology({node['id']: node for node in nodes})
    for node in nodes:
        if node['id'] not in host_ids:
            issues.append({'kind': 'graph-id-without-definition', 'id': node['id']})
    anonymous_mapping = []
    counters = Counter()
    used = set(groups)
    for item in occurrences:
        if item['locator'] not in anonymous:
            continue
        repository_id = item['source'].split(':', 1)[0]
        proposed_id = None
        if item['role'] != 'history':
            while True:
                counters[repository_id] += 1
                proposed_id = f'MIG-REQ-{counters[repository_id]:04d}'
                if (repository_id, proposed_id) not in used:
                    break
            used.add((repository_id, proposed_id))
        anonymous_mapping.append(dict(locator=item['locator'], repository_id=repository_id,
                                      proposed_id=proposed_id, mapping_approved=False,
                                      proposed_role=('historical-evidence' if item['role'] == 'history'
                                                     else 'strategic-requirement' if item['role'] == 'backlog'
                                                     else 'requirement')))
    role_counts = Counter(item['role'] for item in sources)
    summary = dict(source_files=len(sources), source_bytes=total,
                   checkbox_occurrences=sum(item['kind'] == 'checkbox' for item in occurrences),
                   scoped_explicit_ids=len(groups), anonymous_checkboxes=len(anonymous),
                   repeated_ids=sum(len(items) > 1 for items in groups.values()),
                   different_state_ids=sum(item['kind'] == 'different-source-states' for item in issues),
                   source_roles=dict(sorted(role_counts.items())))
    value = dict(schema=SCHEMA, stage='inventory-only', import_ready=False,
                 approval='pending-review', sources=sources, modules=module_reports,
                 occurrences=occurrences, definitions=definitions,
                 anonymous_checkboxes=anonymous, anonymous_mapping_proposals=anonymous_mapping,
                 dependency_hints=nodes,
                 referenced_documents=references, issues=issues, summary=summary,
                 limitations=['Locators are source evidence, not stable task IDs.',
                              'No canonical definition, hierarchy or target mutation is approved.',
                              'Anonymous items require persistent reviewed identity mapping.',
                              'MIG-REQ IDs are initial review proposals, not rename-safe persisted identities.',
                              'Only explicitly selected files are inventoried; links are not followed.'])
    value['inventory_sha256'] = hashlib.sha256(canonical(value)).hexdigest()
    return value


def render_summary(value):
    summary = value['summary']
    lines = ['# Roadmap migration inventory', '',
             'Stage: inventory-only; import_ready: false; approval: pending-review.', '',
             'This is source coverage evidence, not a new authoritative roadmap.', '',
             '| Metric | Count |', '| --- | ---: |']
    for key in ('source_files', 'source_bytes', 'checkbox_occurrences', 'scoped_explicit_ids',
                'anonymous_checkboxes', 'repeated_ids', 'different_state_ids'):
        lines.append(f'| {key} | {summary[key]} |')
    lines += ['', '## Explicitly selected modules', '']
    for module in value['modules']:
        lines.append(f'- {module["module_id"]}: included={module["included"]}; {module["target"]}.')
    lines += ['', '## Source coverage', '', '| Repository | Source | Checkboxes | Without ID |',
              '| --- | --- | ---: | ---: |']
    for source in value['sources']:
        items = [item for item in value['occurrences']
                 if item['source'] == source['key'] and item['kind'] == 'checkbox']
        lines.append(f'| {source["repository_id"]} | {source["path"]} | {len(items)} | '
                     f'{sum(item["id"] is None for item in items)} |')
    lines += ['', '## Repeated IDs to reconcile', '']
    for group in value['definitions']:
        if group['needs_reconciliation']:
            lines.append(f'- {group["id"]}: {len(group["occurrences"])} occurrences; '
                         f'proposed definition `{group["proposed_definition"]}` (not approved).')
    lines += ['', '## Review required', '',
              '- Assign persistent identities and types to anonymous items.',
              '  Anonymous mapping proposals are requirements or historical evidence, not executable tasks.',
              '  Freeze approved identities before applying; do not regenerate them after renaming sources.',
              '- Reconcile repeated IDs using context and evidence, not checkbox majority.',
              '- Confirm module targets and treatment of the existing target plan.',
              '- Review referenced documents before expanding the explicit selection.', '',
              'Detailed occurrences, byte offsets, source hashes and issues are in inventory.json.', '']
    return '\n'.join(lines)
