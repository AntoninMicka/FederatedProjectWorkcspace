# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Disposable demonstration of the existing coordinated storage PoC."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import uuid

import yaml

from spikes.storage import Git
from spikes.workspace import Workspace


def main():
    print('Storage PoC — dočasné demo bez UI, LLM a federace.', flush=True)
    # Existing lifecycle and crash boundaries: ADR 0003. All writes stay in this
    # disposable directory; this is not an initializer for user repositories.
    with tempfile.TemporaryDirectory(prefix='workspace-demo-') as directory:
        base = Path(directory)
        root, state = base / 'project', base / 'state'
        root.mkdir()
        git = Git(root)
        git.run('init', '--initial-branch=main')
        git.run('commit', '--allow-empty', '-m', 'Initialize disposable demo')
        entity = str(uuid.uuid4())
        metadata = dict(schema_version=1, id=entity, title='První demo artefakt',
                        kind='document', created_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                        author_id=str(uuid.uuid4()), privacy='project', provenance='user')
        content = ('---\n' + yaml.safe_dump(metadata, allow_unicode=True)
                   + '---\nTento dokument byl uložen přes Workspace.\n').encode('utf-8')
        path = f'artifacts/{entity}/document.md'
        print(f'1. Dočasný projekt: {root}', flush=True)
        workspace = Workspace(root, state)
        receipt = workspace.apply({path: content}, author_name='Workspace Demo',
                                  author_email='demo@example.invalid', message='Add demo artifact')
        print(f'2. Artefakt: {path}')
        print(f'3. Git commit: {receipt["commit_id"]}')
        reopened = Workspace(root, state)
        if reopened.recover() is not None:
            raise RuntimeError('Unexpected unfinished demo operation')
        print(f'4. Index po znovuotevření: {reopened.read()}')
        print('5. Historie:')
        print(git.run('log', '--oneline', '-2').stdout, end='')
    print('Demo dokončeno; dočasný projekt a stav byly odstraněny.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
