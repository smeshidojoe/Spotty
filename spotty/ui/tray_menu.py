"""
Меню значка в трее — в стиле строки, а не системное.

Нативное QMenu на Windows рисует система: свой фон, шрифт и отступы. Рядом с
тёмной строкой оно выглядит куском другой программы, поэтому рисуем сами, как
меню действий (Ctrl+K). Так же сделано в Knack.

Окно — Qt.Popup: Qt сам закрывает его по клику мимо и по Esc. Открывается без
анимации, как системное меню: его вызывают, чтобы тут же выбрать пункт.
"""

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..core import winapi
from . import theme

ROW = 32
SEPARATOR = 9
PAD = 5
MIN_WIDTH = 200
CHECK_W = 22          # колонка под галочку, если в меню есть отмечаемые пункты
SHADOW_BLUR = 16


@dataclass
class MenuItem:
    id: str
    title: str
    keys: tuple = ()
    checked: bool | None = None       # None — пункт не отмечаемый


class TrayMenu(QWidget):
    triggered = Signal(str)

    def __init__(self):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.items = []               # MenuItem | None — разделитель
        self.current = -1
        self._rows = []               # (top, height, индекс) внутри плашки
        self._check_w = 0
        self._shadow = None

    # --- показ ------------------------------------------------------------- #

    def popup(self, items, pos):
        """Показать у точки pos (курсор), не вылезая за край рабочей области."""
        self.items = list(items)
        self.current = -1
        width, height = self._measure()
        m = SHADOW_BLUR
        self._shadow = theme.blurred_shadow(width, height, 12, m, QColor(0, 0, 0, 140))

        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(pos.x(), area.left()), area.right() - width)
        # Панель задач снизу — меню раскрывается вверх от курсора, сверху — вниз.
        y = pos.y() - height if pos.y() + height > area.bottom() else pos.y()
        y = min(max(y, area.top()), area.bottom() - height)
        self.setGeometry(x - m, y - m, width + m * 2, height + m * 2)
        self.show()
        self.raise_()
        # Меню из трея открывается, когда программа не на переднем плане: без
        # этого оно не получит клавиатуру, а клик мимо его не закроет.
        self.activateWindow()
        winapi.force_foreground(int(self.winId()))

    def _measure(self):
        checks = any(i is not None and i.checked is not None for i in self.items)
        self._check_w = CHECK_W if checks else 0
        fm = QFontMetrics(theme.font(13))
        width = MIN_WIDTH
        y, self._rows = PAD, []
        for index, item in enumerate(self.items):
            h = SEPARATOR if item is None else ROW
            self._rows.append((y, h, index))
            y += h
            if item is not None:
                keys = theme.keycaps_width(None, item.keys) if item.keys else 0
                width = max(width, 10 + self._check_w + fm.horizontalAdvance(item.title)
                            + (keys + 28 if keys else 0) + 18 + PAD * 2)
        return int(width), y + PAD

    # --- клавиатура -------------------------------------------------------- #

    def _selectable(self):
        return [i for i, item in enumerate(self.items) if item is not None]

    def _move(self, step):
        rows = self._selectable()
        if not rows:
            return
        if self.current not in rows:
            self.current = rows[0] if step > 0 else rows[-1]
        else:
            # По кругу, как в меню действий: вверх с первого — на последний.
            self.current = rows[(rows.index(self.current) + step) % len(rows)]
        self.update()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Down:
            self._move(1)
        elif key == Qt.Key.Key_Up:
            self._move(-1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._activate(self.current)
        else:
            super().keyPressEvent(event)      # Esc закрывает popup сам

    # --- мышь -------------------------------------------------------------- #

    def _card(self):
        m = SHADOW_BLUR
        return QRectF(m, m, self.width() - m * 2, self.height() - m * 2)

    def _index_at(self, pos):
        card = self._card()
        if not card.contains(pos):
            return -1
        y = pos.y() - card.top()
        for top, h, index in self._rows:
            if self.items[index] is not None and top <= y < top + h:
                return index
        return -1

    def mouseMoveEvent(self, event):
        index = self._index_at(event.position())
        if index != self.current:
            self.current = index
            self.update()

    def leaveEvent(self, event):
        self.current = -1
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._activate(self._index_at(event.position()))

    def _activate(self, index):
        if 0 <= index < len(self.items) and self.items[index] is not None:
            item_id = self.items[index].id
            self.close()
            self.triggered.emit(item_id)

    # --- отрисовка --------------------------------------------------------- #

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        card = self._card()
        if self._shadow is not None:
            p.drawImage(QRectF(0, 4, self._shadow.width(), self._shadow.height()),
                        self._shadow)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.MENU_BG)
        p.drawRoundedRect(card, 12, 12)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.BORDER, 1))
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 11.5, 11.5)

        for top, h, index in self._rows:
            item = self.items[index]
            if item is None:
                y = card.top() + top + h / 2 + 0.5
                p.setPen(QPen(theme.HAIRLINE, 1))
                p.drawLine(QPointF(card.left() + 12, y), QPointF(card.right() - 12, y))
                continue
            row = QRectF(card.left() + PAD, card.top() + top, card.width() - PAD * 2, h)
            if index == self.current:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.SELECTION)
                p.drawRoundedRect(row, 8, 8)
            if item.checked:
                self._paint_check(p, QPointF(row.left() + 10 + 6, row.center().y()))
            text_left = row.left() + 10 + self._check_w
            keys_w = theme.keycaps_width(p, item.keys) if item.keys else 0
            p.setFont(theme.font(13, QFont.Weight.Normal))
            p.setPen(theme.TEXT)
            p.drawText(QRectF(text_left, row.top(), row.right() - text_left, h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, item.title)
            if item.keys:
                theme.draw_keycaps(p, row.right() - 8 - keys_w, row.center().y(), item.keys)

    @staticmethod
    def _paint_check(p, center):
        p.save()
        p.setPen(QPen(theme.TEXT, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline([QPointF(center.x() - 5, center.y()),
                        QPointF(center.x() - 1.5, center.y() + 3.5),
                        QPointF(center.x() + 5, center.y() - 4)])
        p.restore()
