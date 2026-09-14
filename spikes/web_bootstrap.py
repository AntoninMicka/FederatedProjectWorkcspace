# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Initialize private viewer identity and access key without replacing existing state."""
import argparse
import json
import os
from pathlib import Path
import secrets
import tempfile
import uuid

from spikes.configuration import parse_node, read_config
from spikes.local_api import private_directory
from spikes.web_server import secret


def initialize(root):
    root = private_directory(root)
    values = {'access-key': secrets.token_urlsafe(32) + '\n',
              'node.json': json.dumps({'schema_version': 1, 'id': str(uuid.uuid4()),
                                      'name': 'LXC workspace', 'projects': []}) + '\n'}
    for name, value in values.items():
        target = root / name
        if os.path.lexists(target):
            continue
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=root, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(value.encode()); handle.flush(); os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass  # Concurrent initializer won; validate its result below.
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    fd = os.open(root, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    secret(root / 'access-key')
    parse_node(read_config(root / 'node.json'), location=root / 'node.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    initialize(parser.parse_args().directory)


if __name__ == '__main__':
    main()
