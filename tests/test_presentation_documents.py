# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Basic deck semantics, durable document reuse and private/public projection."""
import base64
import copy
import json
import struct
import zlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from uuid import uuid4

from spikes.presentation_documents import (PresentationDocuments, new_deck, new_slide,
    main_order, relink, set_neighbor, remove_slide, validate_deck, encode_deck, decode_deck,
    project_deck, validate_wallpaper)
from spikes.project_creation import ProjectCreation
from spikes.storage import Git
from spikes.desktop_ui import presentation_public_payload, presentation_status

def png_chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))


PNG = 'data:image/png;base64,' + base64.b64encode(
    b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
    + png_chunk(b'IDAT', zlib.compress(b'\x00\x20\x40\x60')) + png_chunk(b'IEND', b'')).decode()



def sample():
    deck = new_deck()
    deck['slides'] += [new_slide(), new_slide(), new_slide('backup')]
    a, b, c, backup = deck['slides']
    a.update(title='Opening', bullets=['First point', '<b>Plain text</b>'], wallpaper=PNG, notes='Private note')
    backup.update(title='Backup', bullets=['Extra'], notes='Private backup note')
    a['backups'] = [backup['id']]; c['backups'] = [backup['id']]
    relink(deck, [a['id'], b['id'], c['id']])
    return deck


class PresentationModelTests(unittest.TestCase):
    def test_round_trip_reciprocal_neighbors_and_shared_backup(self):
        deck = sample(); a, b, c, backup = deck['slides']
        self.assertEqual(decode_deck(encode_deck(deck)), deck)
        set_neighbor(deck, a['id'], c['id'])
        self.assertEqual(main_order(deck), [a['id'], c['id'], b['id']])
        set_neighbor(deck, b['id'], None, previous=True)
        self.assertEqual(main_order(deck), [b['id'], a['id'], c['id']])
        set_neighbor(deck, b['id'], None)
        self.assertEqual(main_order(deck), [a['id'], c['id'], b['id']])
        projected = project_deck(deck, 'revision')
        self.assertEqual(projected['backups'][0]['after_slides'], [0, 1])
        remove_slide(deck, backup['id'])
        self.assertFalse(a['backups']); self.assertFalse(c['backups'])
        remove_slide(deck, c['id'])
        self.assertEqual(main_order(deck), [a['id'], b['id']])
        remove_slide(deck, b['id'])
        with self.assertRaises(ValueError):
            remove_slide(deck, a['id'])

    def test_optional_playback_settings_and_public_row_prefix(self):
        deck = sample(); first = deck['slides'][0]
        first.update(repeat=True, reveal='step')
        self.assertEqual(decode_deck(encode_deck(deck)), deck)
        projected = project_deck(deck, 'rev')
        self.assertTrue(projected['slides'][0]['repeat'])
        server = SimpleNamespace(presentation_selected_deck=projected)
        request = dict(action='show', slide_id=first['id'], deck_revision='rev', rows=1)
        shown = presentation_public_payload(server, request)
        self.assertEqual(shown['content']['bullets'], ['First point'])
        self.assertEqual(shown['content']['body'], 'First point')
        self.assertNotIn('repeat', shown['content'])
        for rows in (-1, 3, True, '1', None):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                presentation_public_payload(server, dict(request, rows=rows))
            self.assertEqual(presentation_public_payload(server), shown)
        self.assertEqual(len(projected['slides'][0]['bullets']), 2)
        self.assertEqual(len(presentation_public_payload(server, dict(request, rows=2))['content']['bullets']), 2)
        for slide in deck['slides']:
            slide.pop('repeat'); slide.pop('reveal')
        self.assertEqual(decode_deck(encode_deck(deck)), deck)
        legacy = project_deck(deck, 'old')['slides'][0]
        self.assertFalse(legacy['repeat']); self.assertEqual(legacy['reveal'], 'all')
        for fields in ({'repeat': 1}, {'repeat': 'false'}, {'reveal': 'unknown'}):
            bad = copy.deepcopy(deck); bad['slides'][0].update(fields)
            with self.assertRaises(ValueError):
                validate_deck(bad)

    def test_invalid_graphs_wallpapers_and_bounds(self):
        for mutation in (
            lambda d: d['slides'][0].update(next=d['slides'][0]['id']),
            lambda d: d['slides'][0].update(next='missing'),
            lambda d: d['slides'][1].update(next=d['slides'][0]['id']),
            lambda d: d['slides'][0].update(backups=[d['slides'][1]['id']]),
            lambda d: d['slides'][3].update(backups=[d['slides'][3]['id']]),
            lambda d: d['slides'][0].update(background='url(https://example.com)'),
            lambda d: d['slides'][0].update(wallpaper='https://example.com/image.png'),
            lambda d: d['slides'][0].update(wallpaper='data:image/svg+xml;base64,AAAA'),
            lambda d: d['slides'][0].update(bullets=['x'] * 13),
            lambda d: d['slides'][1].update(id=d['slides'][0]['id']),
        ):
            with self.subTest(mutation=mutation):
                deck = sample(); mutation(deck)
                with self.assertRaises(ValueError):
                    validate_deck(deck)
        validate_wallpaper(PNG)
        with self.assertRaises(ValueError):
            validate_wallpaper('data:image/png;base64,@@@@')

    def test_public_snapshot_requires_revision_and_never_contains_private_fields(self):
        deck = sample(); projection = project_deck(deck, 'one')
        server = SimpleNamespace(presentation_selected_deck=projection)
        self.assertFalse(presentation_public_payload(server)['visible'])
        first = projection['slides'][0]
        shown = presentation_public_payload(server, dict(action='show', slide=0, slide_id=first['id'], deck_revision='one'))
        self.assertEqual(shown['content']['wallpaper'], PNG)
        self.assertEqual(shown['content']['bullets'], first['bullets'])
        self.assertNotIn('notes', shown['content']); self.assertNotIn('backups', shown['content'])
        deck['slides'][0]['title'] = 'Edited privately'
        self.assertEqual(presentation_public_payload(server), shown)
        server.presentation_selected_deck = project_deck(deck, 'two')
        with self.assertRaises(ValueError):
            presentation_public_payload(server, dict(action='show', slide_id=first['id'], deck_revision='one'))
        with self.assertRaises(ValueError):
            presentation_public_payload(server, dict(action='show', slide_id='missing', deck_revision='two'))
        self.assertEqual(presentation_public_payload(server), shown)
        status = presentation_status(server); status['slides'][0]['title'] = 'Mutation'
        self.assertEqual(server.presentation_selected_deck['slides'][0]['title'], 'Edited privately')
        backup = projection['backups'][0]
        shown_backup = presentation_public_payload(server, dict(action='show', slide_id=backup['id'], deck_revision='two'))
        self.assertEqual(shown_backup['content']['title'], 'Backup')
        self.assertNotIn('Private', json.dumps(shown_backup))


class PresentationStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.node = self.base / 'node.json'; self.root = self.base / 'project'
        self.project = ProjectCreation(self.node).create('Deck project', str(self.root), str(uuid4()))['id']
        self.git = Git(self.root); self.service = PresentationDocuments(self.node)

    def request(self):
        return dict(project_id=self.project, artifact_id=str(uuid4()), base_head=self.git.head(), new=True, deck=sample())

    def test_save_restart_update_receipt_and_stale_rejection(self):
        request = self.request(); operation = str(uuid4())
        receipt = self.service.save(request, operation)
        self.assertEqual(self.service.save(request, operation), receipt)
        view = PresentationDocuments(self.node).open(self.project)
        self.assertEqual(view['documents'][0]['deck'], request['deck'])
        update = dict(request, base_head=self.git.head(), new=False, deck=copy.deepcopy(request['deck']))
        update['deck']['slides'][0]['bullets'].append('Updated')
        self.service.save(update, str(uuid4()))
        self.assertEqual(self.service.open(self.project)['documents'][0]['deck'], update['deck'])
        with self.assertRaises(ValueError):
            self.service.save(dict(update, deck=request['deck']), str(uuid4()))
        self.assertEqual(self.git.run('status', '--porcelain').stdout, '')
        self.assertEqual(self.git.snapshot(receipt['commit_id'])[f"artifacts/{request['artifact_id']}/content.md"].decode(), encode_deck(request['deck']))

    def test_invalid_deck_never_starts_a_transaction(self):
        request = self.request(); head = self.git.head()
        request['deck']['slides'][0]['next'] = 'missing'
        with self.assertRaises(ValueError):
            self.service.save(request, str(uuid4()))
        self.assertEqual(self.git.head(), head)
        self.assertEqual(self.service.open(self.project)['documents'], [])

    def test_process_crashes_recover_exact_deck_once_at_storage_boundaries(self):
        for stage in ('prepared', 'files-applied', 'ref-updated', 'indexed'):
            with self.subTest(stage=stage):
                request = self.request(); operation = str(uuid4())
                payload = self.base / 'request.json'; payload.write_text(json.dumps(request))
                script = '''
import json, os, sys
from spikes.presentation_documents import PresentationDocuments
request = json.load(open(sys.argv[2]))
def checkpoint(stage):
    if stage == sys.argv[4]: os._exit(73)
PresentationDocuments(sys.argv[1]).save(request, sys.argv[3], checkpoint=checkpoint)
'''
                result = subprocess.run([sys.executable, '-c', script, str(self.node), str(payload), operation, stage],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 73, result.stderr)
                service = PresentationDocuments(self.node)
                view = service.open(self.project)
                doc = next(d for d in view['documents'] if d['id'] == request['artifact_id'])
                self.assertEqual(doc['deck'], request['deck'])
                head = self.git.head()
                self.assertEqual(service.save(request, operation)['commit_id'], head)
                self.assertEqual(self.git.head(), head)
                self.assertEqual(self.git.run('rev-list', '--count', request['base_head'] + '..HEAD').stdout.strip(), '1')
                self.assertEqual(self.git.run('status', '--porcelain').stdout, '')
