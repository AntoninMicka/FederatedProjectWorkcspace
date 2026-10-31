# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Local Ollama proposals for attaching detached roadmap evidence."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import difflib
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from uuid import NAMESPACE_URL, uuid4, uuid5

from spikes.backend_contract import ROLES
from spikes.backend_contract import BackendUnknown
from spikes.configuration import committed_project, parse_node, read_config
from spikes.context_builder import (AdHocInput, Authority, ContextBuilder,
                                    ProjectInput, TaskInstruction)
from spikes.markdown_documents import main_todo_id, document
from spikes.metadata import MAX_FILE, pairs, require, uuid, validate_snapshot
from spikes.ollama_backend import OllamaAdapter, OllamaBinding, OllamaBindings, OllamaRuns
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.roadmap_migration import LINK
from spikes.task_graph import (ALIASES, CHILD_TYPES, DOCUMENT_LINK, RELATION, TASK,
                               project_task_graph)

SCHEMA = 'fpw-roadmap-refinement-proposal-v1'
ANALYZER_REVISION = 'attach-detached-v3'
DEEP_SCHEMA = 'fpw-roadmap-deep-check-proposal-v1'
DEEP_ANALYZER_REVISION = 'semantic-reconciliation-v2'
DEEP_POLICY_REVISION = 'legacy-sequential-to-canonical-v1'
HEADING = '## Samostatné podklady bez jednoznačného přiřazení'
STABLE_ID = re.compile(r'(?<![A-Z0-9-])([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)(?![A-Z0-9-])')
DEEP_ACTIONS = {'keep-history', 'keep-description', 'keep-canonical', 'promote',
                'create-residual', 'merge-alias', 'split', 'update-node',
                'add-dependency', 'remove-dependency', 'conflict'}
INSTRUCTION = '''Review one detached roadmap evidence document against the supplied target catalog.
Return exactly one JSON object with fields:
{"schema":"fpw-roadmap-refinement-proposal-v1","decision":"attach|keep-detached","document_id":"UUID","target_id":"stable ID or null","confidence":"low|medium|high","reason":"Czech explanation"}.
Use attach only when the source provides clear evidence for exactly one existing target. Copy target_id exactly from an "id" field in the supplied catalog. Never invent IDs, rewrite content, change completion state, merge, delete, or use a target absent from the catalog. Use keep-detached when ambiguous. Return JSON only.'''
DEEP_INSTRUCTION = '''Perform one semantic reconciliation review of a legacy roadmap source cluster against the current canonical task graph.
Legacy conventions: TODO held one active feature batch; whole batches including completed subtasks moved sequentially to WORK_LOG; BACKLOG mixed future work with implemented-but-unverified leftovers; the Master Checklist repeated capabilities at a different granularity. A later occurrence is not automatically authoritative. History must not be reopened, free prose is not automatically a task, and dependencies require a real execution prerequisite.
Desired state: one canonical executable node per stable ID, historical evidence stays non-executable, unfinished residual work becomes a concrete task, conflicting definitions are explicitly split/merged/conflicted, and no completion state changes without evidence.
Return exactly one JSON object with fields:
{"schema":"fpw-roadmap-deep-check-proposal-v1","action":"keep-history|keep-description|keep-canonical|promote|create-residual|merge-alias|split|update-node|add-dependency|remove-dependency|conflict","cluster_id":"exact supplied cluster ID","source_ids":["UUID"],"target_ids":["existing ID"],"confidence":"low|medium|high","summary":"Czech proposed change","reason":"Czech evidence-based explanation","changes":[{"kind":"create-node|update-node|add-dependency|remove-dependency","node_id":"ID or null","target_id":"ID or null","title":"text or null","node_type":"milestone|batch|task or null","parent_id":"existing ID or null","checked":true|false|null,"reason":"Czech explanation"}]}.
For keep-history, keep-description, keep-canonical and conflict, changes must be empty. Existing target_ids, target_id and parent_id must be copied exactly from the supplied catalog. New node_id values are proposals only and must be uppercase stable IDs not present in the catalog. Hierarchy is strict: a root is a milestone, a batch belongs to a milestone, and a task belongs to a batch. update-node must preserve the existing type and parent. Do not silently resolve ambiguity, invent completion evidence, or output Markdown. Return JSON only.'''


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _content(files, metadata):
    prefix = 'artifacts/' + metadata['id'] + '/'
    return files[prefix + metadata['file']]


def detached_ids(body):
    """Read only artifact links in the dedicated detached section."""
    active, result = False, []
    for line in body.splitlines():
        if line.strip() == HEADING:
            active = True; continue
        if active and (line.startswith('## ') or re.match(r'^- \[[ xX]\] \[', line)):
            break
        if not active:
            continue
        for target in LINK.findall(line):
            match = re.fullmatch(r'artifacts/([0-9a-f-]{36})/content\.md', target.split('#', 1)[0])
            if match:
                uuid(match[1]); result.append(match[1])
    require(len(result) == len(set(result)), 'Detached document link is duplicated')
    return result


def validate_proposal(raw, document_id, targets):
    require(isinstance(raw, str) and 0 < len(raw.encode()) <= 64 * 1024,
            'Refinement response is invalid or oversized')
    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, RecursionError) as exc:
        raise ValueError('Refinement response is not strict JSON') from exc
    require(isinstance(value, dict) and set(value) == {
        'schema', 'decision', 'document_id', 'target_id', 'confidence', 'reason'},
        'Invalid refinement proposal fields')
    require(value['schema'] == SCHEMA and value['document_id'] == document_id,
            'Refinement proposal identity differs')
    require(value['decision'] in {'attach', 'keep-detached'}
            and value['confidence'] in {'low', 'medium', 'high'}
            and isinstance(value['reason'], str) and bool(value['reason'].strip())
            and len(value['reason'].encode()) <= 4096, 'Invalid refinement decision')
    if value['decision'] == 'attach':
        require(value['target_id'] in targets, 'Refinement target is unavailable')
    else:
        require(value['target_id'] is None, 'Detached decision cannot select a target')
    return value


def validate_deep_proposal(raw, cluster, targets):
    require(isinstance(raw, str) and 0 < len(raw.encode()) <= 64 * 1024,
            'Deep-check response is invalid or oversized')
    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, RecursionError) as exc:
        raise ValueError('Deep-check response is not strict JSON') from exc
    require(isinstance(value, dict) and set(value) == {
        'schema', 'action', 'cluster_id', 'source_ids', 'target_ids',
        'confidence', 'summary', 'reason', 'changes'}, 'Invalid deep-check proposal fields')
    require(value['schema'] == DEEP_SCHEMA and value['cluster_id'] == cluster['cluster_id']
            and value['action'] in DEEP_ACTIONS
            and value['confidence'] in {'low', 'medium', 'high'},
            'Invalid deep-check proposal identity or decision')
    expected_sources = sorted(cluster['source_ids'])
    require(isinstance(value['source_ids'], list) and sorted(value['source_ids']) == expected_sources,
            'Deep-check source identity differs')
    require(isinstance(value['target_ids'], list) and len(value['target_ids']) == len(set(value['target_ids']))
            and all(item in targets for item in value['target_ids']),
            'Deep-check target identity is unavailable')
    for field in ('summary', 'reason'):
        require(isinstance(value[field], str) and bool(value[field].strip())
                and len(value[field].encode()) <= 8192, 'Invalid deep-check explanation')
    require(isinstance(value['changes'], list) and len(value['changes']) <= 16,
            'Invalid deep-check change list')
    if value['action'] in {'keep-history', 'keep-description', 'keep-canonical', 'conflict'}:
        require(not value['changes'], 'Non-mutating deep-check action cannot contain changes')
    allowed = {'kind', 'node_id', 'target_id', 'title', 'node_type', 'parent_id', 'checked', 'reason'}
    for change in value['changes']:
        require(isinstance(change, dict) and set(change) == allowed
                and change['kind'] in {'create-node', 'update-node', 'add-dependency', 'remove-dependency'}
                and (change['target_id'] is None or change['target_id'] in targets)
                and (change['parent_id'] is None or change['parent_id'] in targets)
                and change['node_type'] in {None, 'milestone', 'batch', 'task'}
                and (change['checked'] is None or type(change['checked']) is bool)
                and isinstance(change['reason'], str) and bool(change['reason'].strip()),
                'Invalid deep-check structured change')
        node_id = change['node_id']
        require(node_id is None or bool(re.fullmatch(r'[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+', node_id)),
                'Invalid proposed deep-check node ID')
        if change['kind'] == 'create-node':
            require(node_id not in targets and isinstance(change['title'], str)
                    and bool(change['title'].strip()), 'Created deep-check node collides or lacks title')
            node_type, parent_id = change['node_type'], change['parent_id']
            if parent_id is None:
                require(node_type == 'milestone', 'Created root node must be a milestone')
            else:
                require(node_type in CHILD_TYPES[targets[parent_id]['type']],
                        'Created deep-check node has an invalid parent type')
        else:
            require(node_id in targets, 'Deep-check change refers to unavailable node')
            if change['kind'] == 'update-node':
                current = targets[node_id]
                require(change['node_type'] in {None, current['type']}
                        and change['parent_id'] in {None, current['parent_id']},
                        'Deep-check update cannot change node type or parent')
            else:
                require(change['target_id'] is not None,
                        'Dependency change requires an existing target')
    return value


def _excerpt(lines, index, limit=4096):
    start = max(0, index - 1); end = min(len(lines), index + 7)
    value = '\n'.join(lines[start:end]).strip()
    return value[:limit]


def deep_source_clusters(files, entities, targets):
    """Create a deterministic complete structural inventory before dispatch."""
    clusters = {}
    anonymous = []
    for artifact_id, meta in sorted(entities.items()):
        if not ((meta['kind'] == 'source' and meta.get('file') == 'source.md')
                or 'original-source' in meta.get('tags', [])):
            continue
        raw = _content(files, meta).decode('utf-8'); lines = raw.splitlines()
        source = {'artifact_id': artifact_id, 'title': meta['title'],
                  'sha256': hashlib.sha256(raw.encode()).hexdigest()}
        for index, line in enumerate(lines):
            ids = sorted(set(STABLE_ID.findall(line)))
            for stable_id in ids:
                row = clusters.setdefault('id:' + stable_id, {
                    'cluster_id': 'id:' + stable_id, 'kind': 'stable-id',
                    'stable_id': stable_id, 'source_ids': [], 'occurrences': []})
                if artifact_id not in row['source_ids']:
                    row['source_ids'].append(artifact_id)
                if len(row['occurrences']) < 32:
                    row['occurrences'].append(dict(source=source, line=index + 1,
                                                   excerpt=_excerpt(lines, index)))
            structural = bool(re.match(r'^\s*- \[[ xX]\]', line) or re.match(r'^#{2,6}\s+', line))
            if structural and not ids:
                digest = hashlib.sha256((artifact_id + '\0' + str(index + 1) + '\0' + line).encode()).hexdigest()
                anonymous.append({
                    'cluster_id': 'anon:' + digest, 'kind': 'anonymous-structure',
                    'stable_id': None, 'source_ids': [artifact_id],
                    'occurrences': [dict(source=source, line=index + 1,
                                         excerpt=_excerpt(lines, index))]})
    result = list(clusters.values()) + anonymous
    for cluster in result:
        cluster['source_ids'].sort()
        stable_id = cluster['stable_id']
        cluster['current_target'] = (dict(id=stable_id, **targets[stable_id])
                                     if stable_id in targets else None)
        cluster['current_occurrences'] = []
    # A legacy item can have been preserved in a supporting Markdown document
    # without becoming an executable graph node.  Include those exact-revision
    # occurrences so the model compares source and destination rather than
    # inferring absence from the canonical task graph alone.
    by_id = {cluster['stable_id']: cluster for cluster in result if cluster['stable_id']}
    for artifact_id, meta in sorted(entities.items()):
        is_source = ((meta['kind'] == 'source' and meta.get('file') == 'source.md')
                     or 'original-source' in meta.get('tags', []))
        if is_source or not meta.get('file', '').endswith('.md'):
            continue
        lines = _content(files, meta).decode('utf-8').splitlines()
        for index, line in enumerate(lines):
            for stable_id in sorted(set(STABLE_ID.findall(line)) & by_id.keys()):
                occurrences = by_id[stable_id]['current_occurrences']
                if len(occurrences) < 32:
                    occurrences.append({
                        'artifact_id': artifact_id, 'title': meta['title'],
                        'path': 'artifacts/' + artifact_id + '/' + meta['file'],
                        'line': index + 1, 'excerpt': _excerpt(lines, index),
                    })
    return sorted(result, key=lambda item: item['cluster_id'])


def attach_document(body, document_id, target_id):
    """Move one existing evidence link; never edit the evidence artifact."""
    lines = body.splitlines()
    needle = f'(artifacts/{document_id}/content.md)'
    matches = [index for index, line in enumerate(lines) if needle in line]
    require(len(matches) == 1 and lines[matches[0]].lstrip().startswith('- ['),
            'Expected one detachable evidence link')
    link = lines[matches[0]].strip()[2:]
    del lines[matches[0]]
    target = next((index for index, line in enumerate(lines)
                   if re.match(r'^\s*- \[[ xX]\] \[' + re.escape(target_id) + r'\](?:\s|$)', line)), None)
    require(target is not None, 'Refinement target disappeared')
    indent = len(lines[target]) - len(lines[target].lstrip()) + 2
    insert = target + 1
    while insert < len(lines) and (not lines[insert].strip()
                                   or len(lines[insert]) - len(lines[insert].lstrip()) > indent - 2):
        insert += 1
    lines.insert(insert, ' ' * indent + '- Podklad: ' + link)
    return '\n'.join(lines) + ('\n' if body.endswith('\n') else '')


def _replace_body(files, path, lines, trailing):
    result = dict(files)
    result[path] = ('\n'.join(lines) + ('\n' if trailing else '')).encode('utf-8')
    return result


def _deep_change(files, entities, project_id, head, change):
    """Apply one typed change to a candidate snapshot, validating after every step."""
    graph = project_task_graph(files, entities, project_id, head)
    require(graph['status'] == 'ready', 'Reconciliation candidate task graph is invalid')
    nodes = {item['id']: item for item in graph['nodes']}
    kind, node_id = change['kind'], change['node_id']
    if kind == 'add-dependency':
        from spikes.roadmap_dependencies import add_dependency
        return add_dependency(files, entities, project_id, head, node_id, change['target_id'])
    if kind == 'create-node':
        require(node_id not in nodes, 'Reconciliation creates a duplicate node ID')
        parent_id = change['parent_id']; node_type = change['node_type']
        if parent_id is None:
            require(node_type == 'milestone', 'Created root node must be a milestone')
            path = 'artifacts/' + main_todo_id(project_id) + '/' + entities[main_todo_id(project_id)]['file']
            lines = files[path].decode('utf-8').splitlines(); index = len(lines); indent = 0
        else:
            require(parent_id in nodes and node_type in CHILD_TYPES[nodes[parent_id]['type']],
                    'Created node has an invalid parent type')
            parent = nodes[parent_id]; children = [item for item in nodes.values()
                                                   if item['parent_id'] == parent_id]
            if parent['type'] == 'batch' and children:
                paths = {item['source']['path'] for item in children}
                require(len(paths) == 1, 'Batch children span multiple plan documents')
                path = paths.pop(); lines = files[path].decode('utf-8').splitlines()
                index = len(lines); indent = len(lines[children[0]['line'] - 1]) - len(lines[children[0]['line'] - 1].lstrip())
            else:
                path = parent['source']['path']; lines = files[path].decode('utf-8').splitlines()
                match = TASK.match(lines[parent['line'] - 1]); require(match is not None, 'Parent task line disappeared')
                link = DOCUMENT_LINK.fullmatch(match.group(4))
                if parent['type'] == 'batch' and link:
                    path = link.group(2); require(path in files, 'Linked batch plan disappeared')
                    lines = files[path].decode('utf-8').splitlines(); index = len(lines); indent = 0
                else:
                    parent_indent = len(match.group(1).expandtabs(4)); index = parent['line']
                    while index < len(lines):
                        following = TASK.match(lines[index])
                        if following and len(following.group(1).expandtabs(4)) <= parent_indent:
                            break
                        index += 1
                    indent = parent_indent + 2
        trailing = files[path].endswith(b'\n')
        addition = [' ' * indent + f"- [{'x' if change['checked'] else ' '}] [{node_id}] {change['title']}",
                    ' ' * (indent + 2) + '- type: ' + node_type]
        if index and lines[index - 1].strip(): addition.insert(0, '')
        lines[index:index] = addition
        candidate = _replace_body(files, path, lines, trailing)
    else:
        require(node_id in nodes, 'Reconciliation target disappeared')
        node = nodes[node_id]; path = node['source']['path']; raw = files[path].decode('utf-8')
        lines = raw.splitlines(); line_index = node['line'] - 1; match = TASK.match(lines[line_index])
        require(match is not None, 'Reconciliation task line disappeared')
        trailing = raw.endswith('\n')
        if kind == 'update-node':
            require(change['node_type'] in {None, node['type']}
                    and change['parent_id'] in {None, node['parent_id']},
                    'Reconciliation update cannot change node type or parent')
            title = change['title'] if change['title'] is not None else node['title']
            link = DOCUMENT_LINK.fullmatch(match.group(4))
            if link:
                title = f'[{title}]({link.group(2)})'
            checked = node['checked'] if change['checked'] is None else change['checked']
            lines[line_index] = match.group(1) + f"- [{'x' if checked else ' '}] [{node_id}] {title}"
        else:
            target = change['target_id']; require(target in nodes, 'Dependency target disappeared')
            indent = len(match.group(1).expandtabs(4))
            block_end = min((item['line'] - 1 for item in nodes.values()
                             if item['source']['path'] == path and item['line'] - 1 > line_index),
                            default=len(lines))
            relation_rows = []
            for index in range(line_index + 1, block_end):
                relation = RELATION.match(lines[index])
                if relation and ALIASES.get(relation.group(2).strip().lower()) == 'depends_on':
                    relation_rows.append((index, relation, [item.strip() for item in relation.group(3).split(',')]))
            existing = {item for _, _, values in relation_rows for item in values}
            require(kind == 'remove-dependency' and target in existing, 'Removed dependency does not exist')
            index, relation, values = next(row for row in relation_rows if target in row[2])
            values.remove(target)
            if values:
                lines[index] = relation.group(1) + '- ' + relation.group(2) + ': ' + ', '.join(values)
            else:
                del lines[index]
        candidate = _replace_body(files, path, lines, trailing)
    checked = project_task_graph(candidate, entities, project_id, head)
    require(checked['status'] == 'ready', 'Reconciliation change makes task graph invalid: ' + checked.get('error', 'unknown error'))
    return candidate


class RoadmapRefinement:
    def __init__(self, node, project_id, *, state_dir=None, adapter_factory=None):
        self.node = Path(node).absolute(); uuid(project_id); self.project_id = project_id
        self.state = (Path(state_dir).absolute() if state_dir else
                      self.node.parent / ('.' + self.node.name + '.roadmap-refinement'))
        self.adapter_factory = adapter_factory

    def _root(self):
        self.state.mkdir(mode=0o700, exist_ok=True)
        info = self.state.lstat()
        require(self.state == self.state.resolve() and stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                'Refinement state requires owned mode 0700')
        return self.state

    def _connect(self):
        path = self._root()/'refinement.sqlite'; existed = path.exists()
        if existed:
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe refinement database')
        db = sqlite3.connect(path)
        if not existed:
            os.chmod(path, 0o600)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS proposals('
                   'id TEXT PRIMARY KEY,fingerprint TEXT UNIQUE NOT NULL,project_id TEXT NOT NULL,'
                   'expected_head TEXT NOT NULL,document_id TEXT NOT NULL,document_sha256 TEXT NOT NULL,'
                   'response TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL,receipt TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS dependency_applies('
                   'id TEXT PRIMARY KEY,record TEXT NOT NULL)')
        columns = {row[1] for row in db.execute('PRAGMA table_info(proposals)')}
        if 'mode' not in columns:
            db.execute("ALTER TABLE proposals ADD COLUMN mode TEXT NOT NULL DEFAULT 'detached'")
        if 'input_json' not in columns:
            db.execute("ALTER TABLE proposals ADD COLUMN input_json TEXT NOT NULL DEFAULT '{}'")
        # Older local queues stored a globally unique bare digest. Prefixing it
        # preserves every durable review while making uniqueness project-local.
        legacy = db.execute("SELECT 1 FROM proposals WHERE instr(fingerprint, ':')=0 LIMIT 1").fetchone()
        if legacy:
            db.execute("UPDATE proposals SET fingerprint=project_id || ':' || fingerprint "
                       "WHERE instr(fingerprint, ':')=0")
        db.commit(); return closing(db)

    @contextmanager
    def _deep_lock(self):
        path = self._root()/'deep-check.lock'
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and not info.st_mode & 0o077, 'Unsafe deep-check lock')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('Deep-check is already running') from exc
            yield
        finally:
            os.close(fd)

    def _binding(self):
        chat = self.node.parent / ('.' + self.node.name + '.chat')
        binding = OllamaBindings(chat).load()
        require(binding.boundary == 'same-node', 'Refinement requires same-node Ollama')
        return binding

    def _snapshot(self):
        workspace = Projects(self.node).workspace(self.project_id, blocking=False)
        view = workspace.read_project(self.project_id)
        head = view['commit_id']; files = workspace.git.snapshot(head); entities = validate_snapshot(files)
        root_id = main_todo_id(self.project_id); require(root_id in entities, 'Main plan is unavailable')
        body = document(files, entities, root_id)['body']
        graph = project_task_graph(files, entities, self.project_id, head)
        require(graph['status'] == 'ready', 'Project task graph is invalid')
        targets = {item['id']: {'type': item['type'], 'title': item['title'],
                                'parent_id': item['parent_id']}
                   for item in graph['nodes']}
        return workspace, head, files, entities, root_id, body, targets

    def scan(self, *, limit=1, deep_check=False, forget_previous=False, dependencies_only=False,
             focus_ids=None):
        require(type(forget_previous) is bool, 'Invalid forget-previous flag')
        require(type(dependencies_only) is bool, 'Invalid dependency scan flag')
        if dependencies_only:
            require(not deep_check and not forget_previous, 'Dependency mode cannot reset or mix scans')
            from spikes.roadmap_dependencies import scan
            return scan(self, limit, focus_ids=focus_ids)
        require(focus_ids is None, 'Focus selection requires dependency mode')
        if deep_check:
            return self._scan_deep(limit=limit, forget_previous=forget_previous)
        require(not forget_previous, 'Forget-previous requires deep-check mode')
        require(type(limit) is int and 1 <= limit <= 32, 'Scan limit must be 1..32')
        workspace, head, files, entities, root_id, body, targets = self._snapshot()
        candidates = detached_ids(body); binding = self._binding()
        node = parse_node(read_config(self.node), location=self.node)
        actor = ProjectCreation(self.node).author_id(); created = []
        catalog = canonical({'schema': 'fpw-roadmap-refinement-targets-v1',
                             'targets': [dict(id=id_, **item) for id_, item in sorted(targets.items())]})
        require(len(catalog) <= MAX_FILE, 'Refinement target catalog exceeds limit')
        with self._connect() as db:
            existing = {row[0] for row in db.execute(
                'SELECT fingerprint FROM proposals WHERE project_id=?', (self.project_id,))}
        candidate_rows = []
        for document_id in candidates:
            require(document_id in entities and entities[document_id]['kind'] == 'document',
                    'Detached evidence document is unavailable')
            raw = _content(files, entities[document_id])
            fingerprint = self.project_id + ':' + hashlib.sha256(
                raw + b'\0' + catalog + b'\0' + ANALYZER_REVISION.encode()).hexdigest()
            candidate_rows.append((document_id, raw, fingerprint))
        for document_id, raw, fingerprint in candidate_rows:
            if len(created) >= limit:
                break
            if fingerprint in existing:
                continue
            proposal_id = str(uuid5(NAMESPACE_URL, 'roadmap-refinement:' + self.project_id + ':' + fingerprint))
            run_id, manifest_id, catalog_id = str(uuid4()), str(uuid4()), str(uuid4())
            with self._connect() as db, db:
                db.execute('INSERT INTO proposals('
                           'id,fingerprint,project_id,expected_head,document_id,document_sha256,'
                           'response,state,created_at,receipt,mode,input_json) '
                           'VALUES(?,?,?,?,?,?,?,?,?,NULL,?,?)',
                           (proposal_id, fingerprint, self.project_id, head, document_id,
                            hashlib.sha256(raw).hexdigest(), '{}', 'running', now(),
                            'detached', '{}'))
            authority = Authority('roadmap-refinement:' + proposal_id, actor, node['id'],
                                  'roadmap-refinement-v2', frozenset({document_id}))
            prepared = ContextBuilder(workspace, self.project_id).prepare(
                manifest_id=manifest_id, run_id=run_id, authority=authority, target=binding.target(),
                project_inputs=(ProjectInput(document_id),),
                ad_hoc_inputs=(AdHocInput(catalog_id, catalog, 'project'),),
                task=TaskInstruction('extractor', 'extractor-v1', INSTRUCTION, catalog_id))
            handoff = ContextBuilder(workspace, self.project_id).authorize_for_dispatch(
                prepared, authority=authority, target=binding.target())
            runs = OllamaRuns(self._root()); adapter = self.adapter_factory(runs) if self.adapter_factory else OllamaAdapter(runs)
            role = ROLES.resolve('extractor', 'extractor-v1')
            response = None
            try:
                adapter.prepare(handoff, binding, role, 'json')
                response = adapter.dispatch(handoff, binding, role, 'json')['response']
                value = validate_proposal(response, document_id, targets)
                state = 'pending' if value['decision'] == 'attach' else 'dismissed'
            except BackendUnknown as exc:
                value, state = {'error': str(exc), 'outcome': 'unknown'}, 'unknown'
                with self._connect() as db, db:
                    db.execute('UPDATE proposals SET response=?,state=? WHERE id=?',
                               (json.dumps(value, ensure_ascii=False), state, proposal_id))
                existing.add(fingerprint); created.append(self.get(proposal_id)); continue
            except Exception as exc:
                value, state = {'error': str(exc), 'outcome': 'failed',
                                'raw_response': response}, 'failed'
                with self._connect() as db, db:
                    db.execute('UPDATE proposals SET response=?,state=? WHERE id=?',
                               (json.dumps(value, ensure_ascii=False), state, proposal_id))
                existing.add(fingerprint); created.append(self.get(proposal_id)); continue
            with self._connect() as db, db:
                db.execute('UPDATE proposals SET response=?,state=? WHERE id=? AND state=?',
                           (json.dumps(value, ensure_ascii=False, sort_keys=True,
                            separators=(',', ':')), state, proposal_id, 'running'))
            existing.add(fingerprint); created.append(self.get(proposal_id))
        current = {fingerprint for _, _, fingerprint in candidate_rows}
        with self._connect() as db:
            states = {fingerprint: state for fingerprint, state in db.execute(
                'SELECT fingerprint,state FROM proposals WHERE project_id=?',
                (self.project_id,)) if fingerprint in current}
        terminal = {'rejected', 'applied', 'dismissed'}
        return {'project_id': self.project_id, 'expected_head': head, 'detached': len(candidates),
                'created': created, 'remaining': sum(states.get(value) not in terminal for value in current),
                'converged': not created and bool(current) and
                all(states.get(value) in terminal for value in current)}

    def _prepare_deep(self, head, files, entities, targets):
        graph = project_task_graph(files, entities, self.project_id, head)
        graph_catalog = canonical({
            'schema': 'fpw-roadmap-deep-targets-v1',
            'targets': sorted(({
                'id': item['id'], 'type': item['type'], 'title': item['title'],
                'parent_id': item.get('parent_id'), 'checked': item.get('checked'),
                'depends_on': item.get('depends_on', []),
            } for item in graph['nodes']), key=lambda item: item['id'])})
        require(len(graph_catalog) <= MAX_FILE, 'Deep-check target catalog exceeds limit')
        clusters = deep_source_clusters(files, entities, targets)
        require(bool(clusters), 'No imported roadmap source clusters are available')
        fingerprints = []
        with self._connect() as db, db:
            for cluster in clusters:
                payload = canonical(cluster)
                fingerprint = self.project_id + ':deep:' + hashlib.sha256(
                    head.encode() + b'\0' + payload + b'\0' + graph_catalog + b'\0' +
                    DEEP_POLICY_REVISION.encode() + b'\0' + DEEP_ANALYZER_REVISION.encode()).hexdigest()
                fingerprints.append(fingerprint)
                proposal_id = str(uuid5(NAMESPACE_URL, 'roadmap-deep-check:' + fingerprint))
                document_id = cluster['source_ids'][0]
                db.execute('INSERT OR IGNORE INTO proposals('
                           'id,fingerprint,project_id,expected_head,document_id,document_sha256,'
                           'response,state,created_at,receipt,mode,input_json) '
                           'VALUES(?,?,?,?,?,?,?,?,?,NULL,?,?)',
                           (proposal_id, fingerprint, self.project_id, head, document_id,
                            hashlib.sha256(payload).hexdigest(), '{}', 'queued', now(),
                            'deep-check', payload.decode()))
        return clusters, graph_catalog, fingerprints

    def _scan_deep(self, *, limit=1, forget_previous=False):
        require(type(limit) is int and 1 <= limit <= 100000,
                'Deep-check limit must be 1..100000')
        with self._deep_lock():
            forgotten = 0
            if forget_previous:
                # This is deliberately scoped to the selected project and
                # deep-check mode. Detached refinement reviews remain intact.
                with self._connect() as db, db:
                    forgotten = db.execute(
                        "DELETE FROM proposals WHERE project_id=? AND mode='deep-check'",
                        (self.project_id,)).rowcount
            workspace, head, files, entities, root_id, body, targets = self._snapshot()
            clusters, catalog, fingerprints = self._prepare_deep(head, files, entities, targets)
            with self._connect() as db, db:
                interrupted = db.execute(
                    "SELECT id FROM proposals WHERE project_id=? AND mode='deep-check' "
                    "AND expected_head=? AND state='running'", (self.project_id, head)).fetchall()
                for (proposal_id,) in interrupted:
                    db.execute("UPDATE proposals SET state='unknown',response=? WHERE id=?",
                               (json.dumps({'error': 'Interrupted deep-check dispatch outcome is unknown',
                                            'outcome': 'unknown'}), proposal_id))
            created = []
            current = set(fingerprints)
            with self._connect() as db:
                queued = db.execute(
                    "SELECT id,input_json FROM proposals WHERE project_id=? AND mode='deep-check' "
                    "AND expected_head=? AND state='queued' ORDER BY created_at,id LIMIT ?",
                    (self.project_id, head, limit)).fetchall()
            binding = self._binding() if queued else None
            node = parse_node(read_config(self.node), location=self.node) if queued else None
            actor = ProjectCreation(self.node).author_id() if queued else None
            for proposal_id, input_json in queued:
                cluster = json.loads(input_json); response = None
                with self._connect() as db, db:
                    claimed = db.execute("UPDATE proposals SET state='running' "
                                         "WHERE id=? AND project_id=? AND state='queued'",
                                         (proposal_id, self.project_id)).rowcount
                if claimed != 1:
                    continue
                try:
                    run_id, manifest_id, cluster_input = (str(uuid4()) for _ in range(3))
                    authority = Authority('roadmap-deep-check:' + proposal_id, actor, node['id'],
                                          DEEP_POLICY_REVISION, frozenset(cluster['source_ids']))
                    focused_input = canonical({
                        'schema': 'fpw-roadmap-deep-check-input-v1',
                        'source_cluster': cluster,
                        'current_plan': json.loads(catalog),
                    })
                    require(len(focused_input) <= MAX_FILE, 'Deep-check focused input exceeds limit')
                    prepared = ContextBuilder(workspace, self.project_id).prepare(
                        manifest_id=manifest_id, run_id=run_id, authority=authority,
                        target=binding.target(),
                        # The context contract permits one ad-hoc focused input;
                        # freeze source evidence and the exact target catalog in it.
                        ad_hoc_inputs=(AdHocInput(cluster_input, focused_input, 'project'),),
                        task=TaskInstruction('extractor', 'extractor-v1', DEEP_INSTRUCTION, cluster_input))
                    handoff = ContextBuilder(workspace, self.project_id).authorize_for_dispatch(
                        prepared, authority=authority, target=binding.target())
                    runs = OllamaRuns(self._root())
                    adapter = self.adapter_factory(runs) if self.adapter_factory else OllamaAdapter(runs)
                    role = ROLES.resolve('extractor', 'extractor-v1')
                    adapter.prepare(handoff, binding, role, 'json')
                    response = adapter.dispatch(handoff, binding, role, 'json')['response']
                    value = validate_deep_proposal(response, cluster, targets); state = 'pending'
                except BackendUnknown as exc:
                    value, state = {'error': str(exc), 'outcome': 'unknown'}, 'unknown'
                except Exception as exc:
                    value, state = {'error': str(exc), 'outcome': 'failed',
                                    'raw_response': response}, 'failed'
                with self._connect() as db, db:
                    db.execute('UPDATE proposals SET response=?,state=? WHERE id=? AND state=?',
                               (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                separators=(',', ':')), state, proposal_id, 'running'))
                created.append(self.get(proposal_id))
            with self._connect() as db:
                states = {fingerprint: state for fingerprint, state in db.execute(
                    "SELECT fingerprint,state FROM proposals WHERE project_id=? "
                    "AND mode='deep-check' AND expected_head=?", (self.project_id, head))
                    if fingerprint in current}
            done = {'pending', 'accepted', 'rejected', 'dismissed', 'applied', 'failed', 'unknown'}
            counts = {}
            for state in states.values():
                counts[state] = counts.get(state, 0) + 1
            return {'project_id': self.project_id, 'mode': 'deep-check',
                    'expected_head': head, 'total': len(fingerprints), 'created': created,
                    'forgotten': forgotten,
                    'remaining': sum(states.get(value) == 'queued' for value in current),
                    'states': counts, 'converged': bool(current) and
                    all(states.get(value) in done for value in current)}

    def list(self):
        with self._connect() as db:
            rows = db.execute('SELECT id,response,state,expected_head,created_at,receipt,document_id,mode,input_json FROM proposals '
                              'WHERE project_id=? ORDER BY created_at,id',
                              (self.project_id,)).fetchall()
        return [dict(proposal_id=row[0], proposal=json.loads(row[1]), state=row[2],
                     expected_head=row[3], created_at=row[4], receipt=json.loads(row[5]) if row[5] else None)
                     | {'document_id': row[6], 'mode': row[7], 'input': json.loads(row[8])}
                for row in rows]

    def review_context(self, row):
        """Resolve human review labels from the exact proposal revision."""
        require(isinstance(row, dict) and row.get('state') in {
            'pending', 'accepted', 'rejected', 'applied', 'dismissed',
            'queued', 'running', 'unknown', 'failed', 'needs-context'}, 'Invalid refinement review row')
        proposal_id = row.get('proposal_id'); uuid(proposal_id)
        require(self.get(proposal_id) is not None, 'Proposal is unavailable for this project')
        head = row.get('expected_head')
        workspace = Projects(self.node).workspace(self.project_id, blocking=False)
        files = workspace.git.snapshot(head); entities = validate_snapshot(files)
        project = committed_project(workspace.git, head, self.project_id)
        if row.get('mode') == 'dependency-check':
            frozen = row.get('input') or {}
            evidence = frozen.get('evidence', [])
            with self._connect() as db:
                active = [dict(json.loads(raw), operation_id=i)
                          for i, raw in db.execute('SELECT id,record FROM dependency_applies')]
            intent = next((i for i in active if i['project_id'] == self.project_id
                           and proposal_id in i['proposals'] and not i.get('outcome')
                           and not i.get('cancelled')), None)
            return dict(project_title=project['title'], source_title=frozen.get('stable_id', '-'),
                        source_path=', '.join(e['path'] for e in evidence),
                        source_excerpt='\n\n'.join(
                            f"Podklad {e['id']}: {e['path']}:{e['line_start']}-{e['line_end']} · SHA-256 {e['sha256']}\n{e['text']}"
                            for e in evidence), target=frozen.get('focus'), targets=[],
                        citations=row['proposal'].get('edges', []), pending_apply=intent)
        if row.get('mode') == 'deep-check':
            cluster = row.get('input') or {}
            occurrences = cluster.get('occurrences', [])
            titles = []
            paths = []
            excerpts = []
            for occurrence in occurrences:
                source = occurrence.get('source', {})
                title = source.get('title')
                if title and title not in titles:
                    titles.append(title)
                artifact_id = source.get('artifact_id')
                if artifact_id and artifact_id in entities:
                    path = 'artifacts/' + artifact_id + '/' + entities[artifact_id]['file']
                    if path not in paths:
                        paths.append(path)
                excerpt = occurrence.get('excerpt')
                if excerpt and excerpt not in excerpts:
                    excerpts.append(excerpt)
            target_ids = row['proposal'].get('target_ids', [])
            if not target_ids and cluster.get('current_target'):
                target_ids = [cluster['current_target']['id']]
            graph = project_task_graph(files, entities, self.project_id, head)
            selected = [item for item in graph['nodes'] if item['id'] in target_ids]
            return {
                'project_title': project['title'],
                'source_title': cluster.get('stable_id') or ' / '.join(titles) or cluster.get('cluster_id', '-'),
                'source_path': ', '.join(paths) or '-',
                'source_excerpt': '\n\n'.join(excerpts)[:16384],
                'target': selected[0] if len(selected) == 1 else None,
                'targets': selected,
                'cluster_id': cluster.get('cluster_id'),
            }
        document_id = row.get('document_id') or row['proposal'].get('document_id')
        require(document_id in entities, 'Proposal source document is unavailable')
        meta = entities[document_id]; raw = _content(files, meta).decode('utf-8')
        target_id = row['proposal'].get('target_id'); target = None
        if target_id:
            graph = project_task_graph(files, entities, self.project_id, head)
            target = next((item for item in graph['nodes'] if item['id'] == target_id), None)
        return {
            'project_title': project['title'],
            'source_title': meta['title'],
            'source_path': 'artifacts/' + document_id + '/' + meta['file'],
            'source_excerpt': raw[:4096],
            'target': target,
        }

    def get(self, proposal_id):
        uuid(proposal_id)
        return next((row for row in self.list() if row['proposal_id'] == proposal_id), None)

    def review_list(self):
        """Return a bounded UI projection without source excerpts or raw responses."""
        result = []
        for row in self.list():
            proposal = row['proposal']; frozen = row.get('input') or {}
            summary = {key: proposal[key] for key in (
                'decision', 'action', 'outcome', 'confidence', 'summary', 'target_id',
                'target_ids') if key in proposal}
            changes = proposal.get('changes') or []
            if row['mode'] == 'dependency-check':
                from spikes.roadmap_dependencies import changes as dependency_changes
                changes = dependency_changes(proposal) if proposal.get('edges') else []
                summary.update(action=proposal.get('decision', proposal.get('outcome', 'queued')),
                               target_ids=[e['target_id'] for e in proposal.get('edges', [])])
            impact = 'evidence' if not changes else 'mutation'
            risky = any(change.get('kind') in {'create-node', 'add-dependency',
                                                'remove-dependency'}
                        or change.get('checked') is not None for change in changes)
            result.append({key: row[key] for key in ('proposal_id', 'state', 'mode')}
                | {'proposal': summary,
                   'impact': impact, 'risk': 'high' if risky else ('medium' if changes else 'low'),
                   'source_label': (frozen.get('stable_id') or frozen.get('cluster_id')
                                    or row.get('document_id', '-')[:8])})
        return result

    def review_detail(self, proposal_id):
        row = self.get(proposal_id)
        require(row is not None, 'Proposal is unavailable for this project')
        public_row = {key: value for key, value in row.items() if key != 'input'}
        if row['mode'] == 'dependency-check':
            public_row['proposal'] = dict(row['proposal'], changes=row['proposal'].get('edges', []))
        return {'row': public_row, 'context': self.review_context(row)}

    def decide(self, proposal_id, decision):
        uuid(proposal_id); require(decision in {'accept', 'reject', 'reset'}, 'Unknown review decision')
        source = 'accepted' if decision == 'reset' else 'pending'
        target = 'pending' if decision == 'reset' else ('accepted' if decision == 'accept' else 'rejected')
        with self._connect() as db, db:
            db.execute('BEGIN IMMEDIATE')
            frozen = {p for (raw,) in db.execute('SELECT record FROM dependency_applies')
                      for intent in [json.loads(raw)] if intent['project_id'] == self.project_id
                      and not intent.get('outcome') and not intent.get('cancelled')
                      for p in intent['proposals']}
            require(proposal_id not in frozen, 'Review has a pending apply; recover or cancel it first')
            row = db.execute('SELECT state FROM proposals WHERE id=? AND project_id=?',
                             (proposal_id, self.project_id)).fetchone()
            require(row is not None and row[0] == source,
                    ('Proposal is not accepted' if decision == 'reset'
                     else 'Proposal is not pending review'))
            db.execute('UPDATE proposals SET state=? WHERE id=? AND project_id=?',
                       (target, proposal_id, self.project_id))
        return self.get(proposal_id)

    def decide_many(self, proposal_ids, decision):
        require(isinstance(proposal_ids, list) and 0 < len(proposal_ids) <= 100000
                and len(proposal_ids) == len(set(proposal_ids)),
                'Invalid proposal decision list')
        for proposal_id in proposal_ids:
            uuid(proposal_id)
        require(decision in {'accept', 'reject', 'reset'}, 'Unknown review decision')
        source = 'accepted' if decision == 'reset' else 'pending'
        with self._connect() as db, db:
            # Serialize validation and the whole batch update. A concurrent
            # CLI/TUI decision cannot slip between the pending check and write.
            db.execute('BEGIN IMMEDIATE')
            frozen = {p for (raw,) in db.execute('SELECT record FROM dependency_applies')
                      for intent in [json.loads(raw)] if intent['project_id'] == self.project_id
                      and not intent.get('outcome') and not intent.get('cancelled')
                      for p in intent['proposals']}
            require(not frozen.intersection(proposal_ids), 'Review has a pending apply; recover or cancel it first')
            available = {row[0] for row in db.execute(
                'SELECT id FROM proposals WHERE project_id=? AND state=?',
                (self.project_id, source))}
            require(set(proposal_ids) <= available,
                    ('Some proposals are no longer accepted' if decision == 'reset'
                     else 'Some proposals are no longer pending review'))
            target = 'pending' if decision == 'reset' else ('accepted' if decision == 'accept' else 'rejected')
            db.executemany('UPDATE proposals SET state=? WHERE id=? AND project_id=? AND state=?',
                           ((target, proposal_id, self.project_id, source)
                            for proposal_id in proposal_ids))
        return {'project_id': self.project_id, 'decision': decision,
                'updated': len(proposal_ids), 'proposal_ids': proposal_ids}

    def _reconciliation(self, proposal_ids=None):
        accepted = [row for row in self.list() if row['state'] == 'accepted']
        if proposal_ids is not None:
            require(isinstance(proposal_ids, list) and proposal_ids
                    and len(proposal_ids) == len(set(proposal_ids)),
                    'Invalid reconciliation proposal selection')
            for proposal_id in proposal_ids:
                uuid(proposal_id)
            selected = set(proposal_ids)
            accepted = [row for row in accepted if row['proposal_id'] in selected]
            require({row['proposal_id'] for row in accepted} == selected,
                    'Some selected proposals are no longer accepted')
        require(bool(accepted), 'No accepted refinement proposals')
        heads = {row['expected_head'] for row in accepted}; require(len(heads) == 1, 'Accepted proposals use different HEADs')
        expected_head = heads.pop(); workspace = Projects(self.node).workspace(self.project_id, blocking=False)
        files = workspace.git.snapshot(expected_head); entities = validate_snapshot(files)
        graph = project_task_graph(files, entities, self.project_id, expected_head)
        require(graph['status'] == 'ready', 'Project task graph is invalid')
        targets = {item['id']: {'type': item['type'], 'title': item['title'],
                                'parent_id': item['parent_id']} for item in graph['nodes']}
        candidate = dict(files); evidence = []; mutations = []; blockers = []
        if workspace.git.head() != expected_head:
            blockers.append({'proposal_id': None,
                             'reason': 'Project HEAD changed after accepted proposals'})
        root_id = main_todo_id(self.project_id); meta = entities[root_id]
        root_path = document(files, entities, root_id)['path']
        for row in accepted:
            try:
                if row['mode'] == 'detached':
                    proposal = row['proposal']; require(proposal['target_id'] in targets,
                                                        'Accepted target disappeared')
                    body = candidate[root_path].decode('utf-8')
                    candidate[root_path] = attach_document(
                        body, proposal['document_id'], proposal['target_id']).encode('utf-8')
                    mutations.append((row['proposal_id'], {'kind': 'attach-document'}))
                    continue
                if row['mode'] == 'dependency-check':
                    from spikes.roadmap_dependencies import focus_input, validate, changes as dependency_changes
                    task = next((t for t in graph['nodes'] if t['id'] == row['input'].get('stable_id')), None)
                    require(task is not None, 'Dependency focus disappeared')
                    require(row['input'] == focus_input(task, graph, files, entities),
                            'Dependency evidence differs from pinned snapshot')
                    value = validate(json.dumps(row['proposal'], ensure_ascii=False), row['input'])
                    proposal = {'changes': dependency_changes(value)}
                else:
                    require(row['mode'] == 'deep-check', 'Unknown accepted proposal mode')
                    proposal = validate_deep_proposal(json.dumps(row['proposal'], ensure_ascii=False),
                                                      row['input'], targets)
                if not proposal['changes']:
                    evidence.append(row['proposal_id']); continue
                for change in proposal['changes']:
                    mutations.append((row['proposal_id'], change))
            except (ValueError, KeyError, TypeError) as exc:
                blockers.append({'proposal_id': row['proposal_id'], 'reason': str(exc)})
        touched = {}
        for proposal_id, change in mutations:
            if change['kind'] == 'attach-document':
                continue
            key = (change['kind'], change.get('node_id'), change.get('target_id'))
            owner = touched.get(key)
            if owner:
                blockers.append({'proposal_id': proposal_id,
                                 'reason': 'Structured change duplicates proposal ' + owner})
            else:
                touched[key] = proposal_id
        if not blockers:
            for proposal_id, change in mutations:
                if change['kind'] == 'attach-document':
                    continue
                try:
                    candidate = _deep_change(candidate, entities, self.project_id,
                                             expected_head, change)
                except (ValueError, KeyError, TypeError) as exc:
                    blockers.append({'proposal_id': proposal_id, 'reason': str(exc)})
                    break
        changes = {path: body for path, body in candidate.items()
                   if files.get(path) != body}
        digest_input = {'project_id': self.project_id, 'expected_head': expected_head,
                        'proposals': [row['proposal_id'] for row in accepted],
                        'changes': {path: hashlib.sha256(body).hexdigest()
                                    for path, body in sorted(changes.items())}}
        preview_sha256 = hashlib.sha256(canonical(digest_input)).hexdigest()
        diffs = []
        for path, body in sorted(changes.items()):
            before = files[path].decode('utf-8').splitlines()
            after = body.decode('utf-8').splitlines()
            diffs.extend(difflib.unified_diff(before, after, fromfile='a/' + path,
                                               tofile='b/' + path, lineterm=''))
        diff = '\n'.join(diffs)
        require(len(diff.encode('utf-8')) <= 256 * 1024,
                'Reconciliation preview diff exceeds limit')
        return {'project_id': self.project_id, 'expected_head': expected_head,
                'preview_sha256': preview_sha256,
                'proposal_ids': [row['proposal_id'] for row in accepted],
                'evidence_only': evidence, 'mutation_count': len(mutations),
                'changed_files': sorted(changes), 'blockers': blockers,
                'diff': diff}, changes

    def reconciliation_preview(self, proposal_ids=None):
        return self._reconciliation(proposal_ids)[0]

    def cancel_dependency_apply(self, operation_id):
        """An unstarted intent may be cancelled while holding the native writer lock."""
        uuid(operation_id)
        workspace = Projects(self.node).workspace(self.project_id)
        with workspace.journal.lock(), workspace.journal.connect() as native:
            require(not native.execute('SELECT 1 FROM operations WHERE id=?', (operation_id,)).fetchone(),
                    'Native apply has started; recover it instead of cancelling')
            with self._connect() as db, db:
                row = db.execute('SELECT record FROM dependency_applies WHERE id=?', (operation_id,)).fetchone()
                require(row is not None, 'Dependency apply is unavailable')
                intent = json.loads(row[0])
                require(intent['project_id'] == self.project_id and not intent.get('outcome'),
                        'Dependency apply cannot be cancelled')
                intent['cancelled'] = True
                db.execute('UPDATE dependency_applies SET record=? WHERE id=?',
                           (json.dumps(intent, sort_keys=True), operation_id))
        return dict(operation_id=operation_id, state='cancelled')

    def apply(self, operation_id, preview_sha256=None, proposal_ids=None, *, checkpoint=lambda stage: None):
        uuid(operation_id)
        with self._connect() as db:
            intent = db.execute('SELECT record FROM dependency_applies WHERE id=?', (operation_id,)).fetchone()
        selected = [row for row in self.list() if row['state'] == 'accepted'
                    and (proposal_ids is None or row['proposal_id'] in proposal_ids)]
        if intent or any(row['mode'] == 'dependency-check' for row in selected):
            from spikes.roadmap_dependencies import apply_review
            return apply_review(self, operation_id, preview_sha256, proposal_ids, checkpoint)
        preview, changes = self._reconciliation(proposal_ids)
        require(not preview['blockers'], 'Reconciliation preview has blockers')
        if preview_sha256 is not None:
            require(preview_sha256 == preview['preview_sha256'],
                    'Reconciliation preview changed before apply')
        expected_head = preview['expected_head']; accepted_ids = preview['proposal_ids']
        workspace = Projects(self.node).workspace(self.project_id)
        request = {'action': 'apply-roadmap-refinement', 'project_id': self.project_id,
                   'proposals': accepted_ids, 'expected_head': expected_head,
                   'preview_sha256': preview['preview_sha256']}

        def prepare(active):
            require(active.git.head() == expected_head, 'Project changed before refinement apply')
            author = ProjectCreation(self.node).author_id()
            return changes, 'Local workspace author', author + '@local.invalid', 'Apply reviewed roadmap refinement'

        if changes:
            receipt = workspace.transact(operation_id, request, prepare,
                                         expected_head=expected_head)
        else:
            require(workspace.git.head() == expected_head,
                    'Project changed before evidence-only reconciliation')
            receipt = {'operation_id': operation_id, 'commit_id': expected_head,
                       'state': 'evidence-only'}
        with self._connect() as db, db:
            for proposal_id in accepted_ids:
                db.execute("UPDATE proposals SET state='applied',receipt=? "
                           "WHERE id=? AND project_id=? AND state='accepted'",
                           (json.dumps(receipt, sort_keys=True, separators=(',', ':')),
                            proposal_id, self.project_id))
        return {'operation_id': operation_id, 'receipt': receipt,
                'applied_proposals': accepted_ids,
                'evidence_only': preview['evidence_only']}
