# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit real-IDE smoke, isolated profile and extension installation only."""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile
from uuid import uuid4

from spikes.artifacts import Artifacts, main_todo_id
from spikes.desktop_ui import DesktopHandler
from spikes.ide_bridge import IdeBridge, desktop_bridge
from spikes.local_api import running_api
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--editor', choices=['code', 'codium'], default='codium')
    parser.add_argument('--editor-path', help='explicit portable IDE CLI for the isolated smoke')
    parser.add_argument('--update', action='store_true', help='also install a newer VSIX through the live extension host')
    args = parser.parse_args()
    editor = args.editor_path or args.editor
    checkout = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='workspace-ide-smoke-') as temporary:
        root = Path(temporary); node = root / 'node.json'; repo = root / 'project'
        project = ProjectCreation(node).create('IDE smoke', str(repo), str(uuid4()))['id']
        head = Projects(node).open(project)['commit_id']
        head = Artifacts(node).save(dict(project_id=project, artifact_id=main_todo_id(project),
            base_head=head, title='Tasks', body='- [ ] [TASK-01] Smoke test\n', new=True), str(uuid4()))['commit_id']
        service = IdeBridge(node)
        with running_api('http', handler=DesktopHandler, projects=Projects(node)) as old_server:
            result = service.connection_create({'name': 'Smoke IDE'}, None, old_server.origin)
        discovery_home = root / 'home'
        discovery_root = discovery_home / '.local/state/federated-workspace/ide-discovery'
        with running_api('http', handler=DesktopHandler, projects=Projects(node)) as server, desktop_bridge(
                node, server, discovery_root=discovery_root):
            assert server.origin != result['pairing']['endpoint']
            raw = base64.b64decode(result['package_base64'])
            if args.update:
                # Older fixture version with the same updater; no source or real profile changes.
                output_zip = io.BytesIO()
                with zipfile.ZipFile(io.BytesIO(raw)) as original, zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as target:
                    for name in original.namelist():
                        data = original.read(name)
                        if name == 'extension/package.json':
                            manifest = json.loads(data); manifest['version'] = '0.4.0'
                            data = json.dumps(manifest).encode()
                        elif name == 'extension.vsixmanifest':
                            data = data.replace(b'Version="0.4.3"', b'Version="0.4.0"')
                        target.writestr(name, data)
                raw = output_zip.getvalue()
            package = root / result['filename']; package.write_bytes(raw)
            common = ['--user-data-dir', str(root / 'profile'), '--extensions-dir', str(root / 'extensions')]
            installed = subprocess.run([editor, *common, '--install-extension', str(package), '--force'],
                                      capture_output=True, text=True, timeout=60)
            if installed.returncode:
                raise RuntimeError(installed.stdout + installed.stderr)
            extension = next((root / 'extensions').glob('federated-workspace.workspace-file-bridge-*'))
            fixture = root / 'fixture.json'; output = root / 'result.json'
            fixture.write_text(json.dumps(dict(pairing=result['pairing'], repository=str(repo),
                                               mailbox=str(root / 'mailbox'), result=str(output), project_id=project, head=head,
                                               discovery_home=str(discovery_home), update=args.update,
                                               extensions=str(root / 'extensions'))))
            fixture.chmod(0o600)
            env = dict(os.environ, WORKSPACE_BRIDGE_SMOKE=str(fixture))
            process = subprocess.run([editor, *common, '--disable-workspace-trust',
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
            if args.update:
                entries = json.loads((root / 'extensions' / 'extensions.json').read_text())
                assert any(item['identifier']['id'] == 'federated-workspace.workspace-file-bridge'
                           and item['version'] == '0.4.3' for item in entries)
                assert evidence['updated']
                print('Updater installed 0.4.0 -> 0.4.3 through the real IDE command in an isolated profile; reload deferred; bridge sync still works.')
            print('VSIX installed; desktop restarted on different port without pairing; Workspace connection and project mapping verified; extension host active; ordinary files and receipt/retry verified; project Git unchanged.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
