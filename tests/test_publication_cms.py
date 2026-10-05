# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import json
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from uuid import uuid4

from spikes.local_api import running_api
from spikes.publication_cms import PublicationCms
from spikes.publication_cloudflare import (CloudflareTransport, CloudflareUnavailable,
                                           CloudflareUnknown)
from spikes.desktop_ui import DesktopHandler
from spikes.metadata import ValidationError
from tests import test_local_api


ROOT = Path(__file__).resolve().parents[1]


class Crash(RuntimeError):
    pass


class FakeCloudflare:
    def __init__(self, *, fail=False):
        self.provider = {'exists': True, 'version_id': None, 'release_sha256': None,
                         'deployment_id': None}
        self.fail = fail
        self.calls = []

    def status(self, binding, token):
        self.calls.append(('status', dict(binding), token))
        return dict(self.provider)

    def deploy(self, binding, token, output, hostnames, release_sha256, compatibility_date):
        self.calls.append(('deploy', dict(binding), token, Path(output), list(hostnames),
                           release_sha256, compatibility_date))
        self.provider = {'exists': True, 'version_id': 'version-1',
                         'release_sha256': release_sha256,
                         'deployment_id': 'deployment-1'}
        if self.fail:
            raise TimeoutError('lost response')
        return {'version_id': 'version-1', 'deployment_id': 'deployment-1'}


class RecordingCloudflareTransport(CloudflareTransport):
    def __init__(self):
        self.requests = []
        self.uploads = 0

    def _request(self, method, path, token, **kwargs):
        self.requests.append((method, path, token, kwargs))
        if path.endswith('/assets-upload-session'):
            manifest = kwargs['value']['manifest']
            return {'jwt': 'upload-jwt',
                    'buckets': [[item['hash']] for item in manifest.values()]}
        if '/workers/assets/upload?' in path:
            self.uploads += 1
            return ({'jwt': 'completion-jwt'} if self.uploads == 2 else {})
        if path.endswith('/versions'):
            return {'id': 'version-api'}
        if path.endswith('/deployments'):
            return {'id': 'deployment-api'}
        raise AssertionError(path)


class UnavailableCloudflare:
    def status(self, binding, token):
        raise CloudflareUnavailable('provider unavailable')


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

    def _generated_service(self, transport):
        cms = self.service(deployment_transport=transport)
        preview = cms.preview({'config': self.config, 'hostname': 'proofofidea.cz'})
        cms.generate({'operation_id': str(uuid4()),
                      'preview_sha256': preview['preview_sha256'],
                      'approved': True, 'config': self.config})
        return cms, preview['preview_sha256']

    def test_cloudflare_deployment_has_node_local_binding_preview_and_confirmation(self):
        transport = FakeCloudflare()
        cms, release = self._generated_service(transport)
        token = 'cloudflare-test-token-' + 'x' * 24
        configured = cms.deployment_configure({
            'portal_id': 'main', 'provider': 'cloudflare',
            'account_id': 'a' * 32, 'worker_name': 'publication-site-set',
            'api_token': token})
        self.assertNotIn(token, json.dumps(configured))
        status = cms.deployment_status()
        self.assertEqual(status['state'], 'partial')
        self.assertEqual([item['hostname'] for item in status['domains']],
                         ['antoninmicka.cz', 'proofofidea.cz', 'tonymicka.cz'])
        self.assertTrue(all(item['custom_domain'] == 'unmanaged'
                            for item in status['domains']))
        preview = cms.deployment_preview({})
        self.assertEqual(preview['plan']['portal_id'], 'main')
        self.assertEqual(preview['plan']['release_sha256'], release)
        self.assertEqual(preview['plan']['custom_domains'], 'unchanged')
        request = {'operation_id': str(uuid4()),
                   'preview_sha256': preview['preview_sha256'], 'approved': True}
        receipt = cms.deployment_confirm(request)
        self.assertEqual(receipt['state'], 'completed')
        self.assertEqual(cms.deployment_confirm(request), receipt)
        self.assertEqual(cms.deployment_status()['state'], 'current')
        self.assertNotIn(token, json.dumps(preview))
        self.assertEqual([call[0] for call in transport.calls].count('deploy'), 1)

    def test_lost_cloudflare_response_stays_unknown_until_provider_reconciliation(self):
        transport = FakeCloudflare(fail=True)
        cms, _ = self._generated_service(transport)
        cms.deployment_configure({
            'portal_id': 'main', 'provider': 'cloudflare',
            'account_id': 'b' * 32, 'worker_name': 'publication-site-set',
            'api_token': 'cloudflare-test-token-' + 'y' * 24})
        preview = cms.deployment_preview({})
        request = {'operation_id': str(uuid4()),
                   'preview_sha256': preview['preview_sha256'], 'approved': True}
        with self.assertRaises(CloudflareUnknown):
            cms.deployment_confirm(request)
        with self.assertRaises(CloudflareUnknown):
            cms.deployment_confirm(request)
        self.assertEqual([call[0] for call in transport.calls].count('deploy'), 1)
        completed_provider = dict(transport.provider)
        transport.provider = {'exists': True, 'version_id': None,
                              'release_sha256': None, 'deployment_id': None}
        self.assertEqual(cms.deployment_status()['state'], 'unknown')
        transport.provider = completed_provider
        status = cms.deployment_status()
        self.assertEqual(status['state'], 'current')
        receipt = cms.deployment_confirm(request)
        self.assertTrue(receipt['reconciled'])
        self.assertEqual(receipt['state'], 'completed')

    def test_concrete_cloudflare_transport_uploads_assets_version_and_deployment(self):
        output = Path(self.temp.name) / 'output'
        site = output / 'example.cz'; site.mkdir(parents=True)
        (site / 'index.html').write_text('<h1>Example</h1>', encoding='utf-8')
        (site / 'app.css').write_text('body{}', encoding='utf-8')
        transport = RecordingCloudflareTransport()
        receipt = transport.deploy(
            {'account_id': 'c' * 32, 'worker_name': 'publication-site-set'},
            'provider-token', output, ['example.cz'], 'd' * 64, '2026-09-30')
        self.assertEqual(receipt, {'version_id': 'version-api',
                                   'deployment_id': 'deployment-api'})
        self.assertEqual([item[0] for item in transport.requests],
                         ['POST', 'POST', 'POST', 'POST', 'POST'])
        self.assertEqual(transport.requests[1][2], 'upload-jwt')
        self.assertEqual(transport.requests[1][3]['accepted'], (200, 201, 202))
        self.assertEqual(transport.requests[2][2], 'upload-jwt')
        self.assertEqual(transport.requests[2][3]['accepted'], (200, 201, 202))
        version = transport.requests[3][3]['value']
        self.assertEqual(version['assets']['jwt'], 'completion-jwt')
        self.assertEqual(version['compatibility_date'], '2026-09-30')
        self.assertEqual(version['annotations']['workers/tag'], 'd' * 64)
        script = base64.b64decode(version['modules'][0]['content_base64']).decode()
        self.assertIn('"example.cz"', script)
        deployment = transport.requests[4][3]['value']
        self.assertEqual(deployment['versions'],
                         [{'percentage': 100, 'version_id': 'version-api'}])

    def test_http_routes_keep_preview_and_confirmation_separate(self):
        driver = test_local_api.LocalAPITests()
        cms, _ = self._generated_service(FakeCloudflare())
        cms.deployment_configure({
            'portal_id': 'main', 'provider': 'cloudflare',
            'account_id': 'e' * 32, 'worker_name': 'publication-site-set',
            'api_token': 'cloudflare-test-token-' + 'z' * 24})
        with running_api('http', handler=DesktopHandler) as server:
            server.publication_cms = cms
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
            response = driver.request(server, path='/v1/publication-cms/deployment/status', body=b'{}')
            self.assertIn(b' 200 ', response)
            response = driver.request(server, path='/v1/publication-cms/deployment/preview', body=b'{}')
            deployment_preview = json.loads(response.split(b'\r\n\r\n', 1)[1])
            response = driver.request(server, path='/v1/publication-cms/deployment/confirm',
                body=json.dumps({'operation_id': str(uuid4()), 'approved': True,
                    'preview_sha256': deployment_preview['preview_sha256']}).encode())
            self.assertIn(b' 200 ', response)
            cms.deployment.transport = UnavailableCloudflare()
            response = driver.request(server, path='/v1/publication-cms/deployment/preview', body=b'{}')
            self.assertIn(b' 502 ', response)
            self.assertNotIn(b'provider unavailable', response)
            driver.rejected(server, path='/v1/publication-cms/generate', body=b'{}',
                            headers={'Authorization': None})


if __name__ == '__main__':
    unittest.main()
