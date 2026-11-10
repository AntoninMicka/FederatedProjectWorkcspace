# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""One monotonic transport budget for pinned, literal-IPv4 HTTPS peers.

Socket inactivity timeouts alone do not bound a trickling HTTP status/header/body.
Keep stdlib HTTP parsing and TLS verification; update the remaining budget at
every raw read, not only once before response.read(). No DNS, retries or workers.
"""
import http.client
import io
import ipaddress
import math
import socket
import time


class _Deadline:
    def __init__(self, seconds):
        if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not math.isfinite(seconds) or seconds <= 0):
            raise ValueError('Expected a positive finite network budget')
        self.end = time.monotonic() + seconds

    def remaining(self):
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Network operation deadline exceeded')
        return remaining


class _Reader(io.RawIOBase):
    def __init__(self, raw, transport, deadline):
        super().__init__()
        self.raw, self.transport, self.deadline = raw, transport, deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        self.transport.settimeout(self.deadline.io_timeout()
            if isinstance(self.deadline, _Socket) else self.deadline.remaining())
        try:
            count = self.raw.readinto(buffer)
        except TimeoutError:
            self.deadline.remaining()
            raise
        self.deadline.remaining()
        return count

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class _Socket:
    def __init__(self, transport, deadline, *, timeout=None, watchdog=False):
        self.transport, self.deadline = transport, deadline
        self.timeout = timeout
        self.watchdog = watchdog

    def remaining(self):
        remaining = self.deadline.remaining()
        return min(remaining, self.timeout) if self.timeout is not None else remaining

    def io_timeout(self):
        remaining = self.remaining()
        # An attached run watchdog interrupts in-flight I/O at the current hard
        # deadline. Clamping its kernel wait to the old hard deadline would
        # wrongly expire a read after the user explicitly extends that run.
        return self.timeout if self.watchdog and self.timeout is not None else remaining

    def settimeout(self, timeout):
        self.timeout = timeout
        self.transport.settimeout(self.remaining())

    def __getattr__(self, name):
        return getattr(self.transport, name)

    def sendall(self, data, *args, **kwargs):
        self.transport.settimeout(self.io_timeout())
        self.transport.sendall(data, *args, **kwargs)
        self.deadline.remaining()

    def makefile(self, mode='rb'):
        if mode != 'rb':
            raise ValueError('Deadline HTTP socket supports binary response reads only')
        # Native makefile owns its socket reference. HTTP/1.0 getresponse() may
        # close the connection before its returned response body has been read.
        raw = self.transport.makefile('rb', buffering=0)
        return io.BufferedReader(_Reader(raw, self.transport, self))


class DeadlineHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port=None, *, context, timeout):
        # Callers retain their own private-address policy and pinned CA checks.
        # Literal IPv4 lets connect avoid an unbounded system DNS resolver.
        self.address = str(ipaddress.IPv4Address(host))
        self.deadline = _Deadline(timeout)
        super().__init__(host, port, context=context, timeout=timeout)

    def connect(self):
        if self._tunnel_host is not None:
            raise ValueError('Peer transport does not support proxy tunnels')
        transport = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            transport.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            transport.settimeout(self.deadline.remaining())
            transport.connect((self.address, self.port))
            transport = self._context.wrap_socket(transport, server_hostname=self.host,
                                                   do_handshake_on_connect=False)
            transport.settimeout(self.deadline.remaining())
            transport.do_handshake()
            self.deadline.remaining()
            self.sock = _Socket(transport, self.deadline)
        except BaseException:
            transport.close()
            raise

    def check_deadline(self):
        self.deadline.remaining()
