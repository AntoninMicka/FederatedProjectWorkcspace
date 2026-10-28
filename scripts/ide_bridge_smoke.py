# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit real-IDE smoke, isolated profile and extension installation only."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4

from spikes.artifacts import Artifacts, main_todo_id
from spikes.desktop_ui import DesktopHandler
from spikes.ide_bridge import IdeBridge
from spikes.local_api import running_api
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--editor', choices=['code', 'codium'], default='codium')
    args = parser.parse_args()
    checkout = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='workspace-ide-smoke-') as temporary:
        root = Path(temporary); node = root / 'node.json'; repo = root / 'project'
        project = ProjectCreation(node).create('IDE smoke', str(repo), str(uuid4()))['id']
        head = Projects(node).open(project)['commit_id']
        head = Artifacts(node).save(dict(project_id=project, artifact_id=main_todo_id(project),
            base_head=head, title='Tasks', body='- [ ] [TASK-01] Smoke test\n', new=True), str(uuid4()))['commit_id']
        with running_api('http', handler=DesktopHandler, projects=Projects(node)) as server:
            service = IdeBridge(node)
            result = service.create(dict(project_id=project, expected_head=head,
                repository=str(repo), instructions='Smoke'), None, server.origin)
            package = root / result['filename']; package.write_bytes(base64.b64decode(result['package_base64']))
            common = ['--user-data-dir', str(root / 'profile'), '--extensions-dir', str(root / 'extensions')]
            installed = subprocess.run([args.editor, *common, '--install-extension', str(package), '--force'],
                                      capture_output=True, text=True, timeout=60)
            if installed.returncode:
                raise RuntimeError(installed.stdout + installed.stderr)
            extension = next((root / 'extensions').glob('federated-workspace.workspace-file-bridge-*'))
            fixture = root / 'fixture.json'; output = root / 'result.json'
            fixture.write_text(json.dumps(dict(pairing=result['pairing'], repository=str(repo),
                                               mailbox=str(root / 'mailbox'), result=str(output))))
            fixture.chmod(0o600)
            env = dict(os.environ, WORKSPACE_BRIDGE_SMOKE=str(fixture))
            process = subprocess.run([args.editor, *common, '--disable-workspace-trust',
                '--skip-welcome', '--skip-release-notes', '--no-sandbox', '--wait',
                '--extensionDevelopmentPath=' + str(extension),
                '--extensionTestsPath=' + str(checkout / 'tests/ide_bridge_host.cjs'), str(repo)],
                env=env, capture_output=True, text=True, timeout=90)
            if process.returncode or not output.exists():
                raise RuntimeError(process.stdout[-6000:] + process.stderr[-6000:])
            evidence = json.loads(output.read_text())
            assert evidence['active'] and evidence['receipt']['status'] == 'received'
            assert Projects(node).open(project)['commit_id'] == head
            assert len(service.status(project)['sessions'][0]['messages']) == 1
            print('VSIX installed; extension host active; ordinary files and receipt/retry verified; project Git unchanged.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
