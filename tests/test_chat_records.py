# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.chat_records import ChatRecords, parse_snapshot
from spikes.chat_threads import ChatThreads
from spikes.metadata import ValidationError, validate_snapshot, validate_transition
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git


NOW = '2026-09-18T15:00:00Z'


class ChatRecordTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.node = self.base / 'node.json'; self.root = self.base / 'project'
        self.created = ProjectCreation(self.node).create('Project', str(self.root), str(uuid4()))
        self.project_id = self.created['id']; self.git = Git(self.root)
        self.chat_state = self.base / 'chat'; self.chat_state.mkdir(mode=0o700)
        self.records = ChatRecords(self.node, Projects(self.node), state_dir=self.chat_state)
        self.threads = ChatThreads(self.chat_state)
        node = json.loads(self.node.read_bytes())
        self.node_id = node['id']; self.user_id = ProjectCreation(self.node).author_id()
        self.thread_id = str(uuid4())
        self.threads.create(thread_id=self.thread_id, node_id=self.node_id,
                            user_id=self.user_id, created_at=NOW)
        self._turn('Question', 'Answer', NOW, '2026-09-18T15:00:01Z')
        current = self.threads.get(self.thread_id, self.node_id, self.user_id)
        self.records.assign(project_id=self.project_id, thread_id=self.thread_id,
                            expected_revision=current['revision'])

    def _turn(self, question, answer, asked, answered):
        turn_id, message_id, run_id = (str(uuid4()) for _ in range(3))
        self.threads.prepare_turn(thread_id=self.thread_id, node_id=self.node_id,
            user_id=self.user_id, turn_id=turn_id, message_id=message_id,
            content=question, privacy='project', created_at=asked)
        self.threads.bind_run(turn_id=turn_id, node_id=self.node_id, user_id=self.user_id,
                              run_id=run_id, manifest_id=str(uuid4()))
        self.threads.complete(turn_id=turn_id, node_id=self.node_id, user_id=self.user_id,
            run_id=run_id, message_id=str(uuid4()), content=answer,
            privacy='confidential', created_at=answered)

    def request(self, *, mode='full', base_id=None, base_digest=None):
        thread = self.threads.get(self.thread_id, self.node_id, self.user_id)
        return {'project_id': self.project_id, 'thread_id': self.thread_id,
                'expected_thread_revision': thread['revision'],
                'expected_head': self.git.head(), 'snapshot_id': str(uuid4()),
                'mode': mode, 'title': 'Záznam brainstormingu', 'created_at': NOW,
                'base_snapshot_id': base_id, 'base_snapshot_sha256': base_digest}

    def _record(self, snapshot_id):
        files = self.git.snapshot(self.git.head())
        entities = validate_snapshot(files); meta = entities[snapshot_id]
        return parse_snapshot(files[f'artifacts/{snapshot_id}/{meta["file"]}'])

    def test_full_and_delta_records_preserve_provenance_and_strictest_privacy(self):
        full = self.request(); receipt = self.records.publish(full, str(uuid4()))
        record, digest = self._record(full['snapshot_id'])
        self.assertEqual(receipt['commit_id'], self.git.head())
        self.assertEqual([item['content'] for item in record['messages']], ['Question', 'Answer'])
        self.assertTrue(record['turns'][0]['manifest_id'])
        meta = validate_snapshot(self.git.snapshot(self.git.head()))[full['snapshot_id']]
        self.assertEqual((meta['kind'], meta['provenance'], meta['privacy']),
                         ('snapshot', 'snapshot', 'confidential'))

        self._turn('Next', 'Result', '2026-09-18T15:01:00Z', '2026-09-18T15:01:01Z')
        delta = self.request(mode='delta', base_id=full['snapshot_id'], base_digest=digest)
        self.records.publish(delta, str(uuid4()))
        delta_record, _ = self._record(delta['snapshot_id'])
        self.assertEqual([item['content'] for item in delta_record['messages']], ['Next', 'Result'])
        self.assertEqual(delta_record['base']['snapshot_id'], full['snapshot_id'])
        relation = validate_snapshot(self.git.snapshot(self.git.head()))[delta['snapshot_id']]['relations']
        self.assertEqual(relation, [{'type': 'derived-from', 'target_id': full['snapshot_id']}])

    def test_delta_missing_or_mismatched_base_fails_before_journal(self):
        request = self.request(mode='delta', base_id=str(uuid4()), base_digest='0' * 64)
        before = self.git.head()
        with self.assertRaisesRegex(ValidationError, 'missing'):
            self.records.publish(request, str(uuid4()))
        self.assertEqual(self.git.head(), before)
        self.assertIsNone(self.records.projects.workspace(self.project_id).recover())

        full = self.request(); self.records.publish(full, str(uuid4()))
        self._turn('Next', 'Result', '2026-09-18T15:02:00Z', '2026-09-18T15:02:01Z')
        bad = self.request(mode='delta', base_id=full['snapshot_id'], base_digest='f' * 64)
        with self.assertRaisesRegex(ValidationError, 'digest mismatch'):
            self.records.publish(bad, str(uuid4()))

    def test_retry_recovers_journal_and_snapshot_is_immutable(self):
        request = self.request(); operation = str(uuid4())
        def crash(stage):
            if stage == 'prepared':
                raise RuntimeError(stage)
        with self.assertRaisesRegex(RuntimeError, 'prepared'):
            self.records.publish(request, operation, checkpoint=crash)
        receipt = self.records.publish(request, operation)
        self.assertEqual(receipt['commit_id'], self.git.head())
        files = self.git.snapshot(self.git.head()); changed = dict(files)
        path = f'artifacts/{request["snapshot_id"]}/snapshot.md'
        changed[path] += b'changed\n'
        with self.assertRaisesRegex(ValidationError, 'Immutable snapshot content'):
            validate_transition(files, changed)

    def test_editable_output_keeps_exact_thread_run_manifest_provenance(self):
        thread = self.threads.get(self.thread_id, self.node_id, self.user_id)
        answer = thread['messages'][-1]
        request = {'project_id': self.project_id, 'thread_id': self.thread_id,
                   'expected_thread_revision': thread['revision'],
                   'expected_head': self.git.head(), 'artifact_id': str(uuid4()),
                   'title': 'Výstup', 'body': answer['content'], 'created_at': NOW,
                   'message_ids': [answer['message_id']],
                   'snapshot_id': None, 'snapshot_sha256': None}
        operation = str(uuid4())
        def crash(stage):
            if stage == 'prepared':
                raise RuntimeError(stage)
        with self.assertRaisesRegex(RuntimeError, 'prepared'):
            self.records.publish_output(request, operation, checkpoint=crash)
        receipt = ChatRecords(self.node, Projects(self.node),
                              state_dir=self.chat_state).publish_output(request, operation)
        files = self.git.snapshot(receipt['commit_id']); entities = validate_snapshot(files)
        meta = entities[request['artifact_id']]
        self.assertEqual((meta['kind'], meta['provenance'], meta['privacy']),
                         ('document', 'llm-generated', 'confidential'))
        raw = files[f'artifacts/{request["artifact_id"]}/content.md']
        self.assertIn(b'fpw-chat-output-v1', raw)
        self.assertIn(thread['turns'][0]['manifest_id'].encode(), raw)
        changed = dict(files); changed[f'artifacts/{request["artifact_id"]}/content.md'] = b'Edited\n'
        with self.assertRaisesRegex(ValidationError, 'provenance changed'):
            validate_transition(files, changed)
        workspace = self.records.projects.workspace(self.project_id)
        workspace.index.path.unlink()
        reopened = Projects(self.node).open(self.project_id)
        self.assertEqual(reopened['commit_id'], receipt['commit_id'])

        stale = dict(request, artifact_id=str(uuid4()), expected_head='0' * 40)
        with self.assertRaisesRegex(ValidationError, 'changed'):
            self.records.publish_output(stale, str(uuid4()))

    def test_assignment_and_revision_are_required(self):
        other = str(uuid4())
        self.threads.create(thread_id=other, node_id=self.node_id, user_id=self.user_id,
                            created_at=NOW)
        request = self.request(); request['thread_id'] = other
        request['expected_thread_revision'] = 0
        with self.assertRaisesRegex(ValidationError, 'not assigned'):
            self.records.publish(request, str(uuid4()))
        request = self.request(); request['expected_thread_revision'] -= 1
        with self.assertRaisesRegex(ValidationError, 'changed'):
            self.records.publish(request, str(uuid4()))


if __name__ == '__main__':
    unittest.main()
