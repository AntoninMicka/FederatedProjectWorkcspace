# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Confirmed purpose=output declarations, reused by typed project relations.

No new writer: publication is the existing exact share_write confirmation.
A generic JSON declaration or an unfinished/failed model answer is no grant.
"""
import json

from spikes.metadata import MAX_METADATA, parse_json, require
from spikes.reference_schema import shares
from spikes.reporting_schema import digest

MAX_RECEIPTS_PER_SHARE = 64


def model_ready(meta, raw):
    """Explicit output confirmation accepts the document; failed chat turns stay excluded."""
    marker = b'<!-- fpw-chat-output-v1\n'
    if meta['provenance'] not in {'llm-generated', 'llm-transformed'} or marker not in raw:
        return True
    try:
        require(raw.count(marker) == 1, 'Ambiguous chat provenance')
        tail = raw.split(marker, 1)[1]
        require(b'\n-->\n' in tail, 'Incomplete chat provenance')
        value = parse_json(tail.split(b'\n-->\n', 1)[0], maximum=MAX_METADATA)
        require(isinstance(value, dict), 'Invalid chat provenance')
        turns = value.get('turns')
        return (value.get('schema') == 'fpw-chat-output-v1' and isinstance(turns, list) and bool(turns)
                and all(isinstance(t, dict) and t.get('state') == 'completed' and t.get('error') is None
                        for t in turns))
    except ValueError:
        return False


def publications(workspace, db, project_id, head, files, entities):
    """Return original native publication proofs; current revocation is always live.

    Reconstruct the original share request digest from its committed bytes and
    receipt. Thus a generic apply/import receipt cannot impersonate publication.
    Targets still constrain XREF; approved project relations use their own grant.
    """
    result = {}
    for share_id, value in sorted(shares(files, entities).items()):
        if value['purpose'] != 'output' or value['revoked'] is not None or value['artifact_id'] not in entities:
            continue
        path = f'artifacts/{share_id}/share.json'
        rows = db.execute('SELECT record FROM operations WHERE done=1 AND record LIKE ? ORDER BY rowid DESC LIMIT ?',
                          ('%' + path + '%', MAX_RECEIPTS_PER_SHARE + 1)).fetchall()
        require(len(rows) <= MAX_RECEIPTS_PER_SHARE, 'Output publication receipt coverage limit')
        for (raw_receipt,) in rows:
            receipt = json.loads(raw_receipt); commit = receipt.get('commit_id')
            if not commit or path not in receipt.get('paths', ()):
                continue
            if workspace.git.run('merge-base', '--is-ancestor', commit, head, check=False).returncode:
                continue
            # Read only the declaration and its metadata, not a full project
            # snapshot for every historical publication (potentially many MiB).
            original = workspace.git.run('show', commit + ':' + path, binary=True, check=False)
            metadata = workspace.git.run('show', commit + f':artifacts/{share_id}/metadata.json',
                                         binary=True, check=False)
            if original.returncode or metadata.returncode:
                continue
            record = parse_json(original.stdout, maximum=MAX_METADATA)
            meta = parse_json(metadata.stdout, maximum=MAX_METADATA)
            if any(record.get(k) != value[k] for k in ('artifact_id', 'purpose', 'originator_id', 'created_at')):
                continue
            if record.get('revoked') is not None:
                continue
            preview = dict(schema='fpw-share-write-v1', project_id=project_id, base_head=receipt['base_head'],
                           share_id=share_id, record=record, title=meta['title'], privacy=meta['privacy'],
                           user_id=record['originator_id'])
            request = dict(preview, action='write-share-v1')
            expected = digest(json.dumps(request, sort_keys=True, ensure_ascii=False).encode())
            if receipt.get('request_digest') != expected:
                continue
            proof = dict(schema='fpw-output-publication-v1', project_id=project_id,
                         artifact_id=value['artifact_id'], share_id=share_id, commit_id=commit,
                         operation_id=receipt['operation_id'], sha256=digest(original.stdout),
                         originator_id=record['originator_id'])
            result.setdefault(value['artifact_id'], []).append(proof)
            break
    return result
