"""
Меню действий по Ctrl+K — всплывает над кнопкой «Действия» в нижней полосе.

Это дочерний виджет строки, а не отдельное окно: фокус остаётся в строке
ввода, и вся клавиатура идёт через неё. Открывается без анимации — вызывается
с клавиатуры, а такое открывают сотни раз в день.
"""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme

ROW = 34
PAD = 6
WIDTH = 320
SHADOW_BLUR = 18


class ActionsMenu(QWidget):
    triggered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.actions_ = []
        self.current = 0
        self._shadow = None
        self.hide()

    def open(self, actions, right, bottom):
        """Показать список так, чтобы правый нижний угол пришёлся на (right, bottom)."""
        self.actions_ = actions
        self.current = 0
        height = PAD * 2 + ROW * len(actions)
        # Поле под тень входит в виджет, сама плашка — внутри.
        m = SHADOW_BLUR
        self.setGeometry(int(right - WIDTH - m), int(bottom - height - m),
                         WIDTH + m * 2, height + m * 2)
        self._shadow = theme.blurred_shadow(WIDTH, height, 12, SHADOW_BLUR,
                                            QColor(0, 0, 0, 150))
        self.show()
        self.raise_()

    def close_menu(self):
        self.hide()

    def is_open(self):
        # isHidden, а не isVisible: второе ложно, пока скрыта сама строка.
        return not self.isHidden()

    def move_selection(self, step):
        # По кругу: вверх с первого пункта — на последний. Пунктов меньше
        # десятка, и до нижнего так ближе, чем стрелкой через весь список.
        if self.actions_:
            self.current = (self.current + step) % len(self.actions_)
            self.update()

    def activate(self):
        if self.actions_:
            self.triggered.emit(self.actions_[self.current].id)

    def _card(self):
        m = SHADOW_BLUR
        return QRectF(m, m, self.width() - m * 2, self.height() - m * 2)

    def _row_at(self, pos):
        card = self._card()
        row = int((pos.y() - card.top() - PAD) // ROW)
        return row if card.contains(pos) and 0 <= row < len(self.actions_) else -1

    def mouseMoveEvent(self, event):
        row = self._row_at(event.position())
        if row >= 0 and row != self.current:
            self.current = row
            self.update()

    def mousePressEvent(self, event):
        row = self._row_at(event.position())
        if row >= 0:
            self.current = row
            self.update()

    def mouseReleaseEvent(self, event):
        if self._row_at(event.position()) == self.current:
            self.activate()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        card = self._card()
        if self._shadow is not None:
            p.drawImage(QRectF(0, 6, self._shadow.width(), self._shadow.height()),
                        self._shadow)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.MENU_BG)
        p.drawRoundedRect(card, 12, 12)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.BORDER, 1))
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 11.5, 11.5)

        for i, action in enumerate(self.actions_):
            row = QRectF(card.left() + PAD, card.top() + PAD + i * ROW,
                         card.width() - PAD * 2, ROW)
            if i == self.current:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.SELECTION)
                p.drawRoundedRect(row, 8, 8)
            keys_w = theme.keycaps_width(p, action.keys) if action.keys else 0
            p.setFont(theme.font(13, QFont.Weight.Medium if i == 0 else QFont.Weight.Normal))
            p.setPen(theme.TEXT)
            text_rect = row.adjusted(10, 0, -(keys_w + 16), 0)
            title = p.fontMetrics().elidedText(action.title, Qt.TextElideMode.ElideRight,
                                               int(text_rect.width()))
            p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       title)
            if action.keys:
                theme.draw_keycaps(p, row.right() - 8 - keys_w, row.center().y(),
                                   action.keys)
