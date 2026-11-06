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
    from spikes.working_file import read_working_file
    raw=read_working_file(workspace.git.root,doc['path'],MAX_EDITOR)
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
