# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Extension–backend protocol version (ADR 0060, AUDIT-B3; contract K7).

The protocol is independent of the extension package version and of the
pairing file schema. A missing header is protocol 1, i.e. every extension
released before the header existed.
"""
from spikes.metadata import UnsupportedVersion

HEADER = 'X-Workspace-Bridge-Protocol'
SUPPORTED = (1, 1)
ROUTE_PREFIX = '/v1/ide-bridge/'
UPDATE_ROUTE = '/v1/ide-bridge/connection/exchange'


def response_header():
    return f'{SUPPORTED[0]}-{SUPPORTED[1]}'


def declared(headers):
    """Return the declared protocol, None for an absent header, or raise ValueError."""
    values = headers.get_all(HEADER, [])
    if not values:
        return None
    if len(values) != 1 or not values[0].isascii() or not values[0].isdecimal() or len(values[0]) > 6:
        raise ValueError('Invalid bridge protocol header')
    return int(values[0])


def is_update(path, request):
    return (path == UPDATE_ROUTE and isinstance(request, dict)
            and request.get('action') == 'extension-update')


def check(path, headers, request):
    """Reject an unsupported protocol before any field check; updates stay reachable."""
    if not path.startswith(ROUTE_PREFIX):
        return
    version = declared(headers)
    version = 1 if version is None else version
    if SUPPORTED[0] <= version <= SUPPORTED[1] or is_update(path, request):
        return
    raise UnsupportedVersion('ide-protocol', version, range(SUPPORTED[0], SUPPORTED[1] + 1),
                             update='backend', older='extension')
