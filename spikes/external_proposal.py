# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Strict untrusted proposal emitted by a local orchestration model."""
from dataclasses import dataclass
import hashlib
import json

from spikes.backend_contract import ROLES
from spikes.metadata import require, uuid


@dataclass(frozen=True)
class ExternalCallProposal:
    purpose: str
    role_id: str
    role_revision: str
    capability: str
    output_format: str
    message_ids: tuple

    @classmethod
    def parse(cls, value):
        required = {'schema_version', 'action', 'purpose', 'role_id', 'role_revision',
                    'capability', 'output_format', 'message_ids'}
        require(isinstance(value, dict) and set(value) == required,
                'Unknown or missing external proposal field')
        require(value['schema_version'] == 1
                and value['action'] == 'propose-external-call',
                'Unsupported external proposal')
        purpose = value['purpose']
        require(isinstance(purpose, str) and purpose.strip() == purpose and bool(purpose)
                and len(purpose.encode()) <= 2000 and '\0' not in purpose,
                'Invalid external proposal purpose')
        require(value['capability'] == 'generate-text'
                and value['output_format'] == 'text',
                'Unsupported external proposal capability')
        role = ROLES.resolve(value['role_id'], value['role_revision'])
        require(role.role_id == 'creator' and role.operation == value['capability']
                and role.output_format == value['output_format'],
                'Unsupported external proposal role')
        message_ids = value['message_ids']
        require(isinstance(message_ids, list) and bool(message_ids)
                and len(message_ids) == len(set(message_ids)),
                'External proposal requires unique message IDs')
        for message_id in message_ids:
            uuid(message_id)
        return cls(purpose, role.role_id, role.revision, value['capability'],
                   value['output_format'], tuple(message_ids))

    def serialize(self):
        return {'schema_version': 1, 'action': 'propose-external-call',
                'purpose': self.purpose, 'role_id': self.role_id,
                'role_revision': self.role_revision, 'capability': self.capability,
                'output_format': self.output_format, 'message_ids': list(self.message_ids)}

    def sha256(self):
        raw = json.dumps(self.serialize(), ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode()
        return hashlib.sha256(raw).hexdigest()
