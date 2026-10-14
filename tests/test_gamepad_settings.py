# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Node-local presenter gamepad settings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from spikes.gamepad_settings import (DEFAULT_GAMEPAD_SETTINGS, GamepadSettings,
                                     validate_gamepad_settings)


class GamepadSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.node = Path(self.temp.name) / 'node.json'
        self.store = GamepadSettings(self.node)

    def test_load_is_side_effect_free_and_explicit_save_survives_restart(self):
        self.assertEqual(self.store.load(), DEFAULT_GAMEPAD_SETTINGS)
        self.assertFalse(self.store.path.exists())
        changed = dict(DEFAULT_GAMEPAD_SETTINGS, device_id='Wireless Pad', history_axis=4,
                       history_invert=True, neutral_threshold=0.2, activation_threshold=0.8)
        self.store.save(changed)
        self.assertEqual(GamepadSettings(self.node).load(), changed)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)

    def test_transaction_keeps_previous_mapping_after_process_crash(self):
        first = dict(DEFAULT_GAMEPAD_SETTINGS, confirm_button=1)
        self.store.save(first)
        second = dict(first, confirm_button=2)
        script = ("from spikes.gamepad_settings import GamepadSettings; import json,os,sys; "
                  "GamepadSettings(sys.argv[1]).save(json.loads(sys.argv[2]), "
                  "checkpoint=lambda: os._exit(73))")
        result = subprocess.run([sys.executable, '-c', script, str(self.node), json.dumps(second)])
        self.assertEqual(result.returncode, 73)
        self.assertEqual(GamepadSettings(self.node).load(), first)
        fresh = Path(self.temp.name) / 'fresh.json'
        result = subprocess.run([sys.executable, '-c', script, str(fresh), json.dumps(second)])
        self.assertEqual(result.returncode, 73)
        self.assertEqual(GamepadSettings(fresh).load(), DEFAULT_GAMEPAD_SETTINGS)

    def test_invalid_mapping_is_rejected_before_file_creation(self):
        invalid = [
            dict(DEFAULT_GAMEPAD_SETTINGS, history_axis=-1),
            dict(DEFAULT_GAMEPAD_SETTINGS, confirm_button=True),
            dict(DEFAULT_GAMEPAD_SETTINGS, neutral_threshold=0.7, activation_threshold=0.6),
            dict(DEFAULT_GAMEPAD_SETTINGS, device_id='bad\nvalue'),
            dict(DEFAULT_GAMEPAD_SETTINGS, extra='x'),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_gamepad_settings(value)
        self.assertFalse(self.store.path.exists())

    def test_existing_symlink_is_rejected(self):
        target = Path(self.temp.name) / 'target'
        target.write_text('do not overwrite')
        self.store.path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.store.load()
        with self.assertRaises(ValueError):
            self.store.save(DEFAULT_GAMEPAD_SETTINGS)
        self.assertEqual(target.read_text(), 'do not overwrite')
