"""
Своя плашка в углу экрана вместо системного уведомления (как в Knack).

Уведомления Windows доходят не всегда: «Фокусировка внимания», выключенные
уведомления приложения, полноэкранная игра — и сообщение о новой версии
просто пропадает. Поэтому рисуем свою, в стиле строки.

Правый нижний угол рабочей области экрана, где сейчас курсор, — там же, где
системные. Появляется за 220 мс (прозрачность и подъём на 12 px), уходит
быстрее — за 160 мс: приходит она, когда решила программа, а уходит, когда
человек уже всё решил. Пока курсор на плашке, она не исчезает.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..core import winapi
from . import appicon, theme

WIDTH = 340
HEIGHT = 64               # с подзаголовком; без него — SINGLE
SINGLE = 52
MARGIN = 16               # от края рабочей области
SHADOW = 18
RISE = 12
ICON = 30
CLOSE = 20
ENTER_MS, EXIT_MS = 220, 160
DEFAULT_MS = 5000         # короткое сообщение; 0 — висит, пока не тронут


class Toast(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.title = ""
        self.subtitle = ""
        self.tag = ""
        self._on_click = None
        self._on_close = None
        self._hover = False
        self._hover_close = False
        self._pressed = False
        self._screen = None
        self._shadows = {}
        self._value = 0.0         # 0 — спрятана, 1 — на месте
        self._target = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(theme.ease_out())
        self._anim.valueChanged.connect(self._on_value)
        self._anim.finished.connect(self._on_finished)
        self._life = QTimer(self, singleShot=True)
        self._life.timeout.connect(self.close_message)
        self._left = 0            # сколько оставалось жить, когда навели курсор

    # --- показ ------------------------------------------------------------- #

    def show_message(self, title, subtitle="", timeout_ms=DEFAULT_MS, on_click=None,
                     on_close=None, tag=""):
        """
        on_click — что сделать по клику (плашка при этом закрывается);
        on_close — по крестику. tag — метка, чтобы потом закрыть именно эту
        плашку (close_message(tag)), не задев сменившую её.
        """
        self.title, self.subtitle, self.tag = title, subtitle, tag
        self._on_click, self._on_close = on_click, on_close
        self._pressed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor if on_click
                       else Qt.CursorShape.ArrowCursor)
        self._life.stop()
        self._left = timeout_ms
        if timeout_ms and not self._hover:
            self._life.start(timeout_ms)
        # Экран выбираем один раз: иначе мышь, уведённая на другой монитор,
        # перебросила бы плашку посреди появления.
        if not self.isVisible() or self._value < 0.5:
            self._screen = (QGuiApplication.screenAt(QCursor.pos())
                            or QGuiApplication.primaryScreen())
        self._place()             # высота могла смениться вместе с текстом
        self._animate(1.0, ENTER_MS)
        self.update()

    def close_message(self, tag=None):
        if tag is not None and tag != self.tag:
            return
        self._life.stop()
        if self.isVisible():
            self._animate(0.0, EXIT_MS)

    def is_showing(self, tag):
        return self.isVisible() and self.tag == tag and self._target == 1.0

    def _animate(self, target, duration):
        self._target = target
        self._anim.stop()
        if not winapi.animations_enabled():
            self._on_value(target)
            self._on_finished()
            return
        self._anim.setDuration(duration)
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_value(self, value):
        self._value = float(value)
        self._place()
        self.setWindowOpacity(self._value)
        if self._value > 0 and not self.isVisible():
            self.show()

    def _on_finished(self):
        if self._value <= 0.001:
            self.hide()
            self.tag = ""

    def _height(self):
        return HEIGHT if self.subtitle else SINGLE

    def _place(self):
        screen = self._screen or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        w, h = WIDTH + SHADOW * 2, self._height() + SHADOW * 2
        rise = 0 if not winapi.animations_enabled() else round(RISE * (1.0 - self._value))
        self.setGeometry(area.right() + 1 - MARGIN - WIDTH - SHADOW,
                         area.bottom() + 1 - MARGIN - self._height() - SHADOW + rise, w, h)

    # --- мышь -------------------------------------------------------------- #

    def _card(self):
        return QRectF(SHADOW, SHADOW, WIDTH, self._height())

    def _close_rect(self):
        card = self._card()
        return QRectF(card.right() - 8 - CLOSE, card.top() + 8, CLOSE, CLOSE)

    def enterEvent(self, event):
        self._hover = True
        if self._life.isActive():
            self._left = self._life.remainingTime()
            self._life.stop()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = self._hover_close = self._pressed = False
        # Дочитать не дали — даём ещё немного, а не прячем сразу.
        if self._left and self.isVisible():
            self._life.start(max(self._left, 1500))
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        near = self._close_rect().contains(event.position())
        if near != self._hover_close:
            self._hover_close = near
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._card().contains(event.position()):
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self._pressed:
            return
        self._pressed = False
        pos = event.position()
        if self._close_rect().contains(pos):
            callback = self._on_close
        elif self._card().contains(pos):
            callback = self._on_click
            if callback is None:
                return
        else:
            self.update()
            return
        self.close_message()
        if callback is not None:
            callback()

    # --- отрисовка --------------------------------------------------------- #

    def _shadow(self):
        h = self._height()
        if h not in self._shadows:
            self._shadows[h] = theme.blurred_shadow(WIDTH, h, 14, SHADOW, QColor(0, 0, 0, 150))
        return self._shadows[h]

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        shadow = self._shadow()
        p.drawImage(QRectF(0, 4, shadow.width(), shadow.height()), shadow)

        card = self._card()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.MENU_BG)
        p.drawRoundedRect(card, 14, 14)
        if self._on_click and (self._hover or self._pressed):
            p.setBrush(QColor(255, 255, 255, 14 if self._pressed else 8))
            p.drawRoundedRect(card, 14, 14)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.BORDER, 1))
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 13.5, 13.5)

        icon = QRectF(card.left() + 14, card.center().y() - ICON / 2, ICON, ICON)
        appicon.paint(p, icon, edge=True)

        left = icon.right() + 12
        right = card.right() - (CLOSE + 14 if self._hover else 14)
        width = right - left
        title_font = theme.font(13, QFont.Weight.DemiBold)
        p.setFont(title_font)
        p.setPen(theme.TEXT)
        fm = p.fontMetrics()
        if self.subtitle:
            title_rect = QRectF(left, card.top() + 13, width, 18)
        else:
            title_rect = QRectF(left, card.top(), width, card.height())
        p.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   fm.elidedText(self.title, Qt.TextElideMode.ElideRight, int(width)))
        if self.subtitle:
            p.setFont(theme.font(12))
            p.setPen(theme.TEXT_DIM)
            fm = p.fontMetrics()
            p.drawText(QRectF(left, card.top() + 33, width, 17),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       fm.elidedText(self.subtitle, Qt.TextElideMode.ElideRight, int(width)))

        # Крестик — только при наведении: в покое плашка чище.
        if not self._hover:
            return
        rect = self._close_rect()
        if self._hover_close:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 28))
            p.drawEllipse(rect)
        p.setPen(QPen(theme.TEXT if self._hover_close else theme.TEXT_DIM, 1.4,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c, d = rect.center(), 3.6
        p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
        p.drawLine(QPointF(c.x() + d, c.y() - d), QPointF(c.x() - d, c.y() + d))
