# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Build a deterministic source distribution, never bundle local state or Qt binaries."""
import argparse
import gzip
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
import tarfile

if __package__:
    from .license_files import license_files
    from .release_version import read_version, validate_version
else:
    from license_files import license_files
    from release_version import read_version, validate_version

ROOT = Path(__file__).resolve().parents[1]
NAME = 'federated-workspace-poc'


def archive_prefix(version):
    return NAME + '-' + validate_version(version)


def sources(root):
    paths = [root / name for name in ('VERSION', 'CHANGELOG.md', 'run.sh', 'requirements.txt', 'LICENSE', 'README.md',
             'docs/project-opening.md', 'docs/lxc-web.md', 'docs/ollama-lan.md',
             'docs/searxng-search-acceptance.md',
             'docs/public-source-reader-acceptance.md',
             'docs/public-sources-research.md', 'docs/release-0.1.0.md',
             'docs/roadmap-visualization.md', 'docs/task-planning.md',
             'docs/project-chat-sync.md', 'docs/julia-runner.md')]
    paths.append(root / 'docs/roadmap-graph.json')
    paths.append(root / 'docs/ide-file-bridge.md')
    paths.extend(root / 'extensions/workspace-bridge' / name for name in
                 ('package.json', 'extension.js', 'bridge.js', 'README.md', 'LICENSE'))
    paths.extend(root / 'tests' / name for name in ('ide_bridge.test.js', 'ide_bridge_host.cjs'))
    for directory, pattern in [('spikes', '*.py'), ('scripts', '*.py'), ('tests', '*.py'), ('docs/adr', '*.md')]:
        paths.extend(sorted((root / directory).glob(pattern)))
    paths.extend(sorted((root / 'modules').glob('*.json')))
    paths.extend(root / name for name in ('spikes/libgit2/probe.cpp', 'spikes/libgit2/README.md'))
    # Include docs linked by README/ADRs, excluding the private local inventory.
    paths.extend(root / name for name in ('AGENTS.md', 'ARCHITECTURE.md', 'DATA_MODEL.md',
                 'FEDERATION.md', 'SECURITY.md', 'TODO.md', 'BACKLOG.md', 'WORK_LOG.md', 'REUSE_CATALOG.md', 'CONTRIBUTING.md'))
    paths.extend(root.glob('*Master Checklist*.md'))
    paths.extend(sorted((root / 'docs/IP').glob('*.md')))
    paths.extend(license_files(root))
    paths = sorted(set(paths))
    for path in paths:
        if not path.is_file() or path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError(f'Expected regular source file: {path.relative_to(root)}')
    return paths


def build(root, version=None):
    version = read_version(root) if version is None else validate_version(version)
    prefix = archive_prefix(version)
    files = [(str(p.relative_to(root)), p.read_bytes()) for p in sources(root)]
    files = [(name, (version + '\n').encode('ascii') if name == 'VERSION' else data)
             for name, data in files]
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in files}
    files.append(('MANIFEST.sha256.json', (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()))
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in files:
                info = tarfile.TarInfo(prefix + '/' + name)
                info.size = len(data)
                info.mode = 0o755 if name == 'run.sh' else 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
    return raw.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--version')
    args = parser.parse_args()
    version = read_version(ROOT) if args.version is None else validate_version(args.version)
    output = args.output or ROOT / 'dist' / (archive_prefix(version) + '.tar.gz')
    payload = build(ROOT, version)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Publish only a complete archive, without replacing an existing path/symlink.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix='.package-', delete=False) as target:
            temporary = Path(target.name)
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(output)
    print('SHA256 ' + hashlib.sha256(payload).hexdigest())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
