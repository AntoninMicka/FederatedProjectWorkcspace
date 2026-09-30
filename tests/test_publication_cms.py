# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from uuid import uuid4

from spikes.local_api import running_api
from spikes.publication_cms import PublicationCms
from spikes.desktop_ui import DesktopHandler
from spikes.metadata import ValidationError
from tests import test_local_api


ROOT = Path(__file__).resolve().parents[1]


class Crash(RuntimeError):
    pass


class PublicationCmsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='publication cms ')
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.state = base / 'state'; self.state.mkdir(mode=0o700)
        self.module = base / 'module'; self.module.mkdir()
        package = self.module / 'src' / 'publication_registry'; package.mkdir(parents=True)
        (self.module / 'data').mkdir(); (self.module / 'templates').mkdir()
        shutil.copy(ROOT / 'modules' / 'publication-experiment-registry.module.json',
                    self.module / 'module.json')
        (self.module / '.gitignore').write_text('dist/\n__pycache__/\n*.pyc\n', encoding='utf-8')
        (package / '__init__.py').write_text('', encoding='utf-8')
        (package / 'sitegen.py').write_text('''
import argparse,json
from html import escape
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--registry');p.add_argument('--sites');p.add_argument('--template');p.add_argument('--output');a=p.parse_args()
value=json.loads(Path(a.sites).read_text());sites=value.get('sites')
if value.get('schema_version')!=2 or not isinstance(sites,list) or not sites:raise SystemExit(2)
for site in sites:
 host=site['hostname'];target=Path(a.output)/host/'index.html';target.parent.mkdir(parents=True,exist_ok=True)
 target.write_text('<!doctype html><h1>'+escape(site['title'])+'</h1>',encoding='utf-8')
''', encoding='utf-8')
        self.config = {'schema_version': 2, 'sites': [
            {'hostname': 'proofofidea.cz', 'presentation': 'proof-of-idea',
             'sections': ['profile'], 'title': 'Proof', 'description': 'Ideas',
             'catalog': {'kind': 'sandbox', 'title': 'Sandbox'},
             'contacts': [], 'links': [], 'cv': [], 'timeline': []},
            {'hostname': 'antoninmicka.cz', 'presentation': 'standard',
             'sections': ['profile', 'cv'], 'title': 'Antonín',
             'description': 'Profile', 'catalog': {'kind': 'realized', 'title': 'Projects'},
             'contacts': [], 'links': [], 'cv': [], 'timeline': []},
            {'hostname': 'tonymicka.cz', 'presentation': 'standard',
             'sections': ['timeline'], 'title': 'Timeline',
             'description': 'Events', 'catalog': {'kind': 'realized', 'title': 'Projects'},
             'contacts': [], 'links': [], 'cv': [], 'timeline': []},
        ]}
        (self.module / 'data' / 'sites.json').write_text(json.dumps(self.config), encoding='utf-8')
        (self.module / 'data' / 'registry.json').write_text('{}', encoding='utf-8')
        (self.module / 'templates' / 'site.html').write_text('$main', encoding='utf-8')
        runtime = {}
        for path in [*sorted(package.glob('*.py')),
                     self.module / 'templates' / 'site.html']:
            runtime[str(path.relative_to(self.module))] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.reviewed_sources = base / 'reviewed-sources.json'
        self.reviewed_sources.write_text(json.dumps({'schema_version': 1,
            'module_id': 'cz.proofofidea.publication-experiment-registry',
            'runtime_files': runtime}), encoding='utf-8')
        self.cms = self.service()
        discovered = self.cms.status()
        self.assertFalse(discovered['compatible'])
        self.assertTrue(discovered['modules'][0]['present'])
        self.cms.configure({'module_id': 'cz.proofofidea.publication-experiment-registry',
                            'enabled': True})

    def service(self, **kwargs):
        return PublicationCms(self.state, reviewed_sources=self.reviewed_sources,
                              module_roots=(self.module.parent,), **kwargs)

    def test_discovery_enable_and_manifest_version_replace_git_pin(self):
        preview = self.cms.preview({'config': self.config, 'hostname': 'antoninmicka.cz'})
        self.assertIn('<h1>Antonín</h1>', preview['html'])
        self.assertEqual(preview['module_version'], '0.4.0')
        self.assertEqual(len(preview['preview_sha256']), 64)
        (self.module / 'unreviewed.txt').write_text('change')
        self.assertTrue(self.cms.status()['compatible'])
        (self.module / 'unreviewed.txt').unlink()
        extra_runtime = self.module / 'src' / 'publication_registry' / 'unreviewed.py'
        extra_runtime.write_text('# unreviewed runtime\n')
        self.assertFalse(self.cms.status()['compatible'])
        with self.assertRaises(ValidationError):
            self.cms.preview({'config': self.config, 'hostname': 'antoninmicka.cz'})
        extra_runtime.unlink()
        generator = self.module / 'src' / 'publication_registry' / 'sitegen.py'
        generator.write_text(generator.read_text() + '\n# changed after review\n')
        self.assertFalse(self.cms.status()['compatible'])

    def test_disable_keeps_discovery_but_prevents_execution(self):
        status = self.cms.configure({
            'module_id': 'cz.proofofidea.publication-experiment-registry', 'enabled': False})
        self.assertFalse(status['compatible'])
        self.assertTrue(status['modules'][0]['present'])
        self.assertFalse(status['modules'][0]['enabled'])
        with self.assertRaises(FileNotFoundError):
            self.cms.preview({'config': self.config, 'hostname': 'proofofidea.cz'})

    def test_changed_manifest_version_requires_new_review_and_enable(self):
        manifest_path = self.module / 'module.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['module_version'] = '0.5.0'
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        status = self.cms.status()
        self.assertFalse(status['compatible'])
        self.assertIn('version changed', status['message'])
        with self.assertRaises(ValidationError):
            self.cms.configure({
                'module_id': 'cz.proofofidea.publication-experiment-registry', 'enabled': True})

    def test_legacy_fixed_variants_are_migrated_without_losing_content(self):
        legacy = {'schema_version': 1, 'sites': [
            {'hostname': 'old.example', 'variant': 'profile', 'title': 'Old',
             'description': 'Kept', 'catalog': {'kind': 'realized', 'title': 'Projects'},
             'contacts': [], 'links': [], 'cv': [{'period': '2020', 'title': 'Role',
                                                  'description': 'Work'}]},
        ]}
        self.cms.config_path.write_text(json.dumps(legacy), encoding='utf-8')
        migrated = self.cms.status()['config']
        self.assertEqual(migrated['schema_version'], 2)
        self.assertEqual(migrated['sites'][0]['sections'], ['profile', 'cv'])
        self.assertEqual(migrated['sites'][0]['presentation'], 'standard')
        self.assertEqual(migrated['sites'][0]['cv'][0]['title'], 'Role')
        self.assertEqual(migrated['sites'][0]['timeline'], [])

    def test_confirmed_generation_is_idempotent_and_rejects_stale_preview(self):
        preview = self.cms.preview({'config': self.config, 'hostname': 'proofofidea.cz'})
        request = {'operation_id': str(uuid4()), 'preview_sha256': preview['preview_sha256'],
                   'approved': True, 'config': self.config}
        receipt = self.cms.generate(request)
        self.assertEqual(self.cms.generate(request), receipt)
        self.assertEqual(receipt['generated_hostnames'],
                         ['antoninmicka.cz', 'proofofidea.cz', 'tonymicka.cz'])
        self.assertTrue((self.module / 'dist' / 'sites' / 'tonymicka.cz' / 'index.html').is_file())
        reduced = json.loads(json.dumps(self.config)); reduced['sites'] = reduced['sites'][:2]
        reduced_preview = self.cms.preview({'config': reduced, 'hostname': 'antoninmicka.cz'})
        self.cms.generate({'operation_id': str(uuid4()),
                           'preview_sha256': reduced_preview['preview_sha256'],
                           'approved': True, 'config': reduced})
        self.assertFalse((self.module / 'dist' / 'sites' / 'tonymicka.cz').exists())
        changed = json.loads(json.dumps(self.config)); changed['sites'][0]['title'] = 'Changed'
        with self.assertRaises(ValidationError):
            self.cms.generate(dict(request, operation_id=str(uuid4()), config=changed))
        with self.assertRaises(ValidationError):
            self.cms.generate(dict(request, operation_id=str(uuid4()), approved=False))

    def test_prepared_operation_recovers_after_output_generation_crash(self):
        preview = self.cms.preview({'config': self.config, 'hostname': 'proofofidea.cz'})
        request = {'operation_id': str(uuid4()), 'preview_sha256': preview['preview_sha256'],
                   'approved': True, 'config': self.config}
        crashing = self.service(
            checkpoint=lambda stage: (_ for _ in ()).throw(Crash()) if stage == 'output-generated' else None)
        with self.assertRaises(Crash):
            crashing.generate(request)
        recovered = self.service().status()
        self.assertTrue(recovered['compatible'])
        self.assertEqual(recovered['config'], self.config)
        self.assertEqual(self.service().generate(request)['state'], 'completed')

    def test_http_routes_keep_preview_and_confirmation_separate(self):
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler) as server:
            server.publication_cms = self.cms
            response = driver.request(server, path='/v1/publication-cms/status', body=b'{}')
            self.assertIn(b' 200 ', response)
            body = json.dumps({'config': self.config, 'hostname': 'proofofidea.cz'}).encode()
            response = driver.request(server, path='/v1/publication-cms/preview', body=body)
            preview = json.loads(response.split(b'\r\n\r\n', 1)[1])
            self.assertIn('html', preview)
            request = {'operation_id': str(uuid4()), 'preview_sha256': preview['preview_sha256'],
                       'approved': True, 'config': self.config}
            response = driver.request(server, path='/v1/publication-cms/generate',
                                      body=json.dumps(request).encode())
            self.assertIn(b' 200 ', response)
            driver.rejected(server, path='/v1/publication-cms/generate', body=b'{}',
                            headers={'Authorization': None})


if __name__ == '__main__':
    unittest.main()
