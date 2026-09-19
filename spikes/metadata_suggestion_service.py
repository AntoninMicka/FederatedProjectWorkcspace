# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Same-node durable metadata suggestions without project mutation."""
import base64
import hashlib
import json
import re

import yaml

from spikes.configuration import committed_project
from spikes.context_builder import AdHocInput
from spikes.metadata import require, uuid, validate_snapshot
from spikes.metadata_suggestions import (INSTRUCTION, canonical, project_diff, snapshot,
                                         validate_preview)
from spikes.summary_service import SummaryService


class MetadataSuggestionService(SummaryService):
    request_schema = 'fpw-metadata-suggestion-request-v1'
    role_id = 'metadata-advisor'
    role_revision = 'metadata-advisor-v1'
    policy_revision = 'desktop-metadata-suggestion-v1'
    session_prefix = 'metadata-suggestion:'
    task_filename = 'metadata-suggestion-tasks.sqlite'

    @classmethod
    def _extra_request_fields(cls):
        return {'metadata_input_id'}

    @classmethod
    def _validate_extra_request(cls, request):
        uuid(request['metadata_input_id'])
        selection = request['selection']
        require(selection['kind'] == 'artifacts'
                and len(selection['artifact_ids']) == 1
                and request['focus'] is None
                and request['metadata_input_id'] not in selection['artifact_ids'],
                'Metadata suggestion requires one artifact and no client focus')

    @classmethod
    def _instruction(cls, request):
        return INSTRUCTION

    @classmethod
    def _additional_inputs(cls, request, files, entities):
        artifact_id = request['selection']['artifact_ids'][0]
        current = snapshot(entities[artifact_id])
        return (AdHocInput(request['metadata_input_id'], canonical(current),
                           entities[artifact_id]['privacy']),)

    @classmethod
    def _validate_preview(cls, response, source_ids, request):
        return validate_preview(response)

    @staticmethod
    def _result(task_id, task):
        result = SummaryService._result(task_id, task)
        payload = json.loads(task['payload'])
        metadata_id = task['request']['metadata_input_id']
        encoded = next(item['content_b64'] for item in payload['inputs']
                       if item['input_id'] == metadata_id)
        original = json.loads(base64.b64decode(encoded))
        result.update(original=original,
                      diff=project_diff(original, task['response']))
        return result

    def publish(self, request, *, checkpoint=lambda stage: None):
        required = {'task_id', 'preview_sha256', 'project_id', 'expected_head',
                    'artifact_id', 'apply_description', 'tags', 'operation_id'}
        require(isinstance(request, dict) and set(request) == required,
                'Invalid metadata publication request')
        for key in ('task_id', 'project_id', 'artifact_id', 'operation_id'):
            uuid(request[key])
        require(isinstance(request['preview_sha256'], str)
                and re.fullmatch(r'[0-9a-f]{64}', request['preview_sha256']),
                'Invalid metadata preview digest')
        require(isinstance(request['expected_head'], str)
                and re.fullmatch(r'[0-9a-f]{40,64}', request['expected_head']),
                'Invalid expected project commit')
        require(type(request['apply_description']) is bool
                and isinstance(request['tags'], list), 'Invalid metadata selection')
        node_id, user_id = self._identity(); tasks, _, _ = self._stores()
        task = tasks.get(request['task_id'], node_id, user_id)
        require(task['state'] in {'succeeded', 'publishing', 'published'},
                'Metadata preview is not publishable')
        require(task['response_sha256'] == request['preview_sha256'],
                'Metadata preview changed before publication')
        original_request = task['request']; selected_id = original_request['selection']['artifact_ids'][0]
        require(task['manifest']['project_id'] == request['project_id']
                and task['manifest']['project_commit'] == request['expected_head']
                and selected_id == request['artifact_id'],
                'Metadata publication target differs from preview')
        proposed = json.loads(validate_preview(task['response']))
        diff = project_diff(self._original(task), proposed)
        allowed_tags = diff['tags']['suggested_additions']
        require(len(request['tags']) == len(set(tag.casefold() for tag in request['tags']))
                and all(tag in allowed_tags for tag in request['tags']),
                'Metadata publication contains an unconfirmed tag')
        require((request['apply_description'] and diff['description']['changed'])
                or bool(request['tags']), 'Metadata publication has no selected change')
        task = tasks.begin_publish(request['task_id'], node_id, user_id, request)
        checkpoint('publishing')
        if task['state'] == 'published':
            return self._published_result(request['task_id'], task)
        workspace = self.projects.workspace(request['project_id'], blocking=False)
        intent = dict(request, action='apply-metadata-suggestion', author_id=user_id,
                      task_request_digest=task['request_digest'])

        def prepare(ws):
            head = ws.git.head()
            require(head == request['expected_head'],
                    'Project changed before metadata publication')
            committed_project(ws.git, head, request['project_id'])
            files = ws.git.snapshot(head); entities = validate_snapshot(files)
            require(selected_id in entities, 'Metadata target is unavailable')
            current = entities[selected_id]; original = self._original(task)
            require(snapshot(current) == original, 'Artifact metadata changed after preview')
            manifest_input = next(item for item in task['manifest']['inputs']
                                  if item['source'] == 'project')
            raw = files.get(manifest_input['path'])
            require(raw is not None and hashlib.sha256(raw).hexdigest() == manifest_input['sha256'],
                    'Artifact content changed after preview')
            updated = dict(current)
            if request['apply_description']:
                updated['description'] = proposed['description']
            updated['tags'] = list(original['tags']) + request['tags']
            prefix = f'artifacts/{selected_id}/'; sidecar = prefix + 'metadata.json'
            if sidecar in files:
                changes = {sidecar: (json.dumps(updated, ensure_ascii=False,
                    sort_keys=True, indent=2) + '\n').encode()}
            else:
                path = manifest_input['path']; lines = files[path].splitlines(keepends=True)
                end = next(i for i in range(1, len(lines))
                           if lines[i].rstrip(b'\r\n') == b'---')
                body = b''.join(lines[end + 1:])
                changes = {path: ('---\n' + yaml.safe_dump(updated, allow_unicode=True,
                    sort_keys=True) + '---\n').encode() + body}
            return changes, 'Local workspace author', user_id + '@local.invalid', \
                'Apply confirmed metadata suggestions'

        receipt = workspace.transact(request['operation_id'], intent, prepare,
            expected_head=request['expected_head'], checkpoint=checkpoint)
        checkpoint('workspace-complete')
        task = tasks.complete_publish(request['task_id'], node_id, user_id, receipt)
        checkpoint('published')
        return self._published_result(request['task_id'], task)

    @staticmethod
    def _original(task):
        payload = json.loads(task['payload']); metadata_id = task['request']['metadata_input_id']
        encoded = next(item['content_b64'] for item in payload['inputs']
                       if item['input_id'] == metadata_id)
        return json.loads(base64.b64decode(encoded))
