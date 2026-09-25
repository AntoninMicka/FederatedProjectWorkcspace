# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Local desktop user's contact profile, outside all project repositories."""
import json
import os
from contextlib import closing
import sqlite3
from pathlib import Path

from spikes.metadata import require
from spikes.journal import sync_dir

PROFILE_FIELDS = {'name': 100, 'email': 180, 'phone': 80, 'web': 200}


def validate_profile(value):
    require(isinstance(value, dict) and value.keys() == PROFILE_FIELDS.keys(), 'Neplatná pole profilu.')
    for key, limit in PROFILE_FIELDS.items():
        text = value[key]
        require(isinstance(text, str) and len(text) <= limit
                and not any(ord(c) < 32 or ord(c) == 127 for c in text), 'Neplatná hodnota profilu: ' + key)
    require(len('\n'.join(value.values()).encode('utf-8')) <= 1000, 'Kontakty jsou pro QR příliš dlouhé.')
    return dict(value)


class UserProfile:
    def __init__(self, node_path):
        self.path = Path(node_path).resolve().with_suffix('.profile.sqlite3')

    def load(self):
        if not self.path.exists():
            return {key: '' for key in PROFILE_FIELDS}
        require(not self.path.is_symlink(), 'Profil nesmí být symbolický odkaz.')
        with closing(sqlite3.connect(f'{self.path.as_uri()}?mode=ro', uri=True)) as db:
            # DDL may have committed before the first profile write was interrupted.
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile'").fetchone()
            row = db.execute('SELECT value FROM profile WHERE id=1').fetchone() if exists else None
        return validate_profile(json.loads(row[0])) if row else {key: '' for key in PROFILE_FIELDS}

    def save(self, value, *, checkpoint=lambda: None):
        value = validate_profile(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            require(not self.path.is_symlink(), 'Profil nesmí být symbolický odkaz.')
        else:
            os.close(fd)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
            db.execute('INSERT OR REPLACE INTO profile VALUES (1, ?)', (json.dumps(value, ensure_ascii=False),))
            checkpoint()
        sync_dir(self.path.parent)
        return value
