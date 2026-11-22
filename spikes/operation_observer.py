# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Request-local pre-effect receipt binding; no dispatch or recovery authority."""
from contextvars import ContextVar

native_observer = ContextVar('native_operation_observer', default=None)


def observe_native(root, operation_id, request_digest):
    observer = native_observer.get()
    if observer is not None:
        observer(root, operation_id, request_digest)
