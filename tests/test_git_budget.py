# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import subprocess
import threading
import unittest
from unittest.mock import patch

from spikes.git_budget import GitDeadlineExceeded, effective_deadline, git_budget
from spikes.storage import Git


class GitBudgetTests(unittest.TestCase):
    def test_existing_and_new_git_wrappers_share_nested_remaining_budget(self):
        old = Git('/unused')
        clock = [100.0]
        with patch('spikes.git_budget.time.monotonic', side_effect=lambda: clock[0]), \
             patch('spikes.storage.subprocess.run') as run:
            with git_budget(10):
                old.run('first')
                self.assertEqual(run.call_args.kwargs['timeout'], 10)
                clock[0] += 7
                with git_budget(60):
                    Git('/another-unused').run('second')
                    self.assertEqual(run.call_args.kwargs['timeout'], 3)
                    Git('/unused', deadline=clock[0] + 1).run('shorter')
                    self.assertEqual(run.call_args.kwargs['timeout'], 1)
                self.assertEqual(effective_deadline(), 110)
            self.assertIsNone(effective_deadline())
            old.run('native')
            self.assertEqual(run.call_args.kwargs['timeout'], 30)

    def test_expiry_does_not_start_another_subprocess_and_restores_context(self):
        clock = [100.0]
        with patch('spikes.git_budget.time.monotonic', side_effect=lambda: clock[0]), \
             patch('spikes.storage.subprocess.run') as run:
            with self.assertRaises(GitDeadlineExceeded):
                with git_budget(1):
                    Git('/unused').run('before')
                    clock[0] += 2
                    Git('/unused').run('after')
            self.assertEqual(run.call_count, 1)
            self.assertIsNone(effective_deadline())

    def test_late_cpu_result_is_not_success(self):
        clock = [100.0]
        with patch('spikes.git_budget.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(GitDeadlineExceeded):
                with git_budget(1):
                    clock[0] += 2
            self.assertIsNone(effective_deadline())

    def test_subprocess_timeout_is_transient_only_in_budget_scope(self):
        failure = subprocess.TimeoutExpired('git', 30)
        with patch('spikes.storage.subprocess.run', side_effect=failure):
            with self.assertRaises(GitDeadlineExceeded) as caught:
                with git_budget():
                    Git('/unused').run('blocked')
            self.assertIs(caught.exception.__cause__, failure)
            with self.assertRaises(subprocess.TimeoutExpired):
                Git('/unused').run('native')
        self.assertIsNone(effective_deadline())

    def test_thread_does_not_inherit_another_operations_budget(self):
        observed = []
        with git_budget():
            thread = threading.Thread(target=lambda: observed.append(effective_deadline()))
            thread.start(); thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(observed, [None])
            self.assertIsNotNone(effective_deadline())

    def test_invalid_budgets_are_rejected_without_context_leak(self):
        for seconds in (True, 0, -1, float('nan'), float('inf')):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                with git_budget(seconds):
                    self.fail('Invalid budget entered')
            self.assertIsNone(effective_deadline())
