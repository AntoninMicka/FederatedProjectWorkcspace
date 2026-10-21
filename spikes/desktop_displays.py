# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Session-only native display placement behind the shared presenter form."""
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QLabel


class PresenterDisplays(QObject):
    def __init__(self, app, speaker, audience, *, configuration_callback=None,
                 closed_callback=None, error_callback=None):
        super().__init__(speaker)
        self.app, self.speaker, self.audience = app, speaker, audience
        self.configuration_callback = configuration_callback or (lambda _configuration: None)
        self.closed_callback = closed_callback or (lambda: None)
        self.error_callback = error_callback or (lambda _message: None)
        self.active = False
        self.markers = []
        self.speaker_screen = None
        self.audience_screen = None
        self.saved_geometry = None
        self.selection_token = None
        self.configuration_screens = []
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
        self.selection_token = None
        self.configuration_screens = []
        self.closed_callback()
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
        self.selection_token = None
        self.configuration_screens = []
        self.closed_callback()
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
        self.clear_markers()
        screens = list(self.app.screens())
        if not screens:
            self.selection_token = None
            self.configuration_screens = []
            self.error_callback('Nebyl nalezen žádný dostupný displej.')
            return
        current = self.speaker_screen if self.speaker_screen in screens else self.speaker.screen()
        speaker_index = screens.index(current) if current in screens else 0
        audience_index = screens.index(self.audience_screen) if self.audience_screen in screens else -1
        if audience_index == speaker_index:
            audience_index = -1
        items = []
        for index, screen in enumerate(screens):
            rect = screen.geometry()
            items.append({'index': index, 'label':
                          f'{index + 1} · {screen.name()} · {rect.width()} × {rect.height()}'})
        self.selection_token = str(uuid4())
        self.configuration_screens = screens
        self.configuration_callback({'token': self.selection_token, 'screens': items,
                                     'speaker': speaker_index, 'audience': audience_index})

    def _selection(self, token, speaker_index, audience_index):
        screens = list(self.app.screens())
        if (token != self.selection_token or screens != self.configuration_screens
                or not isinstance(speaker_index, int) or isinstance(speaker_index, bool)
                or not isinstance(audience_index, int) or isinstance(audience_index, bool)
                or speaker_index < 0 or speaker_index >= len(screens)
                or audience_index < -1 or audience_index >= len(screens)):
            raise ValueError('Výběr displejů už neodpovídá aktuálním obrazovkám.')
        return screens

    def identify_selection(self, token, speaker_index, audience_index):
        screens = self._selection(token, speaker_index, audience_index)
        self.identify(screens, speaker_index, audience_index)

    def apply_selection(self, token, speaker_index, audience_index):
        screens = self._selection(token, speaker_index, audience_index)
        if speaker_index == audience_index:
            raise ValueError('Řečník a diváci musí mít různé displeje.')
        self.speaker_screen = screens[speaker_index]
        self.audience_screen = screens[audience_index] if audience_index >= 0 else None
        self.place(self.speaker, self.speaker_screen)
        if self.audience_screen:
            self.place(self.audience, self.audience_screen, fullscreen=True)
        self.clear_markers()
        self.selection_token = None
        self.configuration_screens = []
        self.closed_callback()
        self.speaker.activateWindow()

    def cancel_configuration(self):
        self.clear_markers()
        self.selection_token = None
        self.configuration_screens = []
        self.audience.hide()
        self.closed_callback()
