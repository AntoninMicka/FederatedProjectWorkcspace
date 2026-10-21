# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Nonce-bound signed connectivity probe, never login or data synchronization."""
import base64
import hashlib
import http.client
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

from spikes.administration import Administration, identifier
from spikes.federation_accounts import MappingSignatures, canonical, openssl

PATH = '/v1/federation/probe'


def reply_probe(handler):
    if handler.single('Host') != handler.server.authority:
        return handler.send_error(403)
    if handler.headers.get_all('Origin', []) not in ([], [handler.server.origin]):
        return handler.send_error(403)
    if handler.single('Content-Type') != 'application/json':
        return handler.send_error(415)
    length = handler.single('Content-Length')
    if (not length or not length.isascii() or not length.isdecimal() or len(length) > 4
            or not 0 < int(length) <= 1024 or handler.headers.get_all('Transfer-Encoding')
            or handler.headers.get_all('Expect')):
        return handler.send_error(400)
    try:
        from spikes.metadata import parse_json
        raw = handler.rfile.read(int(length))
        if len(raw) != int(length):
            return handler.send_error(400)
        request = parse_json(raw)
        if not isinstance(request, dict) or set(request) != {'challenge'}:
            return handler.send_error(400)
        identifier(request['challenge'])
        service = handler.server.administration
        with service.locked() as (_, _, _, node):
            signatures = MappingSignatures(service.root)
            identity = signatures.identity()
            payload = dict(schema_version=1, node_id=node['id'], challenge=request['challenge'],
                           endpoint=handler.server.origin, capability='connectivity-only')
            with tempfile.TemporaryDirectory(dir=service.root) as directory:
                message = Path(directory) / 'probe'
                message.write_bytes(canonical(payload))
                signature = openssl('pkeyutl', '-sign', '-rawin', '-inkey', str(signatures.key), '-in', str(message))
        return handler.reply(200, dict(payload=payload, public_key=identity['public_key'],
                                       signature=base64.b64encode(signature).decode()))
    except Exception:
        return handler.reply(422, {'error': 'Node identity unavailable; restore original configuration and keys'})


def check_peer(endpoint, ca, node_id, fingerprint):
    parsed = urlsplit(endpoint)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/')
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('Zadejte HTTPS adresu uzlu bez cesty, credentials či parametrů.')
    address = ipaddress.ip_address(parsed.hostname)
    if address.version != 4 or not address.is_private or address.is_unspecified:
        raise ValueError('Test podporuje pouze privátní IPv4 adresy uzlů.')
    identifier(node_id)
    challenge = str(uuid4())
    try:
        context = ssl.create_default_context(cafile=str(ca))
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        connection = http.client.HTTPSConnection(str(address), parsed.port or 443, context=context, timeout=5)
        try:
            connection.request('POST', PATH, body=json.dumps({'challenge': challenge}),
                               headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            if response.status == 404:
                raise ValueError('Uzel ještě nemá síťový probe endpoint. Aktualizujte aplikaci na tomto uzlu.')
            if response.status != 200:
                raise ValueError('Uzel odmítl probe: HTTP ' + str(response.status))
            raw = response.read(8193)
            if len(raw) > 8192:
                raise ValueError('Odpověď uzlu je příliš velká.')
            envelope = json.loads(raw)
        finally:
            connection.close()
    except ssl.SSLCertVerificationError as exc:
        raise ValueError('TLS ověření selhalo: zkontrolujte CA, platnost certifikátu a IP v SAN. ' + str(exc)) from exc
    except (TimeoutError, ConnectionError, socket.gaierror) as exc:
        raise ValueError('Spojení nedostupné: zkontrolujte běh backendu, adresu, port, směrování a případný firewall. ' + str(exc)) from exc
    if not isinstance(envelope, dict) or set(envelope) != {'payload', 'public_key', 'signature'}:
        raise ValueError('Neplatná podepsaná odpověď uzlu.')
    expected = dict(schema_version=1, node_id=node_id, challenge=challenge,
                    endpoint=endpoint.rstrip('/'), capability='connectivity-only')
    if envelope['payload'] != expected:
        raise ValueError('Odpověď má jinou identitu, adresu nebo nonce; spojení nebylo ověřeno.')
    if not isinstance(envelope['public_key'], str) or not isinstance(envelope['signature'], str):
        raise ValueError('Neplatný podpis uzlu.')
    public = base64.b64decode(envelope['public_key'], validate=True)
    signature = base64.b64decode(envelope['signature'], validate=True)
    if (len(public) != 44 or public[:12] != bytes.fromhex('302a300506032b6570032100')
            or len(signature) != 64 or hashlib.sha256(public).hexdigest() != fingerprint):
        raise ValueError('Veřejný klíč neodpovídá schválenému pinu; důvěra nebyla změněna.')
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'public').write_bytes(public); (root / 'signature').write_bytes(signature)
        (root / 'probe').write_bytes(canonical(expected))
        openssl('pkeyutl', '-verify', '-pubin', '-keyform', 'DER', '-inkey', str(root / 'public'),
                '-rawin', '-in', str(root / 'probe'), '-sigfile', str(root / 'signature'))
    return 'HTTPS, identita uzlu a podepsaná odpověď ověřeny. Synchronizace dat tím není ověřena.'
