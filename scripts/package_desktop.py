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

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'federated-workspace-poc'


def sources(root):
    paths = [root / name for name in ('run.sh', 'requirements.txt', 'LICENSE', 'README.md', 'docs/project-opening.md')]
    for directory, pattern in [('spikes', '*.py'), ('scripts', '*.py'), ('tests', '*.py'), ('docs/adr', '*.md')]:
        paths.extend(sorted((root / directory).glob(pattern)))
    paths.extend(root / name for name in ('spikes/libgit2/probe.cpp', 'spikes/libgit2/README.md'))
    # Include docs linked by README/ADRs, excluding the private local inventory.
    paths.extend(root / name for name in ('AGENTS.md', 'ARCHITECTURE.md', 'DATA_MODEL.md',
                 'FEDERATION.md', 'SECURITY.md', 'TODO.md', 'REUSE_CATALOG.md', 'CONTRIBUTING.md'))
    paths.extend(root.glob('*Master Checklist*.md'))
    paths.extend(sorted((root / 'docs/IP').glob('*.md')))
    paths = sorted(set(paths))
    for path in paths:
        if not path.is_file() or path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError(f'Expected regular source file: {path.relative_to(root)}')
    return paths


def build(root):
    files = [(str(p.relative_to(root)), p.read_bytes()) for p in sources(root)]
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in files}
    files.append(('MANIFEST.sha256.json', (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()))
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in files:
                info = tarfile.TarInfo(PREFIX + '/' + name)
                info.size = len(data)
                info.mode = 0o755 if name == 'run.sh' else 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
    return raw.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / (PREFIX + '.tar.gz'))
    args = parser.parse_args()
    payload = build(ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Publish only a complete archive, without replacing an existing path/symlink.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=args.output.parent, prefix='.package-', delete=False) as target:
            temporary = Path(target.name)
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.link(temporary, args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(args.output)
    print('SHA256 ' + hashlib.sha256(payload).hexdigest())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
