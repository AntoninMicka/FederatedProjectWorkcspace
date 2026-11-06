# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Per-artifact Stage/Commit over the existing Workspace writer and receipts."""
import difflib
import hashlib
import json
from spikes.artifact_preview import preview as file_preview
from spikes.metadata import require, uuid, validate_snapshot, validate_transition, MAX_FILE, MAX_METADATA
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.reporting_schema import validate_git
from spikes.task_graph import project_task_graph
from spikes.working_file import read_working_file


def digest(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()


class ArtifactGit:
    def __init__(self,node,*,network=False):
        self.node=node;self.projects=Projects(node,network=network)
        self.network=network

    def workspace(self,pid):
        require(not self.network,'Stage and Commit are local desktop actions')
        ws=self.projects.workspace(pid,blocking=True);ws._writable();return ws

    @staticmethod
    def current(ws,pid,aid,head):
        uuid(pid);uuid(aid);require(ws.git.head()==head,'Project changed; refresh')
        files=ws.git.snapshot(head);entities=validate_snapshot(files)
        require(aid in entities,'Unknown artifact')
        meta=entities[aid];prefix='artifacts/'+aid+'/'
        path=prefix+meta['file'] if prefix+'metadata.json' in files else next(p for p in files if p.startswith(prefix))
        return files,entities,path,meta

    @staticmethod
    def metadata_unchanged(ws,path,files):
        sidecar=path.rsplit('/',1)[0]+'/metadata.json'
        if sidecar not in files:return True
        try:return read_working_file(ws.git.root,sidecar,MAX_METADATA)==files[sidecar]
        except (OSError,ValueError):return False

    @staticmethod
    def staged(ws,path):
        entries=ws.git.run('ls-files','--stage','-z','--',path).stdout.rstrip('\0').split('\0')
        require(len(entries)==1 and entries[0],'Expected tracked staged file')
        info,name=entries[0].split('\t',1);mode,oid,stage=info.split()
        require(name==path and stage=='0' and mode in {'100644','100755'},'Resolve Git index conflicts first')
        require(int(ws.git.run('cat-file','-s',oid).stdout)<=MAX_FILE,'Staged file exceeds limit')
        return ws.git.run('cat-file','blob',oid,binary=True).stdout

    def status(self,pid,aid,head,*,page=1):
        require(type(page) is int and 1<=page<=4096,'Invalid preview page')
        ws=self.workspace(pid)
        with ws.journal.lock(),ws.journal.connect() as db:
            require(ws._active(db) is None and not db.execute('SELECT 1 FROM pending').fetchone(),'Recover pending operation first')
            files,entities,path,meta=self.current(ws,pid,aid,head)
            raw=read_working_file(ws.git.root,path);staged=self.staged(ws,path);metadata_ok=self.metadata_unchanged(ws,path,files)
            result=dict(project_id=pid,artifact_id=aid,base_head=head,path=path,title=meta['title'],working_sha256=digest(raw),
                        staged_sha256=digest(staged),head_sha256=digest(files[path]),
                        can_stage=raw!=staged and metadata_ok,can_commit=staged!=files[path] and metadata_ok,working_after_stage=raw!=staged)
            if not metadata_ok:result['notice']='Metadata artefaktu se změnila; Stage a Commit vyžadují společné posouzení metadat.'
            if raw!=files[path]:
                item=dict(id=aid,commit_id=head,metadata=meta,path=path,raw=raw,sidecar='artifacts/'+aid+'/metadata.json' in files)
                working=file_preview(item,page)
                working['message']='Pracovní soubor z disku · necommitnuté změny. '+working.get('message','').replace('uložená verze','pracovní verze')
                result['working_preview']=working
            return result

    def stage(self,request,operation_id,*,checkpoint=lambda stage:None):
        require(isinstance(request,dict) and set(request)=={'project_id','artifact_id','base_head','working_sha256'},'Invalid Stage request')
        pid=request['project_id'];ws=self.workspace(pid)
        def prepare(workspace):
            files,_,path,_=self.current(workspace,pid,request['artifact_id'],request['base_head'])
            require(self.metadata_unchanged(workspace,path,files),'Artifact metadata changed; review metadata first')
            raw=read_working_file(workspace.git.root,path)
            require(digest(raw)==request['working_sha256'],'Working file changed since preview; refresh before Stage')
            return path,raw
        return ws.stage_artifact(operation_id,request,prepare,checkpoint=checkpoint)

    def _preview(self,ws,pid,aid,head):
        files,entities,path,meta=self.current(ws,pid,aid,head)
        require(self.metadata_unchanged(ws,path,files),'Artifact metadata changed; review metadata first')
        raw=self.staged(ws,path)
        require(raw!=files[path],'Selected file has no staged changes')
        candidate=dict(files);candidate[path]=raw
        after=validate_transition(files,candidate);validate_git(ws.git,candidate,after,files)
        plan=project_task_graph(candidate,after,pid,head)
        require(plan['status'] in {'ready','missing'},'Roadmap is not valid: '+plan.get('error',''))
        try:
            old=files[path].decode('utf-8');new=raw.decode('utf-8')
            require('\0' not in old+new,'Binary content')
            diff=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='HEAD/'+path,tofile='Stage/'+path))
        except (UnicodeError,ValueError):diff='Binary file: '+str(len(files[path]))+' → '+str(len(raw))+' bytes'
        return dict(schema='fpw-artifact-commit-preview-v1',project_id=pid,artifact_id=aid,base_head=head,path=path,
                    title=meta['title'],head_sha256=digest(files[path]),staged_sha256=digest(raw),bytes=len(raw),diff=diff[:262144],diff_truncated=len(diff)>262144),raw

    def preview(self,pid,aid,head):
        ws=self.workspace(pid)
        with ws.journal.lock(),ws.journal.connect() as db:
            require(ws._active(db) is None and not db.execute('SELECT 1 FROM pending').fetchone(),'Recover pending operation first')
            value,_=self._preview(ws,pid,aid,head)
            return dict(preview=value,approval_digest=digest(canonical(value)))

    def commit(self,preview,approval_digest,message,operation_id,*,confirm=False,checkpoint=lambda stage:None):
        require(confirm is True,'Explicit Commit confirmation required')
        require(isinstance(message,str) and 0<len(message.strip())<=1000 and '\0' not in message,'Commit message required')
        require(digest(canonical(preview))==approval_digest,'Commit preview digest differs')
        pid=preview['project_id'];ws=self.workspace(pid);author=ProjectCreation(self.node).author_id()
        request=dict(action='artifact-staged-commit-v1',preview=preview,approval_digest=approval_digest,message=message)
        def prepare(workspace):
            current,raw=self._preview(workspace,pid,preview['artifact_id'],preview['base_head'])
            require(current==preview,'Staged file changed; review again')
            return {preview['path']:raw},'Local workspace author',author+'@local.invalid',message
        return ws.transact(operation_id,request,prepare,expected_head=preview['base_head'],adopt_staged=True,checkpoint=checkpoint)
