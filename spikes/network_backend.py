# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Opt-in in-process desktop HTTPS connectivity backend; no remote accounts."""
import ipaddress
import json
import os
from pathlib import Path
import stat
import tempfile
import threading

from spikes.administration import Administration
from spikes.configuration import parse_node, read_config, overlap
from spikes.federation_accounts import openssl
from spikes.federation_probe import PATH, reply_probe
from spikes.journal import sync_dir
from spikes.project_creation import ProjectCreation
from spikes.web_server import WebHandler, WebServer


class ProbeHandler(WebHandler):
    def do_POST(self):
        if self.path != PATH:
            return self.send_error(404)
        return reply_probe(self)

    def do_GET(self):
        return self.send_error(405)


def private_root(node):
    node = Path(node).absolute()
    root = node.parent / ('.' + node.name + '.network')
    if root != root.resolve():
        raise ValueError('Network configuration must not use symlinks')
    if node.exists():
        config = parse_node(read_config(node), location=node)
        for project in config['projects']:
            if any(overlap(root, Path(project[key])) for key in ('root', 'state_dir')):
                raise ValueError('Network configuration must remain outside projects and their state')
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Unsafe private network configuration directory')
    return root


def publish(root, path, data):
    fd, temporary = tempfile.mkstemp(prefix='.publish-', dir=root)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path); sync_dir(root)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def trust_ca(node, node_id, certificate):
    from spikes.administration import identifier
    identifier(node_id)
    root = private_root(node)
    publish(root, root / (node_id + '-ca.pem'), certificate)


class NetworkBackend:
    def __init__(self, node):
        self.node, self.server, self.thread, self.config = node, None, None, None

    @property
    def endpoint(self):
        return f"https://{self.config['bind']}:{self.config['port']}" if self.server else ''

    def load(self):
        root = Path(self.node).absolute().parent / ('.' + Path(self.node).name + '.network')
        path = root / 'settings.json'
        if not os.path.lexists(path):
            return None
        private_root(self.node)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('Unsafe network settings')
            value = json.load(handle)
        self.validate(value)
        return value

    def validate(self, config):
        if not isinstance(config, dict) or set(config) != {'bind', 'port', 'lan', 'cert', 'key', 'ca', 'enabled'}:
            raise ValueError('Invalid network configuration')
        address = ipaddress.IPv4Address(config['bind'])
        network = ipaddress.ip_network(config['lan'])
        if (not address.is_private or address.is_unspecified or address.is_loopback
                or network.version != 4 or not network.is_private or network.prefixlen < 8 or address not in network):
            raise ValueError('Vyberte konkrétní privátní IPv4 desktopu v povolené LAN.')
        if type(config['port']) is not int or not 1024 <= config['port'] <= 65535 or type(config['enabled']) is not bool:
            raise ValueError('Port musí být 1024–65535.')
        for key in ('cert', 'key', 'ca'):
            if not isinstance(config[key], str):
                raise ValueError('Invalid TLS path')

    def generate(self, bind, port, lan):
        root = private_root(self.node)
        folder = Path(tempfile.mkdtemp(prefix='tls-', dir=root))
        (folder / 'ca.cnf').write_text('[req]\ndistinguished_name=dn\nx509_extensions=ca\nprompt=no\n[dn]\nCN=Desktop Workspace Local CA\n[ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n')
        openssl('req', '-x509', '-nodes', '-newkey', 'rsa:3072', '-sha256', '-days', '3650',
                '-config', str(folder / 'ca.cnf'), '-keyout', str(folder / 'ca.key'), '-out', str(folder / 'ca.pem'))
        (folder / 'server.ext').write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=IP:' + str(ipaddress.IPv4Address(bind)) + ',IP:127.0.0.1\n')
        openssl('req', '-new', '-nodes', '-newkey', 'rsa:3072', '-keyout', str(folder / 'tls.key'),
                '-out', str(folder / 'tls.csr'), '-subj', '/CN=Desktop Workspace')
        openssl('x509', '-req', '-in', str(folder / 'tls.csr'), '-CA', str(folder / 'ca.pem'),
                '-CAkey', str(folder / 'ca.key'), '-CAcreateserial', '-out', str(folder / 'tls.crt'),
                '-days', '825', '-sha256', '-extfile', str(folder / 'server.ext'))
        for path in folder.iterdir():
            path.chmod(0o600)
            with path.open('rb') as handle:
                os.fsync(handle.fileno())
        sync_dir(folder); sync_dir(root)
        return dict(bind=bind, port=port, lan=lan, cert=str(folder / 'tls.crt'), key=str(folder / 'tls.key'),
                    ca=str(folder / 'ca.pem'), enabled=True)

    def start(self, config):
        import ssl
        self.validate(config)
        if not config['enabled']:
            self.config = config; return
        service = Administration(self.node, deployment='desktop')
        if not os.path.lexists(service.node) and service.repo.exists():
            raise ValueError('Restore original node.json before enabling the backend')
        ProjectCreation(self.node).initialize_node()
        with service.locked():
            pass
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(config['cert'], config['key'])
        server = WebServer((config['bind'], config['port']), ProbeHandler)
        server.tls, server.allowed_network = tls, ipaddress.ip_network(config['lan'])
        server.administration = service
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
        thread.start()
        self.server, self.thread, self.config = server, thread, config

    def stop(self):
        if self.server:
            self.server.shutdown(); self.thread.join(); self.server.server_close()
            self.server, self.thread = None, None

    def configure(self, config):
        previous = self.config
        self.stop()
        try:
            self.start(config)
            root = private_root(self.node)
            publish(root, root / 'settings.json', json.dumps(config).encode() + b'\n')
        except Exception:
            self.stop()
            if previous:
                self.start(previous)
            raise
