# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bound provider DNS and every transport read without retrying HTTP requests."""
import ipaddress
import json
import socket
import subprocess
import sys

from spikes.http_deadline import _Deadline, _Socket

# The resolver is the only child work. Killing it on expiry leaves no resolver
# thread consuming a worker forever. Only hostname/port, never credentials or
# request content, cross this boundary. Numeric endpoints avoid the child.
_RESOLVE = '''import json,socket,sys
rows=socket.getaddrinfo(sys.argv[1],int(sys.argv[2]),type=socket.SOCK_STREAM)
print(json.dumps(rows[:64]))
'''


class _ConnectBudget:
    def __init__(self, deadline, seconds):
        self.deadline, self.local = deadline, _Deadline(seconds)

    def remaining(self):
        return min(self.deadline.remaining(), self.local.remaining())


def _addresses(host, port, deadline):
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        with subprocess.Popen([sys.executable, '-I', '-c', _RESOLVE, host, str(port)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            try:
                while True:
                    try:
                        raw, _ = process.communicate(timeout=min(.1, deadline.remaining()))
                        break
                    except subprocess.TimeoutExpired:
                        continue
                deadline.remaining()
            except BaseException:
                process.kill()
                process.communicate()
                raise
            if process.returncode:
                raise socket.gaierror('Provider name resolution failed')
        rows = json.loads(raw)
        return [(family, kind, protocol, tuple(address))
                for family, kind, protocol, _, address in rows]
    family = socket.AF_INET if address.version == 4 else socket.AF_INET6
    return [(family, socket.SOCK_STREAM, 0, (str(address), port))]


def budget_connection(connection, seconds, *, deadline=None, total_seconds=None):
    """Adapt an existing stdlib HTTP(S) connection; preserve TLS policy/parsing.

    The absolute budget spans DNS, connect, TLS, upload, headers and raw body
    reads. Existing settimeout calls remain stricter inactivity limits. A run
    control may supply its explicit, extendable absolute deadline instead.
    Native HTTP errors retain their caller's before/after-dispatch handling.
    """
    watchdog = deadline is not None
    deadline = deadline if deadline is not None else _Deadline(
        seconds if total_seconds is None else total_seconds)
    original_connect, original_close = connection.connect, connection.close
    original_getresponse = connection.getresponse
    responses = []

    def create(address, timeout=None, source_address=None, **kwargs):
        last = None
        budget = _ConnectBudget(deadline, seconds)
        for family, kind, protocol, target in _addresses(*address, budget):
            transport = socket.socket(family, kind, protocol)
            try:
                transport.settimeout(budget.remaining())
                if source_address:
                    transport.bind(source_address)
                transport.connect(target)
                deadline.remaining()
                return transport
            except OSError as exc:
                transport.close()
                budget.remaining()
                last = exc
        if last is not None:
            raise last
        raise socket.gaierror('Provider name resolution returned no addresses')

    def connect():
        deadline.remaining()
        original_connect()
        deadline.remaining()
        if connection.sock is not None:
            connection.sock = _Socket(connection.sock, deadline, timeout=seconds, watchdog=watchdog)

    def getresponse():
        response = original_getresponse()
        responses.append(response)
        deadline.remaining()
        return response

    def close():
        try:
            while responses:
                response = responses.pop()
                response.close()
        finally:
            original_close()

    connection._create_connection = create
    connection.connect, connection.getresponse, connection.close = connect, getresponse, close
    return connection
