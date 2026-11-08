# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Stable desired executor identity; matching a UUID is not an execute grant."""
from copy import deepcopy
from pathlib import Path

from spikes.configuration import parse_node, read_config
from spikes.metadata import require


def local_node_id(node):
    path=Path(node).absolute()
    return parse_node(read_config(path),location=path)['id']


def pin_placement(value,node_id):
    """Resolve an explicit save's legacy local choice once, never on sync/read."""
    result=deepcopy(value)
    if result['placement']['mode']=='local':
        result['placement']=dict(mode='node',node_id=node_id,capabilities=[])
    return result


def is_local_executor(placement,node_id):
    return placement['mode']=='node' and placement['node_id']==node_id


def require_local_executor(placement,node_id,message):
    require(placement['mode']!='local',
            'Legacy local placement is ambiguous; explicitly assign a node before execution')
    require(is_local_executor(placement,node_id),message)
