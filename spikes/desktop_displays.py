# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Session-only native display assignment for the two existing presenter views."""
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPushButton, QVBoxLayout


class PresenterDisplays(QObject):
    def __init__(self, app, speaker, audience):
        super().__init__(speaker)
        self.app, self.speaker, self.audience = app, speaker, audience
        self.active = False
        self.dialog = None
        self.markers = []
        self.speaker_screen = None
        self.audience_screen = None
        self.saved_geometry = None
        self.refresh = QTimer(self)
        self.refresh.setSingleShot(True)
        self.refresh.timeout.connect(self.configure)
        self.marker_timer = QTimer(self)
        self.marker_timer.setSingleShot(True)
        self.marker_timer.timeout.connect(self.clear_markers)
        app.screenAdded.connect(self.screen_added)
        app.screenRemoved.connect(self.changed)
        for screen in app.screens():
            self.watch(screen)
        app.aboutToQuit.connect(self.stop)

    def watch(self, screen):
        screen.geometryChanged.connect(self.changed)
        screen.availableGeometryChanged.connect(self.changed)

    def screen_added(self, screen):
        self.watch(screen)
        self.changed()

    def changed(self, *_):
        if not self.active:
            return
        # Hide before Qt can relocate the audience window onto the speaker screen.
        self.audience.hide()
        self.clear_markers()
        if self.dialog:
            self.dialog.reject()
        self.refresh.start(200)

    def open(self):
        if not self.active:
            self.saved_geometry = self.speaker.saveGeometry()
        self.active = True
        self.configure()

    def stop(self):
        self.active = False
        self.refresh.stop()
        self.clear_markers()
        self.audience.hide()
        if self.dialog:
            self.dialog.reject()
        if self.saved_geometry is not None:
            self.speaker.restoreGeometry(self.saved_geometry)
            self.saved_geometry = None

    def clear_markers(self):
        self.marker_timer.stop()
        for marker in self.markers:
            marker.close()
            marker.deleteLater()
        self.markers.clear()

    def identify(self, screens, speaker_index, audience_index):
        self.clear_markers()
        for index, screen in enumerate(screens):
            role = 'Řečník' if index == speaker_index else 'Diváci' if index == audience_index else 'Nepoužitý'
            marker = QLabel(f'Displej {index + 1} · {role}')
            marker.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                                  Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
            marker.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setStyleSheet('background:#102b36;color:white;border:4px solid #79c9ac;padding:20px;font: bold 28px sans-serif')
            marker.adjustSize()
            marker.winId()
            marker.windowHandle().setScreen(screen)
            rect = screen.availableGeometry()
            marker.move(rect.x() + 24, rect.y() + 24)
            marker.show()
            self.markers.append(marker)
        self.marker_timer.start(4000)

    @staticmethod
    def place(window, screen, fullscreen=False):
        window.hide()
        window.winId()
        window.windowHandle().setScreen(screen)
        window.setGeometry(screen.availableGeometry())
        if fullscreen:
            window.showFullScreen()
        else:
            window.showMaximized()

    def configure(self):
        if not self.active:
            return
        self.refresh.stop()
        self.audience.hide()
        if self.dialog:
            self.dialog.raise_()
            return
        screens = self.app.screens()
        if not screens:
            return
        dialog = QDialog(self.speaker)
        self.dialog = dialog
        dialog.setWindowTitle('Displeje a role prezentace')
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        layout = QVBoxLayout(dialog)
        info = QLabel('Přiřaďte displej řečníkovi a divákům. Ostatní displeje zůstanou nepoužité.\n'
                      'Na jednom displeji použijte náhled bez promítání. Zrušení ponechá výstup skrytý.')
        info.setWordWrap(True)
        layout.addWidget(info)
        form = QFormLayout()
        speaker = QComboBox()
        audience = QComboBox()
        audience.addItem('Bez promítání', -1)
        for index, screen in enumerate(screens):
            rect = screen.geometry()
            label = f'{index + 1} · {screen.name()} · {rect.width()} × {rect.height()}'
            speaker.addItem(label, index)
            audience.addItem(label, index)
        current = self.speaker_screen if self.speaker_screen in screens else self.speaker.screen()
        speaker.setCurrentIndex(screens.index(current) if current in screens else 0)
        if self.audience_screen in screens and self.audience_screen != current:
            audience.setCurrentIndex(screens.index(self.audience_screen) + 1)
        form.addRow('Řečník — ovládání a poznámky', speaker)
        form.addRow('Diváci — schválený slide', audience)
        layout.addLayout(form)
        error = QLabel()
        layout.addWidget(error)
        identify = QPushButton('Identifikovat displeje')
        identify.clicked.connect(lambda: self.identify(screens, speaker.currentData(), audience.currentData()))
        layout.addWidget(identify)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Použít role')
        layout.addWidget(buttons)

        def validate():
            same = speaker.currentData() == audience.currentData()
            buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not same)
            error.setText('Řečník a diváci musí mít různé displeje.' if same else '')
            self.identify(screens, speaker.currentData(), audience.currentData())

        def apply():
            if screens != self.app.screens():
                self.changed()
                return
            if speaker.currentData() == audience.currentData():
                return
            self.speaker_screen = screens[speaker.currentData()]
            audience_index = audience.currentData()
            self.audience_screen = screens[audience_index] if audience_index >= 0 else None
            self.place(self.speaker, self.speaker_screen)
            if self.audience_screen:
                self.place(self.audience, self.audience_screen, fullscreen=True)
            dialog.accept()
            self.speaker.activateWindow()

        def finished(_):
            self.clear_markers()
            self.dialog = None
            dialog.deleteLater()

        speaker.currentIndexChanged.connect(validate)
        audience.currentIndexChanged.connect(validate)
        buttons.accepted.connect(apply)
        buttons.rejected.connect(dialog.reject)
        dialog.finished.connect(finished)
        dialog.open()
        validate()
