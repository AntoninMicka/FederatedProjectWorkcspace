"""Opt-in Linux network namespace validation of the packaged desktop."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from scripts.package_deb import build, NAME

# Runs after entering the namespace and dropping setup capabilities.
CHECK_AND_RUN = r'''
import errno, json, os, socket, subprocess, sys
assert os.geteuid() != 0
assert os.readlink('/proc/self/ns/net') != sys.argv[2], 'Network isolation missing'
with open('/proc/self/status') as stream:
    status = dict(line.split(':', 1) for line in stream if ':' in line)
assert all(int(status[key].strip(), 16) == 0 for key in ('CapEff', 'CapPrm', 'CapAmb'))
links = json.loads(subprocess.check_output(['ip', '-j', 'address'], text=True))
assert [link['ifname'] for link in links] == ['lo'], links
assert 'UP' in links[0]['flags'], links
for family in ('-4', '-6'):
    assert json.loads(subprocess.check_output(['ip', family, '-j', 'route'], text=True)) == []
try:
    connection = socket.create_connection(('192.0.2.1', 443), timeout=1)
except OSError as error:
    assert error.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH), repr(error)
else:
    connection.close()
    raise AssertionError('Unexpected external route')
print('offline proof: isolated namespace, only loopback, no route or capabilities', flush=True)
for _ in range(2):
    result = subprocess.run([sys.argv[1], '--smoke'], cwd='/tmp', capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'authenticated fetch, value=1' in result.stdout, result.stdout
    assert 'backend stopped' in result.stdout, result.stdout
print('offline proof: packaged desktop click, close and restart passed', flush=True)
'''


@unittest.skipUnless(os.environ.get('M0_OFFLINE_TEST') == '1',
                     'Set M0_OFFLINE_TEST=1 with local X11 and permitted user/network namespaces')
class OfflineDesktopTests(unittest.TestCase):
    def test_packaged_desktop_without_external_network(self):
        display = os.environ.get('DISPLAY', '')
        match = re.fullmatch(r'(?:unix)?:([0-9]+)(?:\.[0-9]+)?', display)
        self.assertIsNotNone(match, 'Requires local X11; do not disconnect a forwarded display')
        self.assertTrue(Path('/tmp/.X11-unix/X' + match[1]).is_socket())
        with tempfile.TemporaryDirectory(prefix='offline desktop ') as tmp:
            root = Path(tmp)
            package = build(root / 'app.deb')
            subprocess.run(['dpkg-deb', '-x', str(package), str(root / 'installed')], check=True)
            launcher = root / 'installed/usr/bin' / NAME
            env = os.environ.copy()
            env['DISPLAY'] = 'unix:' + display.split(':', 1)[1]
            # keep-caps is only for setting lo UP in this newly created namespace.
            # Drop all capabilities before validation and GUI execution.
            command = ['unshare', '--user', '--map-current-user', '--keep-caps', '--net',
                       'sh', '-c', 'ip link set lo up && exec setpriv --bounding-set=-all '
                       '--inh-caps=-all --ambient-caps=-all "$@"', 'offline-test',
                       sys.executable, '-I', '-c', CHECK_AND_RUN, str(launcher),
                       os.readlink('/proc/self/ns/net')]
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('only loopback, no route or capabilities', result.stdout)
            self.assertIn('click, close and restart passed', result.stdout)
