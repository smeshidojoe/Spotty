"""
Короткая подсказка внизу экрана: «Скопировано», «Скачиваю обновление…».

Строка к этому моменту уже закрыта, а подтвердить действие надо — отдельное
окошко без фокуса, сквозь которое проходят клики. Появление — 150 мс, уход —
200 мс, ease-out: это обратная связь, её стоит заметить, но не ждать.
"""

from PySide6.QtCore import QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..core import winapi
from . import theme

HOLD_MS = 1400


class Hud(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.text = ""
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(theme.ease_out())
        self._fade.finished.connect(self._on_faded)
        self._hold = QTimer(self, singleShot=True, interval=HOLD_MS)
        self._hold.timeout.connect(self._fade_out)

    def show_text(self, text):
        self.text = text
        self.setFont(theme.font(14, QFont.Weight.Medium))
        width = self.fontMetrics().horizontalAdvance(text) + 44
        height = 40
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.setGeometry(area.center().x() - width // 2,
                         area.bottom() - height - int(area.height() * 0.12),
                         width, height)
        self._fade.stop()
        if winapi.animations_enabled():
            self.setWindowOpacity(0.0 if not self.isVisible() else self.windowOpacity())
            self.show()
            self._fade.setDuration(150)
            self._fade.setStartValue(self.windowOpacity())
            self._fade.setEndValue(1.0)
            self._fade.start()
        else:
            self.setWindowOpacity(1.0)
            self.show()
        self.update()
        self._hold.start()

    def _fade_out(self):
        if not winapi.animations_enabled():
            self.hide()
            return
        self._fade.stop()
        self._fade.setDuration(200)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_faded(self):
        if self.windowOpacity() <= 0.01:
            self.hide()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.BORDER, 1))
        p.setBrush(theme.MENU_BG)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setFont(self.font())
        p.setPen(theme.TEXT)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text)
