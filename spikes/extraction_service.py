# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Same-node structured extraction with a closed schema catalog."""
import hashlib
import json
import re

from spikes.chat_threads import ChatThreads
from spikes.configuration import committed_project
from spikes.extraction_schemas import canonical, instruction, validate_preview, validate_schema
from spikes.metadata import MAX_FILE, require, timestamp, uuid, validate_snapshot
from spikes.summary_service import SummaryService


class ExtractionService(SummaryService):
    request_schema = 'fpw-extraction-request-v1'
    role_id = 'extractor'
    role_revision = 'extractor-v1'
    policy_revision = 'desktop-extraction-v1'
    session_prefix = 'extraction:'
    task_filename = 'extraction-tasks.sqlite'

    @classmethod
    def _extra_request_fields(cls):
        return {'schema_id', 'schema_revision'}

    @classmethod
    def _validate_extra_request(cls, request):
        validate_schema(request['schema_id'], request['schema_revision'])

    @classmethod
    def _instruction(cls, request):
        return instruction(request['schema_id'], request['schema_revision'])

    @classmethod
    def _validate_preview(cls, response, source_ids, request):
        return validate_preview(response, request['schema_id'],
                                request['schema_revision'], source_ids)

    def publish(self, request, *, checkpoint=lambda stage: None):
        required = {'task_id', 'preview_sha256', 'project_id', 'expected_head',
                    'artifact_id', 'title', 'created_at', 'operation_id'}
        require(isinstance(request, dict) and set(request) == required,
                'Invalid extraction publication request')
        for key in ('task_id', 'project_id', 'artifact_id', 'operation_id'):
            uuid(request[key])
        require(isinstance(request['preview_sha256'], str)
                and re.fullmatch(r'[0-9a-f]{64}', request['preview_sha256']),
                'Invalid extraction preview digest')
        require(isinstance(request['expected_head'], str)
                and re.fullmatch(r'[0-9a-f]{40,64}', request['expected_head']),
                'Invalid expected project commit')
        require(isinstance(request['title'], str)
                and request['title'].strip() == request['title']
                and 0 < len(request['title']) <= 200
                and not any(char in request['title'] for char in '\0\r\n'),
                'Invalid extraction title')
        timestamp(request['created_at'])
        node_id, user_id = self._identity()
        tasks, _, _ = self._stores()
        task = tasks.get(request['task_id'], node_id, user_id)
        require(task['state'] in {'succeeded', 'publishing', 'published'},
                'Extraction preview is not publishable')
        require(task['response_sha256'] == request['preview_sha256'],
                'Extraction preview changed before publication')
        require(task['manifest']['project_id'] == request['project_id']
                and task['manifest']['project_commit'] == request['expected_head'],
                'Extraction publication project or HEAD differs from preview')
        task = tasks.begin_publish(request['task_id'], node_id, user_id, request)
        checkpoint('publishing')
        if task['state'] == 'published':
            return self._published_result(request['task_id'], task)
        workspace = self.projects.workspace(request['project_id'], blocking=False)
        intent = dict(request, action='publish-extraction', author_id=user_id,
                      task_request_digest=task['request_digest'])

        def prepare(ws):
            head = ws.git.head()
            require(head == request['expected_head'],
                    'Project changed before extraction publication')
            committed_project(ws.git, head, request['project_id'])
            files = ws.git.snapshot(head); entities = validate_snapshot(files)
            require(request['artifact_id'] not in entities, 'Artifact ID already exists')
            original = task['request']; selection = original['selection']; manifest = task['manifest']
            if selection['kind'] == 'artifacts':
                selected_ids = selection['artifact_ids']
                by_id = {item['input_id']: item for item in manifest['inputs']
                         if item['source'] == 'project'}
                require(set(by_id) == set(selected_ids)
                        and all(value in entities for value in selected_ids),
                        'Extraction source selection changed')
                for value in selected_ids:
                    item = by_id[value]; raw = files.get(item['path'])
                    require(raw is not None and len(raw) == item['size']
                            and hashlib.sha256(raw).hexdigest() == item['sha256']
                            and entities[value]['privacy'] == item['privacy'],
                            'Extraction source artifact changed')
            else:
                ids = selection['message_ids']
                thread = ChatThreads(self.chat_state_dir).get(
                    selection['thread_id'], node_id, user_id)
                require(thread['project_id'] == request['project_id']
                        and thread['revision'] == selection['thread_revision'],
                        'Extraction chat selection changed')
                by_id = {item['message_id']: item for item in thread['messages']}
                require(all(value in by_id for value in ids)
                        and [item['message_id'] for item in thread['messages']
                             if item['message_id'] in ids] == ids
                        and [item['message_id'] for item in manifest['conversation']['messages']] == ids,
                        'Extraction chat messages changed')
                manifest_inputs = {item['input_id']: item for item in manifest['inputs']}
                for value in ids:
                    message = by_id[value]; item = manifest_inputs[value]
                    raw = message['content'].encode()
                    require(hashlib.sha256(raw).hexdigest() == item['sha256']
                            and message['privacy'] == item['privacy'],
                            'Extraction chat message changed')
            validated = json.loads(validate_preview(task['response'], original['schema_id'],
                                   original['schema_revision'],
                                   (selection['artifact_ids'] if selection['kind'] == 'artifacts'
                                    else selection['message_ids'])))
            sources = [dict(input_id=item['input_id'], source=item['source'],
                            sha256=item['sha256'], privacy=item['privacy'])
                       for item in manifest['inputs']]
            provenance = {'task_id': request['task_id'], 'run_id': task['run_id'],
                'manifest_id': task['manifest_id'],
                'manifest_sha256': hashlib.sha256(canonical(manifest)).hexdigest(),
                'role_id': original['role_id'], 'role_revision': original['role_revision'],
                'schema_id': original['schema_id'],
                'schema_revision': original['schema_revision'],
                'project_id': request['project_id'], 'project_commit': head,
                'sources': sources, 'target': manifest['target'],
                'preview_sha256': task['response_sha256'], 'privacy': task['privacy']}
            content = canonical({'schema': 'fpw-extraction-v1',
                                 'provenance': provenance, 'data': validated}) + b'\n'
            require(len(content) <= MAX_FILE, 'Published extraction exceeds artifact limit')
            relations = ([{'type': 'derived-from', 'target_id': value}
                          for value in selection['artifact_ids']]
                         if selection['kind'] == 'artifacts' else [])
            metadata = {'schema_version': 1, 'id': request['artifact_id'],
                'title': request['title'], 'kind': 'source',
                'created_at': request['created_at'], 'author_id': user_id,
                'privacy': task['privacy'], 'provenance': 'llm-generated',
                'file': 'extraction.json', 'relations': relations}
            prefix = f'artifacts/{request["artifact_id"]}/'
            changes = {prefix + 'extraction.json': content,
                prefix + 'metadata.json': (json.dumps(metadata, ensure_ascii=False,
                    sort_keys=True, indent=2) + '\n').encode()}
            return changes, 'Local workspace author', user_id + '@local.invalid', \
                'Publish structured extraction'

        receipt = workspace.transact(request['operation_id'], intent, prepare,
            expected_head=request['expected_head'], checkpoint=checkpoint)
        checkpoint('workspace-complete')
        task = tasks.complete_publish(request['task_id'], node_id, user_id, receipt)
        checkpoint('published')
        return self._published_result(request['task_id'], task)
