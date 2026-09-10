"""Native editor: untrusted Markdown is plain text, mutations never enter WebEngine."""
from uuid import uuid4

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPlainTextEdit,
                               QPushButton, QLabel, QComboBox, QListWidget, QListWidgetItem,
                               QMessageBox, QSplitter)

from spikes.artifacts import checklist_items


class EditorWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            self.succeeded.emit(self.action())
        except Exception as exc:
            # Native-only error; plain text label, never HTML or a renderer response.
            self.failed.emit(str(exc))


class EditorDialog(QDialog):
    saved = Signal(str)

    def __init__(self, service, project_id, parent=None, *, todo=False):
        super().__init__(parent)
        self.service, self.project_id, self.want_todo = service, project_id, todo
        self.workers, self.busy, self.dirty, self.pending = [], False, False, None
        self.view, self.current = None, None
        self.setWindowTitle('Markdown dokumenty')
        self.resize(1000, 720)
        layout = QVBoxLayout(self)
        self.project_label = QLabel()
        self.project_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.project_label)
        bar = QHBoxLayout()
        self.documents = QComboBox()
        self.new_button = QPushButton('Nový dokument')
        self.todo_button = QPushButton('Hlavní TODO')
        self.history_button = QPushButton('Historie…')
        self.history_button.clicked.connect(self.history)
        self.reload_button = QPushButton('Znovu načíst / obnovit')
        for widget in (self.documents, self.new_button, self.todo_button, self.history_button, self.reload_button):
            bar.addWidget(widget)
        layout.addLayout(bar)
        self.title = QLineEdit(); self.title.setMaxLength(200)
        self.title.setPlaceholderText('Název dokumentu')
        layout.addWidget(self.title)
        splitter = QSplitter()
        self.body = QPlainTextEdit()
        self.body.setPlaceholderText('Markdown text; checklist: - [ ] Úkol')
        self.checks = QListWidget()
        splitter.addWidget(self.body); splitter.addWidget(self.checks)
        splitter.setSizes([700, 300]); layout.addWidget(splitter)
        buttons = QHBoxLayout()
        self.add_check = QPushButton('Přidat položku checklistu')
        self.save_button = QPushButton('Uložit')
        self.status = QLabel(); self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        buttons.addWidget(self.add_check); buttons.addStretch(); buttons.addWidget(self.save_button)
        layout.addLayout(buttons); layout.addWidget(self.status)
        self.title.textChanged.connect(self.changed)
        self.body.textChanged.connect(self.changed)
        self.checks.itemChanged.connect(self.toggle)
        self.documents.activated.connect(self.select)
        self.new_button.clicked.connect(self.new_document)
        self.todo_button.clicked.connect(self.open_todo)
        self.reload_button.clicked.connect(self.reload)
        self.add_check.clicked.connect(self.append_check)
        self.save_button.clicked.connect(self.save)
        self.run(lambda: service.open(project_id), self.loaded)

    def controls(self):
        editable = self.current is not None and not self.busy and self.pending is None
        self.title.setReadOnly(not editable); self.body.setReadOnly(not editable)
        self.checks.setEnabled(editable); self.add_check.setEnabled(editable)
        for widget in (self.documents, self.new_button, self.todo_button):
            widget.setEnabled(self.view is not None and not self.busy and self.pending is None)
        self.history_button.setEnabled(not self.busy and self.pending is None and
                                       self.current is not None and not self.current.get('new', False))
        self.reload_button.setEnabled(not self.busy)
        self.save_button.setEnabled(not self.busy and (self.pending is not None or (editable and self.dirty)))
        self.save_button.setText('Zopakovat uložení' if self.pending else 'Uložit')

    def run(self, action, success):
        self.busy = True; self.controls(); self.status.setText('Pracuji…')
        worker = EditorWorker(action, self); self.workers.append(worker)
        worker.succeeded.connect(success)
        worker.failed.connect(lambda message: self.status.setText(
            'Operace nebyla dokončena: ' + message + '\nText zůstává v editoru. '
            'Uložení lze zopakovat, nebo znovu načíst projekt a obnovit připravený zápis.'))
        def finished():
            self.busy = False; self.controls()
        worker.finished.connect(finished)
        worker.start()

    def discard(self):
        return not (self.dirty or self.pending) or QMessageBox.question(
            self, 'Opustit rozepsaný text?',
            'Zahodit neuložený text v editoru? Již připravený zápis v journalu se při otevření dokončí.',
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def loaded(self, view):
        previous = self.current['id'] if self.current else None
        self.view, self.pending, self.dirty = view, None, False
        self.project_label.setText(view['title'])
        self.documents.clear()
        for doc in view['documents']:
            label = ('Hlavní TODO · ' if doc['id'] == view['main_todo_id'] else '') + doc['title']
            self.documents.addItem(label, doc['id'])
        target = view['main_todo_id'] if self.want_todo else previous
        self.want_todo = False
        doc = next((d for d in view['documents'] if d['id'] == target), None)
        if doc:
            self.show_document(doc)
        elif target == view['main_todo_id']:
            self.open_todo()
        elif view['documents']:
            self.show_document(view['documents'][0])
        else:
            self.new_document()
        self.status.setText('Dokument načten. Změny se zapisují až tlačítkem Uložit.')

    def show_document(self, doc):
        self.current = doc
        self.title.blockSignals(True); self.body.blockSignals(True)
        self.title.setText(doc['title']); self.body.setPlainText(doc['body'])
        self.title.blockSignals(False); self.body.blockSignals(False)
        self.dirty = doc.get('new', False)
        self.documents.setCurrentIndex(self.documents.findData(doc['id']))
        self.refresh_checks(); self.controls()

    def select(self, index):
        id_ = self.documents.itemData(index)
        if self.discard():
            self.show_document(next(d for d in self.view['documents'] if d['id'] == id_))
        else:
            self.documents.setCurrentIndex(self.documents.findData(self.current['id']))

    def new_document(self):
        if self.discard():
            self.show_document(dict(id=str(uuid4()), title='', body='', new=True))

    def open_todo(self):
        if not self.discard():
            return
        id_ = self.view['main_todo_id']
        doc = next((d for d in self.view['documents'] if d['id'] == id_), None)
        self.show_document(doc or dict(id=id_, title='Hlavní TODO', body='# TODO\n\n- [ ] První úkol\n', new=True))

    def refresh_checks(self):
        self.checks.blockSignals(True); self.checks.clear()
        for entry in checklist_items(self.body.toPlainText()):
            item = QListWidgetItem(entry['title'])
            item.setData(Qt.ItemDataRole.UserRole, entry['offset'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if entry['checked'] else Qt.CheckState.Unchecked)
            self.checks.addItem(item)
        self.checks.blockSignals(False)

    def changed(self):
        self.dirty = self.current is not None and (self.current.get('new', False) or
            self.title.text() != self.current['title'] or self.body.toPlainText() != self.current['body'])
        self.refresh_checks(); self.controls()

    def toggle(self, item):
        body = self.body.toPlainText(); offset = item.data(Qt.ItemDataRole.UserRole)
        value = 'x' if item.checkState() == Qt.CheckState.Checked else ' '
        # Qt cursor positions use UTF-16 units, unlike Python string offsets.
        from PySide6.QtGui import QTextCursor
        cursor = self.body.textCursor()
        position = len(body[:offset].encode('utf-16-le')) // 2
        cursor.setPosition(position); cursor.setPosition(position + 1, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(value)

    def append_check(self):
        from PySide6.QtGui import QTextCursor
        cursor = self.body.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(('\n' if self.body.toPlainText() and not self.body.toPlainText().endswith('\n') else '') + '- [ ] Nový úkol\n')
        self.body.setTextCursor(cursor); self.body.setFocus()

    def save(self):
        if self.busy or not self.current:
            return
        if self.pending is None:
            if not self.title.text().strip():
                self.status.setText('Vyplňte název dokumentu.'); return
            request = dict(project_id=self.project_id, artifact_id=self.current['id'],
                           base_head=self.view['commit_id'], title=self.title.text(), body=self.body.toPlainText(),
                           new=self.current.get('new', False))
            self.pending = (request, str(uuid4()))
        request, operation = self.pending
        def saved(receipt):
            self.view['commit_id'] = receipt['commit_id']
            self.current = dict(id=request['artifact_id'], title=request['title'], body=request['body'])
            self.view['documents'] = [d for d in self.view['documents'] if d['id'] != self.current['id']] + [self.current]
            self.loaded(self.view)
            self.status.setText('Uloženo do Gitu.')
            self.saved.emit(self.project_id)
        self.run(lambda: self.service.save(request, operation), saved)

    def history(self):
        if self.busy or self.pending or not self.current or self.current.get('new', False):
            return
        from spikes.desktop_history import HistoryDialog
        dialog = HistoryDialog(self.service.node_path, self.project_id, self.current['id'],
                               self.view['commit_id'], self)
        dialog.exec()
        for worker in dialog.workers:
            worker.wait()
        dialog.deleteLater()

    def reload(self):
        if not self.busy and self.discard():
            self.run(lambda: self.service.open(self.project_id), self.loaded)

    def reject(self):
        if not self.busy and self.discard():
            for worker in self.workers:
                worker.wait()
            super().reject()

    def closeEvent(self, event):
        if self.busy or not self.discard():
            event.ignore()
        else:
            for worker in self.workers:
                worker.wait()
            event.accept()
