"""
Нижняя полоса: слева кнопка настроек, справа подсказки «Открыть ↵ | Действия Ctrl K».

Подсказки кликабельны: не все помнят сочетания, и мышь должна уметь то же,
что клавиатура.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..actions import ENTER
from ..core.constants import APP_VERSION
from ..core.i18n import tr
from . import theme


class Footer(QWidget):
    primary_clicked = Signal()
    actions_clicked = Signal()
    settings_clicked = Signal()
    back_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.mode = "search"
        self.primary = ""
        self.has_actions = False
        self._zones = {}              # имя -> QRectF, пересчитываются при рисовании
        self._hover = None
        self._pressed = None

    def set_primary(self, label, has_actions):
        if (label, has_actions) != (self.primary, self.has_actions):
            self.primary, self.has_actions = label, has_actions
            self.update()

    def set_mode(self, mode):
        self.mode = mode
        self._hover = None
        self.update()

    # --- мышь -------------------------------------------------------------- #

    def _zone_at(self, pos):
        for name, rect in self._zones.items():
            if rect.contains(pos):
                return name
        return None

    def mouseMoveEvent(self, event):
        zone = self._zone_at(event.position())
        if zone != self._hover:
            self._hover = zone
            self.setCursor(Qt.CursorShape.PointingHandCursor if zone
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, _event):
        self._hover = None
        self.update()

    def mousePressEvent(self, event):
        self._pressed = self._zone_at(event.position())
        self.update()

    def mouseReleaseEvent(self, event):
        zone = self._zone_at(event.position())
        pressed, self._pressed = self._pressed, None
        self.update()
        if zone and zone == pressed:
            {"primary": self.primary_clicked, "actions": self.actions_clicked,
             "settings": self.settings_clicked, "back": self.back_clicked}[zone].emit()

    # --- отрисовка --------------------------------------------------------- #

    def _zone_bg(self, p, name, rect):
        if name == self._pressed:
            alpha = 34
        elif name == self._hover:
            alpha = 20
        else:
            return
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, alpha))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self._zones = {}
        cy = self.height() / 2
        if self.mode == "settings":
            self._paint_settings(p, cy)
        else:
            self._paint_search(p, cy)

    def _paint_settings_button(self, p, cy):
        rect = QRectF(12, cy - 16, 32, 32)
        self._zones["settings"] = rect
        p.setPen(Qt.PenStyle.NoPen)
        base = 30 if self._hover == "settings" else 18
        p.setBrush(QColor(255, 255, 255, 44 if self._pressed == "settings" else base))
        p.drawEllipse(rect)
        # Две полосы, нижняя короче — как на референсе.
        p.setPen(QPen(theme.TEXT_DIM, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c = rect.center()
        p.drawLine(QPointF(c.x() - 6, c.y() - 3), QPointF(c.x() + 6, c.y() - 3))
        p.drawLine(QPointF(c.x() - 6, c.y() + 3), QPointF(c.x() + 2, c.y() + 3))

    def _paint_search(self, p, cy):
        self._paint_settings_button(p, cy)
        if not self.primary:
            return
        right = self.width() - 12.0
        text_font = theme.font(13, QFont.Weight.Medium)

        # Справа налево: «Действия Ctrl K», разделитель, «Открыть ↵».
        zones = []
        if self.has_actions:
            zones.append(("actions", tr("footer.actions"), ["Ctrl", "K"]))
        zones.append(("primary", self.primary, [ENTER]))
        for i, (name, label, keys) in enumerate(zones):
            p.setFont(text_font)
            label_w = p.fontMetrics().horizontalAdvance(label)
            keys_w = theme.keycaps_width(p, keys)
            width = 10 + label_w + 8 + keys_w + 6
            rect = QRectF(right - width, cy - 15, width, 30)
            self._zones[name] = rect
            self._zone_bg(p, name, rect)
            p.setFont(text_font)
            p.setPen(theme.TEXT if name == "primary" else theme.TEXT_DIM)
            p.drawText(QRectF(rect.left() + 10, rect.top(), label_w + 1, rect.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
            theme.draw_keycaps(p, rect.left() + 10 + label_w + 8, cy, keys)
            right = rect.left()
            if i < len(zones) - 1:
                p.setPen(QPen(theme.HAIRLINE, 1))
                p.drawLine(QPointF(right - 6, cy - 9), QPointF(right - 6, cy + 9))
                right -= 12

    def _paint_settings(self, p, cy):
        p.setFont(theme.font(12))
        p.setPen(theme.TEXT_FAINT)
        p.drawText(QRectF(18, 0, 300, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "Spotty " + APP_VERSION)
        label = tr("footer.back")
        p.setFont(theme.font(13, QFont.Weight.Medium))
        label_w = p.fontMetrics().horizontalAdvance(label)
        keys_w = theme.keycaps_width(p, ["Esc"])
        width = 10 + label_w + 8 + keys_w + 6
        rect = QRectF(self.width() - 12 - width, cy - 15, width, 30)
        self._zones["back"] = rect
        self._zone_bg(p, "back", rect)
        p.setFont(theme.font(13, QFont.Weight.Medium))
        p.setPen(theme.TEXT)
        p.drawText(QRectF(rect.left() + 10, rect.top(), label_w + 1, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        theme.draw_keycaps(p, rect.left() + 10 + label_w + 8, cy, ["Esc"])
