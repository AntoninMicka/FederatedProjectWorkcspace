"""Build an installable desktop PoC using system runtime dependencies."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'federated-workspace-poc'


def build(output, version='0.1.0~m0'):
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+~]*', version):
        raise ValueError('Invalid package version')
    output = Path(output).absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.deb-', dir=output.parent) as tmp:
        stage = Path(tmp) / 'root'
        def write(name, data, mode=0o644):
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(mode)
        for source in sorted((ROOT / 'spikes').glob('*.py')):
            if source.is_symlink() or not source.is_file():
                raise ValueError('Expected regular source')
            write(f'usr/lib/{NAME}/spikes/{source.name}', source.read_bytes())
        write(f'usr/share/doc/{NAME}/copyright', (ROOT / 'LICENSE').read_bytes())
        write(f'usr/share/doc/{NAME}/README', b'Desktop PoC: in-memory counter only. Close before upgrading.\nRuntime dependencies are supplied by the OS, not bundled.\n')
        write(f'usr/bin/{NAME}', b'#!/bin/sh\nset -eu\ncd -- "$(dirname -- "$(readlink -f -- "$0")")/../lib/federated-workspace-poc"\nexec /usr/bin/python3 -I -c \'import sys; sys.path.insert(0, "."); from spikes.desktop import main; raise SystemExit(main())\' "$@"\n', 0o755)
        write(f'usr/share/applications/{NAME}.desktop', f'[Desktop Entry]\nType=Application\nName=Projektový workspace PoC\nExec={NAME}\nTerminal=false\nCategories=Office;\n'.encode())
        write('DEBIAN/control', f'Package: {NAME}\nVersion: {version}\nArchitecture: all\nMaintainer: Workspace developers <noreply@example.invalid>\nDepends: python3 (>= 3.11), python3-pyside6.qtwebenginewidgets, python3-yaml (>= 6.0.3), python3-yaml (<< 6.0.4), git, coreutils\nSection: utils\nPriority: optional\nDescription: Experimental project workspace desktop\n Local in-memory UI/backend connectivity demonstration.\n'.encode())
        for directory in stage.rglob('*'):
            if directory.is_dir():
                directory.chmod(0o755)
        stage.chmod(0o755)
        candidate = Path(tmp) / 'candidate.deb'
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(stage), str(candidate)], check=True)
        with candidate.open('rb') as stream:
            os.fsync(stream.fileno())
        os.link(candidate, output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / (NAME + '.deb'))
    parser.add_argument('--version', default='0.1.0~m0')
    args = parser.parse_args()
    print(build(args.output, args.version))


if __name__ == '__main__':
    main()
