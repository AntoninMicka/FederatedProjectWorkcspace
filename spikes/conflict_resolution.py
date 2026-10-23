# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""HEAD-bound federation divergence preview and explicit two-parent publication."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time

from spikes.configuration import committed_project
from spikes.administration import Administration, content_authority
from spikes.metadata import MAX_FILE, require, uuid, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import StaleIndex
from spikes.workspace import PendingOperation


MAX_CONFLICT_REFS = 100
MAX_PATHS = 1000
COMMIT = r'(?:[0-9a-f]{40}|[0-9a-f]{64})'
INCOMING = re.compile(
    r'^refs/federation/incoming/'
    r'(?P<peer>[0-9a-f-]{36})/(?P<operation>[0-9a-f-]{36})/(?P<branch>.+)$')


def _commit(value):
    require(isinstance(value, str) and re.fullmatch(COMMIT, value),
            'Expected full commit ID')


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()


class ConflictResolution:
    def __init__(self, node_path, *, timeout=60, network=False):
        self.node_path = Path(node_path).absolute()
        self.timeout = timeout
        self.network = network
        self.projects = Projects(node_path, network=network)
        self.administration = Administration(node_path)

    def _workspace(self, project_id):
        uuid(project_id)
        return self.projects.workspace(
            project_id, blocking=False, deadline=time.monotonic() + self.timeout)

    def _validate_commit(self, git, project_id, revision):
        _commit(revision)
        resolved = git.run('rev-parse', '--verify', revision + '^{commit}').stdout.strip()
        require(resolved == revision, 'Expected commit object')
        committed_project(git, revision, project_id, check_worktree=False)
        files = git.snapshot(revision)
        entities = validate_snapshot(files)
        if self.network:
            require(all(item['privacy'] != 'local-only'
                        for item in entities.values()),
                    'Project contains local-only data')
        return files

    @contextmanager
    def _read(self, project_id, expected_head):
        _commit(expected_head)
        ws = self._workspace(project_id)
        with ws.journal.lock(), ws.journal.connect() as db:
            if ws._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
                raise PendingOperation(
                    'Projekt má nedokončenou operaci. Řešení konfliktu ji neobnovuje.')
            branch = ws._branch()
            require(not ws.git.run('ls-files', '-u').stdout, 'Unresolved Git operation')
            require(ws.git.head() == expected_head,
                    'Projekt se změnil. Znovu načtěte historii konfliktu.')
            self._validate_commit(ws.git, project_id, expected_head)
            yield ws, branch
            if ws.git.head() != expected_head:
                raise StaleIndex('Projekt se během čtení změnil.')

    def _refs(self, git, branch):
        suffix = branch[len('refs/heads/'):]
        output = git.run('for-each-ref',
                         '--format=%(refname) %(objectname)',
                         'refs/federation/incoming/').stdout.splitlines()
        require(len(output) <= MAX_CONFLICT_REFS, 'Too many incoming conflict refs')
        rows = []
        for line in output:
            ref, head = line.split(' ', 1)
            match = INCOMING.fullmatch(ref)
            require(match is not None, 'Invalid incoming conflict ref')
            uuid(match['peer']); uuid(match['operation']); _commit(head)
            require(git.run('check-ref-format',
                            'refs/heads/' + match['branch'], check=False).returncode == 0,
                    'Invalid incoming branch')
            if match['branch'] == suffix:
                rows.append(dict(ref=ref, head=head, peer_id=match['peer'],
                                 operation_id=match['operation'], branch=match['branch']))
        return rows

    def _selected(self, git, branch, expected_head, incoming_ref,
                  incoming_head=None, project_id=None):
        row = next((item for item in self._refs(git, branch)
                    if item['ref'] == incoming_ref), None)
        require(row is not None, 'Incoming conflict is unavailable')
        if incoming_head is not None:
            require(row['head'] == incoming_head, 'Incoming conflict changed')
        if project_id is not None:
            self._validate_commit(git, project_id, row['head'])
        require(git.run('merge-base', '--is-ancestor', row['head'], expected_head,
                        check=False).returncode != 0,
                'Incoming history is already merged')
        require(git.run('merge-base', '--is-ancestor', expected_head, row['head'],
                        check=False).returncode != 0,
                'Incoming history can be fast-forwarded')
        bases = git.run('merge-base', '--all', expected_head,
                        row['head']).stdout.splitlines()
        require(len(bases) == 1, 'Expected one merge base')
        _commit(bases[0]); row['base'] = bases[0]
        if project_id is not None:
            row['authority'] = content_authority(
                self.administration, row['peer_id'], project_id, branch)
        return row

    def list(self, project_id, expected_head):
        with self._read(project_id, expected_head) as (ws, branch):
            rows = []
            for item in self._refs(ws.git, branch):
                if ws.git.run('merge-base', '--is-ancestor', item['head'],
                              expected_head, check=False).returncode == 0:
                    continue
                selected = self._selected(ws.git, branch, expected_head,
                                          item['ref'], project_id=project_id)
                info = ws.git.run(
                    'show', '-s', '--format=%aI%x00%an%x00%s',
                    selected['head']).stdout.rstrip('\n').split('\0', 2)
                rows.append(dict(selected, date=info[0], author=info[1],
                                 subject=info[2]))
            return {'head': expected_head, 'conflicts': rows}

    def _plan(self, git, project_id, expected_head, branch, incoming_ref,
              incoming_head=None):
        selected = self._selected(git, branch, expected_head, incoming_ref,
                                  incoming_head, project_id)
        base, theirs = selected['base'], selected['head']
        base_files = git.snapshot(base)
        ours_files = git.snapshot(expected_head)
        theirs_files = git.snapshot(theirs)
        changed, renames = set(), {}
        for left, right in ((base, expected_head), (base, theirs)):
            names = set(filter(None, git.run(
                'diff', '--name-only', '-z', '--no-renames', left,
                right).stdout.split('\0')))
            require(all(path.startswith(('artifacts/', 'registries/'))
                        for path in names),
                    'Conflict changes unsupported project files')
            changed.update(names)
            tokens = git.run('diff', '--name-status', '-z', '-M',
                             left, right).stdout.split('\0')
            index = 0
            while index < len(tokens) and tokens[index]:
                status = tokens[index]
                if status.startswith(('R', 'C')):
                    require(index + 2 < len(tokens), 'Invalid Git rename inventory')
                    old, new = tokens[index + 1:index + 3]
                    renames[old] = new; renames[new] = old
                    index += 3
                else:
                    require(index + 1 < len(tokens), 'Invalid Git path inventory')
                    index += 2
        require(changed and len(changed) <= MAX_PATHS,
                'Conflict has no supported changes or exceeds path limit')
        with tempfile.TemporaryDirectory() as temporary:
            objects = Path(temporary) / 'objects'; objects.mkdir()
            (objects / 'pack').mkdir(); (objects / 'info').mkdir()
            env = {'GIT_OBJECT_DIRECTORY': str(objects),
                   'GIT_ALTERNATE_OBJECT_DIRECTORIES': str(git.root / '.git' / 'objects')}
            result = git.run('merge-tree', '--write-tree', '--merge-base', base,
                             '--name-only', '--no-messages', expected_head, theirs,
                             check=False, env_extra=env)
            lines = result.stdout.splitlines()
            require(lines and re.fullmatch(COMMIT, lines[0]),
                    'Git did not produce a merge candidate')
            tree = lines[0]
            conflicts = set(lines[1:])
            require(result.returncode in {0, 1} and conflicts <= changed,
                    'Invalid Git merge result')
            candidate_files = git.snapshot(tree, env_extra=env)
        paths = []
        digest_rows = []
        for path in sorted(changed):
            versions = {name: files.get(path) for name, files in
                        [('base', base_files), ('ours', ours_files),
                         ('theirs', theirs_files), ('result', candidate_files)]}
            texts = {}
            editable = True
            for name, raw in versions.items():
                if raw is None:
                    texts[name] = None
                    continue
                try:
                    text = raw.decode('utf-8')
                    require('\0' not in text and len(raw) <= MAX_FILE,
                            'Unsupported text')
                    texts[name] = text
                except (UnicodeError, ValueError):
                    texts[name] = None; editable = False
            status = ('rename/update' if path in renames else
                      'add/add' if versions['base'] is None
                      and versions['ours'] is not None
                      and versions['theirs'] is not None else
                      'change/delete' if ((versions['ours'] is None)
                      != (versions['theirs'] is None)) else
                      'content')
            row = dict(path=path, conflict=path in conflicts, status=status,
                       editable=editable,
                       renamed_path=renames.get(path),
                       **{name + '_exists': raw is not None
                          for name, raw in versions.items()}, **texts)
            paths.append(row)
            digest_rows.append({key: (None if raw is None else hashlib.sha256(raw).hexdigest())
                                for key, raw in versions.items()} | {
                                    'path': path, 'conflict': path in conflicts})
        identity = dict(project_id=project_id, expected_head=expected_head,
                        incoming_ref=incoming_ref, incoming_head=theirs,
                        base=base, authority=selected['authority'],
                        paths=digest_rows)
        return dict(identity, preview_sha256=hashlib.sha256(_canonical(identity)).hexdigest(),
                    files=paths), dict(base=base_files, ours=ours_files,
                                      theirs=theirs_files,
                                      result=candidate_files,
                                      conflicts=conflicts)

    def preview(self, project_id, expected_head, incoming_ref):
        require(isinstance(incoming_ref, str), 'Invalid incoming ref')
        with self._read(project_id, expected_head) as (ws, branch):
            view, _ = self._plan(ws.git, project_id, expected_head, branch,
                                 incoming_ref)
            return view

    def confirm(self, request, operation_id, *, checkpoint=lambda stage: None):
        require(isinstance(request, dict) and set(request) == {
            'project_id', 'expected_head', 'incoming_ref', 'incoming_head',
            'base', 'preview_sha256', 'resolutions'}, 'Invalid conflict resolution request')
        uuid(operation_id); uuid(request['project_id'])
        _commit(request['expected_head']); _commit(request['incoming_head']); _commit(request['base'])
        require(isinstance(request['incoming_ref'], str)
                and isinstance(request['preview_sha256'], str)
                and re.fullmatch(r'[0-9a-f]{64}', request['preview_sha256'])
                and isinstance(request['resolutions'], list),
                'Invalid conflict resolution request')
        ws = self._workspace(request['project_id'])
        author = ProjectCreation(self.node_path).author_id()

        def prepare(workspace):
            branch = workspace._branch()
            view, raw = self._plan(
                workspace.git, request['project_id'], request['expected_head'],
                branch, request['incoming_ref'], request['incoming_head'])
            require(view['base'] == request['base']
                    and view['preview_sha256'] == request['preview_sha256'],
                    'Conflict preview changed')
            rows = request['resolutions']
            require(len(rows) == len(view['files'])
                    and all(isinstance(row, dict) for row in rows),
                    'Every changed path requires one resolution')
            supplied = {row.get('path'): row for row in rows}
            require(len(supplied) == len(rows)
                    and set(supplied) == {row['path'] for row in view['files']},
                    'Resolution paths differ from preview')
            final = dict(raw['ours'])
            for item in view['files']:
                row = supplied[item['path']]
                require(set(row) <= {'path', 'choice', 'text'}
                        and row.get('choice') in {
                            'auto', 'ours', 'theirs', 'both', 'manual', 'delete'},
                        'Invalid path resolution')
                choice = row['choice']; path = item['path']
                if choice == 'auto':
                    require(not item['conflict'], 'Conflicted path needs an explicit resolution')
                    value = raw['result'].get(path)
                elif choice in {'ours', 'theirs'}:
                    value = raw[choice].get(path)
                elif choice == 'both':
                    require(item['editable'] and item['ours'] is not None
                            and item['theirs'] is not None,
                            'Both requires two UTF-8 text versions')
                    value = (item['ours'] + ('\n' if item['ours']
                             and not item['ours'].endswith('\n') else '')
                             + item['theirs']).encode()
                elif choice == 'manual':
                    require(item['editable'] and isinstance(row.get('text'), str)
                            and '\0' not in row['text']
                            and len(row['text'].encode()) <= MAX_FILE,
                            'Manual resolution requires bounded UTF-8 text')
                    value = row['text'].encode()
                else:
                    value = None
                if value is None:
                    final.pop(path, None)
                else:
                    final[path] = value
            entities = validate_snapshot(final)
            if self.network:
                require(all(item['privacy'] != 'local-only'
                            for item in entities.values()),
                        'Project contains local-only data')
            changes = {path: final.get(path) for path in
                       set(raw['ours']) | set(final)
                       if raw['ours'].get(path) != final.get(path)}
            return (changes, 'Local workspace author',
                    author + '@local.invalid', 'Resolve federated divergence')

        return ws.transact(
            operation_id, request, prepare,
            expected_head=request['expected_head'],
            additional_parents=[request['incoming_head']], checkpoint=checkpoint)
