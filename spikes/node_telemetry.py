# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bounded read-only node telemetry and explicit Ollama runtime expectations."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import threading
import time

from spikes.metadata import require


MAX_SETTING = 16 * 1024
EXPECTED_PROCESSORS = {'unspecified', 'cpu', 'gpu'}


def observed_at():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def unknown(reason, *, source):
    return {'status': 'unknown', 'reason': reason, 'source': source}


def available(value, unit, *, source, total=None):
    result = {'status': 'available', 'value': round(value, 2), 'unit': unit,
              'source': source}
    if total is not None:
        result['total'] = round(total, 2)
    return result


def runtime_binding_revision_matches(configured_revision, candidate_revision):
    """Match an exact configured revision or its immutable per-run model derivative."""
    if candidate_revision == configured_revision:
        return True
    prefix = configured_revision + '.run-model-'
    suffix = candidate_revision.removeprefix(prefix)
    return (candidate_revision.startswith(prefix) and len(suffix) == 16
            and all(char in '0123456789abcdef' for char in suffix))


class OllamaRuntimePolicy:
    """Node-local expectation; changing it never changes an authorized target."""
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        self.path = self.root / 'ollama-runtime-policy.json'

    @staticmethod
    def _default(binding):
        return {'schema_version': 1, 'revision': 0,
                'binding_id': binding.binding_id,
                'binding_revision': binding.revision,
                'expected_processor': 'unspecified'}

    @staticmethod
    def _validate(value):
        required = {'schema_version', 'revision', 'binding_id', 'binding_revision',
                    'expected_processor'}
        require(isinstance(value, dict) and set(value) == required,
                'Unknown or missing Ollama runtime policy field')
        require(value['schema_version'] == 1
                and type(value['revision']) is int and value['revision'] >= 1
                and isinstance(value['binding_id'], str) and value['binding_id']
                and isinstance(value['binding_revision'], str) and value['binding_revision']
                and value['expected_processor'] in EXPECTED_PROCESSORS,
                'Invalid Ollama runtime policy')
        return value

    def load(self, binding):
        try:
            flags = os.O_RDONLY | os.O_NOFOLLOW
            fd = os.open(self.path, flags)
        except FileNotFoundError:
            return self._default(binding)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe Ollama runtime policy')
            raw = os.read(fd, MAX_SETTING + 1)
        finally:
            os.close(fd)
        require(len(raw) <= MAX_SETTING, 'Ollama runtime policy exceeds 16 KiB')
        try:
            value = self._validate(json.loads(raw))
        except (UnicodeError, ValueError) as exc:
            raise ValueError('Invalid Ollama runtime policy JSON') from exc
        same_binding = value['binding_id'] == binding.binding_id
        if not (same_binding and runtime_binding_revision_matches(
                value['binding_revision'], binding.revision)):
            return self._default(binding)
        return value

    def save(self, binding, expected_processor):
        require(expected_processor in EXPECTED_PROCESSORS,
                'Invalid expected Ollama processor')
        current = self.load(binding)
        value = {'schema_version': 1, 'revision': current['revision'] + 1,
                 'binding_id': binding.binding_id,
                 'binding_revision': binding.revision,
                 'expected_processor': expected_processor}
        raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
        temporary = self.root / ('.ollama-runtime-policy-' + hashlib.sha256(
            raw + os.urandom(32)).hexdigest() + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.close(fd); fd = -1
            os.replace(temporary, self.path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if fd >= 0:
                os.close(fd)
            if temporary.exists():
                temporary.unlink()
        return value


class NodeTelemetry:
    """Ephemeral Linux metrics; no sample is persisted or treated as run evidence."""
    def __init__(self, filesystem_path, *, clock=time.monotonic,
                 proc_root='/proc', runner=subprocess.run):
        self.filesystem_path = Path(filesystem_path).absolute()
        self.clock = clock
        self.proc_root = Path(proc_root)
        self.runner = runner
        self._previous_cpu = None
        self._previous_network = None
        self._lock = threading.Lock()

    @staticmethod
    def _read_numbers(path, prefix):
        for line in path.read_text().splitlines():
            if line.startswith(prefix):
                return [int(value) for value in line.split()[1:]]
        raise ValueError('metric is unavailable')

    def _cpu(self):
        try:
            values = self._read_numbers(self.proc_root / 'stat', 'cpu ')
            require(len(values) >= 4 and all(value >= 0 for value in values),
                    'Invalid procfs CPU counters')
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values); current = (idle, total)
            previous, self._previous_cpu = self._previous_cpu, current
            if previous is None:
                return unknown('awaiting-second-sample', source='procfs:/proc/stat')
            idle_delta, total_delta = idle - previous[0], total - previous[1]
            if total_delta <= 0 or idle_delta < 0:
                return unknown('counter-reset', source='procfs:/proc/stat')
            return available(100 * (1 - idle_delta / total_delta), 'percent',
                             source='procfs:/proc/stat')
        except (OSError, ValueError):
            return unknown('unavailable', source='procfs:/proc/stat')

    def _memory(self):
        try:
            fields = {}
            for line in (self.proc_root / 'meminfo').read_text().splitlines():
                name, separator, rest = line.partition(':')
                if separator and name in {'MemTotal', 'MemAvailable'}:
                    fields[name] = int(rest.strip().split()[0]) * 1024
            total, free = fields['MemTotal'], fields['MemAvailable']
            require(total > 0 and 0 <= free <= total, 'Invalid procfs memory counters')
            return available(100 * (total - free) / total, 'percent',
                             total=total, source='procfs:/proc/meminfo')
        except (KeyError, OSError, ValueError):
            return unknown('unavailable', source='procfs:/proc/meminfo')

    def _disk(self):
        try:
            value = os.statvfs(self.filesystem_path)
            total = value.f_blocks * value.f_frsize
            available_bytes = value.f_bavail * value.f_frsize
            require(total > 0 and 0 <= available_bytes <= total,
                    'Invalid filesystem counters')
            return available(100 * (total - available_bytes) / total, 'percent',
                             total=total, source='statvfs:workspace-state')
        except (OSError, ValueError):
            return unknown('unavailable', source='statvfs:workspace-state')

    def _network(self, sampled):
        try:
            received = transmitted = 0
            for line in (self.proc_root / 'net/dev').read_text().splitlines()[2:]:
                interface, separator, counters = line.partition(':')
                if not separator or interface.strip() == 'lo':
                    continue
                values = counters.split()
                require(len(values) >= 9, 'Invalid procfs network counters')
                received += int(values[0]); transmitted += int(values[8])
            current = (sampled, received, transmitted)
            previous, self._previous_network = self._previous_network, current
            if previous is None:
                return unknown('awaiting-second-sample', source='procfs:/proc/net/dev')
            elapsed = sampled - previous[0]
            delta = received - previous[1] + transmitted - previous[2]
            if elapsed <= 0 or delta < 0:
                return unknown('counter-reset', source='procfs:/proc/net/dev')
            return available(delta / elapsed, 'bytes-per-second',
                             source='procfs:/proc/net/dev')
        except (OSError, ValueError):
            return unknown('unavailable', source='procfs:/proc/net/dev')

    def _gpu(self):
        source = 'nvidia-smi'
        try:
            result = self.runner([
                'nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total',
                '--format=csv,noheader,nounits'], capture_output=True, text=True,
                timeout=2, check=True)
            rows = []
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                values = [float(value.strip()) for value in line.split(',')]
                require(len(values) == 3 and 0 <= values[0] <= 100
                        and 0 <= values[1] <= values[2] and values[2] > 0,
                        'Invalid NVIDIA telemetry')
                rows.append(values)
            require(rows and len(rows) <= 64, 'No bounded NVIDIA telemetry')
            used, total = sum(row[1] for row in rows), sum(row[2] for row in rows)
            return (available(max(row[0] for row in rows), 'percent', source=source),
                    available(100 * used / total, 'percent', total=total * 1024 * 1024,
                              source=source))
        except (OSError, ValueError, subprocess.SubprocessError):
            return (unknown('unavailable', source=source),
                    unknown('unavailable', source=source))

    def snapshot(self):
        with self._lock:
            sampled = self.clock()
            gpu, vram = self._gpu()
            return {'schema_version': 1, 'scope': 'workspace-node',
                    'observed_at': observed_at(),
                    'metrics': {'cpu': self._cpu(), 'gpu': gpu,
                                'ram': self._memory(), 'vram': vram,
                                'disk': self._disk(), 'net': self._network(sampled)}}
