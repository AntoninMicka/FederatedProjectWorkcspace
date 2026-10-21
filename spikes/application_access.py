# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Durable node-local policy deciding which clients may reach the web app."""
import hashlib
import ipaddress
import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3

from spikes.journal import sync_dir
from spikes.metadata import require


MODES = {'localhost', 'private-network', 'allowlist', 'unrestricted'}
DEFAULT_SETTINGS = {'mode': 'private-network', 'allowed': []}


def _network(value):
    require(isinstance(value, str) and 0 < len(value) <= 64
            and value == value.strip()
            and not any(ord(c) < 33 or ord(c) == 127 for c in value),
            'Povolená adresa musí být číselná IP adresa nebo síť v CIDR.')
    try:
        if '/' in value:
            parsed = ipaddress.ip_network(value, strict=True)
            result = str(parsed)
        else:
            address = ipaddress.ip_address(value)
            parsed = ipaddress.ip_network(f'{address}/{address.max_prefixlen}')
            result = str(address)
    except ValueError:
        raise ValueError('Povolená adresa musí být číselná IP adresa nebo síť v CIDR.') from None
    require(parsed.prefixlen > 0 and not parsed.is_multicast
            and not parsed.network_address.is_unspecified,
            'Multicast ani neurčenou adresu nelze povolit.')
    return result, parsed


def validate_settings(value):
    require(isinstance(value, dict) and set(value) == {'mode', 'allowed'},
            'Neplatná pole dostupnosti aplikace.')
    require(value['mode'] in MODES, 'Neplatný režim dostupnosti aplikace.')
    require(isinstance(value['allowed'], list) and len(value['allowed']) <= 128,
            'Povolené adresy musí být seznam nejvýše 128 položek.')
    normalized = []
    for item in value['allowed']:
        text, _ = _network(item)
        if text not in normalized:
            normalized.append(text)
    if value['mode'] == 'allowlist':
        require(normalized, 'Zadejte alespoň jednu povolenou adresu nebo síť.')
    else:
        require(not normalized, 'Seznam adres lze použít jen v režimu povolených adres.')
    return {'mode': value['mode'], 'allowed': normalized}


def revision(settings):
    raw = json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


class ApplicationAccess:
    """Load without side effects and persist only an explicitly confirmed policy."""

    def __init__(self, node_path, private_network):
        self.path = Path(node_path).resolve().with_suffix('.application-access.sqlite3')
        self.private_network = ipaddress.ip_network(private_network)
        self.settings = self.load()

    def load(self):
        if not self.path.exists():
            return dict(DEFAULT_SETTINGS)
        require(not self.path.is_symlink(), 'Nastavení dostupnosti nesmí být symbolický odkaz.')
        with closing(sqlite3.connect(f'{self.path.as_uri()}?mode=ro', uri=True)) as db:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'").fetchone()
            row = db.execute('SELECT value FROM settings WHERE id=1').fetchone() if exists else None
        return validate_settings(json.loads(row[0])) if row else dict(DEFAULT_SETTINGS)

    def allows(self, peer, settings=None):
        address = ipaddress.ip_address(peer) if isinstance(peer, str) else peer
        if address.is_loopback:
            return True
        current = validate_settings(settings) if settings is not None else self.settings
        if current['mode'] == 'localhost':
            return False
        if current['mode'] == 'unrestricted':
            return True
        if current['mode'] == 'private-network':
            return address.version == self.private_network.version and address in self.private_network
        return any(address.version == network.version and address in network
                   for _, network in map(_network, current['allowed']))

    def status(self, peer):
        return {'runtime': 'server', 'editable': True, 'settings': dict(self.settings),
                'revision': revision(self.settings), 'private_network': str(self.private_network),
                'client_address': str(ipaddress.ip_address(peer))}

    def preview(self, settings, peer):
        settings = validate_settings(settings)
        address = str(ipaddress.ip_address(peer))
        return {'settings': settings, 'expected_revision': revision(self.settings),
                'client_address': address, 'current_client_allowed': self.allows(address, settings)}

    def confirm(self, plan, peer, confirmed_disconnect, *, checkpoint=lambda: None):
        require(isinstance(plan, dict)
                and set(plan) == {'settings', 'expected_revision', 'client_address',
                                  'current_client_allowed'},
                'Neplatný plán změny dostupnosti.')
        require(isinstance(plan['expected_revision'], str)
                and isinstance(plan['client_address'], str)
                and type(plan['current_client_allowed']) is bool,
                'Neplatné typy v plánu změny dostupnosti.')
        expected = self.preview(plan['settings'], peer)
        require(plan == expected, 'Náhled již neodpovídá aktuálnímu stavu nebo klientovi.')
        require(type(confirmed_disconnect) is bool, 'Neplatné potvrzení odpojení.')
        require(plan['current_client_allowed'] or confirmed_disconnect,
                'Potvrďte, že nová politika může odpojit tohoto klienta.')
        value = validate_settings(plan['settings'])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            require(not self.path.is_symlink(), 'Nastavení dostupnosti nesmí být symbolický odkaz.')
        else:
            os.close(fd)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS settings '
                       '(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
            db.execute('INSERT OR REPLACE INTO settings VALUES (1, ?)',
                       (json.dumps(value, ensure_ascii=False),))
            checkpoint()
        sync_dir(self.path.parent)
        self.settings = value
        return self.status(peer)
