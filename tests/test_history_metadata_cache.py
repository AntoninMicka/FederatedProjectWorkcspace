# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.metadata import (_SnapshotMetadataCache, _validate_snapshot,
                             validate_metadata, validate_snapshot)
from spikes.storage import _GitBlobCache
from tests.fixtures import ENTITY, OTHER, markdown, metadata
from tests import test_git_transfer as fixtures


class HistoryMetadataCacheTests(unittest.TestCase):
    def test_unchanged_bytes_reuse_intrinsic_checks_but_layout_is_always_checked(self):
        cache = _SnapshotMetadataCache()
        raw = markdown(metadata(entity_id=ENTITY))
        files = {f'artifacts/{ENTITY}/document.md': raw}
        with patch('spikes.metadata.validate_metadata', wraps=validate_metadata) as validate:
            _validate_snapshot(files, metadata_cache=cache)
            _validate_snapshot(files, metadata_cache=cache)
            self.assertEqual(validate.call_count, 1)
            with self.assertRaisesRegex(ValueError, 'directory must match'):
                _validate_snapshot({f'artifacts/{OTHER}/document.md': raw}, metadata_cache=cache)
            # Public callers never reuse the private walk's cached result.
            validate_snapshot(files)
            self.assertEqual(validate.call_count, 2)

    def test_removing_a_relation_target_is_rejected_after_cache_hit(self):
        cache = _SnapshotMetadataCache()
        first = markdown(metadata(entity_id=ENTITY, relations=[{'type': 'uses', 'target_id': OTHER}]))
        second = markdown(metadata(entity_id=OTHER))
        files = {f'artifacts/{ENTITY}/document.md': first, f'artifacts/{OTHER}/document.md': second}
        _validate_snapshot(files, metadata_cache=cache)
        with self.assertRaisesRegex(ValueError, 'Dangling relation'):
            _validate_snapshot({f'artifacts/{ENTITY}/document.md': first}, metadata_cache=cache)

    def test_content_integrity_is_rechecked_when_metadata_bytes_are_cached(self):
        fixture = fixtures.GitTransferHistoryTests('test_transfer_history_rejects_immutable_source_rewrite')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        files = fixture.git.snapshot(fixture.git.head()); cache = _SnapshotMetadataCache()
        _validate_snapshot(files, metadata_cache=cache)
        path = f'artifacts/{fixture.artifact_id}/{fixture.filename}'
        files[path] += b'changed'
        with self.assertRaisesRegex(ValueError, 'content differs from import provenance'):
            _validate_snapshot(files, metadata_cache=cache)

    def test_cache_limits_and_parser_modes_do_not_weaken_validation(self):
        cache = _SnapshotMetadataCache(max_entries=2, max_bytes=1024)
        for _ in range(6):
            raw = markdown(metadata(entity_id=str(uuid4())))
            cache.metadata(raw, markdown=True)
            self.assertLessEqual(len(cache.entries), 2)
            self.assertLessEqual(cache.size, 1024)
        raw = json.dumps(metadata(entity_id=ENTITY) | {'file': 'document.md'}).encode()
        cache.metadata(raw, sidecar=True)
        with self.assertRaises(ValueError):
            cache.metadata(raw, registry='tasks')

    def test_blob_cache_is_bounded_and_mismatched_size_is_rejected(self):
        cache = _GitBlobCache()
        for n in range(2050): cache.put(str(n), b'x')
        self.assertEqual(len(cache.entries), 2048)
        with self.assertRaisesRegex(ValueError, 'size differs'):
            cache.get('2049', 2)
        data = b'x' * (1024 * 1024)
        for n in range(17): cache.put('large-' + str(n), data)
        self.assertEqual(cache.size, 16 * 1024 * 1024)
        self.assertEqual(len(cache.entries), 16)

    def test_record_cache_preserves_envelope_checks_and_opaque_source_boundary(self):
        from tests import test_reporting
        from spikes.reporting_schema import records, validate_record
        fixture = test_reporting.ReportingTests('test_manual_event_multiple_sources_and_read_projection')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        files = fixture.git.snapshot(fixture.git.head()); cache = _SnapshotMetadataCache()
        with patch('spikes.reporting_schema.validate_record', wraps=validate_record) as validate:
            _validate_snapshot(files, metadata_cache=cache)
            first = validate.call_count
            self.assertGreater(first, 0)
            _validate_snapshot(files, metadata_cache=cache)
            self.assertEqual(validate.call_count, first)
        opaque = str(uuid4())
        files[f'artifacts/{opaque}/record.json'] = files[fixture.task['path']]
        captured = metadata(entity_id=opaque, file='record.json')
        captured.update(kind='source', provenance='external')
        files[f'artifacts/{opaque}/metadata.json'] = json.dumps(captured).encode()
        entities = _validate_snapshot(files, metadata_cache=cache)
        self.assertNotIn(opaque, records(files, entities, _record_cache=cache))
        sidecar = f'artifacts/{fixture.task["artifact_id"]}/metadata.json'
        value = json.loads(files[sidecar]); value['privacy'] = 'public'
        files[sidecar] = json.dumps(value).encode()
        with self.assertRaisesRegex(ValueError, 'envelope differs'):
            _validate_snapshot(files, metadata_cache=cache)
