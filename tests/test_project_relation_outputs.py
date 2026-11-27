# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
import unittest
from uuid import uuid4

from tests import test_project_relation_resolver as fixtures
from spikes.metadata import ValidationError
from spikes.project_relation_resolver import RelationViewUnavailable
from spikes.cross_references import ReferenceUnavailable
from spikes.reference_schema import SHARE
from spikes.reporting_schema import digest, encoded


class OutputResolverTests(unittest.TestCase):
    setUp = fixtures.HierarchyResolverTests.setUp
    save = fixtures.HierarchyResolverTests.save
    relation = fixtures.HierarchyResolverTests.relation
    member = fixtures.HierarchyResolverTests.member
    revoke = fixtures.HierarchyResolverTests.revoke
    keys = staticmethod(fixtures.HierarchyResolverTests.keys)

    def publish(self, pid, id_, *, target=None, checkpoint=lambda stage: None):
        refs = self.lifecycle.references
        value = refs.share_preview(pid, str(uuid4()), id_, [target or self.x], 'Potvrzený výstup', purpose='output')
        op = str(uuid4())
        receipt = refs.share_write(value, op, digest(encoded(value)), confirm=True, checkpoint=checkpoint)
        return value, op, receipt

    def unpublish(self, pid, share_id):
        refs = self.lifecycle.references; preview = refs.revoke_preview(pid, share_id)
        refs.revoke(preview, str(uuid4()), digest(encoded(preview)), confirm=True)

    def test_dependency_exposes_only_confirmed_outputs_including_future_outputs(self):
        self.relation(self.a, self.b, 'depends_on')
        private = self.save(self.b, 'Interní podklad'); output = self.save(self.b, 'Publikovaný výstup')
        before = self.resolver.catalog(self.a)
        self.assertNotIn((self.b, output), self.keys(before))
        declaration, _, _ = self.publish(self.b, output)
        # Explicit XREF target is X, while a separately approved relation authorizes A.
        self.assertEqual(declaration['record']['targets'], [self.x])
        refs = self.lifecycle.references
        with self.assertRaises(ReferenceUnavailable):
            refs.preview(self.a, str(uuid4()), refs.source_pin(self.b, output), 'XREF nadále omezené cíli',
                         share_id=declaration['share_id'], reason_text='Není explicitní cíl')
        reader, _, _ = self.member({self.a: 'reader'})
        view = reader.catalog(self.a)
        self.assertIn((self.b, output), self.keys(view)); self.assertNotIn((self.b, private), self.keys(view))
        self.assertNotIn(private, repr(view)); self.assertNotIn('Interní podklad', repr(view)); self.assertNotIn(self.x, repr(view))
        pin = reader.pin(self.a, self.b, output)
        self.assertEqual(pin['schema'], 'fpw-project-relation-input-v2')
        self.assertEqual(pin['authorization']['scope'], 'outputs')
        self.assertEqual(reader.read(pin)['raw'], 'Publikovaný výstup'.encode())
        added = self.save(self.b, 'Nový výstup'); self.publish(self.b, added)
        self.assertIn((self.b, added), self.keys(reader.catalog(self.a)))
        with self.assertRaises(RelationViewUnavailable):
            reader.pin(self.a, self.b, private)
        reverse_private = self.save(self.a, 'Interní příjemce')
        self.assertNotIn((self.a, reverse_private), self.keys(self.resolver.catalog(self.b)))

    def test_related_projects_share_outputs_both_ways_and_stop_symmetric_cycles(self):
        self.relation(self.a, self.b, 'relates_to'); self.relation(self.b, self.c, 'relates_to')
        self.relation(self.c, self.a, 'relates_to')
        a = self.save(self.a, 'Výstup A'); b = self.save(self.b, 'Výstup B')
        self.publish(self.a, a); self.publish(self.b, b)
        secret = self.save(self.b, 'Tajný podklad B')
        for recipient, provider, id_, body in ((self.a, self.b, b, 'Výstup B'), (self.b, self.a, a, 'Výstup A')):
            view = self.resolver.catalog(recipient)
            self.assertIn((provider, id_), self.keys(view))
            self.assertEqual(self.resolver.read(self.resolver.pin(recipient, provider, id_))['raw'], body.encode())
        self.assertNotIn((self.b, secret), self.keys(self.resolver.catalog(self.a)))

    def test_output_limit_survives_later_hierarchy_and_transitive_related_edge(self):
        ab = self.relation(self.a, self.b, 'depends_on'); bc = self.relation(self.b, self.c)
        self.relation(self.c, self.x, 'relates_to')
        child_private = self.save(self.c, 'Vnořený interní podklad')
        child_output = self.save(self.c, 'Vnořený výstup'); self.publish(self.c, child_output)
        related_output = self.save(self.x, 'Výstup dalšího projektu'); self.publish(self.x, related_output, target=self.b)
        view = self.resolver.catalog(self.a)
        self.assertNotIn((self.c, child_private), self.keys(view))
        self.assertTrue({(self.c, child_output), (self.x, related_output)} <= self.keys(view))
        pin = self.resolver.pin(self.a, self.c, child_output, relation_ids=[ab, bc])
        self.assertEqual(pin['authorization']['scope'], 'outputs')
        forged = deepcopy(pin); forged['authorization']['scope'] = 'data'
        del forged['authorization']['publication']; forged['schema'] = 'fpw-project-relation-input-v1'
        with self.assertRaises(ValidationError):
            self.resolver.read(forged)

    def test_data_alternative_does_not_widen_explicit_output_path_and_rows_are_deduplicated(self):
        wide = self.relation(self.a, self.b)
        ax = self.relation(self.a, self.x, 'depends_on'); xb = self.relation(self.x, self.b)
        private = self.save(self.b, 'Dostupné jen širší cestou')
        output = self.save(self.b, 'Oběma cestami'); self.publish(self.b, output)
        view = self.resolver.catalog(self.a)
        row = next(r for r in view['items'] if r['artifact_id'] == output)
        self.assertEqual(row['scopes'], ['data', 'outputs'])
        self.assertEqual(sum(r['artifact_id'] == output for r in view['items']), 1)
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.pin(self.a, self.b, private, relation_ids=[ax, xb])
        pin = self.resolver.pin(self.a, self.b, private, relation_ids=[wide])
        self.assertEqual(pin['schema'], 'fpw-project-relation-input-v1')
        self.assertEqual(self.resolver.read(pin)['raw'], 'Dostupné jen širší cestou'.encode())

    def test_revoked_publication_keeps_other_declaration_but_never_replaces_pinned_proof(self):
        self.relation(self.a, self.b, 'depends_on'); id_ = self.save(self.b, 'Zachovat důvod publikace')
        self.publish(self.b, id_); self.publish(self.b, id_)
        pin = self.resolver.pin(self.a, self.b, id_)
        chosen = pin['authorization']['publication']['share_id']
        self.unpublish(self.b, chosen)
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.read(pin)
        view = self.resolver.catalog(self.a)
        self.assertIn((self.b, id_), self.keys(view))
        fresh = self.resolver.pin(self.a, self.b, id_)
        self.assertNotEqual(fresh['authorization']['publication']['share_id'], chosen)
        self.unpublish(self.b, fresh['authorization']['publication']['share_id'])
        self.assertNotIn((self.b, id_), self.keys(self.resolver.catalog(self.a)))
        self.assertIn(id_, self.lifecycle.references.project_state(self.b, extra_ids=[id_])['artifacts'])

    def test_historical_bytes_survive_edits_but_prepublication_pin_is_rejected(self):
        self.relation(self.a, self.b, 'depends_on'); id_ = self.save(self.b, 'Ještě nepublikovaný draft')
        before = self.resolver._snapshot(self.b, self.artifacts.workspace(self.b).git.head())
        old_path, raw, meta = self.resolver._content(before[1], before[2], id_)
        old_source = self.resolver._source(self.b, self.artifacts.workspace(self.b).git.head(), old_path, raw, meta)
        self.save(self.b, 'Schválená verze', id_=id_, new=False); self.publish(self.b, id_)
        pin = self.resolver.pin(self.a, self.b, id_)
        self.save(self.b, 'Nová revize výstupu', id_=id_, new=False)
        read = self.resolver.read(pin)
        self.assertEqual(read['raw'], 'Schválená verze'.encode()); self.assertIsNotNone(read['newer'])
        forged = deepcopy(pin); forged['source'] = old_source
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.read(forged)
        forged = deepcopy(pin); forged['authorization']['publication']['operation_id'] = str(uuid4())
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.read(forged)

    def test_purpose_output_json_without_exact_native_confirmation_is_not_publication(self):
        self.relation(self.a, self.b, 'depends_on'); id_ = self.save(self.b, 'Podvržené označení')
        refs = self.lifecycle.references
        preview = refs.share_preview(self.b, str(uuid4()), id_, [self.x], 'Bez potvrzení', purpose='output')
        with self.assertRaises(ValidationError):
            refs.share_write(preview, str(uuid4()), digest(encoded(preview)))
        share_id = preview['share_id']; record = preview['record']
        meta = dict(schema_version=1, id=share_id, title=preview['title'], kind='document',
                    created_at=record['created_at'], author_id=refs.user_id, privacy='project',
                    provenance='user', file='share.json', tags=[SHARE])
        ws = self.artifacts.workspace(self.b)
        ws.apply({f'artifacts/{share_id}/share.json': encoded(record), f'artifacts/{share_id}/metadata.json': encoded(meta)},
                 author_name='Test', author_email='test@local.invalid', message='Generic import of claimed output')
        self.assertNotIn((self.b, id_), self.keys(self.resolver.catalog(self.a)))
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.pin(self.a, self.b, id_)

    def test_unaccepted_model_drafts_and_failed_unknown_chat_outputs_are_not_published(self):
        self.relation(self.a, self.b, 'depends_on')
        ids = {}
        for state in ('completed', 'failed', 'unknown'):
            id_ = str(uuid4()); ws = self.artifacts.workspace(self.b)
            marker = dict(schema='fpw-chat-output-v1', turns=[dict(state=state, error=None)])
            body = '<!-- fpw-chat-output-v1\n' + json.dumps(marker) + '\n-->\nModelový text\n'
            self.artifacts.save(dict(project_id=self.b, artifact_id=id_, base_head=ws.git.head(),
                                     title='Model ' + state, body=body, new=True), str(uuid4()), provenance='llm-generated')
            ids[state] = id_
            if state != 'completed':
                self.publish(self.b, id_)
        # Even successful model text is not published until explicit editorial confirmation.
        view = self.resolver.catalog(self.a)
        self.assertTrue(all((self.b, id_) not in self.keys(view) for id_ in ids.values()))
        self.publish(self.b, ids['completed'])
        self.assertIn((self.b, ids['completed']), self.keys(self.resolver.catalog(self.a)))
        for state in ('failed', 'unknown'):
            with self.assertRaises(RelationViewUnavailable):
                self.resolver.pin(self.a, self.b, ids[state])

    def test_native_chat_output_requires_separate_confirmed_output_declaration(self):
        from spikes.chat_records import ChatRecords
        from spikes.chat_threads import ChatThreads
        from spikes.projects import Projects
        self.relation(self.a, self.b, 'depends_on')
        chat = self.base / 'chat'; chat.mkdir(mode=0o700)
        threads = ChatThreads(chat); records = ChatRecords(self.node, Projects(self.node), state_dir=chat)
        node = json.loads(self.node.read_bytes()); uid = self.lifecycle.user_id
        tid, turn, user_message, run, answer = (str(uuid4()) for _ in range(5))
        now = '2026-11-26T00:00:00Z'
        threads.create(thread_id=tid, node_id=node['id'], user_id=uid, created_at=now)
        threads.prepare_turn(thread_id=tid, node_id=node['id'], user_id=uid, turn_id=turn,
                             message_id=user_message, content='Zadání', privacy='project', created_at=now,
                             response_language='cs-CZ', language_source='node')
        threads.bind_run(turn_id=turn, node_id=node['id'], user_id=uid, run_id=run, manifest_id=str(uuid4()))
        threads.complete(turn_id=turn, node_id=node['id'], user_id=uid, run_id=run, message_id=answer,
                         content='Nativně uložená odpověď', privacy='project', created_at=now)
        thread = threads.get(tid, node['id'], uid)
        records.assign(project_id=self.b, thread_id=tid, expected_revision=thread['revision'])
        thread = threads.get(tid, node['id'], uid); id_ = str(uuid4())
        request = dict(project_id=self.b, thread_id=tid, expected_thread_revision=thread['revision'],
                       expected_head=self.artifacts.workspace(self.b).git.head(), artifact_id=id_, title='Odpověď',
                       body='Nativně uložená odpověď', created_at=now, message_ids=[answer],
                       snapshot_id=None, snapshot_sha256=None)
        records.publish_output(request, str(uuid4()))
        self.assertNotIn((self.b, id_), self.keys(self.resolver.catalog(self.a)))
        self.publish(self.b, id_)
        result = self.resolver.read(self.resolver.pin(self.a, self.b, id_))
        self.assertIn('Nativně uložená odpověď'.encode(), result['raw'])

    def test_pending_publication_recovery_and_local_only_checks_keep_fail_closed_behavior(self):
        self.relation(self.a, self.b, 'depends_on'); id_ = self.save(self.b, 'Lokální výstup', privacy='local-only')
        def crash(stage):
            if stage == 'prepared': raise RuntimeError('publication stopped')
        with self.assertRaises(RuntimeError):
            self.publish(self.b, id_, checkpoint=crash)
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.catalog(self.a)
        self.artifacts.workspace(self.b).recover()
        self.assertIn((self.b, id_), self.keys(self.resolver.catalog(self.a)))
        self.assertNotIn(id_, repr(self.resolver.catalog(self.a, boundary='external-provider')))
        pin = self.resolver.pin(self.a, self.b, id_)
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.read(pin, boundary='external-provider')
