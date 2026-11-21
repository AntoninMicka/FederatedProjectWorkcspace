# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.artifact_sharing import ArtifactSharing
from spikes.artifacts import Artifacts
from spikes.cross_references import CrossReferences, ReferenceUnavailable
from spikes.metadata import ValidationError
from spikes.project_creation import ProjectCreation


class SharingFacadeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='artifact sharing '); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name); self.node = base / 'node.json'; creator = ProjectCreation(self.node)
        self.parent = creator.create('Nadřazený projekt', base / 'parent', str(uuid4()))['id']
        self.child = creator.create('Podprojekt', base / 'child', str(uuid4()))['id']
        self.hidden = creator.create('Skrytý projekt', base / 'hidden', str(uuid4()))['id']
        self.artifacts = Artifacts(self.node); self.assignment = str(uuid4())
        ws = self.artifacts.workspace(self.parent)
        self.artifacts.save(dict(project_id=self.parent, base_head=ws.git.head(), artifact_id=self.assignment,
                                 title='Zadání podprojektu', body='Zadání v1.\n', new=True), str(uuid4()))
        self.sharing = ArtifactSharing(CrossReferences(self.node))

    def share_and_attach(self, sharing=None):
        sharing = sharing or self.sharing
        offer = sharing.share_preview(self.parent, self.assignment, [self.child], 'share', 'Zadání pro tým')
        self.assertEqual(offer['display']['artifact_title'], 'Zadání podprojektu')
        self.assertEqual(offer['display']['targets'], [dict(id=self.child, title='Podprojekt')])
        sharing.share_confirm(offer['preview'], offer['sha256'], str(uuid4()))
        share_id = offer['preview']['share_id']
        attach = sharing.attach_preview(self.child, self.parent, share_id, 'Zadání', 'Pracujeme podle něj')
        self.assertEqual((attach['display']['source_title'], attach['display']['purpose']), ('Nadřazený projekt', 'share'))
        sharing.attach_confirm(attach['preview'], attach['sha256'], str(uuid4()))
        return share_id, attach['preview']['reference_id']

    def test_offer_attach_open_and_usage_overview(self):
        before = self.sharing.overview(self.child)
        self.assertEqual([c['title'] for c in before['candidates']], ['Nadřazený projekt', 'Skrytý projekt'])
        self.assertEqual(before['offers'], [])
        share_id, ref = self.share_and_attach()
        child = self.sharing.overview(self.child)
        self.assertEqual([(o['share_id'], o['source_title'], o['attached_reference_ids']) for o in child['offers']],
                         [(share_id, 'Nadřazený projekt', [ref])])
        self.assertEqual([(r['reference_id'], r['source_title'], r['share']['reason']) for r in child['references']],
                         [(ref, 'Nadřazený projekt', 'Pracujeme podle něj')])
        parent = self.sharing.overview(self.parent)
        self.assertEqual(parent['shares'][0]['usage'], [dict(project_id=self.child, project_title='Podprojekt',
                                                             reference_id=ref, title='Zadání')])
        view = self.sharing.reference_view(self.child, ref)
        self.assertTrue(view['read_only']); self.assertEqual(view['state'], 'current')
        self.assertEqual((view['preview']['text'], view['source_title']), ('Zadání v1.\n', 'Nadřazený projekt'))
        self.assertNotIn('content_b64', view)

    def test_output_offer_and_wrong_target_is_never_attachable(self):
        out = str(uuid4()); ws = self.artifacts.workspace(self.child)
        self.artifacts.save(dict(project_id=self.child, base_head=ws.git.head(), artifact_id=out,
                                 title='Výsledek', body='Výstup.\n', new=True), str(uuid4()))
        offer = self.sharing.share_preview(self.child, out, [self.parent], 'output', 'Výsledek podprojektu')
        self.sharing.share_confirm(offer['preview'], offer['sha256'], str(uuid4()))
        offers = self.sharing.overview(self.parent)['offers']
        self.assertEqual([(o['purpose'], o['artifact_title']) for o in offers], [('output', 'Výsledek')])
        self.assertEqual(self.sharing.overview(self.hidden)['offers'], [])
        with self.assertRaises(ReferenceUnavailable):
            self.sharing.attach_preview(self.hidden, self.child, offer['preview']['share_id'], 'X', 'Y')

    def test_inaccessible_projects_are_not_revealed_and_confirm_requires_exact_digest(self):
        admin = Administration(self.node); actor = dict(id=None, node_role='federation-admin', memberships={})
        def change(**data):
            current = admin.request(actor, dict(action='list'))
            return admin.request(actor, dict(expected_commit=current['commit_id'], **data))
        uid = change(action='create-user', name='Člen', node_role='member')['users'][0]['id']
        change(action='update-user', user_id=uid, active=True, node_role='member',
               memberships={self.parent: 'editor', self.child: 'editor'})
        member = ArtifactSharing(CrossReferences(self.node, user_id=uid))
        share_id, ref = self.share_and_attach()
        hidden_offer = self.sharing.share_preview(self.parent, self.assignment, [self.hidden, self.child], 'share', 'Dva cíle')
        self.sharing.share_confirm(hidden_offer['preview'], hidden_offer['sha256'], str(uuid4()))
        overview = member.overview(self.parent)
        self.assertEqual([c['title'] for c in overview['candidates']], ['Podprojekt'])
        text = repr(overview)
        self.assertNotIn(self.hidden, text); self.assertNotIn('Skrytý projekt', text)
        with self.assertRaises(AccessDenied):
            member.share_preview(self.parent, self.assignment, [self.hidden], 'share', 'Skrytý cíl')
        offer = member.share_preview(self.parent, self.assignment, [self.child], 'share', 'Člen sdílí')
        with self.assertRaises(ValidationError):
            member.share_confirm(offer['preview'], '0' * 64, str(uuid4()))
        with self.assertRaises(ValidationError):
            member.share_confirm(dict(offer['preview'], reason='Podvržený důvod'), offer['sha256'], str(uuid4()))

    def test_deleted_source_is_a_visible_state_in_the_reference_view(self):
        share_id, ref = self.share_and_attach()
        ws = self.artifacts.workspace(self.parent)
        self.artifacts.delete(dict(project_id=self.parent, artifact_id=self.assignment, base_head=ws.git.head()), str(uuid4()))
        view = self.sharing.reference_view(self.child, ref)
        self.assertEqual((view['state'], view['preview'], view['title']), ('deleted', None, 'Zadání'))
        self.assertFalse(self.sharing.overview(self.parent)['shares'][0]['available'])


if __name__ == '__main__': unittest.main()
