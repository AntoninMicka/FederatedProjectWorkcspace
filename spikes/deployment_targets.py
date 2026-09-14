# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Private local deployment preferences, never credentials or project data."""
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from spikes.journal import sync_dir


class DeploymentTargets:
    def __init__(self, node):
        node = Path(node).absolute()
        self.path = node.parent / ('.' + node.name + '.deployment-targets.json')

    def load(self):
        if not os.path.lexists(self.path):
            return []
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('Unsafe deployment preferences')
            value = json.load(handle)
        if not isinstance(value, dict) or value.get('schema_version') != 1 or not isinstance(value.get('targets'), list):
            raise ValueError('Invalid deployment preferences; preserve the file for recovery')
        required = {'host', 'container', 'lan', 'desktop_endpoint', 'endpoint', 'node_id', 'fingerprint'}
        for target in value['targets']:
            if not isinstance(target, dict) or set(target) != required or not all(isinstance(v, str) for v in target.values()):
                raise ValueError('Invalid deployment target')
        return value['targets']

    def remember(self, target):
        if self.path.parent != self.path.parent.resolve():
            raise ValueError('Deployment preferences directory must not use symlinks')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock, 'a+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            targets = self.load()
            targets = [t for t in targets if (t['host'], t['container']) != (target['host'], target['container'])]
            targets.append(target)
            fd, temporary = tempfile.mkstemp(prefix='.deployment-targets-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w') as output:
                    json.dump({'schema_version': 1, 'targets': targets}, output, ensure_ascii=False, indent=2)
                    output.write('\n'); output.flush(); os.fsync(output.fileno())
                os.replace(temporary, self.path)
                sync_dir(self.path.parent)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)


def address_candidates():
    """Interface addresses only; do not claim that an HTTPS backend listens there."""
    import ipaddress
    try:
        result = subprocess.run(['ip', '-j', '-4', 'address', 'show', 'up'], capture_output=True, check=True, timeout=3)
        interfaces = json.loads(result.stdout)
        values = set()
        for interface in interfaces:
            for address in interface.get('addr_info', []):
                ip = ipaddress.ip_address(address['local'])
                if ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local:
                    values.add(str(ip))
        return [f'https://{ip}:8443' for ip in sorted(values, key=ipaddress.ip_address)]
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return []
