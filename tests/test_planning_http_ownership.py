# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Planning review, project documents and source references retain native writers."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.desktop_management import DesktopManagementHandler
from spikes.local_api import running_api
from spikes.presentation_documents import PresentationDocuments, new_deck
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.request_ownership import ProjectBusy, bounded_project_requests
from spikes.roadmap_refinement import RoadmapRefinement
from tests import test_project_http_ownership as ownership


class PlanningHTTPOwnershipTests(unittest.TestCase):
    post = ownership.ProjectHTTPOwnershipTests.post

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.node = self.root / 'node.json'
        self.ids = [ProjectCreation(self.node).create('Planning '+str(i), self.root / str(i), str(uuid4()))['id']
                    for i in range(2)]
        self.projects = Projects(self.node)
        self.documents = PresentationDocuments(self.node)
        self.heads = [self.projects.repository(pid).head() for pid in self.ids]

    def test_slow_document_read_allows_same_project_view_presenter_and_application(self):
        entered, release = threading.Event(), threading.Event()
        results = []; original = self.documents.open
        def blocked(pid):
            if pid == self.ids[0]:
                entered.set()
                if not release.wait(5): raise AssertionError('Document owner not released')
            return original(pid)
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.presentation_documents = self.documents
            with patch.object(self.documents, 'open', side_effect=blocked):
                worker = threading.Thread(target=lambda: results.append(self.post(server,
                    '/v1/presentations/open', {'project_id': self.ids[0], 'expected_head': self.heads[0]})))
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    code, payload, _ = self.post(server, '/v1/projects/open', {'project_id': self.ids[0]})
                    self.assertEqual(code, 200, payload)
                    server.application_lane.acquire(); server.presentation_lane.acquire()
                    try:
                        self.assertEqual(self.post(server, '/v1/outputs/definitions',
                            {'project_id': self.ids[1], 'expected_head': self.heads[1]})[0], 200)
                    finally:
                        server.presentation_lane.release(); server.application_lane.release()
                    self.assertEqual(self.post(server, '/v1/counter', {'action': 'increment'})[0], 200)
                finally:
                    release.set(); worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results[0][0], 200, results)

    def test_nested_document_save_uses_project_owner_and_keeps_selected_deck(self):
        pid = self.ids[0]
        document = dict(project_id=pid, artifact_id=str(uuid4()), base_head=self.heads[0], new=True, deck=new_deck())
        request = dict(operation_id=str(uuid4()), document=document)
        selected = {'revision': 'selected-immutable-snapshot'}
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.presentation_documents = self.documents
            server.presentation_selected_deck = selected
            with server.project_lanes.acquire(pid, .1):
                code, payload, _ = self.post(server, '/v1/presentations/save', request)
                self.assertEqual(code, 503, payload)
                self.assertEqual(payload['outcome'], 'not-started')
                self.assertEqual(self.projects.repository(pid).head(), self.heads[0])
            server.application_lane.acquire(); server.presentation_lane.acquire()
            try:
                code, result, _ = self.post(server, '/v1/presentations/save', request)
                self.assertEqual(code, 200, result)
            finally:
                server.presentation_lane.release(); server.application_lane.release()
            self.assertIs(server.presentation_selected_deck, selected)
        self.assertEqual(self.projects.repository(pid).run('rev-list', '--count', self.heads[0]+'..HEAD').stdout.strip(), '1')

    def test_review_decisions_share_read_owner_but_not_project_document_owner(self):
        entered, release = threading.Event(), threading.Event()
        results = []; original = RoadmapRefinement.review_list
        def blocked(service):
            entered.set()
            if not release.wait(5): raise AssertionError('Review owner not released')
            return original(service)
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.presentation_documents = self.documents
            with patch.object(RoadmapRefinement, 'review_list', blocked):
                worker = threading.Thread(target=lambda: results.append(self.post(server,
                    '/v1/roadmap-refinement/list', {'project_id': self.ids[0]})))
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    body = {'project_id': self.ids[1], 'proposal_id': str(uuid4()), 'decision': 'reject'}
                    self.assertEqual(self.post(server, '/v1/roadmap-refinement/decide', body, token='invalid')[0], 401)
                    code, payload, _ = self.post(server, '/v1/roadmap-refinement/decide', body)
                    self.assertEqual(code, 503, payload)
                    self.assertEqual(payload['outcome'], 'not-started')
                    self.assertEqual(self.post(server, '/v1/presentations/open',
                        {'project_id': self.ids[1], 'expected_head': self.heads[1]})[0], 200)
                    self.assertEqual(self.post(server, '/v1/document-patterns', {'action': 'catalog'})[0], 200)
                finally:
                    release.set(); worker.join(5)
                self.assertFalse(worker.is_alive()); self.assertEqual(results[0][0], 200, results)

    def test_refinement_sqlite_and_native_scan_lock_are_bounded_in_http(self):
        service = RoadmapRefinement(self.node, self.ids[0])
        with service._connect(): pass
        path = service.state / 'refinement.sqlite'; before = path.read_bytes()
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            with closing(sqlite3.connect(path)) as owner:
                owner.execute('BEGIN EXCLUSIVE')
                code, payload, _ = self.post(server, '/v1/roadmap-refinement/list', {'project_id': self.ids[0]})
                self.assertEqual(code, 503, payload); self.assertEqual(payload['outcome'], 'unknown')
                self.assertEqual(self.post(server, '/v1/projects/open', {'project_id': self.ids[1]})[0], 200)
                owner.rollback()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.post(server, '/v1/roadmap-refinement/list', {'project_id': self.ids[0]})[0], 200)
        with service._deep_lock():
            with bounded_project_requests(), self.assertRaises(ProjectBusy):
                with service._deep_lock(): self.fail('Acquired occupied owner')
            with self.assertRaisesRegex(ValueError, 'already running'):
                with service._deep_lock(): self.fail('Changed native refusal')
        with service._connect() as db:
            self.assertEqual(db.execute('PRAGMA busy_timeout').fetchone()[0], 5000)
        with bounded_project_requests(), service._connect() as db:
            self.assertEqual(db.execute('PRAGMA busy_timeout').fetchone()[0], 0)

    def test_document_open_preserves_external_pending_operation_as_conflict(self):
        pid = self.ids[0]; workspace = self.projects.workspace(pid)
        operation_id = str(uuid4())
        marker = json.dumps({'kind': 'external-replication', 'operation_id': operation_id})
        with workspace.journal.connect() as db:
            db.execute('INSERT INTO operations(id,record) VALUES (?,?)', (operation_id, marker))
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.presentation_documents = self.documents
            code, payload, _ = self.post(server, '/v1/presentations/open',
                                         {'project_id': pid, 'expected_head': self.heads[0]})
            self.assertEqual(code, 409, payload)
        with workspace.journal.connect() as db:
            self.assertEqual(db.execute('SELECT record,done FROM operations WHERE id=?',
                                         (operation_id,)).fetchone(), (marker, 0))
        self.assertEqual(workspace.git.head(), self.heads[0])

    def test_reference_generation_does_not_own_live_project_or_review(self):
        entered, release = threading.Event(), threading.Event()
        results = []
        class SourceGraph:
            def project(inner):
                entered.set()
                if not release.wait(5): raise AssertionError('Reference owner not released')
                return {'revision': 'source-only-fixture', 'nodes': []}
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.roadmap_graph = SourceGraph()
            worker = threading.Thread(target=lambda: results.append(self.post(server, '/v1/roadmap/graph', {'format': 'json'})))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                code, payload, _ = self.post(server, '/v1/document-patterns', {'action': 'catalog'})
                self.assertEqual(code, 503, payload); self.assertEqual(payload['outcome'], 'not-started')
                self.assertEqual(self.post(server, '/v1/projects/open', {'project_id': self.ids[0]})[0], 200)
                self.assertEqual(self.post(server, '/v1/roadmap-refinement/list', {'project_id': self.ids[0]})[0], 200)
            finally:
                release.set(); worker.join(5)
            self.assertFalse(worker.is_alive()); self.assertEqual(results[0][0], 200, results)
