# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Named network budgets and the single federated address policy (AUDIT-B5-T1).

Budgets are total deadlines of one outbound HTTPS exchange
(``DeadlineHTTPSConnection``). A background scheduler that may be inside such
an exchange gets ``stop_timeout(budget)`` to finish at shutdown.

Address policy (docs/network-limits.md): IPv4 and IPv6 are both supported.
A peer, listener or client LAN uses a literal private address, never a host
name, so connecting never waits on the unbounded system DNS resolver.

- IPv4: ``ipaddress.is_private`` (RFC 1918 and loopback ``127.0.0.0/8``).
- IPv6: unique local ``fc00::/7`` and loopback ``::1``. Link-local
  ``fe80::/10`` needs an interface zone and is refused; IPv4-mapped addresses
  are refused so that one host has one canonical spelling.
"""
import ipaddress
from urllib.parse import urlsplit

from spikes.metadata import require

CATALOG_EXCHANGE_TIMEOUT = 15     # project catalog request/response
CONTENT_STATE_TIMEOUT = 15        # content state manifest probe
RSS_EXCHANGE_TIMEOUT = 15         # RSS preference exchange
REPLICATION_TIMEOUT = 30          # one replication bundle transfer
CONTENT_SYNC_TIMEOUT = 60         # one content sync bundle transfer
ENROLLMENT_TIMEOUT = 10           # one enrollment request/response
PROBE_TIMEOUT = 5                 # interactive peer connection test
SHUTDOWN_MARGIN = 5               # join slack beyond the in-flight exchange
RESPONSE_MARGIN = 15              # receiver work ends this long before the sender gives up
# History verification of one received content sync bundle. Shorter than the
# sender's exchange budget, so an overloaded receiver still answers "busy"
# (git-budget) instead of the sender timing out (AUDIT-B7-T1).
CONTENT_RECEIVE_BUDGET = CONTENT_SYNC_TIMEOUT - RESPONSE_MARGIN
# Streamed content sync (receiver works in the background and sends heartbeat
# frames): the sender gives up after HEARTBEAT_IDLE_TIMEOUT without a frame, or
# after CONTENT_SYNC_MAX_WAIT in total. The background receive job verifies
# history within BACKGROUND_RECEIVE_BUDGET (AUDIT-B7-T1).
HEARTBEAT_IDLE_TIMEOUT = 20
CONTENT_SYNC_MAX_WAIT = 900
BACKGROUND_RECEIVE_BUDGET = CONTENT_SYNC_MAX_WAIT - 5 * 60

UNIQUE_LOCAL = ipaddress.ip_network('fc00::/7')
MIN_IPV4_LAN_PREFIX = 8


def stop_timeout(budget):
    """Bounded scheduler join: the in-flight exchange budget plus a margin."""
    return budget + SHUTDOWN_MARGIN


def private_address(address):
    """True for an allowed private literal address of either family."""
    if address.is_unspecified:
        return False
    if address.version == 4:
        return address.is_private or address.is_loopback
    return (address.scope_id is None and address.ipv4_mapped is None
            and (address.is_loopback or address in UNIQUE_LOCAL))


def private_lan(network):
    """True for a client LAN: private IPv4 /8 or narrower, or unique local IPv6."""
    if network.version == 4:
        return network.is_private and network.prefixlen >= MIN_IPV4_LAN_PREFIX
    return network.subnet_of(UNIQUE_LOCAL)


def canonical_address(value):
    """A literal address; an IPv4-mapped IPv6 address from a dual-stack socket
    becomes plain IPv4, so loopback and LAN checks do not depend on Python's
    version-specific handling of mapped addresses."""
    address = ipaddress.ip_address(value)
    if address.version == 6 and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def origin(address, port):
    """HTTPS origin of a literal address; IPv6 is bracketed."""
    address = canonical_address(address)
    host = f'[{address}]' if address.version == 6 else str(address)
    return f'https://{host}:{port}'


def private_peer_endpoint(endpoint, *, invalid, private):
    """Return (parsed URL, address) of an allowed peer or raise ValidationError.

    ``invalid`` and ``private`` are the caller's error messages.
    """
    parsed = urlsplit(endpoint)
    require(parsed.scheme == 'https' and not parsed.path.strip('/')
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment, invalid)
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    require(address is not None and private_address(address), private)
    # Canonical host spelling: the receiver compares Host with its socket address.
    host = f'[{address}]' if address.version == 6 else str(address)
    netloc = host if parsed.port is None else f'{host}:{parsed.port}'
    return parsed._replace(netloc=netloc), address
# A streamed content state answer (automatic change check) is computed in a
# background job on the peer: CONTENT_STATE_TIMEOUT then bounds only the
# response head, heartbeats bound silence, and this caps the whole answer.
CONTENT_STATE_MAX_WAIT = 5 * 60
BACKGROUND_STATE_BUDGET = CONTENT_STATE_MAX_WAIT - 30
