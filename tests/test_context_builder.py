# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import dataclasses
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.context_builder import (AdHocInput, Authority, ContextBuilder, ConversationSelection,
                                    ProjectInput, Target)
from spikes.metadata import ValidationError
from spikes.project_creation import ProjectCreation
from spikes.storage import Git


class ContextBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.node = base / 'node.json'; self.root = base / 'project'
        created = ProjectCreation(self.node).create('Project', str(self.root), str(uuid4()))
        self.project_id = created['id']; self.git = Git(self.root)
        self.artifact_id = str(uuid4())
        Artifacts(self.node).save(dict(project_id=self.project_id, artifact_id=self.artifact_id,
            base_head=self.git.head(), title='Context', body='Přesné bajty.\n', new=True), str(uuid4()))
        self.workspace = Artifacts(self.node).workspace(self.project_id)
        self.builder = ContextBuilder(self.workspace, self.project_id)
        self.authority = Authority('session-1', ProjectCreation(self.node).author_id(),
                                   str(uuid4()), 'policy-1', frozenset({self.artifact_id}))
        self.target = Target(str(uuid4()), 'binding-1', 'same-node', 'local-runtime', 'model-a')

    def prepare(self, **extra):
        args = dict(manifest_id=str(uuid4()), run_id=str(uuid4()), authority=self.authority,
                    target=self.target, project_inputs=(ProjectInput(self.artifact_id),))
        args.update(extra)
        return self.builder.prepare(**args)

    def test_exact_deterministic_payload_and_handoff(self):
        prepared = self.prepare(omitted=((str(uuid4()), 'optional input not selected'),))
        manifest = dict(prepared.manifest)
        self.assertEqual(manifest['project_commit'], self.git.head())
        self.assertEqual(manifest['inputs'][0]['sha256'],
                         __import__('hashlib').sha256('Přesné bajty.\n'.encode()).hexdigest())
        self.assertEqual(json.loads(prepared.payload)['inputs'][0]['content_b64'],
                         'UMWZZXNuw6kgYmFqdHkuCg==')
        handoff = self.builder.authorize_for_dispatch(prepared, authority=self.authority,
                                                      target=self.target)
        self.assertEqual(handoff.payload, prepared.payload)

    def test_conversation_selection_is_explicit_and_bound_to_input_order(self):
        first, second = str(uuid4()), str(uuid4())
        conversation = ConversationSelection(str(uuid4()), 2, (first, second),
                                             ('user', 'assistant'))
        prepared = self.builder.prepare(manifest_id=str(uuid4()), run_id=str(uuid4()),
            authority=self.authority, target=self.target,
            ad_hoc_inputs=(AdHocInput(first, b'one', 'project'),
                           AdHocInput(second, b'two', 'confidential')),
            conversation=conversation)
        self.assertEqual(prepared.manifest['conversation'], dict(
            thread_id=conversation.thread_id, thread_revision=2,
            messages=[dict(message_id=first, role='user'),
                      dict(message_id=second, role='assistant')]))
        self.assertEqual(json.loads(prepared.payload)['conversation'], [
            dict(message_id=first, role='user'),
            dict(message_id=second, role='assistant')])
        with self.assertRaisesRegex(ValidationError, 'match included input order'):
            self.builder.prepare(manifest_id=str(uuid4()), run_id=str(uuid4()),
                authority=self.authority, target=self.target,
                ad_hoc_inputs=(AdHocInput(first, b'one', 'project'),
                               AdHocInput(second, b'two', 'project')),
                conversation=dataclasses.replace(conversation, message_ids=(second, first)))

    def test_stale_head_authority_and_target_are_rejected(self):
        prepared = self.prepare()
        changed = dataclasses.replace(self.authority, policy_revision='policy-2')
        with self.assertRaisesRegex(ValidationError, 'Authority changed'):
            self.builder.authorize_for_dispatch(prepared, authority=changed, target=self.target)
        changed_target = dataclasses.replace(self.target, target_id='another-runtime')
        with self.assertRaisesRegex(ValidationError, 'target changed'):
            self.builder.authorize_for_dispatch(prepared, authority=self.authority,
                                                target=changed_target)
        self.git.run('commit', '--allow-empty', '-m', 'Move HEAD')
        with self.assertRaisesRegex(ValidationError, 'Project changed'):
            self.builder.authorize_for_dispatch(prepared, authority=self.authority,
                                                target=self.target)

    def test_permission_privacy_and_no_implicit_fallback(self):
        denied = dataclasses.replace(self.authority, readable_entities=frozenset())
        with self.assertRaisesRegex(ValidationError, 'not authorized'):
            self.prepare(authority=denied)
        cloud = dataclasses.replace(self.target, boundary='external-provider',
                                    target_id='provider.example')
        local = AdHocInput(str(uuid4()), b'secret', 'local-only')
        with self.assertRaisesRegex(ValidationError, 'local-only'):
            self.builder.prepare(manifest_id=str(uuid4()), run_id=str(uuid4()),
                authority=self.authority, target=cloud, ad_hoc_inputs=(local,))
        private_network = dataclasses.replace(self.target, boundary='private-network',
                                              target_id='10.0.0.2')
        with self.assertRaisesRegex(ValidationError, 'local-only'):
            self.builder.prepare(manifest_id=str(uuid4()), run_id=str(uuid4()),
                authority=self.authority, target=private_network, ad_hoc_inputs=(local,))
        # A changed target is rejected; authorize never chooses an alternate target itself.
        prepared = self.prepare()
        with self.assertRaisesRegex(ValidationError, 'target changed'):
            self.builder.authorize_for_dispatch(prepared, authority=self.authority,
                                                target=cloud)

    def test_tampering_duplicates_limits_and_omissions(self):
        with self.assertRaisesRegex(ValidationError, 'Duplicate'):
            self.prepare(project_inputs=(ProjectInput(self.artifact_id),
                                         ProjectInput(self.artifact_id)))
        with self.assertRaisesRegex(ValidationError, 'Included input'):
            self.prepare(omitted=((self.artifact_id, 'not used'),))
        missing = str(uuid4())
        optional_authority = dataclasses.replace(
            self.authority, readable_entities=frozenset({self.artifact_id, missing}))
        prepared_optional = self.prepare(authority=optional_authority,
            project_inputs=(ProjectInput(self.artifact_id), ProjectInput(missing, required=False)))
        self.assertEqual(prepared_optional.manifest['omitted'], [dict(
            input_id=missing, reason='optional project input unavailable')])
        with self.assertRaisesRegex(ValidationError, 'Required project input'):
            self.prepare(authority=optional_authority,
                         project_inputs=(ProjectInput(missing),))
        prepared = self.prepare()
        tampered = dataclasses.replace(prepared, payload=prepared.payload + b'x')
        with self.assertRaisesRegex(ValidationError, 'payload changed'):
            self.builder.authorize_for_dispatch(tampered, authority=self.authority,
                                                target=self.target)
