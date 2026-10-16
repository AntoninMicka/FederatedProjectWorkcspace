# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicitly saved, node-local presenter gamepad mapping."""
import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3

from spikes.journal import sync_dir
from spikes.metadata import require


DEFAULT_GAMEPAD_SETTINGS = {
    'enabled': True,
    'device_id': '',
    'history_axis': 0,
    'history_invert': False,
    'main_axis': 1,
    'main_invert': False,
    'tabs_axis': 2,
    'tabs_invert': False,
    'items_axis': 3,
    'items_invert': False,
    'confirm_button': 0,
    'neutral_threshold': 0.35,
    'activation_threshold': 0.65,
}


def validate_gamepad_settings(value):
    require(isinstance(value, dict) and value.keys() == DEFAULT_GAMEPAD_SETTINGS.keys(),
            'Neplatná pole nastavení gamepadu.')
    result = dict(value)
    require(type(result['enabled']) is bool, 'Neplatné zapnutí gamepadu.')
    require(isinstance(result['device_id'], str) and len(result['device_id']) <= 512
            and not any(ord(c) < 32 or ord(c) == 127 for c in result['device_id']),
            'Neplatné ID gamepadu.')
    for key in ('history_axis', 'main_axis', 'tabs_axis', 'items_axis'):
        require(type(result[key]) is int and 0 <= result[key] <= 31,
                'Neplatná osa gamepadu: ' + key)
    for key in ('history_invert', 'main_invert', 'tabs_invert', 'items_invert'):
        require(type(result[key]) is bool, 'Neplatné obrácení osy: ' + key)
    require(type(result['confirm_button']) is int and 0 <= result['confirm_button'] <= 63,
            'Neplatné potvrzovací tlačítko.')
    neutral, activation = result['neutral_threshold'], result['activation_threshold']
    require(type(neutral) in (int, float) and type(neutral) is not bool
            and type(activation) in (int, float) and type(activation) is not bool
            and 0.05 <= neutral <= 0.8 and neutral < activation <= 1.0,
            'Prahy gamepadu musí splnit 0,05 ≤ neutrální < aktivační ≤ 1.')
    result['neutral_threshold'] = float(neutral)
    result['activation_threshold'] = float(activation)
    return result


class GamepadSettings:
    """Load without side effects; create durable state only on explicit save."""

    def __init__(self, node_path):
        self.path = Path(node_path).resolve().with_suffix('.gamepad.sqlite3')

    def load(self):
        if not self.path.exists():
            return dict(DEFAULT_GAMEPAD_SETTINGS)
        require(not self.path.is_symlink(), 'Nastavení gamepadu nesmí být symbolický odkaz.')
        with closing(sqlite3.connect(f'{self.path.as_uri()}?mode=ro', uri=True)) as db:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'").fetchone()
            row = db.execute('SELECT value FROM settings WHERE id=1').fetchone() if exists else None
        return validate_gamepad_settings(json.loads(row[0])) if row else dict(DEFAULT_GAMEPAD_SETTINGS)

    def save(self, value, *, checkpoint=lambda: None):
        value = validate_gamepad_settings(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            require(not self.path.is_symlink(), 'Nastavení gamepadu nesmí být symbolický odkaz.')
        else:
            os.close(fd)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS settings '
                       '(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
            db.execute('INSERT OR REPLACE INTO settings VALUES (1, ?)',
                       (json.dumps(value, ensure_ascii=False),))
            checkpoint()
        sync_dir(self.path.parent)
        return value
