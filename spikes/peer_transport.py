# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Named network budgets and the single federated peer address policy (AUDIT-B5-T1).

Budgets are total deadlines of one outbound HTTPS exchange
(``DeadlineHTTPSConnection``). A background scheduler that may be inside such
an exchange gets ``stop_timeout(budget)`` to finish at shutdown.

Peer policy: an HTTPS origin without path, credentials, query or fragment on a
literal private IPv4 address. IPv4 only is a documented decision
(docs/network-limits.md, ADR 0020); IPv6 and host names are refused with an
explicit error. Loopback is part of ``is_private`` for IPv4, so it is allowed
for every peer kind, replication included.
"""
import ipaddress
from urllib.parse import urlsplit

from spikes.metadata import require

CATALOG_EXCHANGE_TIMEOUT = 15     # project catalog request/response
CONTENT_STATE_TIMEOUT = 15        # content state manifest probe
RSS_EXCHANGE_TIMEOUT = 15         # RSS preference exchange
REPLICATION_TIMEOUT = 30          # one replication bundle transfer
CONTENT_SYNC_TIMEOUT = 60         # one content sync bundle transfer
SHUTDOWN_MARGIN = 5               # join slack beyond the in-flight exchange


def stop_timeout(budget):
    """Bounded scheduler join: the in-flight exchange budget plus a margin."""
    return budget + SHUTDOWN_MARGIN


def private_peer_endpoint(endpoint, *, invalid, private):
    """Return (parsed URL, IPv4 address) of an allowed peer or raise ValidationError.

    ``invalid`` and ``private`` are the caller's existing error messages.
    """
    parsed = urlsplit(endpoint)
    require(parsed.scheme == 'https' and not parsed.path.strip('/')
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment, invalid)
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    require(address is not None and address.version == 4 and not address.is_unspecified
            and (address.is_private or address.is_loopback), private)
    return parsed, address
