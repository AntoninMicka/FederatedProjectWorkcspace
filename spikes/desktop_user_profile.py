# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native local profile editor opened from application settings."""
import sqlite3
from PySide6.QtWidgets import QDialog, QFormLayout, QLineEdit, QLabel, QPushButton
from spikes.user_profile import PROFILE_FIELDS


class UserProfileDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle('Uživatelský profil')
        self.resize(520, 300)
        form = QFormLayout(self)
        info = QLabel('Údaje se zobrazí na závěrečném slidu prezentace textově a v QR kódu. '
                      'Zůstávají v lokálním profilu; do projektu se neukládají.')
        info.setWordWrap(True); form.addRow(info)
        values = service.load()
        self.fields = {}
        for key, label in (('name', 'Jméno'), ('email', 'E-mail'), ('phone', 'Telefon'), ('web', 'Web')):
            field = QLineEdit(values[key]); field.setMaxLength(PROFILE_FIELDS[key])
            self.fields[key] = field; form.addRow(label, field)
        self.status = QLabel(); self.status.setWordWrap(True); form.addRow(self.status)
        self.save_button = QPushButton('Uložit profil'); self.save_button.clicked.connect(self.save)
        form.addRow(self.save_button)

    def save(self):
        try:
            self.service.save({key: field.text().strip() for key, field in self.fields.items()})
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc)); return
        self.accept()
