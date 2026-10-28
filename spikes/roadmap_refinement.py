# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Local Ollama proposals for attaching detached roadmap evidence."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from uuid import NAMESPACE_URL, uuid4, uuid5

from spikes.backend_contract import ROLES
from spikes.backend_contract import BackendUnknown
from spikes.configuration import parse_node, read_config
from spikes.context_builder import (AdHocInput, Authority, ContextBuilder,
                                    ProjectInput, TaskInstruction)
from spikes.markdown_documents import main_todo_id
from spikes.metadata import MAX_FILE, pairs, require, uuid, validate_snapshot
from spikes.ollama_backend import OllamaAdapter, OllamaBinding, OllamaBindings, OllamaRuns
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.roadmap_migration import LINK
from spikes.task_graph import project_task_graph

SCHEMA = 'fpw-roadmap-refinement-proposal-v1'
ANALYZER_REVISION = 'attach-detached-v3'
HEADING = '## Samostatné podklady bez jednoznačného přiřazení'
INSTRUCTION = '''Review one detached roadmap evidence document against the supplied target catalog.
Return exactly one JSON object with fields:
{"schema":"fpw-roadmap-refinement-proposal-v1","decision":"attach|keep-detached","document_id":"UUID","target_id":"stable ID or null","confidence":"low|medium|high","reason":"Czech explanation"}.
Use attach only when the source provides clear evidence for exactly one existing target. Copy target_id exactly from an "id" field in the supplied catalog. Never invent IDs, rewrite content, change completion state, merge, delete, or use a target absent from the catalog. Use keep-detached when ambiguous. Return JSON only.'''


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
        # Older local queues stored a globally unique bare digest. Prefixing it
        # preserves every durable review while making uniqueness project-local.
        legacy = db.execute("SELECT 1 FROM proposals WHERE instr(fingerprint, ':')=0 LIMIT 1").fetchone()
        if legacy:
            db.execute("UPDATE proposals SET fingerprint=project_id || ':' || fingerprint "
                       "WHERE instr(fingerprint, ':')=0")
        db.commit(); return closing(db)

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
        body = _content(files, entities[root_id]).decode('utf-8')
        graph = project_task_graph(files, entities, self.project_id, head)
        require(graph['status'] == 'ready', 'Project task graph is invalid')
        targets = {item['id']: {'type': item['type'], 'title': item['title'],
                                'parent_id': item['parent_id']}
                   for item in graph['nodes']}
        return workspace, head, files, entities, root_id, body, targets

    def scan(self, *, limit=1):
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
                db.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                           (proposal_id, fingerprint, self.project_id, head, document_id,
                            hashlib.sha256(raw).hexdigest(), '{}', 'running', now()))
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

    def list(self):
        with self._connect() as db:
            rows = db.execute('SELECT id,response,state,expected_head,created_at,receipt FROM proposals '
                              'WHERE project_id=? ORDER BY created_at,id',
                              (self.project_id,)).fetchall()
        return [dict(proposal_id=row[0], proposal=json.loads(row[1]), state=row[2],
                     expected_head=row[3], created_at=row[4], receipt=json.loads(row[5]) if row[5] else None)
                for row in rows]

    def get(self, proposal_id):
        uuid(proposal_id)
        return next((row for row in self.list() if row['proposal_id'] == proposal_id), None)

    def decide(self, proposal_id, decision):
        uuid(proposal_id); require(decision in {'accept', 'reject'}, 'Unknown review decision')
        with self._connect() as db, db:
            row = db.execute('SELECT state FROM proposals WHERE id=? AND project_id=?',
                             (proposal_id, self.project_id)).fetchone()
            require(row is not None and row[0] == 'pending', 'Proposal is not pending review')
            db.execute('UPDATE proposals SET state=? WHERE id=? AND project_id=?',
                       ('accepted' if decision == 'accept' else 'rejected',
                        proposal_id, self.project_id))
        return self.get(proposal_id)

    def apply(self, operation_id):
        uuid(operation_id)
        accepted = [row for row in self.list() if row['state'] == 'accepted']
        require(bool(accepted), 'No accepted refinement proposals')
        heads = {row['expected_head'] for row in accepted}; require(len(heads) == 1, 'Accepted proposals use different HEADs')
        expected_head = heads.pop(); workspace = Projects(self.node).workspace(self.project_id)
        request = {'action': 'apply-roadmap-refinement', 'project_id': self.project_id,
                   'proposals': [row['proposal_id'] for row in accepted], 'expected_head': expected_head}

        def prepare(active):
            require(active.git.head() == expected_head, 'Project changed before refinement apply')
            files = active.git.snapshot(expected_head); entities = validate_snapshot(files)
            root_id = main_todo_id(self.project_id); meta = entities[root_id]
            path = 'artifacts/' + root_id + '/' + meta['file']; body = files[path].decode('utf-8')
            graph = project_task_graph(files, entities, self.project_id, expected_head)
            targets = {item['id'] for item in graph['nodes']}
            for row in accepted:
                proposal = row['proposal']; require(proposal['target_id'] in targets, 'Accepted target disappeared')
                body = attach_document(body, proposal['document_id'], proposal['target_id'])
            candidate = dict(files); candidate[path] = body.encode(); candidate_entities = validate_snapshot(candidate)
            require(project_task_graph(candidate, candidate_entities, self.project_id, expected_head)['status'] == 'ready',
                    'Refined task graph is invalid')
            author = ProjectCreation(self.node).author_id()
            return {path: body.encode()}, 'Local workspace author', author + '@local.invalid', 'Apply reviewed roadmap refinement'

        receipt = workspace.transact(operation_id, request, prepare, expected_head=expected_head)
        with self._connect() as db, db:
            for row in accepted:
                db.execute("UPDATE proposals SET state='applied',receipt=? "
                           "WHERE id=? AND project_id=? AND state='accepted'",
                           (json.dumps(receipt, sort_keys=True, separators=(',', ':')),
                            row['proposal_id'], self.project_id))
        return {'operation_id': operation_id, 'receipt': receipt,
                'applied_proposals': [row['proposal_id'] for row in accepted]}
