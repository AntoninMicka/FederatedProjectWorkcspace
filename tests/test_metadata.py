# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
import hashlib
import unittest

from spikes.metadata import (MAX_METADATA, ValidationError, frontmatter, parse_json,
                             validate_metadata, validate_snapshot, validate_transition)
from tests.fixtures import ENTITY, OTHER, encoded, markdown, metadata, registry, source


class MetadataTests(unittest.TestCase):
    def test_frontmatter_and_source_byte_preservation(self):
        original = b'---\ntitle: untrusted original\n---\r\n\xff'
        files = source(original, 'original.md')
        files[f'artifacts/{OTHER}/document.md'] = markdown(metadata(entity_id=OTHER))
        result = validate_snapshot(files)
        self.assertEqual(set(result), {ENTITY, OTHER})
        self.assertEqual(files[f'artifacts/{ENTITY}/original.md'], original)

    def test_duplicate_keys_json_yaml_and_nested(self):
        for data in [b'{"title":"A","title":"B"}', b'{"x":{"a":1,"a":2}}']:
            with self.assertRaises(ValidationError):
                parse_json(data)
        for text in ['title: A\ntitle: B\n', 'x: {a: 1, a: 2}\n']:
            with self.assertRaises(ValidationError):
                frontmatter(('---\n' + text + '---\n').encode())

    def test_unsafe_yaml_and_resource_limits(self):
        inputs = ['a: &anchor 1\nb: *anchor\n', 'a: !!python/object:object {}\n',
                  'a: !!str hello\n', 'a: ' + '[' * 17 + '0' + ']' * 17 + '\n',
                  'a: ' + 'x' * MAX_METADATA + '\n', 'a: {<<: {b: 1}}\n']
        for text in inputs:
            with self.subTest(text=text[:50]), self.assertRaises(ValidationError):
                frontmatter(('---\n' + text + '---\n').encode())
        for data in [b'[' * 17 + b'0' + b']' * 17, b'{"x":NaN}', b'\xff']:
            with self.assertRaises(ValidationError):
                parse_json(data)

    def test_schema_rejects_invalid_values(self):
        for key, value in [('schema_version', True), ('schema_version', 3), ('id', 'bad'),
                           ('created_at', '2026-02-30T12:00:00Z'), ('created_at', '2026-09-09'),
                           ('privacy', 'secret'), ('title', ''), ('tags', 'tag'),
                           ('relations', [{'type': 'source', 'target_id': 'bad'}]),
                           ('unexpected', 'field')]:
            meta = metadata()
            meta[key] = value
            with self.subTest(key=key), self.assertRaises(ValidationError):
                validate_metadata(meta)
        self.assertEqual(validate_metadata(frontmatter(markdown()))['created_at'], '2026-09-09T12:00:00Z')

    def test_v2_import_provenance_is_strict_and_binds_source_bytes(self):
        raw = b'%PDF-1.7\noriginal\n'
        imported = dict(imported_at='2026-09-09T12:00:00Z', imported_by='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                        content_sha256=hashlib.sha256(raw).hexdigest(), source_author='External author',
                        source_created_at='2026-09-08T09:00:00Z', source_revision='r7',
                        importer={'name': 'workspace-native-import', 'version': '2'})
        meta = metadata(file='source.pdf')
        meta.update(schema_version=2, kind='source', provenance='external')
        meta['import'] = imported
        files = {f'artifacts/{ENTITY}/source.pdf': raw,
                 f'artifacts/{ENTITY}/metadata.json': encoded(meta),
                 f'artifacts/{OTHER}/document.md': markdown(metadata(entity_id=OTHER))}
        result = validate_snapshot(files)
        self.assertEqual(result[ENTITY]['import'], imported)
        self.assertEqual(result[OTHER]['schema_version'], 1)

        invalid = [dict(meta, schema_version=1), dict(meta, provenance='user'),
                   dict(meta, **{'import': dict(imported, unknown='x')}),
                   dict(meta, **{'import': dict(imported, content_sha256='A' * 64)}),
                   dict(meta, **{'import': dict(imported, imported_by=OTHER)}),
                   dict(meta, **{'import': dict(imported, imported_at='2026-09-08T09:00:00Z')})]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValidationError):
                validate_metadata(candidate, sidecar=True)
        changed = dict(files); changed[f'artifacts/{ENTITY}/source.pdf'] = raw + b'changed'
        with self.assertRaisesRegex(ValidationError, 'differs'):
            validate_snapshot(changed)
        external_without_import = metadata()
        external_without_import.update(schema_version=2, provenance='external')
        with self.assertRaises(ValidationError):
            validate_metadata(external_without_import)

    def test_source_transition_preserves_bytes_identity_and_v2_provenance(self):
        base = source()
        allowed = dict(base)
        meta = parse_json(allowed[f'artifacts/{ENTITY}/metadata.json'])
        meta.update(title='Updated title', description='Project annotation', tags=['reviewed'])
        allowed[f'artifacts/{ENTITY}/metadata.json'] = encoded(meta)
        self.assertIn(ENTITY, validate_transition(base, allowed))

        for path, value, message in [
                (f'artifacts/{ENTITY}/source.pdf', b'%PDF-changed', 'content'),
                (f'artifacts/{ENTITY}/metadata.json', encoded(dict(meta, author_id=OTHER)), 'metadata')]:
            changed = dict(allowed); changed[path] = value
            with self.subTest(message=message), self.assertRaisesRegex(ValidationError, 'Immutable source'):
                validate_transition(base, changed)

        relaxed = dict(allowed)
        relaxed_meta = dict(meta, privacy='public')
        relaxed[f'artifacts/{ENTITY}/metadata.json'] = encoded(relaxed_meta)
        with self.assertRaisesRegex(ValidationError, 'privacy relaxation'):
            validate_transition(base, relaxed)
        self.assertIn(ENTITY, validate_transition(base, relaxed, allow_privacy_relaxation=True))
        with self.assertRaisesRegex(ValidationError, 'removal'):
            validate_transition(base, {})

    def test_sidecar_paths_orphans_and_identity(self):
        for filename in ['../escape', '/tmp/escape', '.git', 'C:\\escape', 'metadata.json']:
            files = source()
            meta = metadata(file=filename)
            files[f'artifacts/{ENTITY}/metadata.json'] = encoded(meta)
            with self.subTest(filename=filename), self.assertRaises(ValidationError):
                validate_snapshot(files)
        files = source()
        del files[f'artifacts/{ENTITY}/source.pdf']
        with self.assertRaises(ValidationError):
            validate_snapshot(files)
        with self.assertRaises(ValidationError):
            validate_snapshot({f'artifacts/{OTHER}/document.md': markdown()})

    def test_relations_and_registry_states(self):
        meta = metadata(relations=[{'type': 'supports', 'target_id': OTHER}])
        files = {f'artifacts/{ENTITY}/document.md': markdown(meta),
                 f'registries/decisions/{OTHER}.json': registry(entity_id=OTHER)}
        self.assertEqual(len(validate_snapshot(files)), 2)
        del files[f'registries/decisions/{OTHER}.json']
        with self.assertRaises(ValidationError):
            validate_snapshot(files)
        bad = metadata()
        bad.update(kind='decisions', status='done', body='x')
        with self.assertRaises(ValidationError):
            validate_metadata(bad, registry='decisions')

    def test_duplicate_id_across_artifact_and_registry(self):
        with self.assertRaises(ValidationError):
            validate_snapshot({f'artifacts/{ENTITY}/document.md': markdown(),
                               f'registries/decisions/{ENTITY}.json': registry()})
