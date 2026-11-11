# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Volatile automatic-retry pacing, never recovery or operation authority."""
from collections import OrderedDict
import math
import threading
import time


class AutomaticRetry:
    def __init__(self):
        self.lock = threading.Lock()
        self.failures = OrderedDict()

    def ready(self, key):
        with self.lock:
            row = self.failures.get(key)
            return row is None or time.monotonic() >= row[1]

    def failed(self, key):
        with self.lock:
            count = min(self.failures.get(key, (0, 0))[0] + 1, 5)
            self.failures[key] = count, time.monotonic() + min(900, 60 * 2 ** (count - 1))
            self.failures.move_to_end(key)
            while len(self.failures) > 128:
                self.failures.popitem(last=False)

    def remaining(self, key):
        with self.lock:
            row = self.failures.get(key)
            return max(0, math.ceil(row[1] - time.monotonic())) if row else 0

    def succeeded(self, key):
        with self.lock:
            self.failures.pop(key, None)


automatic_retry = AutomaticRetry()
