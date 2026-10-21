# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Closed, untrusted result contract for unified AI task routing."""
from dataclasses import dataclass
import hashlib
import json
import re

from spikes.metadata import require, uuid
from spikes.presentation_documents import encode_deck, validate_deck


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
    content: str | None = None
    title: str | None = None
    artifact_kind: str | None = None
    purpose: str | None = None
    message_ids: tuple = ()
    artifact_ids: tuple = ()
    operation: str | None = None
    target_artifact_id: str | None = None
    source_artifact_ids: tuple = ()
    base_revision: str | None = None
    deck: dict | None = None
    deck_sha256: str | None = None

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
        if kind in {'external-request', 'web-search'}:
            require(set(value) == {'schema_version', 'kind', 'purpose', 'query',
                                   'message_ids', 'artifact_ids'},
                    'Unknown external or search request field')
            query_name = 'web search query' if kind == 'web-search' else 'external query'
            query_limit = 4096 if kind == 'web-search' else MAX_OUTCOME_CONTENT
            return cls(kind, _content(value['query'], query_name, query_limit),
                       purpose=_content(value['purpose'], 'external purpose', 2000),
                       message_ids=_ids(value['message_ids'], 'Message IDs'),
                       artifact_ids=_ids(value['artifact_ids'], 'Artifact IDs'))
        if kind == 'presentation-draft':
            fields = {'schema_version', 'kind', 'operation', 'target_artifact_id',
                      'source_artifact_ids', 'base_revision', 'deck', 'deck_sha256'}
            require(set(value) == fields and value['operation'] in {'create', 'update'},
                    'Invalid presentation draft')
            target = value['target_artifact_id']
            require((value['operation'] == 'create' and target is None)
                    or (value['operation'] == 'update' and isinstance(target, str)),
                    'Invalid presentation draft target')
            if target is not None:
                uuid(target)
            sources = _ids(value['source_artifact_ids'], 'Presentation source IDs')
            require(isinstance(value['base_revision'], str)
                    and re.fullmatch(r'[0-9a-f]{40,64}', value['base_revision']),
                    'Invalid presentation base revision')
            deck = validate_deck(value['deck'])
            require(deck == value['deck'], 'Presentation draft is not normalized')
            digest = hashlib.sha256(encode_deck(deck).encode('utf-8')).hexdigest()
            require(value['deck_sha256'] == digest, 'Invalid presentation draft digest')
            return cls(kind, operation=value['operation'], target_artifact_id=target,
                       source_artifact_ids=sources, base_revision=value['base_revision'],
                       deck=deck, deck_sha256=digest)
        raise ValueError('Unsupported AI task outcome kind')

    def serialize(self):
        if self.kind == 'direct-answer':
            return {'schema_version': 1, 'kind': self.kind, 'content': self.content}
        if self.kind == 'artifact-draft':
            return {'schema_version': 1, 'kind': self.kind,
                    'artifact_kind': self.artifact_kind, 'title': self.title,
                    'content': self.content}
        if self.kind == 'presentation-draft':
            return {'schema_version': 1, 'kind': self.kind,
                    'operation': self.operation,
                    'target_artifact_id': self.target_artifact_id,
                    'source_artifact_ids': list(self.source_artifact_ids),
                    'base_revision': self.base_revision, 'deck': self.deck,
                    'deck_sha256': self.deck_sha256}
        return {'schema_version': 1, 'kind': self.kind, 'purpose': self.purpose,
                'query': self.content, 'message_ids': list(self.message_ids),
                'artifact_ids': list(self.artifact_ids)}

    def canonical(self):
        return json.dumps(self.serialize(), ensure_ascii=False, sort_keys=True,
                          separators=(',', ':')).encode('utf-8')
