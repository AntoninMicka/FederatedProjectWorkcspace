# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Closed, untrusted result contract for unified AI task routing."""
from dataclasses import dataclass
import json

from spikes.metadata import require, uuid


MAX_OUTCOME_CONTENT = 1024 * 1024


def _content(value, name, limit=MAX_OUTCOME_CONTENT):
    require(isinstance(value, str) and bool(value.strip()) and '\0' not in value
            and len(value.encode('utf-8')) <= limit, f'Invalid {name}')
    return value


def _ids(value, name):
    require(isinstance(value, list) and len(value) == len(set(value)),
            f'{name} must be a unique list')
    for item in value:
        uuid(item)
    return tuple(value)


@dataclass(frozen=True)
class AITaskOutcome:
    kind: str
    content: str
    title: str | None = None
    artifact_kind: str | None = None
    purpose: str | None = None
    message_ids: tuple = ()
    artifact_ids: tuple = ()

    @classmethod
    def parse(cls, value):
        require(isinstance(value, dict) and value.get('schema_version') == 1,
                'Invalid AI task outcome')
        kind = value.get('kind')
        if kind == 'direct-answer':
            require(set(value) == {'schema_version', 'kind', 'content'},
                    'Unknown direct answer field')
            return cls(kind, _content(value['content'], 'direct answer'))
        if kind == 'artifact-draft':
            require(set(value) == {'schema_version', 'kind', 'artifact_kind',
                                   'title', 'content'},
                    'Unknown artifact draft field')
            require(value['artifact_kind'] == 'document',
                    'Unsupported artifact draft kind')
            title = _content(value['title'], 'artifact title', 200)
            require('\r' not in title and '\n' not in title,
                    'Invalid artifact title')
            return cls(kind, _content(value['content'], 'artifact content'),
                       title, value['artifact_kind'])
        if kind == 'external-request':
            require(set(value) == {'schema_version', 'kind', 'purpose', 'query',
                                   'message_ids', 'artifact_ids'},
                    'Unknown external request field')
            return cls(kind, _content(value['query'], 'external query'),
                       purpose=_content(value['purpose'], 'external purpose', 2000),
                       message_ids=_ids(value['message_ids'], 'Message IDs'),
                       artifact_ids=_ids(value['artifact_ids'], 'Artifact IDs'))
        raise ValueError('Unsupported AI task outcome kind')

    def serialize(self):
        if self.kind == 'direct-answer':
            return {'schema_version': 1, 'kind': self.kind, 'content': self.content}
        if self.kind == 'artifact-draft':
            return {'schema_version': 1, 'kind': self.kind,
                    'artifact_kind': self.artifact_kind, 'title': self.title,
                    'content': self.content}
        return {'schema_version': 1, 'kind': self.kind, 'purpose': self.purpose,
                'query': self.content, 'message_ids': list(self.message_ids),
                'artifact_ids': list(self.artifact_ids)}

    def canonical(self):
        return json.dumps(self.serialize(), ensure_ascii=False, sort_keys=True,
                          separators=(',', ':')).encode('utf-8')
