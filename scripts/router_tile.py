# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Install/remove only this workspace's router integration; persistent rollback journal."""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

if __package__:
    from .router_entry import arguments
else:
    from router_entry import arguments

JOURNAL = '/etc/federated-workspace-tile-rollback.json'
CA = '/etc/federated-workspace-ca.pem'
PATHS = ('/usr/lib/federated-workspace/router_entry.py',
         '/etc/init.d/federated-workspace-entry',
         '/etc/lighttpd/conf.d/federated-workspace.conf',
         '/etc/turris-webapps/90-federated-workspace.json',
         '/www/webapps-icons/federated-workspace.svg')
AUTOSTART = 'lxc-auto.federated_workspace'


def files(container, lan, port):
    arguments(container, lan, port)
    # Values above are validated before interpolation into shell service options.
    return {
        PATHS[0]: (Path(__file__).with_name('router_entry.py').read_bytes(), 0o644),
        PATHS[1]: (f'''#!/bin/sh /etc/rc.common
# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
START=95
USE_PROCD=1
start_service() {{
 procd_open_instance
 procd_set_param command /usr/bin/python3 {PATHS[0]} --container {container} --lan {lan} --port {port} --ca {CA}
 procd_set_param respawn
 procd_close_instance
}}
'''.encode(), 0o755),
        PATHS[2]: ('''# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
server.modules += ( "mod_proxy" )
$HTTP["url"] =~ "^/federated-workspace/?$" {
 proxy.server = ( "" => ( ( "host" => "127.0.0.1", "port" => 8846 ) ) )
}
'''.encode(), 0o644),
        # JSON does not support comments. Ownership is recorded by the generator.
        PATHS[3]: ((json.dumps({'id': 'federated-workspace', 'title': 'Projektový workspace',
                               'icon': '/icons/federated-workspace.svg',
                               'url': '/federated-workspace/', 'description': {
                                   'cs': 'Projekty, podklady a rozhodnutí',
                                   'cz': 'Projekty, podklady a rozhodnutí',
                                   'en': 'Projects, sources and decisions'}}, ensure_ascii=False) + '\n').encode(), 0o644),
        PATHS[4]: ('''<!-- SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0 -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><rect width="96" height="96" rx="16" fill="#142638"/><path d="M20 30h24l8 10h24v34H20z" fill="#79c9ac"/><path d="M30 50h36M30 60h26" stroke="#142638" stroke-width="4"/></svg>
'''.encode(), 0o644),
    }


def atomic(path, data, mode):
    path = Path(path)
    if path.absolute() != path.resolve():
        raise ValueError('Symlink target rejected')
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    for parent in missing:
        parent.chmod(0o755)  # WebApps/lighttpd must traverse newly created parents.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), mode)
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def snapshot(paths):
    result = {}
    for path in paths:
        p = Path(path)
        if p.absolute() != p.resolve():
            raise ValueError('Symlink target rejected')
        if p.exists():
            info = p.stat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Expected regular integration file')
            result[path] = [base64.b64encode(p.read_bytes()).decode(), stat.S_IMODE(info.st_mode)]
        else:
            result[path] = None
    return result


def restore(record):
    for path, old in record['files'].items():
        if path not in PATHS:
            raise ValueError('Invalid rollback path')
        if old is None:
            Path(path).unlink(missing_ok=True)
        else:
            atomic(path, base64.b64decode(old[0]), old[1])


def command(*args, check=True, capture=False):
    return subprocess.run(args, stdin=subprocess.DEVNULL, check=check, timeout=30,
                          stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.PIPE, text=capture)


def autostart_state(container):
    """Return whether our exact UCI section exists; reject partial/foreign ownership."""
    section = command('uci', '-q', 'get', AUTOSTART, check=False, capture=True)
    if section.returncode != 0:
        return False
    name = command('uci', '-q', 'get', AUTOSTART + '.name', check=False, capture=True)
    timeout = command('uci', '-q', 'get', AUTOSTART + '.timeout', check=False, capture=True)
    if section.stdout.strip() != 'container' or name.returncode or name.stdout.strip() != container \
            or timeout.returncode or timeout.stdout.strip() != '60':
        raise ValueError('UCI section lxc-auto.federated_workspace exists but is not owned by this installation')
    return True


def write_autostart(container, enabled):
    """Write our deterministic section; caller established ownership or is rolling it back."""
    if enabled:
        command('uci', 'set', AUTOSTART + '=container')
        command('uci', 'set', AUTOSTART + '.name=' + container)
        command('uci', 'set', AUTOSTART + '.timeout=60')
    else:
        command('uci', 'delete', AUTOSTART)
    command('uci', 'commit', 'lxc-auto')


def configure_autostart(container, enabled):
    current = autostart_state(container)
    if current != enabled:
        write_autostart(container, enabled)


def activate(enabled, active=None):
    if active is None:
        active = enabled
    command('lighttpd', '-tt', '-f', '/etc/lighttpd/lighttpd.conf')
    if Path(PATHS[1]).exists():
        command(PATHS[1], 'enable' if enabled else 'disable')
        command(PATHS[1], 'restart' if active else 'stop')
    command('/etc/init.d/lighttpd', 'reload')


def rollback(journal):
    record = json.loads(journal.read_text())
    command(PATHS[1], 'stop', check=False) if Path(PATHS[1]).exists() else None
    command(PATHS[1], 'disable', check=False) if Path(PATHS[1]).exists() else None
    restore(record)
    activate(record['enabled'], record['active'])
    if 'container' in record:
        write_autostart(record['container'], record.get('autostart', False))
    journal.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'install', 'remove', 'recover'])
    parser.add_argument('--container', default='workspace-m0')
    parser.add_argument('--lan', default='192.168.1.0/24')
    parser.add_argument('--port', type=int, default=8443)
    args = parser.parse_args()
    payload = files(args.container, args.lan, args.port)
    if args.action == 'plan':
        print(json.dumps({path: data.decode() for path, (data, mode) in payload.items()}, ensure_ascii=False, indent=2))
        return
    if os.geteuid() != 0:
        parser.error('Run on the router as root')
    journal = Path(JOURNAL)
    fd = os.open(journal.with_suffix('.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'recover':
            rollback(journal)
            return
        if journal.exists():
            parser.error('Interrupted installation: run recover first')
        if args.action == 'install' and not Path(CA).is_file():
            parser.error('Install the service CA certificate first')
        enabled = Path(PATHS[1]).exists() and command(PATHS[1], 'enabled', check=False).returncode == 0
        active = Path(PATHS[1]).exists() and command(PATHS[1], 'status', check=False).returncode == 0
        autostart = autostart_state(args.container)
        atomic(journal, json.dumps({'files': snapshot(PATHS), 'enabled': enabled, 'active': active,
                                    'autostart': autostart, 'container': args.container}).encode(), 0o600)
        try:
            if args.action == 'install':
                for path, (data, mode) in payload.items():
                    atomic(path, data, mode)
                configure_autostart(args.container, True)
                activate(True)
            else:
                if Path(PATHS[1]).exists():
                    command(PATHS[1], 'stop'); command(PATHS[1], 'disable')
                for path in PATHS:
                    Path(path).unlink(missing_ok=True)
                activate(False)
                configure_autostart(args.container, False)
        except BaseException:
            rollback(journal)
            raise
        journal.unlink()


if __name__ == '__main__':
    main()
