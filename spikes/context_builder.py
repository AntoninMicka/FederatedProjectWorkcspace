# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only, backend-neutral Context Manifest PoC."""
from dataclasses import dataclass
import base64
import hashlib
import json
from types import MappingProxyType

from spikes.configuration import committed_project
from spikes.metadata import MAX_FILE, require, uuid, validate_snapshot
from spikes.workspace import PendingOperation


MAX_CONTEXT = 16 * 1024 * 1024
BOUNDARIES = {'same-node', 'private-network', 'trusted-federation', 'external-provider'}
PRIVACY = {'public', 'project', 'confidential', 'local-only'}


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()


def _text(value, label):
    require(isinstance(value, str) and value.strip() == value and bool(value)
            and not any(c in value for c in '\0\r\n'), f'Invalid {label}')
    return value


@dataclass(frozen=True)
class Authority:
    session_id: str
    user_id: str
    node_id: str
    policy_revision: str
    readable_entities: frozenset

    def validate(self):
        _text(self.session_id, 'session ID')
        uuid(self.user_id); uuid(self.node_id)
        _text(self.policy_revision, 'policy revision')
        require(isinstance(self.readable_entities, frozenset), 'Readable entities must be frozen')
        for value in self.readable_entities:
            uuid(value)
        return self


@dataclass(frozen=True)
class Target:
    binding_id: str
    binding_revision: str
    boundary: str
    target_id: str
    model: str

    def validate(self):
        uuid(self.binding_id)
        _text(self.binding_revision, 'binding revision')
        require(self.boundary in BOUNDARIES, 'Invalid execution boundary')
        _text(self.target_id, 'target ID'); _text(self.model, 'model')
        return self


@dataclass(frozen=True)
class ProjectInput:
    entity_id: str
    required: bool = True


@dataclass(frozen=True)
class AdHocInput:
    input_id: str
    content: bytes
    privacy: str
    required: bool = True


@dataclass(frozen=True)
class PreparedContext:
    manifest: MappingProxyType
    manifest_bytes: bytes
    payload: bytes


@dataclass(frozen=True)
class DispatchHandoff:
    run_id: str
    manifest_id: str
    manifest_sha256: str
    target: Target
    payload: bytes


class ContextBuilder:
    def __init__(self, workspace, project_id):
        self.workspace = workspace
        uuid(project_id)
        self.project_id = project_id

    def prepare(self, *, manifest_id, run_id, authority, target, project_inputs=(),
                ad_hoc_inputs=(), omitted=()):
        uuid(manifest_id); uuid(run_id)
        authority.validate(); target.validate()
        require(isinstance(project_inputs, tuple) and isinstance(ad_hoc_inputs, tuple),
                'Inputs must be immutable tuples')
        require(isinstance(omitted, tuple), 'Omissions must be an immutable tuple')
        with self.workspace.journal.lock(), self.workspace.journal.connect() as db:
            return self._prepare_locked(db, manifest_id, run_id, authority, target,
                                        project_inputs, ad_hoc_inputs, omitted)

    def _prepare_locked(self, db, manifest_id, run_id, authority, target,
                        project_inputs, ad_hoc_inputs, omitted):
        if self.workspace._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
            raise PendingOperation('Project has an unfinished operation')
        self.workspace._branch()
        head = self.workspace.git.head()
        committed_project(self.workspace.git, head, self.project_id)
        files = self.workspace.git.snapshot(head)
        entities = validate_snapshot(files)
        records, parts, omissions, seen, total = [], [], [], set(), 0
        for choice in project_inputs:
            require(isinstance(choice, ProjectInput), 'Invalid project input')
            uuid(choice.entity_id)
            require(type(choice.required) is bool and choice.entity_id not in seen,
                    'Duplicate or invalid project input')
            seen.add(choice.entity_id)
            require(choice.entity_id in authority.readable_entities,
                    'Input is not authorized for this user')
            if choice.entity_id not in entities:
                require(not choice.required, 'Required project input is unavailable')
                omissions.append(dict(input_id=choice.entity_id,
                                      reason='optional project input unavailable'))
                continue
            meta = entities[choice.entity_id]
            prefix = f'artifacts/{choice.entity_id}/'
            candidates = sorted(p for p in files if p.startswith(prefix) and not p.endswith('/metadata.json'))
            require(len(candidates) == 1, 'Project input has no unique content')
            path, raw = candidates[0], files[candidates[0]]
            total += len(raw); require(total <= MAX_CONTEXT, 'Context exceeds 16 MiB')
            records.append(dict(input_id=choice.entity_id, source='project', required=choice.required,
                                path=path, privacy=meta['privacy'], size=len(raw), sha256=_digest(raw)))
            parts.append(dict(input_id=choice.entity_id, content_b64=base64.b64encode(raw).decode()))
        for choice in ad_hoc_inputs:
            require(isinstance(choice, AdHocInput), 'Invalid ad-hoc input')
            uuid(choice.input_id)
            require(type(choice.content) is bytes and len(choice.content) <= MAX_FILE,
                    'Invalid or oversized ad-hoc input')
            require(choice.privacy in PRIVACY and type(choice.required) is bool
                    and choice.input_id not in seen, 'Duplicate or invalid ad-hoc input')
            seen.add(choice.input_id); total += len(choice.content)
            require(total <= MAX_CONTEXT, 'Context exceeds 16 MiB')
            records.append(dict(input_id=choice.input_id, source='ad-hoc', required=choice.required,
                                privacy=choice.privacy, size=len(choice.content),
                                sha256=_digest(choice.content)))
            parts.append(dict(input_id=choice.input_id,
                              content_b64=base64.b64encode(choice.content).decode()))
        for item in omitted:
            require(isinstance(item, tuple) and len(item) == 2, 'Invalid omission')
            input_id, reason = item; uuid(input_id); _text(reason, 'omission reason')
            require(input_id not in seen and not any(row['input_id'] == input_id for row in omissions),
                    'Included input cannot also be omitted')
            omissions.append(dict(input_id=input_id, reason=reason))
        require(records, 'At least one included input is required')
        require(not any(row['privacy'] == 'local-only' for row in records)
                or target.boundary == 'same-node', 'local-only requires same-node execution')
        payload = _canonical(dict(schema_version=1, inputs=parts))
        manifest = dict(schema_version=1, manifest_id=manifest_id, run_id=run_id,
                        project_id=self.project_id, project_commit=head,
                        session_id=authority.session_id, user_id=authority.user_id,
                        node_id=authority.node_id, policy_revision=authority.policy_revision,
                        target=dict(binding_id=target.binding_id,
                                    binding_revision=target.binding_revision,
                                    boundary=target.boundary, target_id=target.target_id,
                                    model=target.model), inputs=records, omitted=omissions,
                        payload_sha256=_digest(payload), payload_size=len(payload))
        manifest_bytes = _canonical(manifest)
        require(self.workspace.git.head() == head, 'Project changed during context preparation')
        return PreparedContext(MappingProxyType(manifest), manifest_bytes, payload)

    def authorize_for_dispatch(self, prepared, *, authority, target):
        require(isinstance(prepared, PreparedContext), 'Invalid prepared context')
        authority.validate(); target.validate()
        manifest = dict(prepared.manifest)
        require(prepared.manifest_bytes == _canonical(manifest), 'Manifest bytes changed')
        require(manifest['payload_sha256'] == _digest(prepared.payload)
                and manifest['payload_size'] == len(prepared.payload), 'Prepared payload changed')
        with self.workspace.journal.lock(), self.workspace.journal.connect() as db:
            if self.workspace._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
                raise PendingOperation('Project has an unfinished operation')
            require(self.workspace.git.head() == manifest['project_commit'],
                    'Project changed after context preparation')
            require((manifest['session_id'], manifest['user_id'], manifest['node_id'],
                     manifest['policy_revision']) ==
                    (authority.session_id, authority.user_id, authority.node_id,
                     authority.policy_revision), 'Authority changed after context preparation')
            require(manifest['target'] == dict(binding_id=target.binding_id,
                    binding_revision=target.binding_revision, boundary=target.boundary,
                    target_id=target.target_id, model=target.model),
                    'Backend target changed after context preparation')
            files = self.workspace.git.snapshot(manifest['project_commit'])
            validate_snapshot(files)
            for item in manifest['inputs']:
                if item['source'] == 'project':
                    require(item['input_id'] in authority.readable_entities,
                            'Input authorization was revoked')
                    raw = files.get(item['path'])
                    require(raw is not None and len(raw) == item['size']
                            and _digest(raw) == item['sha256'], 'Project input changed')
                require(item['privacy'] != 'local-only' or target.boundary == 'same-node',
                        'local-only requires same-node execution')
            require(self.workspace.git.head() == manifest['project_commit'],
                    'Project changed during dispatch authorization')
            return DispatchHandoff(manifest['run_id'], manifest['manifest_id'],
                                   _digest(prepared.manifest_bytes), target,
                                   prepared.payload)
