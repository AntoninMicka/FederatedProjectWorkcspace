# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Background content receive jobs and their heartbeat stream (AUDIT-B7-T1)."""
import io
import json
import threading
import unittest
from unittest.mock import patch

from spikes import content_receive_jobs as jobs
from spikes.federation_sync import SyncBusy, SyncCancelled, SyncConflict
from spikes.git_budget import GitDeadlineExceeded
from spikes.request_ownership import ProjectBusy

OPERATION = '6f1f4c1e-8f43-4d55-9d27-0a5d8c2b1e01'
OTHER = '0b6f8a7e-2a59-4a0b-8f1c-4b8d4f5d2c11'


class Gate:
    """A receive target that blocks until released."""
    def __init__(self, result=b'response-body', error=None):
        self.entered, self.release = threading.Event(), threading.Event()
        self.result, self.error, self.calls = result, error, 0

    def __call__(self):
        self.calls += 1
        self.entered.set()
        assert self.release.wait(10)
        if self.error is not None:
            raise self.error
        return self.result


class ReceiveJobsTests(unittest.TestCase):
    def setUp(self):
        self.jobs = jobs.ReceiveJobs()
        self.addCleanup(self.jobs.drain, 5)

    def test_same_request_attaches_to_the_running_job(self):
        gate = Gate()
        first = self.jobs.start_or_attach('/node', OPERATION, b'body', gate)
        self.assertTrue(gate.entered.wait(5))
        second = self.jobs.start_or_attach('/node', OPERATION, b'body', Gate())
        self.assertIs(first, second)
        gate.release.set()
        self.assertTrue(first.done.wait(5))
        self.assertEqual(first.result, b'response-body')
        # A finished result is handed to a reattaching sender, not recomputed.
        self.assertIs(self.jobs.start_or_attach('/node', OPERATION, b'body', Gate()), first)
        self.assertEqual(gate.calls, 1)

    def test_same_operation_with_other_bytes_is_rejected(self):
        gate = Gate()
        self.jobs.start_or_attach('/node', OPERATION, b'body', gate)
        with self.assertRaisesRegex(ValueError, 'another request'):
            self.jobs.start_or_attach('/node', OPERATION, b'tampered', Gate())
        gate.release.set()

    def test_another_operation_on_the_same_node_is_busy(self):
        gate = Gate()
        self.jobs.start_or_attach('/node', OPERATION, b'body', gate)
        self.assertTrue(gate.entered.wait(5))
        with self.assertRaises(SyncBusy) as caught:
            self.jobs.start_or_attach('/node', OTHER, b'body', Gate())
        self.assertEqual(caught.exception.busy_resource, 'incoming-capacity')
        # Another node in the same process is independent.
        other = Gate(); other.release.set()
        self.assertTrue(self.jobs.start_or_attach('/second', OTHER, b'body', other).done.wait(5))
        gate.release.set()

    def test_failed_job_is_run_again_on_retry(self):
        failing = Gate(error=SyncBusy('private-payload', resource='sync-journal'))
        failing.release.set()
        job = self.jobs.start_or_attach('/node', OPERATION, b'body', failing)
        self.assertTrue(job.done.wait(5))
        self.assertEqual(job.error['status'], 503)
        self.assertEqual(job.error['busy_resource'], 'sync-journal')
        self.assertNotIn('private-payload', json.dumps(job.error))
        retry = Gate(); retry.release.set()
        again = self.jobs.start_or_attach('/node', OPERATION, b'body', retry)
        self.assertIsNot(again, job)
        self.assertTrue(again.done.wait(5))
        self.assertEqual((again.result, retry.calls), (b'response-body', 1))

    def test_finished_results_expire(self):
        gate = Gate(); gate.release.set()
        job = self.jobs.start_or_attach('/node', OPERATION, b'body', gate)
        self.assertTrue(job.done.wait(5))
        job.finished_at -= jobs.FINISHED_TTL + 1
        fresh = Gate(); fresh.release.set()
        self.assertIsNot(self.jobs.start_or_attach('/node', OPERATION, b'body', fresh), job)

    def test_drain_reports_an_unfinished_job(self):
        gate = Gate()
        self.jobs.start_or_attach('/node', OPERATION, b'body', gate)
        self.assertTrue(gate.entered.wait(5))
        self.assertFalse(self.jobs.drain(0.05))
        gate.release.set()
        self.assertTrue(self.jobs.drain(5))

    def test_error_frames_are_typed_and_never_carry_exception_text(self):
        cases = ((SyncBusy('secret', resource='message-pools'), 503, 'message-pools'),
                 (ProjectBusy('secret', resource='project-index'), 503, 'project-index'),
                 (GitDeadlineExceeded('secret'), 503, 'git-budget'),
                 (SyncConflict('secret'), 409, None),
                 (ValueError('secret'), 422, None),
                 (RuntimeError('secret'), 422, None))
        for exc, status, resource in cases:
            with self.subTest(exc=type(exc).__name__):
                value = jobs.error_frame(exc)
                self.assertEqual(value['status'], status)
                self.assertEqual(value.get('busy_resource'), resource)
                self.assertNotIn('secret', json.dumps(value))


class StreamTests(unittest.TestCase):
    def run_stream(self, job, **kwargs):
        out = io.BytesIO()
        jobs.stream(job, out.write, **kwargs)
        return out.getvalue()

    def test_stream_sends_heartbeats_until_the_result(self):
        registry = jobs.ReceiveJobs()
        gate = Gate(result=b'\x00\x00\x00\x02{}payload')
        job = registry.start_or_attach('/node', OPERATION, b'body', gate,
                                       phase_source=lambda: 'receive-publication-git')
        timer = threading.Timer(.25, gate.release.set); timer.start()
        raw = self.run_stream(job, interval=.05)
        timer.join()
        source = io.BytesIO(raw)
        beats = []
        kind, body = jobs.read_frames(source.readline, source.read, on_heartbeat=beats.append)
        self.assertEqual((kind, body), ('result', gate.result))
        self.assertGreaterEqual(len(beats), 3)
        self.assertEqual({beat['peer_phase'] for beat in beats}, {'receive-publication-git'})

    def test_unknown_phase_is_not_forwarded(self):
        registry = jobs.ReceiveJobs()
        gate = Gate(); gate.release.set()
        job = registry.start_or_attach('/node', OPERATION, b'body', gate,
                                       phase_source=lambda: '/secret/path')
        self.assertTrue(job.done.wait(5))
        self.assertIsNone(job.heartbeat()['peer_phase'])

    def test_lost_sender_does_not_stop_the_job(self):
        registry = jobs.ReceiveJobs()
        gate = Gate()
        job = registry.start_or_attach('/node', OPERATION, b'body', gate)
        def broken(raw):
            raise BrokenPipeError('sender gone')
        with self.assertRaises(OSError):
            jobs.stream(job, broken, interval=.01)
        self.assertFalse(job.done.is_set())
        gate.release.set()
        self.assertTrue(job.done.wait(5))
        self.assertEqual(job.result, b'response-body')

    def test_reader_handles_errors_truncation_and_cancellation(self):
        error = jobs.frame({'type': 'error', 'status': 503, 'busy_resource': 'sqlite'})
        source = io.BytesIO(jobs.frame({'type': 'heartbeat', 'peer_phase': None}) + error)
        self.assertEqual(jobs.read_frames(source.readline, source.read)[0], 'error')
        for raw in (b'', b'{"type":"heart', jobs.frame({'type': 'result', 'length': 99}) + b'short'):
            with self.subTest(raw=raw), self.assertRaises(TimeoutError):
                source = io.BytesIO(raw)
                jobs.read_frames(source.readline, source.read)
        for raw in (b'[1]\n', jobs.frame({'type': 'error', 'status': 200}),
                    jobs.frame({'type': 'result', 'length': -1}), b'x' * (jobs.MAX_FRAME + 2)):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                source = io.BytesIO(raw)
                jobs.read_frames(source.readline, source.read)
        source = io.BytesIO(jobs.frame({'type': 'heartbeat', 'peer_phase': None}) * 3)
        with self.assertRaises(SyncCancelled):
            jobs.read_frames(source.readline, source.read, cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
