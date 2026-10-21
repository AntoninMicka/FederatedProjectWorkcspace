# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Single validated release version shared by distribution builders."""
import re
from pathlib import Path


VERSION_PATTERN = re.compile(
    r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
    r'(?:~[0-9A-Za-z][0-9A-Za-z.+~-]*)?'
)


def validate_version(value):
    if not isinstance(value, str) or not VERSION_PATTERN.fullmatch(value):
        raise ValueError('Invalid release version')
    return value


def read_version(root):
    path = Path(root).absolute() / 'VERSION'
    if (not path.is_file() or path.is_symlink()
            or path.resolve() != path.absolute() or path.stat().st_size > 128):
        raise ValueError('Expected a small regular VERSION file')
    raw = path.read_bytes()
    try:
        value = raw.decode('ascii')
    except UnicodeDecodeError as exc:
        raise ValueError('VERSION must be ASCII') from exc
    if not value.endswith('\n') or '\n' in value[:-1] or '\r' in value:
        raise ValueError('VERSION must contain one LF-terminated value')
    return validate_version(value[:-1])
