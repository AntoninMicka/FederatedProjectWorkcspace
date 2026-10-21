# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Ephemeral native OpenSSH password prompt; no credential persistence."""
import sys


def main():
    from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit
    app = QApplication([sys.argv[0]])
    text, accepted = QInputDialog.getText(None, 'SSH přihlášení',
                                         sys.argv[1] if len(sys.argv) > 1 else 'SSH heslo:',
                                         QLineEdit.EchoMode.Password)
    if not accepted:
        return 1
    print(text, flush=True)
    return 0
