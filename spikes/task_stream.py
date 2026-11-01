# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Ephemeral, owner-scoped deadline decisions; durable run evidence stays in OllamaRuns."""
import socket
import threading
import time
from contextlib import contextmanager

from spikes.metadata import require, uuid

SOFT_SECONDS = 180


class RunDeadline:
    def __init__(self, emit, *, soft=SOFT_SECONDS, clock=time.monotonic):
        require(isinstance(soft, (int, float)) and soft > 0, 'Invalid soft deadline')
        self.emit, self.soft, self.clock = emit, soft, clock
        self.lock = threading.RLock()
        self.started = None
        self.extended = False
        self.reason = None
        self.finished = False
        self.sock = None
        self.closed = threading.Event()
        self.thread = None

    def start(self):
        with self.lock:
            require(self.started is None and self.reason is None, 'Run deadline already started or stopped')
            self.started = self.clock()
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()

    def snapshot(self):
        with self.lock:
            elapsed = max(0, self.clock()-self.started) if self.started is not None else 0
            return dict(soft_seconds=self.soft, elapsed_seconds=int(elapsed),
                        hard_seconds=self.soft*(10 if self.extended else 2),
                        extended=self.extended, stopped=self.reason)

    def tick(self):
        with self.lock:
            if self.started is None or self.reason or self.closed.is_set(): return
            elapsed = self.clock()-self.started
            if elapsed >= self.soft*(10 if self.extended else 2):
                self.stop('hard-timeout')
                return
        self.emit({'type': 'deadline', **self.snapshot()})

    def _watch(self):
        while not self.closed.wait(min(0.5, self.soft/10)):
            try: self.tick()
            except OSError:
                self.stop('client-disconnected')
                return

    def attach(self, sock):
        with self.lock:
            self.sock = sock
            if self.reason: self._interrupt()

    def _interrupt(self):
        if self.sock is not None:
            try: self.sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass

    def stop(self, reason='user-stopped'):
        with self.lock:
            if self.reason is None and not self.finished:
                self.reason = reason
                self._interrupt()

    def extend(self):
        with self.lock:
            require(self.started is not None and not self.closed.is_set() and not self.reason
                    and self.clock()-self.started < self.soft*(10 if self.extended else 2),
                    'Run deadline already expired')
            self.extended = True
        return self.snapshot()

    def check(self):
        self.tick()
        require(self.reason is None, 'Run stopped: '+str(self.reason))

    def complete(self):
        with self.lock:
            if self.started is not None and self.clock()-self.started >= self.soft*(10 if self.extended else 2):
                self.stop('hard-timeout')
            require(self.reason is None, 'Run stopped: '+str(self.reason))
            self.finished = True
            self.closed.set()

    def close(self):
        self.closed.set()
        if self.thread: self.thread.join(1)


def key(service, request):
    for name in ('project_id', 'run_id'): uuid(request.get(name))
    allowed = service._request_writable_project_ids.get()
    require(allowed is None or request['project_id'] in allowed, 'Project access denied')
    return (*service._identity(), request['project_id'], request['run_id'])


@contextmanager
def registered(service, request, emit):
    identity = key(service, request)
    control = RunDeadline(emit)
    with service.task_stream_lock:
        require(identity not in service.task_stream_controls, 'Run stream already active')
        service.task_stream_controls[identity] = control
    try:
        yield control
    finally:
        control.close()
        with service.task_stream_lock: service.task_stream_controls.pop(identity, None)


def decide(service, request):
    require(isinstance(request, dict) and set(request) == {'project_id', 'run_id', 'action'}
            and request['action'] in {'stop', 'extend'}, 'Invalid run deadline decision')
    identity = key(service, request)
    with service.task_stream_lock:
        control = service.task_stream_controls.get(identity)
        require(control is not None and not control.closed.is_set(), 'Run stream is no longer active')
        if request['action'] == 'stop': control.stop()
        else: control.extend()
        return control.snapshot()


def serve(handler, request):
    import json
    from spikes.ollama_backend import UnknownRun, OllamaResponseError
    from spikes.document_patch import PatchValidationError
    require(isinstance(request, dict), 'Invalid streamed task request')
    key(handler.server.chat_service, request)
    handler.close_connection = True
    handler.send_response_only(200)
    for k, v in [('Content-Type','application/x-ndjson; charset=utf-8'),
                 ('Cache-Control','no-store'), ('Connection','close'),
                 ('X-Content-Type-Options','nosniff')]: handler.send_header(k,v)
    handler.end_headers()
    output_lock = threading.Lock()
    def emit(value):
        with output_lock:
            handler.wfile.write(json.dumps(value, ensure_ascii=False).encode()+b'\n')
            handler.wfile.flush()
    with registered(handler.server.chat_service, request, emit) as control:
        try:
            result = handler.server.chat_service.task_route(request,
                on_delta=lambda delta: emit(dict(type='delta',delta=delta)),
                on_status=lambda status: emit(dict(type='status',status=status)), control=control)
            emit(dict(type='result',result=result))
        except PatchValidationError as exc:
            emit(dict(type='error', status=422, error=str(exc), diagnostic=exc.code, outcome='invalid-proposal'))
        except (UnknownRun, OllamaResponseError, ValueError, OSError) as exc:
            control.stop(control.reason or 'stream-failed')
            try: emit(dict(type='error',status=409 if isinstance(exc, UnknownRun) or control.reason in {
                'user-stopped','hard-timeout'} else 422,
                error=('Běh byl ukončen po časovém limitu.' if control.reason=='hard-timeout' else
                       'Běh byl ukončen uživatelem.' if control.reason=='user-stopped' else
                       'Průběžný výsledek úlohy nelze bezpečně použít.')+
                       ' Původní běh automaticky neopakujte.', diagnostic=control.reason))
            except OSError: pass
