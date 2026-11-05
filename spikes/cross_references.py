# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Local cross-project read-only references, explicit repinning and local forks.

Source authorization is live. Offline cache is same-node display only and
never a Context Manifest/fork input. No cross-repository transaction or network.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile

from spikes.administration import Administration, AccessDenied
from spikes.artifacts import Artifacts
from spikes.configuration import committed_project, overlap, parse_node, read_config
from spikes.metadata import MAX_FILE, parse_json, require, uuid, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.projects import directory
from spikes.reference_schema import SCHEMA, FORK, descriptor, pin, references
from spikes.reporting_schema import PRIVACY, digest, encoded, fields, hex_id, text
from spikes.storage import StaleIndex
from spikes.workspace import PendingOperation


class ReferenceUnavailable(ValueError):
    def __init__(self, state):
        super().__init__('Reference source unavailable: ' + state)
        self.state = state


class CrossReferences:
    def __init__(self, node_path, *, user_id=None, allowed_projects=None, writable_projects=None):
        self.node = Path(node_path).absolute()
        self.artifacts = Artifacts(self.node)
        self.user_id = user_id or ProjectCreation(self.node).author_id()
        uuid(self.user_id)
        self.allowed_projects = None if allowed_projects is None else frozenset(allowed_projects)
        self.writable_projects = None if writable_projects is None else frozenset(writable_projects)
        for scope in (self.allowed_projects, self.writable_projects):
            if scope is not None:
                for project_id in scope: uuid(project_id)
        self.cache = self.node.parent / ('.' + self.node.name + '.reference-cache')

    def authorize(self, project_id, *, write=False):
        """Re-read active grants before revealing any source title or existence."""
        uuid(project_id)
        if ((self.allowed_projects is not None and project_id not in self.allowed_projects)
                or (write and self.writable_projects is not None and project_id not in self.writable_projects)):
            raise AccessDenied('Reference access denied')
        node = parse_node(read_config(self.node), location=self.node)
        if self.user_id == ProjectCreation(self.node).author_id():
            actor = dict(id=self.user_id, node_role='local-node-owner', node_id=node['id'])
        else:
            admin = Administration(self.node)
            try:
                with admin.read_locked() as state:
                    actor = next((u for u in state['users'] if u['id'] == self.user_id and u['active']), None)
                    if not actor or not Administration.allowed(actor, project_id):
                        raise AccessDenied('Reference access denied')
                    if write and not (Administration.is_admin(actor) or actor['memberships'].get(project_id) in {'editor', 'project-admin'}):
                        raise AccessDenied('Reference write access denied')
            except FileNotFoundError as exc:
                raise AccessDenied('Reference access denied') from exc
        if not any(p['project_id'] == project_id for p in node['projects']):
            raise AccessDenied('Reference access denied')
        # Cache authorization binds current grants/registration, not old claims
        # stored alongside the cached body. No filesystem path enters project Git.
        return digest(encoded(dict(actor=actor, project_id=project_id, node_id=node['id'],
            allowed_projects=sorted(self.allowed_projects) if self.allowed_projects is not None else None,
            writable_projects=sorted(self.writable_projects) if self.writable_projects is not None else None)))

    @staticmethod
    def content(files, entities, artifact_id):
        require(artifact_id in entities, 'Source artifact is unavailable')
        require(artifact_id not in references(files, entities), 'Reference chains are outside XREF-01')
        prefix = f'artifacts/{artifact_id}/'
        paths = [p for p in files if p.startswith(prefix) and not p.endswith('/metadata.json')]
        require(len(paths) == 1, 'Source has no unique artifact content')
        return paths[0], files[paths[0]], entities[artifact_id]

    @staticmethod
    def pinned(project_id, head, path, raw, meta):
        return dict(project_id=project_id, repository='fpw-project-git:' + project_id,
            artifact_id=meta['id'], commit_id=head, path=path, sha256=digest(raw),
            metadata_sha256=digest(encoded(meta)), privacy=meta['privacy'])

    def source_pin(self, project_id, artifact_id, commit_id=None):
        self.authorize(project_id); uuid(artifact_id)
        ws = self.artifacts.workspace(project_id)
        with ws.journal.lock(), ws.journal.connect() as db:
            ws._read_locked(db)
            head = ws.git.head(); committed_project(ws.git, head, project_id)
            current = ws.git.snapshot(head); current_entities = validate_snapshot(current)
            require(artifact_id in current_entities, 'Source artifact is unavailable')
            selected = commit_id or head; hex_id(selected, True)
            require(ws.git.run('rev-parse', '--verify', selected + '^{commit}').stdout.strip() == selected, 'Full source commit required')
            committed_project(ws.git, selected, project_id, check_worktree=False)
            files = ws.git.snapshot(selected); entities = validate_snapshot(files)
            path, raw, meta = self.content(files, entities, artifact_id)
            result = self.pinned(project_id, selected, path, raw, meta)
            self.authorize(project_id)
            require(ws.git.head() == head, 'Source changed while pinning')
            return result

    def live(self, source, *, boundary='same-node'):
        pin(source)
        access = self.authorize(source['project_id'])
        ws = self.artifacts.workspace(source['project_id'])
        with ws.journal.lock(), ws.journal.connect() as db:
            # Nonblocking writer locks prevent reciprocal A→B/B→A deadlocks.
            ws._read_locked(db)
            head = ws.git.head(); committed_project(ws.git, head, source['project_id'])
            current = ws.git.snapshot(head); current_entities = validate_snapshot(current)
            if source['artifact_id'] not in current_entities:
                raise ReferenceUnavailable('deleted')
            try:
                require(ws.git.run('rev-parse', '--verify', source['commit_id'] + '^{commit}').stdout.strip() == source['commit_id'], 'Invalid pinned source commit')
                committed_project(ws.git, source['commit_id'], source['project_id'], check_worktree=False)
                files = ws.git.snapshot(source['commit_id']); entities = validate_snapshot(files)
                path, raw, meta = self.content(files, entities, source['artifact_id'])
            except (KeyError, ValueError) as exc:
                raise ReferenceUnavailable('invalid-pin') from exc
            require(self.pinned(source['project_id'], source['commit_id'], path, raw, meta) == source,
                    'Pinned source content or metadata differs')
            latest_path, latest_raw, latest_meta = self.content(current, current_entities, source['artifact_id'])
            privacy = max(source['privacy'], latest_meta['privacy'], key=PRIVACY.get)
            require(privacy != 'local-only' or boundary == 'same-node', 'local-only requires same-node execution')
            latest = self.pinned(source['project_id'], head, latest_path, latest_raw, latest_meta)
            newer = latest if (latest['path'], latest['sha256'], latest['metadata_sha256']) != (source['path'], source['sha256'], source['metadata_sha256']) else None
            require(self.authorize(source['project_id']) == access and ws.git.head() == head,
                    'Source access or HEAD changed while reading')
            return dict(raw=raw, metadata=meta, privacy=privacy, source_head=head,
                        access_revision=access, newer=newer)

    def _cache_path(self, source):
        return self.cache / (digest(encoded(dict(user_id=self.user_id, source=source))) + '.json')

    def cache_location(self):
        require(self.node == self.node.resolve(), 'Node configuration must not use symlinks')
        node = parse_node(read_config(self.node), location=self.node)
        require(not any(overlap(self.cache, Path(p[key])) for p in node['projects'] for key in ('root','state_dir')),
                'Reference cache must remain outside project Git and authoritative state')

    def save_cache(self, source, result):
        self.cache_location()
        self.cache.mkdir(mode=0o700, exist_ok=True); directory(self.cache, private=True)
        value = dict(schema='fpw-reference-cache-v1', user_id=self.user_id, source=source,
                     raw=base64.b64encode(result['raw']).decode(), metadata=result['metadata'],
                     privacy=result['privacy'], source_head=result['source_head'],
                     access_revision=result['access_revision'], verified_at=self.now())
        destination = self._cache_path(source)
        fd, temporary = tempfile.mkstemp(prefix='.reference-', dir=self.cache)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, destination)
            fd = os.open(self.cache, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(fd)
            finally: os.close(fd)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def load_cache(self, source):
        self.cache_location()
        access = self.authorize(source['project_id'])
        directory(self.cache, private=True)
        fd = os.open(self._cache_path(source), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
                    and not info.st_mode & 0o077, 'Unsafe reference cache')
            value = parse_json(stream.read(24 * 1024 * 1024 + 1), maximum=24 * 1024 * 1024)
        fields(value, 'schema user_id source raw metadata privacy source_head access_revision verified_at')
        require(value['schema'] == 'fpw-reference-cache-v1' and value['source'] == source
                and value['user_id'] == self.user_id and value['access_revision'] == access, 'Cached reference authorization changed')
        raw = base64.b64decode(value['raw'], validate=True)
        require(len(raw) <= MAX_FILE and digest(raw) == source['sha256']
                and digest(encoded(value['metadata'])) == source['metadata_sha256'], 'Reference cache hash mismatch')
        require(value['privacy'] in PRIVACY and PRIVACY[value['privacy']] >= PRIVACY[source['privacy']], 'Invalid cached privacy')
        return dict(raw=raw, metadata=value['metadata'], privacy=value['privacy'],
                    source_head=value['source_head'], access_revision=access, newer=None,
                    verified_at=value['verified_at'])

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    def local(self, project_id, reference_id):
        self.authorize(project_id); uuid(reference_id)
        ws = self.artifacts.workspace(project_id)
        with ws.journal.lock(), ws.journal.connect() as db:
            head = ws.git.head(); ws._read_locked(db, expected_head=head)
            committed_project(ws.git, head, project_id)
            files = ws.git.snapshot(head); entities = validate_snapshot(files)
            value = references(files, entities).get(reference_id)
            require(value is not None, 'Reference unavailable')
            require(ws.git.head() == head, 'Reference changed while reading')
            return head, value, entities[reference_id]

    def resolve_input(self, project_id, reference_id, files, entities, *, boundary='same-node'):
        self.authorize(project_id)
        value = references(files, entities).get(reference_id)
        require(value is not None, 'Reference unavailable')
        source = value['source']; require(source['project_id'] != project_id, 'Cross-project reference requires another project')
        result = self.live(source, boundary=boundary)
        result['privacy'] = max(result['privacy'], entities[reference_id]['privacy'], key=PRIVACY.get)
        require(result['privacy'] != 'local-only' or boundary == 'same-node', 'local-only requires same-node execution')
        result['proof'] = dict(schema=SCHEMA, source=source, source_head=result['source_head'],
                               access_revision=result['access_revision'])
        return result

    def view(self, project_id, reference_id, *, offline=True, boundary='same-node'):
        head, value, meta = self.local(project_id, reference_id)
        source = value['source']; require(source['project_id'] != project_id, 'Reference must target another project')
        try:
            result = self.live(source, boundary=boundary)
        except (FileNotFoundError, TimeoutError):
            require(offline and boundary == 'same-node', 'Offline reference is display-only on the same node')
            result = self.load_cache(source); state = 'offline-stale'
        else:
            self.save_cache(source, result)
            state = 'newer-available' if result['newer'] else 'current'
        privacy = max(result['privacy'], meta['privacy'], key=PRIVACY.get)
        require(privacy != 'local-only' or boundary == 'same-node', 'local-only requires same-node execution')
        self.authorize(project_id)
        require(self.artifacts.workspace(project_id).git.head() == head, 'Reference changed while resolving')
        from spikes.artifact_preview import preview as present
        presentation = present(dict(raw=result['raw'],path=source['path'],metadata=result['metadata'],
                                    sidecar='file' in result['metadata']))
        return dict(project_id=project_id, reference_id=reference_id, commit_id=head, read_only=True,
                    state=state, stale=state == 'offline-stale', privacy_unverified=state == 'offline-stale',
                    source=source, newer=result['newer'], privacy=privacy, title=result['metadata']['title'],
                    preview=presentation,
                    content_b64=base64.b64encode(result['raw']).decode())

    def preview(self, project_id, reference_id, source, title, *, update=False):
        self.authorize(project_id, write=True); uuid(reference_id); pin(source); text(title)
        require(reference_id != source['artifact_id'], 'Reference needs a distinct local ID')
        require(source['project_id'] != project_id, 'Cross-project reference requires another project')
        require(type(update) is bool and len(title) <= 200 and not any(c in title for c in '\r\n'), 'Invalid reference title')
        result = self.live(source); self.save_cache(source, result)
        ws = self.artifacts.workspace(project_id); ws.recover()
        with ws.journal.lock(), ws.journal.connect() as db:
            ws._writable(); head = ws.git.head(); ws._read_locked(db)
            committed_project(ws.git, head, project_id)
            files = ws.git.snapshot(head); entities = validate_snapshot(files)
            require((reference_id in entities) == update, 'Reference create/update mismatch')
            if update:
                before = references(files, entities).get(reference_id)
                require(before is not None and all(before['source'][k] == source[k] for k in ('project_id','repository','artifact_id')),
                        'Repinning cannot change source identity')
            privacy = max(result['privacy'], entities[reference_id]['privacy'] if update else 'public', key=PRIVACY.get)
            return dict(schema='fpw-reference-write-v1', project_id=project_id, base_head=head,
                        reference_id=reference_id, source=source, title=title, privacy=privacy,
                        update=update, user_id=self.user_id)

    def write(self, preview, operation_id, sha256, *, confirm=False, checkpoint=lambda stage: None):
        require(confirm is True and digest(encoded(preview)) == sha256, 'Exact reference preview must be confirmed')
        fields(preview, 'schema project_id base_head reference_id source title privacy update user_id')
        require(preview['schema'] == 'fpw-reference-write-v1' and preview['user_id'] == self.user_id, 'Invalid reference request')
        self.authorize(preview['project_id'], write=True)
        ws = self.artifacts.workspace(preview['project_id'])
        def prepare(workspace):
            require(workspace.git.head() == preview['base_head'], 'Reference target changed')
            committed_project(workspace.git, preview['base_head'], preview['project_id'])
            # preview cannot be called recursively while target lock is held.
            files = workspace.git.snapshot(preview['base_head']); entities = validate_snapshot(files)
            self.authorize(preview['project_id'], write=True)
            result = self.live(preview['source'])
            id_ = preview['reference_id']; uuid(id_); text(preview['title'])
            require(len(preview['title']) <= 200 and not any(c in preview['title'] for c in '\r\n'), 'Invalid reference title')
            require(type(preview['update']) is bool and (id_ in entities) == preview['update'], 'Reference create/update mismatch')
            privacy = max(result['privacy'], entities[id_]['privacy'] if preview['update'] else 'public', key=PRIVACY.get)
            require(privacy == preview['privacy'], 'Reference privacy changed; review a fresh preview')
            if preview['update']:
                require(id_ in references(files, entities), 'Not a reference')
                meta = dict(entities[id_], title=preview['title'], privacy=privacy)
            else:
                meta = dict(schema_version=1,id=id_,title=preview['title'],kind='document',created_at=self.now(),
                    author_id=self.user_id,privacy=privacy,provenance='user',file='reference.json',tags=[SCHEMA])
            require(preview['source']['project_id'] != preview['project_id'], 'Reference must target another project')
            changes = {f'artifacts/{id_}/metadata.json': encoded(meta),
                       f'artifacts/{id_}/reference.json': encoded(dict(schema=SCHEMA,source=preview['source']))}
            return changes,'Local workspace author',self.user_id+'@local.invalid','Write pinned artifact reference'
        return ws.transact(operation_id,dict(preview,action='write-reference-v1'),prepare,
                           expected_head=preview['base_head'],checkpoint=checkpoint)

    def fork_preview(self, project_id, reference_id, new_id):
        uuid(new_id); self.authorize(project_id, write=True)
        head, value, meta = self.local(project_id, reference_id)
        result = self.live(value['source'])
        return dict(schema='fpw-reference-fork-preview-v1',project_id=project_id,base_head=head,
                    reference_id=reference_id,new_id=new_id,source=value['source'],user_id=self.user_id,
                    privacy=max(meta['privacy'],result['privacy'],key=PRIVACY.get))

    def fork(self, preview, operation_id, sha256, *, confirm=False, checkpoint=lambda stage: None):
        require(confirm is True and digest(encoded(preview)) == sha256,'Exact fork preview must be confirmed')
        fields(preview,'schema project_id base_head reference_id new_id source user_id privacy')
        require(preview['schema']=='fpw-reference-fork-preview-v1' and preview['user_id']==self.user_id,'Invalid fork request')
        self.authorize(preview['project_id'],write=True); uuid(preview['new_id'])
        ws=self.artifacts.workspace(preview['project_id'])
        def prepare(workspace):
            require(workspace.git.head()==preview['base_head'],'Fork target changed')
            committed_project(workspace.git,preview['base_head'],preview['project_id'])
            self.authorize(preview['project_id'],write=True)
            files=workspace.git.snapshot(preview['base_head']); entities=validate_snapshot(files)
            value=references(files,entities).get(preview['reference_id'])
            require(value is not None and value['source']==preview['source'],'Reference changed')
            result=self.resolve_input(preview['project_id'],preview['reference_id'],files,entities)
            require(result['privacy']==preview['privacy'],'Fork privacy changed')
            id_=preview['new_id']; require(id_ not in entities,'Fork ID already exists')
            require(id_ != preview['source']['artifact_id'],'Fork requires a new source identity')
            filename=preview['source']['path'].split('/')[-1]; now=self.now()
            editable=result['metadata']['kind']=='document' and filename.endswith('.md')
            provenance=dict(schema=FORK,reference_project_id=preview['project_id'],reference_id=preview['reference_id'],source=preview['source'])
            meta=dict(schema_version=1 if editable else 2,id=id_,title=result['metadata']['title'],kind='document' if editable else 'source',
                created_at=now,author_id=self.user_id,privacy=result['privacy'],provenance='user' if editable else 'external',
                file=filename,tags=[FORK],description=encoded(provenance).decode())
            if not editable:
                meta['import']=dict(imported_at=now,imported_by=self.user_id,content_sha256=digest(result['raw']),
                    importer=dict(name='cross-project-fork',version='1'),source_revision=preview['source']['commit_id'])
            return {f'artifacts/{id_}/{filename}':result['raw'],f'artifacts/{id_}/metadata.json':encoded(meta)},'Local workspace author',self.user_id+'@local.invalid','Fork pinned artifact into a new local identity'
        return ws.transact(operation_id,dict(preview,action='fork-reference-v1'),prepare,expected_head=preview['base_head'],checkpoint=checkpoint)

    def index(self, project_id):
        self.authorize(project_id)
        ws=self.artifacts.workspace(project_id)
        with ws.journal.lock(),ws.journal.connect() as db:
            head=ws.git.head(); projection=ws._read_locked(db,ws.index.read_projection,expected_head=head)
            files=ws.git.snapshot(head); entities=validate_snapshot(files)
            ids=list(references(files,entities))
            require(all(id_ in projection['entities'] for id_ in ids),'Reference index differs from Git')
        rows=[]
        for id_ in ids:
            try:
                result=self.view(project_id,id_,offline=False)
                rows.append(dict(reference_id=id_,state=result['state'],source=result['source'],privacy=result['privacy']))
            except (ValueError,OSError):
                rows.append(dict(reference_id=id_,state='unavailable'))
        require(ws.git.head()==head,'Reference index changed while resolving')
        return dict(project_id=project_id,commit_id=head,references=rows)


def main():
    parser=argparse.ArgumentParser(description='Local pinned cross-project references')
    parser.add_argument('--node',required=True)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('pin');p.add_argument('project_id');p.add_argument('artifact_id');p.add_argument('--commit')
    p=sub.add_parser('preview');p.add_argument('project_id');p.add_argument('reference_id');p.add_argument('source',type=Path);p.add_argument('title');p.add_argument('--update',action='store_true')
    p=sub.add_parser('view');p.add_argument('project_id');p.add_argument('reference_id');p.add_argument('--online-only',action='store_true')
    p=sub.add_parser('index');p.add_argument('project_id')
    p=sub.add_parser('fork-preview');p.add_argument('project_id');p.add_argument('reference_id');p.add_argument('new_id')
    for name in ('write','fork'):
        p=sub.add_parser(name);p.add_argument('preview',type=Path);p.add_argument('--operation-id',required=True);p.add_argument('--sha256',required=True);p.add_argument('--confirm',action='store_true')
    args=parser.parse_args();service=CrossReferences(args.node)
    def read(path):
        with path.open('rb') as f:value=parse_json(f.read(65537))
        if isinstance(value,dict) and value.keys()=={'value','sha256'}:
            require(digest(encoded(value['value']))==value['sha256'],'Saved reference envelope changed');return value['value']
        return value
    if args.command=='pin':result=service.source_pin(args.project_id,args.artifact_id,args.commit)
    elif args.command=='preview':result=service.preview(args.project_id,args.reference_id,read(args.source),args.title,update=args.update)
    elif args.command=='view':result=service.view(args.project_id,args.reference_id,offline=not args.online_only)
    elif args.command=='index':result=service.index(args.project_id)
    elif args.command=='fork-preview':result=service.fork_preview(args.project_id,args.reference_id,args.new_id)
    else:result=getattr(service,args.command)(read(args.preview),args.operation_id,args.sha256,confirm=args.confirm)
    print(json.dumps(dict(value=result,sha256=digest(encoded(result))),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
