# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit editor classification, using the existing native transaction journal."""
import json
import yaml
from spikes.metadata import require

LEVELS = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}


def selection(request, previous=None, *, network=False):
    value = request.get('privacy', previous or 'project')
    require(isinstance(value, str) and value in LEVELS, 'Invalid document privacy')
    approved = request.get('authorize_privacy_relaxation', False)
    require(type(approved) is bool, 'Invalid privacy authorization')
    require(not network or value != 'local-only', 'Local-only classification requires the desktop')
    require(previous is None or LEVELS[value] >= LEVELS[previous] or approved,
            'Snížení ochrany souboru vyžaduje výslovné potvrzení.')
    return value


def changes(doc, content, privacy):
    meta = dict(doc['metadata'], privacy=privacy)
    if doc['sidecar']:
        return {doc['path']: content.encode(), doc['sidecar']:
            (json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()}
    return {doc['path']: ('---\n'+yaml.safe_dump(meta, allow_unicode=True, sort_keys=True)+'---\n'+content).encode()}


def audit(previous, current):
    return '' if previous == current else f'; privacy {previous} -> {current} (explicit editor classification)'
