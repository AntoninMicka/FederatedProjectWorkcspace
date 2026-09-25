# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native basic presentation editor; project writes never originate in WebEngine."""
import base64
import copy
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, Signal, QRectF, QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPlainTextEdit, QPushButton, QLabel, QListWidget, QListWidgetItem,
    QComboBox, QSplitter, QMessageBox, QColorDialog, QFileDialog, QTabWidget, QCheckBox)

from spikes.desktop_editor import EditorWorker
from spikes.presentation_documents import (MAX_WALLPAPER, new_deck, new_slide, main_order,
    relink, set_neighbor, remove_slide, validate_deck, project_deck)


class SlidePreview(QWidget):
    def __init__(self):
        super().__init__()
        self.slide = None
        self.setMinimumSize(320, 180)

    def paintEvent(self, event):
        if not self.slide:
            return
        s = self.slide
        painter = QPainter(self)
        width = min(self.width(), self.height() * 16 / 9)
        height = width * 9 / 16
        rect = QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)
        painter.fillRect(rect, QColor(s['background']))
        if s['wallpaper']:
            image = QImage.fromData(base64.b64decode(s['wallpaper'].split(',', 1)[1]))
            if not image.isNull():
                image = image.scaled(int(width), int(height), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
                source = QRectF((image.width() - width) / 2, (image.height() - height) / 2, width, height)
                painter.drawImage(rect, image, source)
        painter.setPen(QColor(s['foreground']))
        font = QFont('Sans Serif'); font.setPixelSize(max(12, int(width * .05))); font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect.adjusted(width * .07, height * .08, -width * .07, -height * .64),
                         Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, s['title'])
        font.setPixelSize(max(9, int(width * .028))); font.setBold(False); painter.setFont(font)
        painter.drawText(rect.adjusted(width * .07, height * .38, -width * .07, -height * .06),
                         Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                         '\n'.join('• ' + bullet for bullet in s['bullets']))


class PresentationEditorDialog(QDialog):
    selected = Signal(object)

    def __init__(self, service, project_id, parent=None):
        super().__init__(parent)
        self.service, self.project_id = service, project_id
        self.view = None
        self.deck = None
        self.artifact_id = None
        self.slide_id = None
        self.new = True
        self.busy = False
        self.dirty = False
        self.pending = None
        self.workers = []
        self.loading = False
        self.setWindowTitle('Editor prezentací')
        self.resize(1180, 820)
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.documents = QComboBox()
        self.new_button = QPushButton('Nová prezentace')
        self.reload_button = QPushButton('Znovu načíst')
        for w in (self.documents, self.new_button, self.reload_button):
            top.addWidget(w)
        root.addLayout(top)
        self.content = QWidget(); content = QVBoxLayout(self.content)
        self.deck_title = QLineEdit(); self.deck_title.setMaxLength(200)
        content.addWidget(QLabel('Název prezentace'))
        content.addWidget(self.deck_title)
        split = QSplitter()
        left = QWidget(); left_layout = QVBoxLayout(left)
        self.slides = QListWidget(); left_layout.addWidget(self.slides)
        self.add_main = QPushButton('+ Hlavní slide'); self.add_backup = QPushButton('+ Backup')
        self.delete_button = QPushButton('Odstranit slide')
        for w in (self.add_main, self.add_backup, self.delete_button):
            left_layout.addWidget(w)
        split.addWidget(left)
        right = QWidget(); right_layout = QVBoxLayout(right)
        self.preview = SlidePreview(); right_layout.addWidget(self.preview, 1)
        tabs = QTabWidget()
        fields = QWidget(); form = QFormLayout(fields)
        self.title = QLineEdit(); self.title.setMaxLength(200)
        self.bullets = QPlainTextEdit(); self.bullets.setPlaceholderText('Jedna odrážka na řádek (nejvýše 12).')
        self.bullets.setMaximumHeight(130)
        self.notes = QPlainTextEdit(); self.notes.setMaximumHeight(75)
        form.addRow('Nadpis', self.title); form.addRow('Odrážky', self.bullets); form.addRow('Soukromé poznámky', self.notes)
        self.repeat = QCheckBox('Povolit opakované promítnutí')
        self.reveal = QComboBox()
        self.reveal.addItem('Všechny řádky najednou', 'all')
        self.reveal.addItem('Postupně po řádcích', 'step')
        form.addRow(self.repeat); form.addRow('Zobrazení odrážek', self.reveal)
        colors = QHBoxLayout()
        self.background = QPushButton('Barva pozadí'); self.foreground = QPushButton('Barva textu')
        self.wallpaper = QPushButton('Vybrat tapetu…'); self.clear_wallpaper = QPushButton('Odebrat tapetu')
        for w in (self.background, self.foreground, self.wallpaper, self.clear_wallpaper):
            colors.addWidget(w)
        form.addRow(colors)
        tabs.addTab(fields, 'Obsah a vzhled')
        links = QWidget(); links_form = QFormLayout(links)
        self.previous = QComboBox(); self.next = QComboBox(); self.backups = QListWidget()
        self.backup_label = QLabel()
        links_form.addRow('Previous — předchozí', self.previous)
        links_form.addRow('Next — následující', self.next)
        links_form.addRow(self.backup_label, self.backups)
        hint = QLabel('Next a previous mění pořadí hlavní linie oběma směry. Backup se vrací k místu odbočení.'); hint.setWordWrap(True)
        links_form.addRow(hint)
        tabs.addTab(links, 'Vazby')
        right_layout.addWidget(tabs, 1)
        split.addWidget(right); split.setSizes([260, 850]); content.addWidget(split)
        root.addWidget(self.content)
        bottom = QHBoxLayout()
        self.save_button = QPushButton('Uložit do projektu')
        self.use_button = QPushButton('Spustit uloženou prezentaci')
        bottom.addWidget(self.save_button); bottom.addWidget(self.use_button)
        root.addLayout(bottom)
        self.status = QLabel(); self.status.setWordWrap(True); self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        self.documents.activated.connect(self.choose_document)
        self.new_button.clicked.connect(self.create)
        self.reload_button.clicked.connect(self.reload)
        self.slides.currentItemChanged.connect(self.choose_slide)
        self.add_main.clicked.connect(lambda: self.add('main'))
        self.add_backup.clicked.connect(lambda: self.add('backup'))
        self.delete_button.clicked.connect(self.delete)
        self.deck_title.textChanged.connect(self.edit)
        self.title.textChanged.connect(self.edit)
        self.bullets.textChanged.connect(self.edit)
        self.notes.textChanged.connect(self.edit)
        self.repeat.toggled.connect(self.edit)
        self.reveal.currentIndexChanged.connect(self.edit)
        self.background.clicked.connect(lambda: self.color('background'))
        self.foreground.clicked.connect(lambda: self.color('foreground'))
        self.wallpaper.clicked.connect(self.pick_wallpaper)
        self.clear_wallpaper.clicked.connect(lambda: self.set_wallpaper(''))
        self.previous.activated.connect(lambda: self.neighbor(True))
        self.next.activated.connect(lambda: self.neighbor(False))
        self.backups.itemChanged.connect(self.link_backup)
        self.save_button.clicked.connect(self.save)
        self.use_button.clicked.connect(self.use)
        self.run(lambda: service.open(project_id), self.loaded)

    def update_enabled(self):
        self.content.setEnabled(not self.busy and self.pending is None and self.deck is not None)
        for widget in (self.documents, self.new_button):
            widget.setEnabled(not self.busy and self.pending is None)
        self.reload_button.setEnabled(not self.busy)
        self.save_button.setEnabled(not self.busy and self.deck is not None and (self.dirty or self.pending is not None))
        self.save_button.setText('Opakovat stejné uložení' if self.pending else 'Uložit do projektu')
        self.use_button.setEnabled(not self.busy and not self.dirty and not self.new and self.deck is not None and self.pending is None)

    def run(self, action, done):
        self.busy = True; self.update_enabled(); self.status.setText('Pracuji…')
        worker = EditorWorker(action, self); self.workers.append(worker)
        def success(value):
            self.busy = False
            done(value)
            self.update_enabled()
        def failure(message):
            self.busy = False
            self.status.setText(message + (' Opakujte stejné uložení, nebo znovu načtěte projekt pro obnovu.' if self.pending else ''))
            self.update_enabled()
        worker.succeeded.connect(success); worker.failed.connect(failure); worker.start()

    def discard(self):
        if not self.dirty and self.pending is None:
            return True
        text = ('Uložení má neověřený výsledek. Znovunačtení obnoví připravenou operaci z journalu. '
                if self.pending else '') + 'Zahodit neuložené úpravy editoru?'
        return QMessageBox.question(self, 'Neuložené změny', text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes

    def loaded(self, view):
        self.view = view
        self.documents.blockSignals(True); self.documents.clear()
        for doc in view['documents']:
            self.documents.addItem(doc['title'] + (' — neplatná' if 'error' in doc else ''), doc['id'])
        self.documents.blockSignals(False)
        if view['documents']:
            index = next((i for i, d in enumerate(view['documents']) if d['id'] == self.artifact_id), 0)
            self.install(view['documents'][index]); self.documents.setCurrentIndex(index)
        else:
            self.create_unchecked()
        self.status.setText('Načten projekt: ' + view['title'] + '. Editace nemění veřejný výstup.'
                            if self.deck else 'Vybranou prezentaci nelze načíst; dokument zůstal beze změny.')

    def install(self, document):
        self.deck = copy.deepcopy(document.get('deck'))
        self.artifact_id = document['id']; self.new = False; self.pending = None; self.dirty = False
        self.slide_id = None
        if self.deck:
            self.slide_id = self.deck['slides'][0]['id']; self.refresh()
        else:
            self.slides.clear(); self.preview.slide = None; self.preview.update()
            self.status.setText(document.get('error', 'Neplatná prezentace.'))
        self.update_enabled()

    def choose_document(self, index):
        if self.discard():
            self.install(self.view['documents'][index])
        else:
            self.documents.setCurrentIndex(self.documents.findData(self.artifact_id))

    def create_unchecked(self):
        self.deck = new_deck(); self.artifact_id = str(uuid4()); self.new = True
        self.pending = None; self.dirty = True; self.slide_id = self.deck['slides'][0]['id']
        self.documents.setCurrentIndex(-1); self.refresh(); self.update_enabled()

    def create(self):
        if self.discard():
            self.create_unchecked()

    def reload(self):
        if self.discard():
            self.run(lambda: self.service.open(self.project_id), self.loaded)

    def current(self):
        return next(s for s in self.deck['slides'] if s['id'] == self.slide_id)

    def refresh(self):
        self.loading = True
        self.deck_title.setText(self.deck['title'])
        self.slides.clear()
        order = main_order(self.deck)
        by_id = {s['id']: s for s in self.deck['slides']}
        for id_ in order + [s['id'] for s in self.deck['slides'] if s['kind'] == 'backup']:
            s = by_id[id_]; item = QListWidgetItem(('Backup · ' if s['kind'] == 'backup' else '') + s['title'])
            item.setData(Qt.ItemDataRole.UserRole, id_); self.slides.addItem(item)
            if id_ == self.slide_id:
                self.slides.setCurrentItem(item)
        self.loading = False; self.show_slide()

    def choose_slide(self, item, previous):
        if self.loading or not item:
            return
        self.slide_id = item.data(Qt.ItemDataRole.UserRole); self.show_slide()

    def show_slide(self):
        self.loading = True; s = self.current()
        self.title.setText(s['title']); self.bullets.setPlainText('\n'.join(s['bullets'])); self.notes.setPlainText(s['notes'])
        self.repeat.setChecked(s.get('repeat', False))
        self.reveal.setCurrentIndex(self.reveal.findData(s.get('reveal', 'all')))
        order = main_order(self.deck); by_id = {s['id']: s for s in self.deck['slides']}
        for combo, label in ((self.previous, 'Začátek'), (self.next, 'Konec')):
            combo.clear(); combo.addItem(label, None); combo.setEnabled(s['kind'] == 'main')
            for id_ in order:
                if id_ != self.slide_id:
                    combo.addItem(by_id[id_]['title'], id_)
        if s['kind'] == 'main':
            index = order.index(s['id'])
            self.previous.setCurrentIndex(self.previous.findData(order[index - 1] if index else None))
            self.next.setCurrentIndex(self.next.findData(s['next']))
        self.backups.clear()
        self.backup_label.setText('Backupy tohoto slidu' if s['kind'] == 'main' else 'Backup pro / návrat k')
        for other in self.deck['slides']:
            if other['kind'] == s['kind']:
                continue
            item = QListWidgetItem(other['title']); item.setData(Qt.ItemDataRole.UserRole, other['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            linked = other['id'] in s['backups'] if s['kind'] == 'main' else s['id'] in other['backups']
            item.setCheckState(Qt.CheckState.Checked if linked else Qt.CheckState.Unchecked)
            self.backups.addItem(item)
        self.loading = False; self.paint_preview()

    def paint_preview(self):
        self.preview.slide = self.current(); self.preview.update()
        for button, key, label in ((self.background, 'background', 'Pozadí'), (self.foreground, 'foreground', 'Text')):
            button.setText(label + ' ' + self.current()[key])
        self.clear_wallpaper.setEnabled(bool(self.current()['wallpaper']))

    def changed(self):
        self.dirty = True; self.update_enabled(); self.paint_preview()

    def edit(self):
        if self.loading or not self.deck:
            return
        self.deck['title'] = self.deck_title.text()
        s = self.current(); s['title'] = self.title.text()
        s['bullets'] = [line for line in self.bullets.toPlainText().splitlines() if line.strip()]
        s['notes'] = self.notes.toPlainText()
        s['repeat'] = self.repeat.isChecked()
        s['reveal'] = self.reveal.currentData()
        if self.slides.currentItem():
            self.slides.currentItem().setText(('Backup · ' if s['kind'] == 'backup' else '') + s['title'])
        self.changed()

    def neighbor(self, previous):
        combo = self.previous if previous else self.next
        set_neighbor(self.deck, self.slide_id, combo.currentData(), previous=previous)
        self.refresh(); self.changed()

    def link_backup(self, item):
        if self.loading:
            return
        other = next(s for s in self.deck['slides'] if s['id'] == item.data(Qt.ItemDataRole.UserRole))
        current = self.current(); source, target = (current, other) if current['kind'] == 'main' else (other, current)
        if item.checkState() == Qt.CheckState.Checked:
            if target['id'] not in source['backups']:
                source['backups'].append(target['id'])
        else:
            source['backups'] = [id_ for id_ in source['backups'] if id_ != target['id']]
        self.changed()

    def add(self, kind):
        if len(self.deck['slides']) >= 100:
            self.status.setText('Limit je 100 slidů.'); return
        order = main_order(self.deck); slide = new_slide(kind)
        self.deck['slides'].append(slide)
        if kind == 'main':
            relink(self.deck, order + [slide['id']])
        elif self.current()['kind'] == 'main':
            self.current()['backups'].append(slide['id'])
        self.slide_id = slide['id']; self.refresh(); self.changed()

    def delete(self):
        try:
            remove_slide(self.deck, self.slide_id)
        except ValueError as exc:
            self.status.setText(str(exc)); return
        self.slide_id = self.deck['slides'][0]['id']; self.refresh(); self.changed()

    def color(self, key):
        value = QColorDialog.getColor(QColor(self.current()[key]), self)
        if value.isValid():
            self.current()[key] = value.name(); self.changed()

    def set_wallpaper(self, value):
        self.current()['wallpaper'] = value; self.changed()

    def pick_wallpaper(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Tapeta', '', 'Obrázky (*.png *.jpg *.jpeg *.webp)')
        if not filename:
            return
        try:
            if Path(filename).stat().st_size > 10 * 1024 * 1024:
                raise ValueError('Zdrojový obrázek smí mít nejvýše 10 MiB.')
            reader = QImageReader(filename)
            size = reader.size()
            if not size.isValid() or size.width() > 8192 or size.height() > 8192:
                raise ValueError('Neplatný obrázek nebo rozměry nad 8192 pixelů.')
            size.scale(960, 540, Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(size); image = reader.read()
            if image.isNull():
                raise ValueError('Obrázek nelze načíst.')
            while True:
                data = QByteArray(); buffer = QBuffer(data); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                if not image.save(buffer, 'PNG'):
                    raise ValueError('Obrázek nelze převést na PNG.')
                value = 'data:image/png;base64,' + base64.b64encode(bytes(data)).decode('ascii')
                if len(value) <= MAX_WALLPAPER:
                    break
                image = image.scaled(max(1, image.width() * 3 // 4), max(1, image.height() * 3 // 4),
                                     Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.set_wallpaper(value)
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def save(self):
        if self.busy:
            return
        if self.pending is None:
            try:
                validate_deck(self.deck)
            except (ValueError, TypeError, KeyError) as exc:
                self.status.setText(str(exc)); return
            self.pending = (dict(project_id=self.project_id, artifact_id=self.artifact_id,
                                 base_head=self.view['commit_id'], new=self.new, deck=copy.deepcopy(self.deck)), str(uuid4()))
        request, operation = self.pending
        def action():
            self.service.save(request, operation)
            return self.service.open(self.project_id)
        self.run(action, self.loaded)

    def use(self):
        if self.busy or self.dirty or self.pending or self.new:
            return
        self.selected.emit(project_deck(self.deck, self.view['commit_id'] + ':' + self.artifact_id))
        self.accept()

    def reject(self):
        if not self.busy and self.discard():
            super().reject()

    def closeEvent(self, event):
        if self.busy or not self.discard():
            event.ignore()
        else:
            event.accept()
