# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Reviewed updates of one selected document through the existing native writer."""
import difflib
import hashlib
import json

from spikes.artifacts import Artifacts
from spikes.markdown_documents import MAX_EDITOR, document
from spikes.metadata import require, uuid, validate_snapshot
from spikes.presentation_documents import is_presentation_document
from spikes.task_graph import project_task_graph
from spikes.task_outcomes import TaskOutcomes
from spikes.task_plan import ExplicitTaskPlan


def body(value):
    require(isinstance(value, str) and '\0' not in value and len(value.encode()) <= MAX_EDITOR,
            'Invalid or oversized replacement Markdown')
    require(not is_presentation_document(value), 'Presentation editing uses its dedicated editor')
    return value


def authorize(service, project_id):
    allowed = service._request_writable_project_ids.get()
    require(allowed is None or project_id in allowed, 'Project file editing is not allowed for this user')
    replication = service.projects.replication(project_id)
    require(not replication or replication['role'] != 'read-only-replica', 'Project is read-only')
    git = service.projects.repository(project_id)
    head = git.head()
    if service.projects.network:
        require(all(meta['privacy'] != 'local-only' for meta in validate_snapshot(git.snapshot(head)).values()),
                'Local-only project content is unavailable over the network')
    return {'commit_id': head}


def target_document(service, project_id, target, base_head, *, privacy=None, current=True):
    view = authorize(service, project_id)
    require(not current or view['commit_id'] == base_head, 'File edit target is stale; reopen the current document')
    git = service.projects.repository(project_id)
    files = git.snapshot(base_head)
    entities = validate_snapshot(files)
    doc = document(files, entities, target)
    require(not is_presentation_document(doc['body']), 'Presentation editing uses its dedicated editor')
    if privacy is not None:
        from spikes.chat_service import PRIVACY_ORDER
        require(PRIVACY_ORDER[doc['metadata']['privacy']] >= PRIVACY_ORDER[privacy],
                'File edit cannot lower the privacy of its context')
    return doc, files, entities


def validate_patch_proposal(service, request, outcome):
    from spikes.document_patch import apply_patch
    doc, files, _ = target_document(service, request['project_id'], request['task_plan']['target_artifact_id'],
                                   request['expected_head'], current=False)
    if outcome['kind'] == 'markdown-patch':
        from spikes.markdown_patch import apply as apply_markdown, build as markdown_context
        plan = ExplicitTaskPlan.parse(request['task_plan'])
        require(plan.edit_format == 'blocks', 'Markdown patch requires an explicit block plan')
        from spikes.markdown_patch import SCHEMA_V1, SCHEMAS
        pinned = request.get('file_edit_context')
        schema = pinned.get('schema') if isinstance(pinned, dict) else None
        require(schema in SCHEMAS or pinned is None, 'Unknown pinned Markdown context')
        projection = markdown_context(files, validate_snapshot(files), request['project_id'],
            request['expected_head'], plan.target_artifact_id, request['run_id'], plan.edit_block_ids,
            schema=schema or SCHEMA_V1)
        require(request.get('file_edit_context') == projection['metadata'], 'Markdown scope differs from the pinned context')
        replacement = body(apply_markdown(doc['body'], outcome, selected_ids=plan.edit_block_ids))
    else:
        replacement = body(apply_patch(doc['body'], outcome['edits']))
    files[doc['path']] = replacement.encode()
    graph = project_task_graph(files, validate_snapshot(files), request['project_id'], request['expected_head'])
    if outcome['kind'] == 'markdown-patch' and graph['status'] not in {'ready', 'missing'}:
        from spikes.markdown_patch import MarkdownPatchError
        raise MarkdownPatchError('Návrh vytváří neplatnou roadmapu: ' + graph.get('error', ''))
    require(graph['status'] in {'ready', 'missing'}, 'Patch leaves an invalid roadmap: ' + graph.get('error', ''))
    if outcome['kind'] != 'markdown-patch' and request.get('file_edit_context') is not None:
        from spikes.roadmap_append_context import build, validate
        original = service.projects.repository(request['project_id']).snapshot(request['expected_head'])
        projection = build(original, validate_snapshot(original), request['project_id'], request['expected_head'],
                           request['task_plan']['target_artifact_id'], request['run_id'])
        require(projection is not None and projection['metadata'] == request['file_edit_context'],
                'Append context no longer matches the pinned document')
        validate(projection, outcome['edits'], graph)
    return replacement


def _row(service, task_id):
    uuid(task_id)
    node_id, user_id = service._identity()
    store = TaskOutcomes(service._root())
    row = store.get(task_id, node_id, user_id)
    plan = ExplicitTaskPlan.parse(row['request'].get('task_plan'))
    require(plan.output_kind == 'file-edit', 'Task is not a selected-file edit')
    authorize(service, row['project_id'])
    return store, row, plan


def _preview(service, row, plan, replacement, *, current=True):
    replacement = body(replacement)
    doc, files, entities = target_document(service, row['project_id'], plan.target_artifact_id,
        row['project_commit'], privacy=row['privacy'], current=current)
    files[doc['path']] = replacement.encode()
    graph = project_task_graph(files, validate_snapshot(files), row['project_id'], row['project_commit'])
    require(graph['status'] in {'ready', 'missing'},
            'Replacement leaves an invalid roadmap: ' + graph.get('error', ''))
    proof = dict(task_id=row['task_id'], project_id=row['project_id'],
                 artifact_id=plan.target_artifact_id, base_head=row['project_commit'],
                 before_sha256=hashlib.sha256(doc['body'].encode()).hexdigest(),
                 body_sha256=hashlib.sha256(replacement.encode()).hexdigest(),
                 title=doc['title'], run_id=row['run_id'], manifest_id=row['manifest_id'], privacy=row['privacy'])
    digest = hashlib.sha256(json.dumps(proof, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':')).encode()).hexdigest()
    return {'title': doc['title'], 'document': doc, 'body': replacement,
            'diff': ''.join(difflib.unified_diff(doc['body'].splitlines(True), replacement.splitlines(True),
                                               fromfile=doc['path'], tofile=doc['path'])),
            'confirmation': dict(task_id=row['task_id'], artifact_id=plan.target_artifact_id,
                project_id=row['project_id'], base_head=row['project_commit'], body=replacement, approval_digest=digest, approved=True)}


def preview(service, request):
    require(isinstance(request, dict) and set(request) in ({'project_id', 'task_id'}, {'project_id', 'task_id', 'body'}), 'Invalid file edit preview')
    _, row, plan = _row(service, request['task_id'])
    require(request['project_id'] == row['project_id'], 'File edit belongs to another project')
    require(row['state'] == 'prepared' and row['outcome']['kind'] in {'artifact-draft', 'artifact-patch', 'markdown-patch'}, 'File edit is closed')
    pending = row['result']
    if 'body' in request:
        replacement = request['body']
    elif pending is not None:
        replacement = pending['request']['body']
    elif row['outcome']['kind'] in {'artifact-patch', 'markdown-patch'}:
        replacement = validate_patch_proposal(service, row['request'], row['outcome'])
    else:
        replacement = row['outcome']['content']
    if pending is not None:
        require(pending.get('kind') == 'file-edit-approval' and pending['request']['body'] == replacement,
                'Resume the original approved file edit before editing again')
    result = _preview(service, row, plan, replacement, current=pending is None)
    result['pending_confirmation'] = pending is not None
    if pending is not None:
        result['confirmation'] = pending['request']
    return result


def confirm(service, request, *, checkpoint=lambda stage: None):
    require(isinstance(request, dict) and set(request) == {
        'project_id', 'task_id', 'artifact_id', 'operation_id', 'base_head', 'body', 'approval_digest', 'approved'}
        and request['approved'] is True, 'Invalid file edit confirmation')
    for key in ('task_id', 'artifact_id', 'operation_id'): uuid(request[key])
    body(request['body'])
    store, row, plan = _row(service, request['task_id'])
    require(request['project_id'] == row['project_id'], 'File edit belongs to another project')
    require(request['artifact_id'] == plan.target_artifact_id, 'File edit targets a different document')
    if row['state'] == 'completed':
        result = row['result']
        require(result.get('kind') == 'artifact-link' and all(result.get(k) == request[k]
                for k in ('artifact_id', 'operation_id', 'approval_digest', 'base_head'))
                and result.get('body_sha256') == hashlib.sha256(request['body'].encode()).hexdigest(),
                'File edit was completed differently')
        return row['projection']
    require(row['state'] == 'prepared' and row['outcome']['kind'] in {'artifact-draft', 'artifact-patch', 'markdown-patch'}, 'File edit is closed')
    expected = _preview(service, row, plan, request['body'], current=row['result'] is None)
    require(all(request[k] == v for k, v in expected['confirmation'].items()),
            'Confirmation does not match the exact file edit preview')
    store.bind_file_edit_approval(row['task_id'], row['node_id'], row['user_id'], request)
    checkpoint('file-edit-approval-bound')
    def still_approved():
        current = store.get(row['task_id'], row['node_id'], row['user_id'])
        require(current['state'] == 'prepared' and current['result'] == {
            'kind': 'file-edit-approval', 'request': request}, 'File edit approval was cancelled or changed')
    receipt = Artifacts(service.node_path).save(dict(project_id=row['project_id'],
        artifact_id=plan.target_artifact_id, base_head=row['project_commit'], title=expected['title'],
        body=request['body'], new=False), request['operation_id'], checkpoint=checkpoint,
        transformation={key: row[key] for key in ('task_id', 'run_id', 'manifest_id')}, before_write=still_approved)
    checkpoint('file-edit-before-outcome')
    result = dict(schema_version=1, kind='artifact-link', artifact_id=plan.target_artifact_id,
                  title=expected['title'], project_commit=receipt['commit_id'],
                  operation_id=request['operation_id'], approval_digest=request['approval_digest'],
                  base_head=row['project_commit'], body_sha256=hashlib.sha256(request['body'].encode()).hexdigest(),
                  run_id=row['run_id'], manifest_id=row['manifest_id'])
    return store.finish(row['task_id'], row['node_id'], row['user_id'], 'completed', result=result)['projection']


def cancel(service, task_id):
    store, row, _ = _row(service, task_id)
    workspace = service.projects.workspace(row['project_id'], blocking=False)
    with workspace.journal.lock(), workspace.journal.connect() as db:
        row = store.get(task_id, row['node_id'], row['user_id'])
        if row['result'] is not None:
            require(row['state'] == 'prepared' and row['result'].get('kind') == 'file-edit-approval',
                    'File edit is already completed')
            operation = row['result']['request']['operation_id']
            require(db.execute('SELECT 1 FROM operations WHERE id=?', (operation,)).fetchone() is None,
                    'Approved file write has started; resume its original operation')
        return store.finish(task_id, row['node_id'], row['user_id'], 'cancelled',
                            file_edit_unwritten=True)['projection']
