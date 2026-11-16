# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import unittest
from uuid import uuid4
from tests import test_monitoring_blocks as fixtures
from spikes.metadata import ValidationError
from spikes.reporting_schema import encoded


class BlockDeleteTests(unittest.TestCase):
    setUp=fixtures.BlockTests.setUp

    def deletion(self, index):
        catalog=self.service.catalog(self.f.project)
        row=next(b for b in catalog['blocks'] if b['id']==self.specs[index]['id'])
        return catalog['commit_id'],dict(id=row['id'],previous=[row['ref']],privacy=row['privacy'],value=dict(row['value'],deleted=True))

    def test_delete_dependency_guards_exact_revision_replay_and_history(self):
        head,block=self.deletion(0)
        with self.assertRaisesRegex(ValidationError,'dependency'):
            self.service.remove(self.f.project,head,block,str(uuid4()),confirm=True)
        self.assertEqual(self.f.git.head(),head)
        head,block=self.deletion(4);operation=str(uuid4())
        with self.assertRaises(ValidationError):self.service.remove(self.f.project,head,block,operation,confirm=False)
        with self.assertRaisesRegex(ValidationError,'confirmed'):
            self.service.blocks.save(self.f.project,head,[block],operation)
        receipt=self.service.remove(self.f.project,head,block,operation,confirm=True)
        after=self.f.git.head()
        self.assertEqual(self.service.remove(self.f.project,head,block,operation,confirm=True),receipt)
        self.assertEqual(self.f.git.head(),after)
        catalog=self.service.catalog(self.f.project)
        self.assertNotIn(block['id'],{b['id'] for b in catalog['blocks']})
        records=self.service.blocks.reporting.read(self.f.project)['records']
        original=next(r for r in records if r['revision_id']==block['previous'][0]['artifact_id'])
        self.assertEqual(original['value'],{k:v for k,v in block['value'].items() if k!='deleted'})
        tombstone=next(r for r in records if r['value'].get('deleted'))
        resurrection=dict(block,previous=[self.service.blocks.reporting.pin(self.f.project,tombstone['revision_id'])],value=deepcopy(original['value']))
        with self.assertRaisesRegex(ValidationError,'restored'):
            self.service.blocks.save(self.f.project,after,[resurrection],str(uuid4()))

    def test_unknown_related_effect_blocks_deletion_and_precommit_crash_recovers_once(self):
        head,block=self.deletion(4)
        migration=str(uuid4())
        with self.service.pools.db() as db:
            db.execute('INSERT INTO block_jobs VALUES(?,?,?,?,NULL)',(migration,self.f.project,'prepared',encoded(dict(kind='migration',plan=dict(blocks=[dict(id=block['id'])])))))
        with self.assertRaisesRegex(ValidationError,'převod'):
            self.service.remove(self.f.project,head,block,str(uuid4()),confirm=True)
        with self.service.pools.db() as db:db.execute("UPDATE block_jobs SET state='completed' WHERE id=?",(migration,))
        job=str(uuid4())
        with self.service.pools.db() as db:
            db.execute('INSERT INTO block_jobs VALUES(?,?,?,?,NULL)',(job,self.f.project,'unknown',encoded(dict(kind='task',block=dict(id=block['id'])))))
        with self.assertRaisesRegex(ValidationError,'unknown'):
            self.service.remove(self.f.project,head,block,str(uuid4()),confirm=True)
        with self.service.pools.db() as db:db.execute("UPDATE block_jobs SET state='failed' WHERE id=?",(job,))
        operation=str(uuid4())
        def crash(stage):
            if stage=='before-ref':raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError):self.service.remove(self.f.project,head,block,operation,confirm=True,checkpoint=crash)
        self.service.remove(self.f.project,head,block,operation,confirm=True)
        after=self.f.git.head()
        self.service.remove(self.f.project,head,block,operation,confirm=True)
        self.assertEqual(self.f.git.head(),after)
        self.assertEqual(sum(bool(r['value'].get('deleted')) for r in self.service.blocks.reporting.read(self.f.project)['records']),1)

    def test_post_ref_recovery_preserves_exactly_one_deletion_revision(self):
        head,block=self.deletion(4);operation=str(uuid4())
        def crash(stage):
            if stage=='ref-updated':raise RuntimeError('after commit')
        with self.assertRaises(RuntimeError):self.service.remove(self.f.project,head,block,operation,confirm=True,checkpoint=crash)
        committed=self.f.git.head()
        self.service.remove(self.f.project,head,block,operation,confirm=True)
        self.assertEqual(self.f.git.head(),committed)
        self.assertEqual(sum(bool(r['value'].get('deleted')) for r in self.service.blocks.reporting.read(self.f.project)['records']),1)
