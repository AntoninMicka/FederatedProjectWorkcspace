# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Same-node durable metadata suggestions without project mutation."""
import base64
import json

from spikes.context_builder import AdHocInput
from spikes.metadata import require, uuid
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
