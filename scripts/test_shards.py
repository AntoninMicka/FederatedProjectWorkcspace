# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Run one deterministic, complete shard of the top-level unittest modules."""
import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / 'tests'
DEFAULT_SHARDS = 4


def discover_modules(tests_dir=TESTS):
    tests_dir = Path(tests_dir)
    if not tests_dir.is_dir() or not (tests_dir / '__init__.py').is_file():
        raise ValueError('Test package is unavailable')
    modules = []
    for path in sorted(tests_dir.glob('test_*.py')):
        if not path.is_file() or path.is_symlink():
            raise ValueError('Test module must be a regular file')
        modules.append(('tests.' + path.stem, path.stat().st_size))
    if not modules:
        raise ValueError('No test modules discovered')
    return modules


def partition_modules(modules, shard_count):
    if type(shard_count) is not int or not 1 <= shard_count <= 32:
        raise ValueError('Shard count must be between 1 and 32')
    normalized = []
    seen = set()
    for module, weight in modules:
        if (not isinstance(module, str) or not module.startswith('tests.test_')
                or module in seen or type(weight) is not int or weight < 1):
            raise ValueError('Invalid test module inventory')
        seen.add(module)
        normalized.append((module, weight))
    if not normalized:
        raise ValueError('No test modules to partition')

    # Largest-processing-time scheduling with source bytes as a stable local
    # cost proxy. It is deterministic and includes new test modules without a
    # hand-maintained allowlist; CI jobs still run in isolated checkouts.
    shards = [{'weight': 0, 'modules': []} for _ in range(shard_count)]
    for module, weight in sorted(normalized, key=lambda item: (-item[1], item[0])):
        index = min(range(shard_count),
                    key=lambda candidate: (shards[candidate]['weight'], candidate))
        shards[index]['modules'].append(module)
        shards[index]['weight'] += weight
    for shard in shards:
        shard['modules'].sort()
    return shards


def selected_modules(shard_number, shard_count, tests_dir=TESTS):
    if type(shard_number) is not int or not 1 <= shard_number <= shard_count:
        raise ValueError('Shard number must be between 1 and shard count')
    return partition_modules(discover_modules(tests_dir), shard_count)[
        shard_number - 1]


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--shard', type=int, required=True,
                        help='one-based shard number')
    result.add_argument('--shards', type=int, default=DEFAULT_SHARDS,
                        help='total shard count (default: 4)')
    result.add_argument('--list', action='store_true',
                        help='print selected modules without running them')
    return result


def main(argv=None):
    arguments = parser().parse_args(argv)
    try:
        shard = selected_modules(arguments.shard, arguments.shards)
    except ValueError as exc:
        parser().error(str(exc))
    modules = shard['modules']
    print('test shard {}/{}: {} modules, {} source bytes'.format(
        arguments.shard, arguments.shards, len(modules), shard['weight']),
        file=sys.stderr, flush=True)
    if arguments.list:
        print('\n'.join(modules))
        return 0
    completed = subprocess.run(
        [sys.executable, '-m', 'unittest', '-v', *modules], cwd=ROOT)
    return completed.returncode


if __name__ == '__main__':
    raise SystemExit(main())
