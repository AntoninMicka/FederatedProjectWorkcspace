# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
import io
import os
import tempfile
from pathlib import Path
import subprocess
import tarfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from scripts import deploy_omnia


class DeployTests(unittest.TestCase):
    def test_bundle_contains_only_sources(self):
        data, names = deploy_omnia.bundle(deploy_omnia.ROOT)
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            self.assertEqual(archive.getnames(), names)
            self.assertTrue(all(m.isfile() for m in archive))
        self.assertIn('spikes/workspace.py', names)
        self.assertFalse(any('private' in n or '.venv' in n or n.startswith('/') for n in names))

    def test_dry_run_and_input_rejection_do_not_connect(self):
        with patch('sys.argv', ['deploy', 'root@example.invalid', '--dry-run']), patch('subprocess.run') as run, patch('builtins.print'):
            self.assertEqual(deploy_omnia.main(), 0)
            run.assert_not_called()
        for arguments in (['root@example.invalid', '--container', 'x;touch evil'], ['-bad@host']):
            result = subprocess.run(['./run.sh', 'deploy-omnia', *arguments], capture_output=True)
            self.assertEqual(result.returncode, 2)

    def test_remote_shell_syntax_and_failure_propagation(self):
        script = deploy_omnia.remote_script('workspace-m0', 'a'*32)
        subprocess.run(['sh', '-n'], input=script.encode(), check=True)
        subprocess.run(['sh', '-n'], input=deploy_omnia.install_script('a'*32).encode(), check=True)
        with patch('sys.argv', ['deploy', 'root@example.invalid']), patch('subprocess.run') as run:
            run.return_value.returncode = 255
            self.assertEqual(deploy_omnia.main(), 255)
            self.assertIn('StrictHostKeyChecking=yes', run.call_args.args[0])
            self.assertIsInstance(run.call_args.kwargs['input'], bytes)

    def test_remote_retry_recover_flow(self):
        failed = SimpleNamespace(returncode=255)
        success = SimpleNamespace(returncode=0)
        with patch('sys.argv', ['deploy', 'root@example.invalid', '--retries', '2']), patch('subprocess.run') as run:
            run.side_effect = [failed, success, success]
            self.assertEqual(deploy_omnia.main(), 0)
            self.assertEqual(run.call_count, 3)

    def test_web_reset_mode_uses_reset_script(self):
        with patch('sys.argv', ['deploy', 'root@example.invalid', '--web-lan', '192.168.100.0/24', '--reset']), patch('subprocess.run') as run:
            run.return_value = SimpleNamespace(returncode=0)
            self.assertEqual(deploy_omnia.main(), 0)
            run.assert_called_once()
            self.assertIn('Web deployment state reset', run.call_args.args[0][-1])

    def test_web_deploy_copies_ca_certificate(self):
        payload = SimpleNamespace(returncode=0, stdout=b'-----BEGIN CERTIFICATE-----\n', stderr=b'')
        write_ok = SimpleNamespace(returncode=0, stderr=b'', stdout=b'')
        with patch('sys.argv', ['deploy', 'root@example.invalid', '--web-lan', '192.168.100.0/24']), \
                patch('scripts.deploy_omnia.run_ssh', side_effect=[payload, write_ok]) as run_ssh, \
                patch('scripts.deploy_omnia.run_ssh_output', return_value=payload):
            self.assertEqual(deploy_omnia.main(), 0)
            self.assertEqual(run_ssh.call_count, 2)
            self.assertEqual(run_ssh.call_args_list[1][0][1], 'cat > /etc/federated-workspace-ca.pem && chmod 0644 /etc/federated-workspace-ca.pem')
            self.assertEqual(run_ssh.call_args_list[1][0][2], b'-----BEGIN CERTIFICATE-----\n')

    def test_regen_tls_requires_web_lan(self):
        with patch('sys.argv', ['deploy', 'root@example.invalid', '--regen-tls']):
            with self.assertRaises(SystemExit):
                deploy_omnia.main()

    def test_failed_install_preserves_previous_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / 'install'
            (base / 'releases' / 'old').mkdir(parents=True)
            (base / 'current').symlink_to('releases/old')
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            apt = bin_dir / 'apt-get'
            apt.write_text('#!/bin/sh\nexit 7\n')
            apt.chmod(0o755)
            script = deploy_omnia.install_script('new').replace('. /etc/os-release', 'ID=debian').replace('/opt/federated-workspace', str(base))
            payload, _ = deploy_omnia.bundle(deploy_omnia.ROOT)
            env = dict(os.environ, PATH=str(bin_dir) + ':' + os.environ['PATH'])
            result = subprocess.run(['sh', '-c', script], input=payload, env=env, capture_output=True)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(os.readlink(base / 'current'), 'releases/old')
            self.assertTrue((base / 'releases/new/spikes/workspace.py').exists())
