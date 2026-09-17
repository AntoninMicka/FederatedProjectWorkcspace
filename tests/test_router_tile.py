# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import ipaddress
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock
from scripts import router_entry, router_tile, install_web, deploy_omnia


class RouterTests(unittest.TestCase):
    def resolve(self, values):
        result = [Mock(stdout=v) for v in values]
        connection = Mock()
        connection.getresponse.return_value.status = 200
        with patch.object(router_entry.subprocess,'run',side_effect=result) as run, \
             patch.object(router_entry.ssl,'create_default_context'), \
             patch.object(router_entry.http.client,'HTTPSConnection',return_value=connection):
            url = router_entry.destination('workspace-m0',ipaddress.ip_network('192.168.100.0/24'),8443,'ca')
            for call in run.call_args_list:
                self.assertNotIn('shell',call.kwargs)
            return url

    def test_address_is_resolved_again_on_each_click(self):
        for ip in ('192.168.100.10','192.168.100.11'):
            self.assertEqual(self.resolve(['RUNNING',ip+'\nfd00::1','RUNNING',ip]),f'https://{ip}:8443/')

    def test_stopped_ambiguous_outside_lan_and_changed_address_fail_closed(self):
        for values in (['STOPPED'], ['RUNNING',''],['RUNNING','8.8.8.8'],
                       ['RUNNING','192.168.100.10\n192.168.100.11'],
                       ['RUNNING','192.168.100.10','STOPPED'],
                       ['RUNNING','192.168.100.10','RUNNING','192.168.100.11']):
            with self.subTest(values=values), self.assertRaises(ValueError): self.resolve(values)

    def test_install_inputs_shell_and_legal_bundle(self):
        for args in [('bad;id','192.168.100.0/24',8443),('ok','0.0.0.0/0',8443),('ok','192.168.100.0/24',0)]:
            with self.assertRaises(ValueError): router_tile.files(*args)
        files=router_tile.files('workspace-m0','192.168.100.0/24',8443)
        tile=json.loads(files[router_tile.PATHS[3]][0])
        self.assertEqual(tile['url'],'/federated-workspace/')
        self.assertNotIn('192.168',str(tile))
        subprocess.run(['sh','-n'],input=files[router_tile.PATHS[1]][0],check=True)
        subprocess.run(['sh','-n'],input=install_web.install_script('a'*32,'192.168.100.0/24').encode(),check=True)
        _,names=deploy_omnia.bundle(deploy_omnia.ROOT)
        self.assertIn('spikes/web_server.py',names)
        self.assertIn('docs/legal/licenses/LICENSE.PyYAML-6.0.3',names)

    def test_atomic_snapshot_restore_preserves_foreign_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); own=root/'own'; other=root/'foreign'
            own.write_bytes(b'old'); own.chmod(0o640); other.write_bytes(b'untouched')
            paths=(str(own),str(root/'new'))
            with patch.object(router_tile,'PATHS',paths):
                record={'files':router_tile.snapshot(paths)}
                router_tile.atomic(own,b'new',0o644)
                router_tile.atomic(root/'new',b'added',0o644)
                router_tile.restore(record)
            self.assertEqual(own.read_bytes(),b'old')
            self.assertEqual(own.stat().st_mode & 0o777,0o640)
            self.assertFalse((root/'new').exists())
            self.assertEqual(other.read_bytes(),b'untouched')
            link=root/'link'; link.symlink_to(other)
            with self.assertRaises(ValueError): router_tile.atomic(link,b'bad',0o644)

    def test_failed_activation_rolls_back_and_repeated_install_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            paths=tuple(str(root/str(i)) for i in range(len(router_tile.PATHS)))
            journal=root/'journal'
            ca=root/'ca'; ca.write_text('test CA')
            foreign=root/'other-tile.json'; foreign.write_text('unchanged')
            def run(action, activate):
                with patch.object(router_tile,'PATHS',paths), patch.object(router_tile,'JOURNAL',str(journal)), \
                     patch.object(router_tile,'CA',str(ca)), patch.object(router_tile.os,'geteuid',return_value=0), \
                     patch.object(router_tile,'activate',side_effect=activate), \
                     patch.object(router_tile,'autostart_state',return_value=False), \
                     patch.object(router_tile,'configure_autostart'), \
                     patch.object(router_tile,'command',return_value=Mock(returncode=0)), \
                     patch('sys.argv',['tile',action,'--lan','192.168.100.0/24']):
                    router_tile.main()
            run('install',lambda *a:None)
            before=[Path(p).read_bytes() for p in paths]
            run('install',lambda *a:None)
            self.assertEqual(before,[Path(p).read_bytes() for p in paths])
            with self.assertRaises(RuntimeError):
                run('install',[RuntimeError('bad lighttpd'),None])
            self.assertEqual(before,[Path(p).read_bytes() for p in paths])
            self.assertFalse(journal.exists())
            run('remove',lambda *a:None)
            self.assertTrue(all(not Path(p).exists() for p in paths))
            self.assertEqual(foreign.read_text(),'unchanged')

    def test_turris_autostart_uses_owned_uci_section_only(self):
        missing = Mock(returncode=1, stdout='')
        with patch.object(router_tile, 'command', return_value=missing):
            self.assertFalse(router_tile.autostart_state('workspace-m0'))

        values = [Mock(returncode=0, stdout='container\n'),
                  Mock(returncode=0, stdout='workspace-m0\n'),
                  Mock(returncode=0, stdout='60\n')]
        with patch.object(router_tile, 'command', side_effect=values):
            self.assertTrue(router_tile.autostart_state('workspace-m0'))

        foreign = [Mock(returncode=0, stdout='container\n'),
                   Mock(returncode=0, stdout='other\n'),
                   Mock(returncode=0, stdout='60\n')]
        with patch.object(router_tile, 'command', side_effect=foreign), self.assertRaises(ValueError):
            router_tile.autostart_state('workspace-m0')

        calls = []
        def run(*args, **kwargs):
            calls.append(args)
            return Mock(returncode=0, stdout='')
        with patch.object(router_tile, 'autostart_state', side_effect=[False, True]), \
             patch.object(router_tile, 'command', side_effect=run):
            router_tile.configure_autostart('workspace-m0', True)
            router_tile.configure_autostart('workspace-m0', False)
        self.assertIn(('uci', 'set', 'lxc-auto.federated_workspace.name=workspace-m0'), calls)
        self.assertIn(('uci', 'commit', 'lxc-auto'), calls)
        self.assertIn(('uci', 'delete', 'lxc-auto.federated_workspace'), calls)

        journal = Mock()
        journal.read_text.return_value = json.dumps({
            'files': {}, 'enabled': False, 'active': False,
            'container': 'workspace-m0', 'autostart': False})
        with patch.object(router_tile, 'restore'), patch.object(router_tile, 'activate'), \
             patch.object(router_tile, 'write_autostart') as restore_autostart, \
             patch.object(router_tile, 'command', return_value=Mock(returncode=0)):
            router_tile.rollback(journal)
        restore_autostart.assert_called_once_with('workspace-m0', False)

    def test_lxc_failed_healthcheck_restores_current_unit_and_keeps_recovery(self):
        import io
        import os
        import tarfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); base=root/'app'; config=root/'config'; config.mkdir()
            (config/'tls.crt').write_text('test'); (config/'tls.key').write_text('test')
            (config/'ca.crt').write_text('test')
            (base/'releases'/'old').mkdir(parents=True)
            (base/'current').symlink_to('releases/old')
            unit=root/'unit'; unit.write_text('old unit')
            binary=root/'bin'; binary.mkdir()
            commands={
                'apt-get':'exit 0', 'id':'exit 0', 'chown':'exit 0', 'runuser':'exit 0',
                'systemctl':'exit 0',
                'install':'for last; do :; done; mkdir -p "$last"',
                'python3':'''if [ "$1" = -m ]; then
mkdir -p "$3/bin"
printf '#!/bin/sh\\nexit 0\\n' > "$3/bin/python"
chmod +x "$3/bin/python"
else exit 7; fi'''}
            for name,body in commands.items():
                p=binary/name; p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
            script=install_web.install_script('b'*32,'192.168.100.0/24')
            script=script.replace('. /etc/os-release','ID=debian').replace('/opt/federated-workspace',str(base))
            script=script.replace('/etc/federated-workspace',str(config)).replace('/etc/systemd/system/federated-workspace.service',str(unit))
            script=script.replace('/var/lib/federated-workspace',str(root/'state'))
            stream=io.BytesIO()
            with tarfile.open(fileobj=stream,mode='w:gz'): pass
            result=subprocess.run(['sh','-c',script],input=stream.getvalue(),capture_output=True,
                                  env=dict(os.environ,PATH=str(binary)+':'+os.environ['PATH']))
            self.assertEqual(result.returncode,7,result.stderr)
            self.assertEqual(os.readlink(base/'current'),'releases/old')
            self.assertEqual(unit.read_text(),'old unit')
            self.assertTrue((base/'web-rollback'/'previous').exists())
