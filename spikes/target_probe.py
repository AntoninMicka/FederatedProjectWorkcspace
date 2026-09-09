"""Manual Linux storage measurements and process-crash recovery on a chosen filesystem."""
from contextlib import closing
import argparse
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

from spikes.journal import snapshot
from spikes.storage import Git
from spikes.workspace import PendingOperation, Workspace

ENTITY = '11111111-1111-4111-8111-111111111111'
STAGES = ('prepared', 'file:0', 'file:1', 'applied', 'files-applied', 'commit-created',
          'commit-ready', 'ref-updated', 'committed', 'git-indexed', 'indexed', 'completed')


def changes():
    metadata = dict(schema_version=1, id=ENTITY, title='Target probe', kind='source',
                    created_at='2026-09-09T12:00:00Z', author_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                    privacy='project', provenance='external', file='source.pdf')
    return {f'artifacts/{ENTITY}/source.pdf': b'%PDF-1.7\x00\xff\r\n',
            f'artifacts/{ENTITY}/metadata.json': json.dumps(metadata).encode()}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def filesystem(path):
    """Find the most specific mount in the current Linux namespace."""
    found = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, right = line.split(' - ', 1)
        fields = left.split()
        mount = fields[4]
        for code, value in [('040', ' '), ('011', '\t'), ('012', '\n'), ('134', '\\')]:
            mount = mount.replace('\\' + code, value)
        mount = Path(mount)
        if path == mount or mount in path.parents:
            found.append((len(mount.parts), right.split()[0]))
    require(bool(found), 'Cannot identify target mount')
    return max(found)[1]


def worker():
    base, stage = Path(sys.argv[1]), sys.argv[2]
    root = base / 'project'
    root.mkdir()
    git = Git(root)
    git.run('init', '--initial-branch=main')
    git.run('commit', '--allow-empty', '-m', 'Initialize disposable probe')
    workspace = Workspace(root, base / 'state')
    require(root.stat().st_dev == workspace.journal.state.stat().st_dev, 'Different filesystems')
    def checkpoint(current):
        if current == stage:
            os._exit(73)
    start = time.monotonic()
    workspace.apply(changes(), author_name='Target Probe', author_email='probe@example.invalid',
                    message='Import probe artifact', checkpoint=checkpoint)
    print(json.dumps({'apply_s': time.monotonic() - start,
                      'python_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))


def verify(base):
    root, state = base / 'project', base / 'state'
    workspace = Workspace(root, state)
    with closing(sqlite3.connect(workspace.journal.database)) as db:
        row = db.execute('SELECT record FROM operations WHERE done=0').fetchone()
    pending = json.loads(row[0]) if row else None
    if pending:
        try:
            workspace.read()
        except PendingOperation:
            pass
        else:
            raise RuntimeError('Pending operation exposed readable data')
    start = time.monotonic()
    receipt = workspace.recover()
    recovery_s = time.monotonic() - start
    commit = workspace.git.head()
    if pending and pending['commit_id']:
        require(commit == pending['commit_id'], 'Recovery replaced stored candidate')
    if receipt:
        require(workspace.receipt(receipt['operation_id']) == receipt, 'Missing receipt')
    require(workspace.recover() is None, 'Repeated recovery was not a no-op')
    require(workspace.git.head() == commit, 'Repeated recovery changed HEAD')
    require(workspace.git.run('rev-list', '--count', 'HEAD').stdout.strip() == '2', 'Duplicate or missing commit')
    require(workspace.git.snapshot(commit) == changes(), 'Committed bytes differ')
    require(snapshot(root) == changes(), 'Working files differ')
    require(workspace.read() == [(ENTITY, 'Target probe')], 'Index differs')
    workspace.index.path.unlink()
    require(Workspace(root, state).read() == [(ENTITY, 'Target probe')], 'Index rebuild failed')
    require(workspace.git.run('status', '--porcelain').stdout == '', 'Dirty repository after recovery')
    return recovery_s


def run(base, expected_fstype='btrfs'):
    base = Path(base).resolve(strict=True)
    require(base.is_dir(), 'Base must be an existing directory')
    actual = filesystem(base)
    require(actual == expected_fstype, f'Expected {expected_fstype}, found {actual}; no probe created')
    directory = Path(tempfile.mkdtemp(prefix='workspace-probe-', dir=base))
    print(json.dumps({'probe_dir': str(directory), 'filesystem': actual, 'machine': platform.machine(),
                      'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
                      'git': subprocess.check_output(['git', '--version'], text=True).strip()}), flush=True)
    # ADR 0003 boundaries, adapted from tests/test_workspace.py. Retain on any failure.
    try:
        for number, stage in enumerate(('normal',) * 3 + STAGES):
            case = directory / str(number)
            case.mkdir()
            start = time.monotonic()
            result = subprocess.run([sys.executable, '-c',
                                     'from spikes.target_probe import worker; worker()', str(case), stage],
                                    capture_output=True, text=True, timeout=120)
            elapsed = time.monotonic() - start
            require(result.returncode == (0 if stage == 'normal' else 73),
                    f'Worker {stage}: exit {result.returncode}: {result.stderr}')
            recovery_s = verify(case)
            record = dict(stage=stage, process_s=round(elapsed, 4), recovery_s=round(recovery_s, 4), verified=True)
            if stage == 'normal':
                record.update(json.loads(result.stdout))
            print(json.dumps(record), flush=True)
    except BaseException:
        print(f'FAILED: diagnostic data retained at {directory}', file=sys.stderr, flush=True)
        raise
    shutil.rmtree(directory)
    print('target probe: PASS; 3 measured runs, 12 crash boundaries; temporary data removed', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True, help='Existing directory on target SSD')
    parser.add_argument('--expected-fstype', default='btrfs', help='Expected Linux filesystem type (default btrfs)')
    args = parser.parse_args()
    run(args.base, args.expected_fstype)


if __name__ == '__main__':
    main()
