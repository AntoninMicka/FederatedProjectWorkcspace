# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bounded nonblocking TLS/header intake, separate from application workers."""
import io
import logging
import re
import selectors
import socket
import ssl
import threading
import time
from spikes.http_admission_policy import RESERVED_ROUTES

_RESERVED_PATHS = frozenset(path.encode('ascii') for path in RESERVED_ROUTES)


class _PrefixReader(io.RawIOBase):
    def __init__(self, owner, raw):
        self.owner, self.raw = owner, raw

    def readable(self):
        return True

    def readinto(self, buffer):
        if self.owner.prefix:
            count = min(len(buffer), len(self.owner.prefix))
            buffer[:count] = self.owner.prefix[:count]
            del self.owner.prefix[:count]
            return count
        return self.raw.readinto(buffer)

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class PrefixedSocket:
    """Give the original HTTP parser every byte consumed during admission."""
    def __init__(self, transport, prefix, started):
        self.transport, self.prefix = transport, bytearray(prefix)
        self.header_started = started

    def __getattr__(self, name):
        return getattr(self.transport, name)

    def makefile(self, mode, buffering=-1):
        if mode != 'rb':
            return self.transport.makefile(mode, buffering)
        raw = _PrefixReader(self, self.transport.makefile('rb', buffering=0))
        return raw if buffering == 0 else io.BufferedReader(raw)


class HeaderAdmission:
    """One selector thread; pending sockets never consume application workers.

    Header bytes are bounded to 64 KiB/socket, at most 64 pending sockets by
    default. Overflow is refused before any handler/authentication/dispatch.
    """
    def __init__(self, dispatch, reject, *, capacity=64, header_bytes=65536,
                 seconds=60, idle_seconds=1, static_paths=()):
        self.dispatch, self.reject = dispatch, reject
        self.capacity, self.header_bytes = capacity, header_bytes
        self.seconds, self.idle_seconds = seconds, idle_seconds
        self.static_paths = frozenset(path.encode('ascii') for path in static_paths)
        self.guard = threading.Lock()
        self.pending = {}
        self.closed = False
        self.selector = selectors.DefaultSelector()
        self.wake_read, self.wake_write = socket.socketpair()
        self.wake_read.setblocking(False); self.wake_write.setblocking(False)
        self.selector.register(self.wake_read, selectors.EVENT_READ, None)
        self.thread = threading.Thread(target=self._run, name='http-header-admission', daemon=True)
        self.thread.start()

    def _wake(self):
        try:
            self.wake_write.send(b'.')
        except (BlockingIOError, OSError):
            pass

    def add(self, connection, address):
        with self.guard:
            if self.closed or len(self.pending) >= self.capacity:
                accepted = False
            else:
                now = time.monotonic()
                connection.setblocking(False)
                self.pending[connection] = dict(address=address, started=now, last=now,
                    prefix=bytearray(), registered=False,
                    handshake=isinstance(connection, ssl.SSLSocket))
                accepted = True
        if accepted:
            self._wake()
        else:
            self.reject(connection)

    def count(self):
        with self.guard:
            return len(self.pending)

    def _remove(self, connection):
        with self.guard:
            item = self.pending.pop(connection, None)
        if item and item['registered']:
            try:
                self.selector.unregister(connection)
            except (KeyError, ValueError, OSError):
                pass
        return item

    def _read(self, connection, item):
        try:
            if item['handshake']:
                connection.do_handshake()
                item['handshake'] = False
                item['last'] = time.monotonic()
            chunk = connection.recv(min(16384, self.header_bytes + 1 - len(item['prefix'])))
            if not chunk:
                self._remove(connection); connection.close(); return
            item['prefix'].extend(chunk); item['last'] = time.monotonic()
            # Match the original parser's CRLF, LF and mixed line endings.
            marker = re.search(br'\n\r?\n', item['prefix'])
            if ((marker is None and len(item['prefix']) > self.header_bytes)
                    or marker is not None and marker.end() > self.header_bytes):
                self._remove(connection); self.reject(connection, code=431); return
            if marker is not None:
                self._remove(connection)
                first = bytes(item['prefix']).split(b'\n', 1)[0].split()
                method, path = first[:2] if len(first) >= 2 else (b'', b'')
                reserved = (method in (b'GET', b'HEAD') and path in self.static_paths or
                    method == b'POST' and path in _RESERVED_PATHS)
                connection.setblocking(True)
                self.dispatch(PrefixedSocket(connection, item['prefix'], item['started']), item['address'], reserved)
            elif isinstance(connection, ssl.SSLSocket) and connection.pending():
                # Decrypted bytes may remain even without another OS readiness edge.
                self._read(connection, item)
        except ssl.SSLWantWriteError:
            self.selector.modify(connection, selectors.EVENT_WRITE, item)
        except (ssl.SSLWantReadError, BlockingIOError):
            self.selector.modify(connection, selectors.EVENT_READ, item)
        except (OSError, ValueError):
            self._remove(connection); connection.close()
        except Exception as exc:
            logging.getLogger(__name__).warning('http_ingress_failed error_type=%s', type(exc).__name__)
            self._remove(connection); connection.close()

    def _run(self):
        try:
            while True:
                with self.guard:
                    if self.closed:
                        break
                    pending = list(self.pending.items())
                now = time.monotonic()
                for connection, item in pending:
                    idle = 2 if item['handshake'] else self.idle_seconds
                    if now-item['started'] >= self.seconds or now-item['last'] >= idle:
                        self._remove(connection); connection.close()
                    elif not item['registered']:
                        self.selector.register(connection, selectors.EVENT_READ, item)
                        item['registered'] = True
                for key, _ in self.selector.select(.1):
                    if key.data is None:
                        try:
                            self.wake_read.recv(4096)
                        except BlockingIOError:
                            pass
                    else:
                        self._read(key.fileobj, key.data)
        finally:
            with self.guard:
                self.closed = True
                pending = list(self.pending)
            for connection in pending:
                self._remove(connection); connection.close()
            self.selector.close()
            self.wake_read.close(); self.wake_write.close()

    def close(self):
        with self.guard:
            self.closed = True
        self._wake()
        self.thread.join(timeout=2)
        return not self.thread.is_alive()
