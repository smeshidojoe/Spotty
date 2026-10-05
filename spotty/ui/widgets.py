"""
Мелкие элементы настроек: переключатель, кнопка, поле сочетания, сегменты.

Нажатие отзывается сразу, на press, а не на отпускание. Анимирован только
переключатель — это смена состояния, которую полезно увидеть; и то его можно
выключить системной настройкой «Анимация элементов управления».

Кнопки и переключатели фокус не берут. Иначе кнопка «Проверить», выключаясь
на время проверки, передавала фокус следующей кнопке, а страница настроек
прокручивалась к ней — вид прыгал вниз из-под курсора.
"""

from PySide6.QtCore import QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from ..core import hotkey as hotkey_mod
from ..core import winapi
from ..core.i18n import tr
from . import theme


def _mix(a, b, t):
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t),
                  round(a.alpha() + (b.alpha() - a.alpha()) * t))


class Toggle(QAbstractButton):
    OFF = QColor(255, 255, 255, 40)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(40, 24)
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(theme.ease_out())
        self._anim.valueChanged.connect(self._on_value)
        self.toggled.connect(self._animate)

    def set_silently(self, checked):
        """Выставить без сигнала и без анимации — при открытии настроек."""
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._anim.stop()
        self._pos = 1.0 if checked else 0.0
        self.update()

    def _animate(self, checked):
        target = 1.0 if checked else 0.0
        if not winapi.animations_enabled():
            self._pos = target
            self.update()
            return
        # С текущего положения, а не с края: повторный клик посреди движения
        # разворачивает ручку без скачка.
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_value(self, value):
        self._pos = float(value)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_mix(self.OFF, theme.ACCENT, self._pos))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        d = rect.height() - 4
        x = rect.left() + 2 + (rect.width() - d - 4) * self._pos
        # Нажатая ручка чуть темнеет — отклик на press.
        p.setBrush(QColor(235, 235, 240) if self.isDown() else QColor("white"))
        p.drawEllipse(QRectF(x, rect.top() + 2, d, d))


class Button(QAbstractButton):
    """accent=True — синяя кнопка главного действия («Перезапустить и обновить»)."""

    def __init__(self, text="", parent=None, danger=False, accent=False):
        super().__init__(parent)
        self.setText(text)
        self._danger = danger
        self._accent = accent
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFont(theme.font(13, QFont.Weight.Medium))

    def set_danger(self, on):
        self._danger = on
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        width = self.fontMetrics().horizontalAdvance(self.text()) if self.text() else 0
        return QSize(max(28, width + 24), 28)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        if self._accent:
            # Нажатая темнеет, под курсором светлеет — как Toggle.
            p.setBrush(theme.ACCENT.darker(115) if self.isDown()
                       else theme.ACCENT.lighter(112) if self.underMouse() else theme.ACCENT)
        else:
            alpha = 40 if self.isDown() else 30 if self.underMouse() else 20
            if not self.isEnabled():
                alpha = 10
            p.setBrush(QColor(255, 255, 255, alpha))
        p.drawRoundedRect(rect, 8, 8)
        p.setFont(self.font())
        color = QColor("white") if self._accent else theme.DANGER if self._danger else theme.TEXT
        if not self.isEnabled():
            color = theme.TEXT_FAINT
        p.setPen(color)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())


class HotkeyField(QAbstractButton):
    """
    Поле сочетания клавиш. Клик — запись: следующее нажатие с модификатором
    становится новым сочетанием, Esc отменяет.

    Пока идёт запись, глобальный хоткей надо снять (сигнал recording): иначе
    нажатие текущего сочетания перехватит Windows и сюда оно не дойдёт.
    """

    changed = Signal(str)
    recording = Signal(bool)

    def __init__(self, combo, parent=None):
        super().__init__(parent)
        self.combo = combo
        self._recording = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(28)
        self.clicked.connect(self.start)

    def sizeHint(self):
        return QSize(140, 28)

    def is_recording(self):
        return self._recording

    def set_combo(self, combo):
        self.combo = combo
        self.update()

    def start(self):
        if self._recording:
            return
        self._recording = True
        self.recording.emit(True)
        self.setFocus()
        self.grabKeyboard()
        self.update()

    def stop(self):
        if not self._recording:
            return
        self._recording = False
        self.releaseKeyboard()
        self.recording.emit(False)
        self.update()

    def keyPressEvent(self, event):
        if not self._recording:
            return super().keyPressEvent(event)
        if event.key() == Qt.Key.Key_Escape:
            self.stop()
            return
        combo = hotkey_mod.from_qt(event.key(), event.modifiers(),
                                   event.nativeVirtualKey())
        if combo:
            self.stop()
            self.changed.emit(combo)

    def focusOutEvent(self, event):
        self.stop()
        super().focusOutEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        if self._recording:
            p.setBrush(QColor(10, 132, 255, 60))
        else:
            p.setBrush(QColor(255, 255, 255, 30 if self.underMouse() else 18))
        p.drawRoundedRect(rect, 8, 8)
        if self._recording:
            p.setFont(theme.font(13))
            p.setPen(theme.TEXT)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr("settings.hotkey_wait"))
            return
        labels = hotkey_mod.keycaps(self.combo)
        width = theme.keycaps_width(p, labels)
        theme.draw_keycaps(p, rect.center().x() - width / 2, rect.center().y(), labels)


class Segmented(QWidget):
    """Выбор одного из нескольких: [English | Русский]."""

    changed = Signal(str)

    def __init__(self, options, current, parent=None):
        super().__init__(parent)
        self.options = options          # [(значение, подпись)]
        self.current = current
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(28)
        self.setFont(theme.font(13))
        self._rects = []

    def sizeHint(self):
        fm = self.fontMetrics()
        width = sum(fm.horizontalAdvance(label) + 28 for _, label in self.options)
        return QSize(max(width, 200), 28)

    def _layout(self):
        fm = self.fontMetrics()
        widths = [fm.horizontalAdvance(label) + 28 for _, label in self.options]
        scale = self.width() / max(1, sum(widths))
        x, self._rects = 0.0, []
        for w in widths:
            self._rects.append(QRectF(x, 0, w * scale, self.height()))
            x += w * scale

    def mousePressEvent(self, event):
        self._layout()
        for (value, _), rect in zip(self.options, self._rects):
            if rect.contains(event.position()) and value != self.current:
                self.current = value
                self.update()
                self.changed.emit(value)
                return

    def paintEvent(self, _event):
        self._layout()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        p.setFont(theme.font(13))
        for (value, label), rect in zip(self.options, self._rects):
            if value == self.current:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 46))
                p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)
            p.setPen(theme.TEXT if value == self.current else theme.TEXT_DIM)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
