# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Loopback-only router landing endpoint; resolve the selected LXC on each click."""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import re
import ssl
import subprocess


def destination(container, network, port, ca):
    def info(flag):
        result = subprocess.run(['lxc-info', '-P', '/srv/lxc', '-n', container, flag],
                                stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=3, check=True)
        if len(result.stdout) > 4096:
            raise ValueError('Invalid LXC response')
        return result.stdout.strip()
    if info('-sH') != 'RUNNING':
        raise ValueError('Container stopped')
    def current_addresses():
        return {ip for ip in (ipaddress.ip_address(line) for line in info('-iH').splitlines())
                if ip.version == 4 and ip in network}
    addresses = current_addresses()
    if len(addresses) != 1:
        raise ValueError('Container needs exactly one address in configured LAN')
    ip = str(addresses.pop())
    connection = http.client.HTTPSConnection(ip, port, timeout=3,
                                             context=ssl.create_default_context(cafile=ca))
    try:
        connection.request('GET', '/')
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Service unavailable')
    finally:
        connection.close()
    # Detect stop/address changes during healthcheck; never retain cached results.
    if info('-sH') != 'RUNNING' or current_addresses() != {ipaddress.ip_address(ip)}:
        raise ValueError('Container changed')
    return f'https://{ip}:{port}/'


class EntryHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(2)
        super().setup()

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path not in ('/federated-workspace', '/federated-workspace/'):
            return self.answer(404, 'Nenalezeno.')
        try:
            url = destination(*self.server.target)
        except (ValueError, OSError, subprocess.SubprocessError, http.client.HTTPException):
            return self.answer(503, 'Workspace není dostupný. Ověřte kontejner, jeho adresu a HTTPS službu.')
        self.answer(302, 'Otevírám workspace.', url)

    def answer(self, code, text, location=None):
        data = text.encode()
        self.send_response_only(code)
        if location:
            self.send_header('Location', location)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.answer(405, 'Metoda není podporována.')


def arguments(container, lan, port):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,62}', container):
        raise ValueError('Invalid container name')
    network = ipaddress.ip_network(lan)
    if network.version != 4 or not network.is_private or network.prefixlen < 8:
        raise ValueError('Expected private IPv4 LAN')
    if not 1024 <= port <= 65535:
        raise ValueError('Invalid service port')
    return network


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', required=True)
    parser.add_argument('--lan', required=True)
    parser.add_argument('--port', type=int, default=8443)
    parser.add_argument('--ca', required=True)
    args = parser.parse_args()
    network = arguments(args.container, args.lan, args.port)
    with HTTPServer(('127.0.0.1', 8846), EntryHandler) as server:
        server.target = (args.container, network, args.port, args.ca)
        server.serve_forever()


if __name__ == '__main__':
    main()
