# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bound request header/body trickling before any application dispatch."""
import io
from spikes.http_deadline import _Deadline, _Reader, _Socket


class RequestReadTimeout(TimeoutError):
    """The request was not fully read; no domain operation was dispatched."""


class _RequestReader(_Reader):
    def readinto(self, buffer):
        try:
            return super().readinto(buffer)
        except TimeoutError as exc:
            raise RequestReadTimeout('HTTP request read deadline exceeded') from exc


def request_reader(transport, seconds):
    budget = _Socket(transport, _Deadline(seconds), timeout=1)
    return io.BufferedReader(_RequestReader(
        transport.makefile('rb', buffering=0), transport, budget))
