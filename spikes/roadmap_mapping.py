# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Conservative, read-only hierarchy preview over pinned inventory evidence.

Historical feature batches and the active feature can be projected. Broad
backlog requirements remain a catalogue until explicitly designed as batches.
"""
from collections import Counter
from copy import deepcopy
import difflib
import hashlib
import json
import re
from uuid import NAMESPACE_URL, uuid5

from spikes.markdown_documents import document, main_todo_id
from spikes.metadata import require, validate_snapshot
from spikes.projects import Projects
from spikes.roadmap_graph import _catalog
from spikes.roadmap_migration import ID, PinnedRepository, canonical, markdown_occurrences
from spikes.task_graph import project_task_graph

SCHEMA = 'fpw-roadmap-migration-mapping-v1'


def load_sources(value, roots):
    expected = value.get('inventory_sha256')
    content = {key: item for key, item in value.items() if key != 'inventory_sha256'}
    require(expected == hashlib.sha256(canonical(content)).hexdigest(), 'Inventory digest differs')
    require(value.get('schema') == 'fpw-roadmap-migration-inventory-v1', 'Unsupported inventory')
    repositories, raw_sources = {}, {}
    for source in value['sources']:
        key = (source['repository_id'], source['commit_id'])
        require(source['repository_id'] in roots, 'Missing explicit repository root')
        if key not in repositories:
            repositories[key] = PinnedRepository(roots[key[0]], *key)
        raw = repositories[key].read(source['path'])
        require(len(raw) == source['size'] and hashlib.sha256(raw).hexdigest() == source['sha256'],
                'Pinned source hash differs')
        raw_sources[source['key']] = raw
    return raw_sources


def source_block(raw, occurrence):
    """Preserve the complete bounded entry; original full source is also retained."""
    lines = raw.decode('utf-8').splitlines(keepends=True)
    start = occurrence['line'] - 1
    require(0 <= start < len(lines) and lines[start].rstrip('\r\n') == occurrence['text'],
            'Occurrence differs from pinned source')
    first = lines[start]
    indent = len(first[:len(first) - len(first.lstrip())].expandtabs(4))
    heading = re.match(r'^ {0,3}(#{1,6})\s', first)
    end = start + 1
    fence, comment = None, False
    while end < len(lines):
        line = lines[end]
        if fence is None:
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
        marker = re.match(r'^\s*(`{3,}|~{3,})(.*)', line)
        if marker:
            token, tail = marker.groups()
            if fence is None:
                fence = (token[0], len(token))
            elif token[0] == fence[0] and len(token) >= fence[1] and not tail.strip():
                fence = None
        if fence is None and not marker:
            next_heading = re.match(r'^ {0,3}(#{1,6})\s', line)
            next_box = re.match(r'^(\s*)[-+*]\s+\[[ xX]\]', line)
            if next_heading and (not heading or len(next_heading[1]) <= len(heading[1])):
                break
            if not heading and next_box and len(next_box[1].expandtabs(4)) <= indent:
                break
        end += 1
    return ''.join(lines[start:end])


def node_title(occurrence, block):
    body = re.sub(r'^\s*(?:#{1,6}\s+|[-+*]\s+\[[ xX]\]\s*)', '', block)
    body = re.sub(r'^\[(?:planned|in progress|completed|blocked)\]\s*', '', body)
    bold = re.match(r'^\*\*(.*?)\*\*', body, flags=re.DOTALL)
    label = ' '.join(bold[1].split()) if bold else body.splitlines()[0].replace('**', '')
    label = re.sub(r'^\[(?:planned|in progress|completed|blocked)\]\s*', '', label)
    label = re.sub(r'^\[?' + re.escape(occurrence['id']) + r'\]?\s*', '', label)
    maturity_only = re.fullmatch(r'\((?:designed|implemented|PoC validated|production-ready)\)', label)
    excerpt = False
    if bold and (not label or maturity_only):
        # Legacy module entries label only ID/maturity; use the first original
        # prose line as an explicitly marked excerpt and retain the full block.
        label = body[bold.end():].splitlines()[0]
        excerpt = True
    return label.strip('* —:') or occurrence['id'], excerpt


def task_checklist(block):
    items, _ = markdown_occurrences(block.encode())
    require(not any(item['id'] for item in items[1:]),
            'Nested stable ID needs task hierarchy review')
    return [dict(checked=item['checkbox_state'] == 'checked',
                 text=re.sub(r'^\s*[-+*]\s+\[[ xX]\]\s*', '', item['text']),
                 relative_line=item['line'])
            for item in items[1:] if item['kind'] == 'checkbox']


def _preview_graph(repository_id, body, *, project_id=None):
    # Validate only the task bundle layer. Metadata, actual target project ID,
    # permissions and live expected HEAD are intentionally not fabricated here.
    project_id = project_id or str(uuid5(NAMESPACE_URL, 'migration-preview:' + repository_id))
    todo_id = main_todo_id(project_id)
    prefix = 'artifacts/' + todo_id + '/'
    entities = {todo_id: dict(id=todo_id, kind='document', title='Migration preview',
                              file='content.md', tags=[])}
    files = {prefix + 'content.md': body.encode(), prefix + 'metadata.json': b'{}'}
    graph = project_task_graph(files, entities, project_id, '0' * 40)
    require(graph['status'] == 'ready', 'Generated plan is invalid: ' + graph.get('error', 'unknown'))
    return {key: graph[key] for key in ('status', 'profile', 'nodes', 'ready', 'blocked')}


def build_mapping(value, roots, *, module_placements=()):
    """Freeze candidate identities and preserve every occurrence in coverage.

    Placements are explicit review decisions, never inferred from a module's
    presence or similarly named headings. No module project is created.
    """
    raw = load_sources(value, roots)
    occurrences = {item['locator']: item for item in value['occurrences']}
    groups = {(item['repository_id'], item['id']): item for item in value['definitions']}
    decisions, nodes, warnings = {}, {}, deepcopy(value['issues'])
    source_refs = {}
    for source in value['sources']:
        artifact_id = str(uuid5(NAMESPACE_URL, 'migration-source:' + source['key'] + ':' + source['sha256']))
        filename = 'source.md' if source['path'].endswith('.md') else 'source.json'
        source_refs[source['key']] = f'artifacts/{artifact_id}/{filename}'

    host_sources = {source['path']: raw[source['key']].decode('utf-8')
                    for source in value['sources'] if source['repository_id'] == 'federated-workspace'}
    hints = {item['id']: item for item in value['dependency_hints']}
    catalog = _catalog(host_sources, hints)
    eligible = {id_ for id_, entry in catalog.items() if entry['status'] in {'completed', 'in progress'}}
    eligible -= {id_ for (scope, id_), group in groups.items()
                 if scope == 'federated-workspace' and len(group['checkbox_states']) > 1}
    # Do not silently remove an external requirement dependency and thereby
    # turn an actually constrained batch into an apparently ready batch.
    while True:
        removed = {id_ for id_ in eligible if not set(hints[id_]['depends_on']) <= eligible}
        if not removed:
            break
        eligible -= removed
        warnings.extend(dict(kind='unprojected-dependency-boundary', id=id_) for id_ in sorted(removed))
    for id_ in sorted(eligible):
        group = groups[('federated-workspace', id_)]
        occurrence = occurrences[group['proposed_definition']]
        lane = hints[id_]['milestone']
        require(re.fullmatch(ID, 'MILESTONE-' + lane), 'Invalid milestone identity')
        nodes[('federated-workspace', id_)] = dict(
            id=id_, type='batch', parent_id='MILESTONE-' + lane,
            title=catalog[id_]['title'], checked=catalog[id_]['status'] == 'completed',
            depends_on=hints[id_]['depends_on'], source=occurrence['locator'])

    seen_placements = set()
    for placement in module_placements:
        require(isinstance(placement, dict) and set(placement) == {
            'repository_id', 'batch_id', 'milestone_id', 'milestone_title', 'source', 'heading'},
            'Invalid module placement')
        repository_id, batch_id = placement['repository_id'], placement['batch_id']
        require(repository_id != 'federated-workspace' and (repository_id, batch_id) in groups,
                'Unknown selected module batch')
        require((repository_id, batch_id) not in seen_placements, 'Duplicate module placement')
        seen_placements.add((repository_id, batch_id))
        source = next((item for item in value['sources'] if item['key'] == placement['source']), None)
        require(source is not None and source['repository_id'] == repository_id,
                'Module milestone source differs')
        require(placement['heading'] in raw[source['key']].decode('utf-8').splitlines(),
                'Module milestone heading differs from pin')
        require(re.fullmatch(ID, placement['milestone_id']), 'Invalid module milestone ID')
        require(isinstance(placement['milestone_title'], str) and
                placement['milestone_title'] == re.sub(r'^#{1,6}\s+', '', placement['heading']),
                'Module milestone title differs from heading')
        group = groups[(repository_id, batch_id)]
        occurrence = occurrences[group['proposed_definition']]
        # An active heading does not prove completion of its batch. Even a
        # fully checked leaf list is not an independently accepted feature.
        nodes[(repository_id, batch_id)] = dict(
            id=batch_id, type='batch', parent_id=placement['milestone_id'],
            title=occurrence['text'].split('—', 1)[-1].strip(), checked=False,
            depends_on=[], source=occurrence['locator'])

    # Only explicit leaves inside a known batch section are promoted to tasks.
    for (repository_id, id_), group in groups.items():
        if (repository_id, id_) in nodes:
            continue
        item = occurrences[group['proposed_definition']]
        if (item['kind'] != 'checkbox' or item['role'] not in {'active', 'history'}
                or len(group['checkbox_states']) > 1):
            continue
        parents = [node for (scope, batch_id), node in nodes.items()
                   if scope == repository_id and node['type'] == 'batch' and id_.startswith(batch_id + '-')
                   and any(re.match(r'(?:TODO\s+—\s+)?' + re.escape(batch_id) + r'(?:\s|:|$)', section)
                           for section in item['section'])]
        if not parents:
            continue
        parent = max(parents, key=lambda node: len(node['id']))
        block = source_block(raw[item['source']], item)
        title, excerpt = node_title(item, block)
        nodes[(repository_id, id_)] = dict(
            id=id_, type='task', parent_id=parent['id'], title=title, title_is_excerpt=excerpt,
            checked=item['checkbox_state'] == 'checked', depends_on=[], source=item['locator'],
            checklist=task_checklist(block))

    for key, group in groups.items():
        occurrence = occurrences[group['proposed_definition']]
        node = nodes.get(key)
        decisions[key] = dict(
            repository_id=key[0], id=key[1],
            classification=node['type'] if node else ('historical-evidence' if occurrence['role'] == 'history' else 'requirement'),
            definition=group['proposed_definition'], evidence=group['occurrences'],
            decision='proposed', source_block=source_block(raw[occurrence['source']], occurrence),
            **({'parent_id': node['parent_id'], 'title': node['title'],
                'title_is_excerpt': node.get('title_is_excerpt', False)} if node else {}))

    checklist_owners = {}
    for (repository_id, id_), node in nodes.items():
        occurrence = occurrences[node['source']]
        for ordinal, condition in enumerate(node.get('checklist', [])):
            locator = occurrence['source'] + ':' + str(occurrence['line'] + condition['relative_line'] - 1)
            require(locator not in checklist_owners, 'Checklist condition has multiple owners')
            checklist_owners[locator] = dict(repository_id=repository_id, id=None,
                                             classification='checklist', parent_id=id_, ordinal=ordinal)
    coverage = {}
    for key, decision in decisions.items():
        for locator in decision['evidence']:
            require(locator not in coverage, 'Occurrence has multiple owners')
            coverage[locator] = dict(repository_id=key[0], id=key[1], classification=decision['classification'])
    for proposal in value['anonymous_mapping_proposals']:
        locator = proposal['locator']
        require(locator not in coverage, 'Anonymous occurrence has multiple owners')
        coverage[locator] = checklist_owners.get(locator) or dict(
            repository_id=proposal['repository_id'], id=proposal['proposed_id'],
            classification=proposal['proposed_role'])
    for item in value['occurrences']:
        if item['role'] == 'support':
            coverage[item['locator']] = dict(id=None, classification='supporting-document')
    require(set(coverage) == set(occurrences), 'Source coverage is incomplete')

    projects = []
    scopes = sorted({source['repository_id'] for source in value['sources']})
    for scope in scopes:
        scoped_nodes = {id_: item for (repo, id_), item in nodes.items() if repo == scope}
        milestones = sorted({node['parent_id'] for node in scoped_nodes.values() if node['type'] == 'batch'})
        require(not set(milestones) & {id_ for (repo, id_) in groups if repo == scope},
                'Generated milestone collides with existing identity')
        lines = ['<!-- fpw-plan-profile: software-development/v1 -->', '', '# Migrační náhled', '']
        for milestone in milestones:
            placement = next((item for item in module_placements if item['repository_id'] == scope
                              and item['milestone_id'] == milestone), None)
            title = placement['milestone_title'] if placement else milestone.removeprefix('MILESTONE-')
            lines += [f'- [ ] [{milestone}] {title}', '  - type: milestone']
            for batch in sorted((node for node in scoped_nodes.values() if node['type'] == 'batch'
                                 and node['parent_id'] == milestone), key=lambda node: node['id']):
                lines += _node_lines(batch, 2, occurrences, source_refs)
                for task in sorted((node for node in scoped_nodes.values() if node['type'] == 'task'
                                    and node['parent_id'] == batch['id']), key=lambda node: node['id']):
                    lines += _node_lines(task, 4, occurrences, source_refs)
        body = '\n'.join(lines) + '\n'
        graph = _preview_graph(scope, body) if milestones else None
        if not graph:
            warnings.append(dict(kind='module-placement-required', repository_id=scope))
        projects.append(dict(repository_id=scope, target_project_id=None,
                             target_policy='existing-project' if scope == 'federated-workspace' else 'linked-project',
                             existing_plan_policy='archive-before-replacement-review',
                             body=body, graph=graph,
                             source_references={key: path for key, path in source_refs.items()
                                                if key.startswith(scope + ':')}))
    counts = Counter(item['classification'] for item in coverage.values())
    anonymous = []
    for proposal in value['anonymous_mapping_proposals']:
        occurrence = occurrences[proposal['locator']]
        proposed = dict(proposal, source_block=source_block(raw[occurrence['source']], occurrence))
        if proposal['locator'] in checklist_owners:
            owner = checklist_owners[proposal['locator']]
            proposed.update(proposed_id=None, proposed_role='checklist',
                            parent_id=owner['parent_id'], ordinal=owner['ordinal'])
        anonymous.append(proposed)
    result = dict(schema=SCHEMA, stage='hierarchy-preview', import_ready=False,
                  approval='pending-live-target-preview', inventory_sha256=value['inventory_sha256'],
                  mapping_policy='active-and-historical-batches-v1',
                  module_placements=list(module_placements),
                  projects=projects, definitions=list(decisions.values()),
                  anonymous_identities=anonymous,
                  coverage=coverage, warnings=warnings,
                  preserved_dependency_hints=value['dependency_hints'],
                  summary=dict(covered_occurrences=len(coverage), classifications=dict(sorted(counts.items())),
                               projected_nodes=sum(len(project['graph']['nodes']) for project in projects if project['graph'])),
                  limitations=['Task graph validation only; artifact metadata and live target are not approved.',
                               'Unprojected requirements and dependency hints remain in the catalogue.',
                               'Repeated definitions retain all evidence; proposed owners are not automatic acceptance.',
                               'Original source bytes must accompany eventual import.',
                               'Frozen identities bind this inventory; a changed source requires explicit rebase.'])
    result['mapping_sha256'] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def validate_mapping_binding(mapping, value):
    require(mapping.get('schema') == SCHEMA, 'Unsupported mapping')
    data = {key: item for key, item in mapping.items() if key != 'mapping_sha256'}
    require(mapping.get('mapping_sha256') == hashlib.sha256(canonical(data)).hexdigest(),
            'Mapping digest differs')
    require(mapping['inventory_sha256'] == value['inventory_sha256'],
            'Source changed; frozen mapping requires explicit rebase')


def bind_target_preview(mapping, node_path, project_id, *, repository_id='federated-workspace'):
    """Read committed target bytes without initializing any journal or index."""
    result = deepcopy(mapping)
    project = next((item for item in result['projects'] if item['repository_id'] == repository_id), None)
    require(project is not None and project['graph'] is not None, 'No generated project plan to bind')
    git = Projects(node_path).repository(project_id)
    head = git.head()
    files = git.snapshot(head)
    entities = validate_snapshot(files)
    old = document(files, entities, main_todo_id(project_id))
    original = files[old['path']]
    original_graph = project_task_graph(files, entities, project_id, head)
    graph = _preview_graph(repository_id, project['body'], project_id=project_id)
    dirty = bool(git.run('status', '--porcelain=v1', env_extra={'GIT_OPTIONAL_LOCKS': '0'}).stdout)
    require(git.head() == head, 'Target HEAD changed during preview')
    project.update(target_project_id=project_id, graph=graph, target_preview=dict(
        expected_head=head, artifact_id=old['id'], original_path=old['path'],
        original_content=original.decode('utf-8'), original_sha256=hashlib.sha256(original).hexdigest(),
        original_metadata=old['metadata'], worktree_dirty=dirty,
        original_plan_status=original_graph['status'],
        removed_plan_ids=sorted({node['id'] for node in original_graph['nodes']}
                                - {node['id'] for node in graph['nodes']}),
        message_history_policy='retain-original-task-and-revision-references',
        action='archive-original-before-main-todo-replacement', approved=False,
        diff=''.join(difflib.unified_diff(old['body'].splitlines(keepends=True),
                                        project['body'].splitlines(keepends=True),
                                        fromfile='main-todo-before.md', tofile='main-todo-proposed.md'))))
    limitation = 'Target preview covers main TODO only; complete artifact metadata/apply plan is pending.'
    if limitation not in result['limitations']:
        result['limitations'].append(limitation)
    result.pop('mapping_sha256', None)
    result['mapping_sha256'] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def _node_lines(node, indent, occurrences, source_refs):
    title = node['title']
    require(isinstance(title, str) and 0 < len(title) <= 500 and '\n' not in title and '\r' not in title,
            'Node title requires review')
    # Batch titles must not accidentally become file-include directives.
    require(not re.fullmatch(r'\[.*\]\(.*\)', title), 'Node title looks like an include')
    prefix = ' ' * indent
    source = occurrences[node['source']]
    lines = [f'{prefix}- [{"x" if node["checked"] else " "}] [{node["id"]}] {title}',
             f'{prefix}  - type: {node["type"]}',
             f'{prefix}  - Zdroj: [{source["source"]}:{source["line"]}]({source_refs[source["source"]]})']
    if node['depends_on']:
        lines.append(f'{prefix}  - depends_on: ' + ', '.join(node['depends_on']))
    for item in node.get('checklist', []):
        lines.append(f'{prefix}  - [{"x" if item["checked"] else " "}] {item["text"]}')
    return lines


def render_mapping_summary(value):
    lines = ['# Náhled mapování roadmapy', '',
             'Stav: návrh hierarchie; import_ready: false. Živý projekt nebyl změněn.', '',
             'Typy uzlů byly ověřeny stávajícím validátorem plánu; metadata artefaktů,',
             'finální cíle modulů, privacy a úplný diff všech artefaktů teprve čekají na ověření.', '',
             '## Cílové projekty', '']
    for project in value['projects']:
        graph = project['graph']
        counts = Counter(node['type'] for node in graph['nodes']) if graph else Counter()
        lines.append(f'- **{project["repository_id"]}**: {dict(sorted(counts.items()))}; '
                     f'plán [{project["repository_id"]}/TODO.md]({project["repository_id"]}/TODO.md).')
        if project.get('target_preview'):
            lines.append(f'  Aktuální cílový HEAD: `{project["target_preview"]["expected_head"]}`; '
                         f'[diff hlavního plánu]({project["repository_id"]}/target.diff).')
            lines.append('  Původní ID mimo navržený plán: ' +
                         ', '.join(project['target_preview']['removed_plan_ids']) +
                         '. Jejich historie/zprávy vyžadují zachování původní revize; automatické přemapování se neprovádí.')
    lines += ['', '## Zachované rozpory a nedokončená rozhodnutí', '']
    for warning in value['warnings']:
        lines.append('- ' + json.dumps(warning, ensure_ascii=False))
    lines += ['', 'Široké budoucí položky zůstávají katalogem požadavků; nejsou tím',
              'automaticky převedené na dávky ani dokončené. Nezařazené dependency',
              'hrany jsou zachované v mapping.json. Historické důkazy zůstávají dohledatelné.', '',
              'Každý projekt má requirements.md a history.md s odkazy na původní',
              'bajty zdrojů. mapping.json drží všechny výskyty a úplné zdrojové bloky.', '',
              'Ukázkový cílový plán má navržené archivování před nahrazením; pokud byl',
              'načten, report obsahuje původní bajty a diff. Nic nebylo nahrazeno.',
              'Přiřazení modulu k milníku je návrh, nikoli vytvoření projektu nebo',
              'změna autority. Samotné zaškrtnutí všech modulových podúkolů nedokládá',
              'akceptaci celé dávky; modulová dávka proto nebyla automaticky dokončena.', '']
    return '\n'.join(lines)
