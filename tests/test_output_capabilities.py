# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from spikes.metadata import ValidationError
from spikes.output_capabilities import (OutputCapabilityCatalog,
    canonical_output_capability, load_output_catalog, parse_output_capability,
    read_output_capability, reviewed_output_catalog)


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / 'modules' / 'output-capabilities' / 'web-static.output-capability.json'


class OutputCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.value = read_output_capability(DESCRIPTOR)

    def parse(self, value):
        return parse_output_capability(json.dumps(value).encode())

    def test_reviewed_descriptor_is_portable_canonical_and_non_executable(self):
        self.assertEqual(self.value['capability_id'], 'renderer.web-static')
        self.assertEqual(self.value['kind'], 'renderer')
        self.assertEqual(self.value['required_backend_capabilities'], [])
        raw = json.dumps(self.value).lower()
        for forbidden in ('credential', 'endpoint', 'base_url', 'executable'):
            self.assertNotIn(forbidden, raw)
        self.assertEqual(parse_output_capability(
            canonical_output_capability(self.value)), self.value)
        self.assertEqual(reviewed_output_catalog().resolve(
            'renderer.web-static', '1.0'), self.value)

    def test_unknown_missing_versions_duplicates_and_bindings_fail_closed(self):
        cases = []
        cases.append(dict(self.value, endpoint='http://127.0.0.1:1'))
        missing = deepcopy(self.value); del missing['permissions']; cases.append(missing)
        future = deepcopy(self.value); future['schema_version'] = 2; cases.append(future)
        duplicate = deepcopy(self.value); duplicate['inputs'].append(
            deepcopy(duplicate['inputs'][0])); cases.append(duplicate)
        foreign = deepcopy(self.value); foreign['output']['schema'] = (
            'module://other.module/schemas/output.json'); cases.append(foreign)
        secret = deepcopy(self.value); secret['module']['credential'] = 'secret'; cases.append(secret)
        external = deepcopy(self.value); external['side_effect'] = 'external'; cases.append(external)
        no_preview_confirmation = deepcopy(self.value)
        no_preview_confirmation['confirmations'] = []; cases.append(no_preview_confirmation)
        unversioned_role = deepcopy(self.value)
        unversioned_role['required_roles'] = ['creator']; cases.append(unversioned_role)
        incompatible = deepcopy(self.value); incompatible['output_kind'] = 'table'; cases.append(incompatible)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.parse(value)

    def test_catalog_is_sorted_copy_safe_and_never_falls_back(self):
        older = deepcopy(self.value); older['capability_version'] = '0.9'
        catalog = OutputCapabilityCatalog([self.value, older])
        self.assertEqual([item['capability_version'] for item in catalog.list()],
                         ['0.9', '1.0'])
        resolved = catalog.resolve('renderer.web-static', '1.0')
        resolved['description'] = 'changed'
        self.assertEqual(catalog.resolve('renderer.web-static', '1.0')['description'],
                         self.value['description'])
        with self.assertRaises(ValidationError):
            catalog.resolve('renderer.web-static', '2.0')
        with self.assertRaises(ValidationError):
            OutputCapabilityCatalog([self.value, deepcopy(self.value)])

    def test_static_loader_rejects_symlink_and_unexpected_catalog_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'web.output-capability.json'
            target.write_bytes(canonical_output_capability(self.value))
            catalog = load_output_catalog(root)
            self.assertEqual(catalog.resolve('renderer.web-static', '1.0'), self.value)
            (root / 'README.txt').write_text('not a descriptor')
            with self.assertRaises(ValidationError):
                load_output_catalog(root)
            (root / 'README.txt').unlink()
            target.unlink()
            target.symlink_to(DESCRIPTOR)
            with self.assertRaises(ValidationError):
                load_output_catalog(root)


if __name__ == '__main__':
    unittest.main()
