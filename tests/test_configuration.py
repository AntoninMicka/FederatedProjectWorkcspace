from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from spikes.configuration import parse_node, parse_project, read_config
from spikes.metadata import MAX_METADATA, ValidationError
from tests.fixtures import AUTHOR, ENTITY, OTHER, encoded


def project():
    return dict(schema_version=1, id=ENTITY, title='Portable project',
                created_at='2026-09-09T12:00:00Z', author_id=AUTHOR)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='config tests ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.location = self.base / 'node.json'
        self.node = dict(schema_version=1, id=OTHER, name='Local node', projects=[
            dict(project_id=ENTITY, root=str(self.base / 'project'), state_dir=str(self.base / 'state'))])

    def test_valid_roundtrip_and_no_directory_creation(self):
        for config in (project(), dict(project(), description='Optional description')):
            self.assertEqual(parse_project(encoded(config)), config)
        for config in (self.node, dict(self.node, projects=[]),
                       dict(self.node, identity_credential_ref='credential:node-key')):
            self.assertEqual(parse_node(encoded(config), location=self.location), config)
        self.assertEqual(list(self.base.iterdir()), [])

    def test_missing_fields_and_wrong_types(self):
        for config, parse in [(project(), parse_project),
                              (self.node, lambda data: parse_node(data, location=self.location))]:
            for key in config:
                missing = deepcopy(config)
                del missing[key]
                with self.subTest(key=key), self.assertRaises(ValidationError):
                    parse(encoded(missing))
                invalid = deepcopy(config)
                invalid[key] = None
                with self.subTest(key=key), self.assertRaises(ValidationError):
                    parse(encoded(invalid))
            for value in ([], None, 'config', 1):
                with self.assertRaises(ValidationError):
                    parse(encoded(value))

    def test_versions_are_explicit_and_do_not_migrate(self):
        for version in (0, 2, -1, True, 1.0, '1'):
            for config, parse in [(project(), parse_project),
                                  (self.node, lambda data: parse_node(data, location=self.location))]:
                value = dict(config, schema_version=version)
                before = deepcopy(value)
                with self.subTest(version=version), self.assertRaises(ValidationError):
                    parse(encoded(value))
                self.assertEqual(value, before)

    def test_project_rejects_local_fields_and_invalid_metadata(self):
        for key, value in [('node_id', OTHER), ('root', '/tmp'), ('state_dir', '/tmp/state'),
                           ('credentials', {'key': 'secret'}), ('identity_credential_ref', 'credential:key'),
                           ('backend', 'example'), ('id', 'bad'), ('author_id', 'bad'),
                           ('title', '  '), ('description', []), ('created_at', '2026-02-30T12:00:00Z'),
                           ('created_at', '2026-09-09T12:00:00+00:00')]:
            with self.subTest(key=key), self.assertRaises(ValidationError):
                parse_project(encoded(dict(project(), **{key: value})))

    def test_node_credential_references_and_unknown_fields(self):
        for ref in ('secret', '/tmp/key', 'credential:', 'credential:a/b',
                    'credential:' + 'x' * 129, None, {'key': 'secret'}):
            with self.subTest(ref=ref), self.assertRaises(ValidationError):
                parse_node(encoded(dict(self.node, identity_credential_ref=ref)), location=self.location)
        for key in ('credentials', 'private_key', 'users', 'backends'):
            with self.assertRaises(ValidationError):
                parse_node(encoded(dict(self.node, **{key: 'not allowed'})), location=self.location)

    def test_duplicate_registrations_and_overlap(self):
        for field in ('root', 'state_dir'):
            node = deepcopy(self.node)
            other = dict(project_id=AUTHOR, root=str(self.base / 'other'), state_dir=str(self.base / 'other-state'))
            other[field] = node['projects'][0][field]
            node['projects'].append(other)
            with self.assertRaises(ValidationError):
                parse_node(encoded(node), location=self.location)
        node = deepcopy(self.node)
        node['projects'].append(dict(project_id=ENTITY, root=str(self.base / 'other'), state_dir=str(self.base / 'other-state')))
        with self.assertRaises(ValidationError):
            parse_node(encoded(node), location=self.location)
        for state in (self.base / 'project', self.base / 'project' / 'state', self.base):
            node = deepcopy(self.node)
            node['projects'][0]['state_dir'] = str(state)
            with self.assertRaises(ValidationError):
                parse_node(encoded(node), location=self.location)

    def test_path_validation_and_node_file_inside_project(self):
        for path in ('relative', '/', str(self.base / '..' / 'state'), '/tmp/.git/data', '/tmp/bad\npath'):
            node = deepcopy(self.node)
            node['projects'][0]['root'] = path
            with self.subTest(path=path), self.assertRaises(ValidationError):
                parse_node(encoded(node), location=self.location)
        with self.assertRaises(ValidationError):
            parse_node(encoded(self.node), location=self.base / 'project' / 'node.json')
        target = self.base / 'project'
        target.mkdir()
        alias = self.base / 'alias'
        alias.symlink_to(target, target_is_directory=True)
        node = deepcopy(self.node)
        node['projects'][0]['state_dir'] = str(alias / 'state')
        with self.assertRaises(ValidationError):
            parse_node(encoded(node), location=self.location)
        with self.assertRaises(ValidationError):
            parse_node(encoded(self.node), location=alias / 'node.json')

    def test_json_limits_and_duplicate_nested_keys(self):
        for data in (b'{"schema_version":1,"schema_version":1}', b'{"x":{"a":1,"a":2}}',
                     b'\xff', b'[' * 17 + b'0' + b']' * 17,
                     b'{"value":NaN}', b' ' * (MAX_METADATA + 1)):
            for parse in (parse_project, lambda raw: parse_node(raw, location=self.location)):
                with self.assertRaises(ValidationError):
                    parse(data)
        for value in ([], {'project_id': ENTITY}, dict(self.node['projects'][0], extra=True)):
            with self.assertRaises(ValidationError):
                parse_node(encoded(dict(self.node, projects=[value])), location=self.location)

    def test_file_reader_is_bounded_and_refuses_special_files(self):
        config = self.base / 'project.json'
        config.write_bytes(encoded(project()))
        self.assertEqual(read_config(config), config.read_bytes())
        alias = self.base / 'link.json'
        alias.symlink_to(config)
        with self.assertRaises(OSError):
            read_config(alias)
        fifo = self.base / 'pipe'
        os.mkfifo(fifo)
        with self.assertRaises(ValidationError):
            read_config(fifo)
        config.write_bytes(b' ' * (MAX_METADATA + 1))
        with self.assertRaises(ValidationError):
            read_config(config)

    def test_cli_and_wrapper_are_read_only_and_preserve_exit_codes(self):
        self.location.write_bytes(encoded(self.node))
        config = self.base / 'project metadata.json'
        config.write_bytes(encoded(project()))
        script = Path(__file__).resolve().parents[1] / 'run.sh'
        for kind, path in [('project', config), ('node', self.location)]:
            before = path.read_bytes()
            result = subprocess.run([str(script), 'config', kind, path.name], cwd=self.base,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_bytes(), before)
        for args, code in [(['project', str(self.base / 'missing')], 1), (['other', str(config)], 2)]:
            result = subprocess.run([sys.executable, '-m', 'spikes.check_config', *args],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, code, result.stderr)
        config.write_text('{"credentials": TOP_SECRET_BROKEN_JSON}')
        result = subprocess.run([str(script), 'config', 'project', str(config)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('TOP_SECRET', result.stdout + result.stderr)
        self.assertEqual(config.read_text(), '{"credentials": TOP_SECRET_BROKEN_JSON}')
        for args in (['config'], ['config', 'project'], ['config', 'other', str(config)]):
            result = subprocess.run([str(script), *args], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 2)
