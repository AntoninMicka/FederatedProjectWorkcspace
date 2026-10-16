# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Durable exact public histories and export projections."""
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from uuid import uuid4

from spikes.artifact_actions import ArtifactActions
from spikes.desktop_ui import (finish_presentation_session, presentation_public_payload,
                               presentation_status)
from spikes.presentation_documents import PresentationDocuments, new_deck
from spikes.presentation_sessions import (PresentationSessions, decode_session,
                                           encode_session, validate_session)
from spikes.project_creation import ProjectCreation
from spikes.storage import Git


class PresentationSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.node = self.base / 'node.json'
        self.root = self.base / 'project'
        self.project = ProjectCreation(self.node).create(
            'Session project', str(self.root), str(uuid4()))['id']
        self.git = Git(self.root); self.documents = PresentationDocuments(self.node)
        self.deck_id = str(uuid4()); self.deck = new_deck(); self.deck['title'] = 'Bezpečný deck'
        self.deck['slides'][0].update(title='Veřejný nadpis', bullets=['První', 'Druhý'],
                                      notes='Soukromá poznámka')
        self.documents.save(dict(project_id=self.project, artifact_id=self.deck_id,
                                 base_head=self.git.head(), new=True, deck=self.deck), str(uuid4()))
        self.revision = self.git.head() + ':' + self.deck_id
        self.sessions = PresentationSessions(self.node)

    def content(self, bullets=None):
        return dict(title='Veřejný nadpis', body='\n'.join(bullets or ['První']),
                    bullets=bullets or ['První'], background='#102b36',
                    foreground='#ffffff', wallpaper='', layout={
                        'id': 'content', 'revision': 1, 'name': 'Nadpis a obsah',
                        'preset': 'title-content', 'title_align': 'left',
                        'content_align': 'left', 'density': 'normal',
                        'background': '#102b36', 'foreground': '#ffffff',
                        'accent': '#79c9ac'}, column_break=0)

    def test_finish_materializes_exact_public_pages_and_export_modes(self):
        session_id = self.sessions.start(self.project, self.deck_id, self.revision,
                                         self.deck['title'])
        slide_id = self.deck['slides'][0]['id']
        self.sessions.record(session_id, slide_id, '16:9', self.content(['První']))
        self.sessions.record(session_id, slide_id, '16:9', self.content(['První', 'Druhý']))
        artifact_id = self.sessions.finish(session_id)

        view = self.documents.open(self.project)
        self.assertEqual(len(view['sessions']), 1)
        row = view['sessions'][0]
        self.assertEqual(row['id'], artifact_id)
        self.assertEqual(row['session']['outcome'], 'completed')
        self.assertEqual([page['content']['bullets'] for page in row['session']['pages']],
                         [['První'], ['První', 'Druhý']])
        self.assertNotIn('Soukromá', row['body'])

        session_preview = self.documents.export_preview(
            self.project, self.deck_id, view['commit_id'], session_artifact_id=artifact_id)
        self.assertEqual(session_preview['mode'], 'session')
        self.assertEqual([page['bullets'] for page in session_preview['pages']],
                         [['První'], ['První', 'Druhý']])
        canonical = self.documents.export_preview(
            self.project, self.deck_id, view['commit_id'])
        self.assertEqual(canonical['mode'], 'canonical')
        self.assertEqual(len(canonical['pages']), 1)
        self.assertNotIn('notes', canonical['pages'][0])

    def test_presenter_api_records_only_confirmed_show_before_success(self):
        selected = self.documents.select(self.project, self.deck_id, self.git.head())
        server = SimpleNamespace(presentation_selected_deck=selected,
                                 presentation_sessions=self.sessions)
        started = presentation_status(server, start=True)
        first = started['slides'][0]
        request = dict(action='show', slide=0, slide_id=first['id'],
                       deck_revision=first['deck_revision'], rows=1)
        shown = presentation_public_payload(server, request)
        self.assertEqual(shown['content']['bullets'], ['První'])
        receipt = finish_presentation_session(server)
        self.assertTrue(receipt['saved'])
        session = self.documents.open(self.project)['sessions'][0]['session']
        self.assertEqual(len(session['pages']), 1)
        self.assertEqual(session['pages'][0]['content']['bullets'], ['První'])

    def test_restart_recovers_unfinished_session_once_as_interrupted(self):
        session_id = self.sessions.start(self.project, self.deck_id, self.revision,
                                         self.deck['title'])
        self.sessions.record(session_id, self.deck['slides'][0]['id'], '4:3', self.content())
        recovered = PresentationSessions(self.node).recover()
        self.assertEqual(len(recovered), 1)
        head = self.git.head()
        self.assertEqual(PresentationSessions(self.node).recover(), [])
        self.assertEqual(self.git.head(), head)
        session = self.documents.open(self.project)['sessions'][0]['session']
        self.assertEqual(session['outcome'], 'interrupted')
        self.assertEqual(session['pages'][0]['ratio'], '4:3')

    def test_session_delete_uses_exact_head_preview_and_keeps_git_history(self):
        session_id = self.sessions.start(self.project, self.deck_id, self.revision,
                                         self.deck['title'])
        self.sessions.record(session_id, self.deck['slides'][0]['id'], '16:9', self.content())
        artifact_id = self.sessions.finish(session_id); head = self.git.head()
        actions = ArtifactActions(self.node)
        preview = actions.deletion_preview(self.project, artifact_id, head)
        actions.delete(self.project, artifact_id, head, preview['preview_sha256'], str(uuid4()))
        self.assertEqual(self.documents.open(self.project)['sessions'], [])
        path = f'artifacts/{artifact_id}/content.md'
        self.assertIn(path, self.git.snapshot(head))
        self.assertNotIn(path, self.git.snapshot(self.git.head()))

    def test_post_commit_retry_uses_stable_operation_without_duplicate(self):
        session_id = self.sessions.start(self.project, self.deck_id, self.revision,
                                         self.deck['title'])
        self.sessions.record(session_id, self.deck['slides'][0]['id'], '16:9', self.content())
        original = self.sessions.artifacts.save
        def uncertain(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('uncertain acknowledgement')
        self.sessions.artifacts.save = uncertain
        with self.assertRaises(OSError):
            self.sessions.finish(session_id)
        committed = self.git.head()
        self.sessions.artifacts.save = original
        self.sessions.finish(session_id)
        self.assertEqual(self.git.head(), committed)
        self.assertEqual(len(self.documents.open(self.project)['sessions']), 1)

    def test_session_schema_rejects_private_or_unknown_content(self):
        session_id = self.sessions.start(self.project, self.deck_id, self.revision,
                                         self.deck['title'])
        with self.assertRaises(ValueError):
            self.sessions.record(session_id, self.deck['slides'][0]['id'], '16:9',
                                 dict(self.content(), notes='secret'))
        value = dict(version=1, session_id=session_id, source_project_id=self.project,
                     source_artifact_id=self.deck_id, source_revision=self.revision,
                     title=self.deck['title'], started_at='2026-10-16T10:00:00Z',
                     ended_at='2026-10-16T10:01:00Z', outcome='completed', pages=[])
        self.assertEqual(decode_session(encode_session(value)), validate_session(value))


if __name__ == '__main__':
    unittest.main()
