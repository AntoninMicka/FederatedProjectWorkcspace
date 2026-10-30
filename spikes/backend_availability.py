# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Ephemeral availability samples; one probe, no queued work or socket ownership."""
from collections import OrderedDict
from datetime import datetime, timezone
import threading
import time

from spikes.ollama_backend import OllamaAdapter


class BackendAvailability:
    def __init__(self, *, ttl=30, clock=time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self._condition = threading.Condition()
        self._samples = OrderedDict()
        self._running = None
        self._closed = False

    def status(self, binding):
        """The caller validates and authorizes the immutable binding before admission."""
        with self._condition:
            sample = self._samples.get(binding)
            stale = sample is None or self.clock() - sample[0] >= self.ttl
            if stale and self._running is None and not self._closed:
                self._running = binding
                worker = threading.Thread(target=self._probe, args=(binding,),
                                          name='backend-availability', daemon=True)
                try:
                    worker.start()
                except BaseException:
                    self._running = None
                    raise
            result = dict(sample[1]) if sample else {
                'status': 'unknown', 'available': None,
                'model_available': None, 'checked_at': None}
            return dict(result, stale=stale, checking=self._running == binding,
                        retry_after_ms=1000 if stale and not self._closed else None)

    def _probe(self, binding):
        result = None
        try:
            value = OllamaAdapter.probe(binding, timeout=10)
            result = {'status': 'available', 'available': True,
                      'model_available': value['model_available']}
        except Exception:
            # Transport diagnostics may contain private endpoints. This is only
            # a liveness sample; detailed manual testing retains its own API.
            result = {'status': 'unavailable', 'available': False,
                      'model_available': None}
        finally:
            with self._condition:
                if result is not None and not self._closed:
                    result['checked_at'] = datetime.now(timezone.utc).isoformat()
                    self._samples[binding] = (self.clock(), result)
                    self._samples.move_to_end(binding)
                    while len(self._samples) > 8:
                        self._samples.popitem(last=False)
                self._running = None
                self._condition.notify_all()

    def close(self, timeout):
        """Stop admission and drain the bounded network probe before node cleanup."""
        with self._condition:
            self._closed = True
            return self._condition.wait_for(lambda: self._running is None,
                                            timeout=max(0, timeout))
