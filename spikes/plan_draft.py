# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Local, read-only preview of a manually edited main plan; never a writer."""
import hashlib
import os
from pathlib import PurePosixPath
import stat
from spikes.markdown_documents import MAX_EDITOR, document, main_todo_id
from spikes.metadata import require, validate_snapshot
from spikes.storage import StaleIndex
from spikes.task_graph import project_task_graph, task_outline


def read_plan_draft(workspace, project_id, head):
    """Caller owns the Workspace lock. Return (display projection, raw) or None."""
    if workspace.git.head() != head:raise StaleIndex('Project changed while reading plan draft')
    files=workspace.git.snapshot(head);entities=validate_snapshot(files);aid=main_todo_id(project_id)
    if aid not in entities:return None
    doc=document(files,entities,aid);relative=PurePosixPath(doc['path']);parts=relative.parts
    require(not relative.is_absolute() and all(p not in {'.','..'} for p in parts),'Unsafe plan draft path')
    fd=os.open(workspace.git.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=next_fd
        content_fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        with os.fdopen(content_fd,'rb') as handle:
            before=os.fstat(handle.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and before.st_nlink==1,
                    'Plan draft must be an owned regular file')
            require(before.st_size<=MAX_EDITOR,'Plan draft exceeds 1 MiB')
            raw=handle.read(MAX_EDITOR+1);after=os.fstat(handle.fileno())
            current=os.stat(parts[-1],dir_fd=fd,follow_symlinks=False)
            identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
            require(identity(before)==identity(after)==identity(current),'Plan draft changed while reading; refresh')
    finally:os.close(fd)
    require(len(raw)<=MAX_EDITOR,'Plan draft exceeds 1 MiB')
    if raw==files[doc['path']]:return None
    candidate=dict(files);candidate[doc['path']]=raw
    body=document(candidate,entities,aid)['body'];require('\0' not in body,'Plan draft contains NUL')
    rows,truncated=task_outline(body,source=dict(artifact_id=aid,path=doc['path']))
    validation=project_task_graph(candidate,entities,project_id,head)
    if workspace.git.head()!=head:raise StaleIndex('Project changed while reading plan draft')
    return dict(schema='fpw-plan-draft-v1',status='draft',revision=hashlib.sha256(raw).hexdigest(),
                base_commit=head,outline=rows,outline_truncated=truncated,nodes=[],ready=[],blocked=[],subgraphs=[],
                error=validation.get('error'),draft_valid=validation['status']=='ready',
                source=dict(artifact_id=aid,path=doc['path']),text=body),raw
