# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import subprocess
import sys
import unittest

from scripts import test_shards


class TestShardTests(unittest.TestCase):
    def test_four_shards_are_complete_disjoint_deterministic_and_balanced(self):
        inventory = test_shards.discover_modules()
        first = test_shards.partition_modules(inventory, 4)
        second = test_shards.partition_modules(inventory, 4)
        self.assertEqual(first, second)

        expected = {module for module, _weight in inventory}
        selected = [module for shard in first for module in shard['modules']]
        self.assertEqual(set(selected), expected)
        self.assertEqual(len(selected), len(expected))
        self.assertTrue(all(shard['modules'] for shard in first))
        weights = [shard['weight'] for shard in first]
        self.assertLessEqual(max(weights) - min(weights),
                             max(weight for _module, weight in inventory))

    def test_invalid_inventory_and_coordinates_fail_closed(self):
        for modules, count in [([], 4), ([('bad', 1)], 4),
                               ([('tests.test_x', 0)], 4),
                               ([('tests.test_x', 1), ('tests.test_x', 2)], 4),
                               ([('tests.test_x', 1)], 0)]:
            with self.subTest(modules=modules, count=count), self.assertRaises(ValueError):
                test_shards.partition_modules(modules, count)
        for number, count in [(0, 4), (5, 4)]:
            with self.subTest(number=number, count=count), self.assertRaises(ValueError):
                test_shards.selected_modules(number, count)

    def test_list_cli_selects_exactly_one_shard_without_running_tests(self):
        completed = subprocess.run([
            sys.executable, str(test_shards.ROOT / 'scripts/test_shards.py'),
            '--shard', '2', '--shards', '4', '--list'], cwd=test_shards.ROOT,
            text=True, capture_output=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        expected = test_shards.selected_modules(2, 4)['modules']
        self.assertEqual(completed.stdout.splitlines(), expected)
        self.assertIn('test shard 2/4:', completed.stderr)

    def test_launcher_runs_explicit_selector_and_rejects_unittest_options(self):
        launcher = test_shards.ROOT / 'run.sh'
        selected = subprocess.run([
            str(launcher), 'test',
            'tests.test_ai_outcome.AITaskOutcomeTests.'
            'test_closed_variants_round_trip_bounded_content'],
            cwd=test_shards.ROOT, text=True, capture_output=True, timeout=20)
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertIn('Ran 1 test', selected.stderr)

        rejected = subprocess.run([str(launcher), 'test', '--failfast'],
                                  cwd=test_shards.ROOT, text=True,
                                  capture_output=True, timeout=10)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn('Neplatný unittest selektor', rejected.stderr)

    def test_ci_uses_four_isolated_non_fail_fast_shards(self):
        workflow = (test_shards.ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('name: tests (${{ matrix.shard }}/4)', workflow)
        self.assertIn('fail-fast: false', workflow)
        self.assertIn('shard: [1, 2, 3, 4]', workflow)
        self.assertIn(
            'python scripts/test_shards.py --shard "${{ matrix.shard }}" --shards 4',
            workflow)
        self.assertIn('needs: test_shards', workflow)
        self.assertIn('SHARD_RESULT: ${{ needs.test_shards.result }}', workflow)


if __name__ == '__main__':
    unittest.main()
