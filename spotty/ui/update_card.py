"""
Карточка установки обновления поверх строки (как в Knack).

Пока качается новая версия, строку нельзя ни закрыть, ни потыкать: сейчас
Spotty подменит собственный exe и перезапустится, и начатое в строке всё равно
пропадёт. Поэтому строка затемняется, поверх выплывает карточка с полосой
прогресса, а клики и клавиши до строки не доходят. Закрыть её не дают ни Esc,
ни клик мимо, ни сочетание вызова — см. Panel.locked().

Карточка — это когда человек сам нажал «Установить» и ждёт. Фоновая загрузка
строку не трогает: там в конце появляется кнопка «Перезапустить и обновить».
"""

from PySide6.QtCore import QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..core import winapi
from ..core.i18n import tr
from . import theme

CARD_W, CARD_H, CARD_R = 340, 104, 16
BAR_W, BAR_H = 292, 6
RISE = 14
APPEAR_MS = 260
BAR_MS = 220              # полоса догоняет новое значение, а не прыгает
DIM = QColor(8, 8, 12, 150)


class UpdateCard(QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.title = ""
        self.restarting = False
        self._target = 0.0          # доля скачанного
        self._shown_fraction = 0.0  # то, что сейчас нарисовано
        self._appear = 0.0
        self._appear_anim = QVariantAnimation(self)
        self._appear_anim.setEasingCurve(theme.ease_out())
        self._appear_anim.setDuration(APPEAR_MS)
        self._appear_anim.valueChanged.connect(self._on_appear)
        self._bar = QVariantAnimation(self)
        self._bar.setEasingCurve(theme.ease_out())
        self._bar.setDuration(BAR_MS)
        self._bar.valueChanged.connect(self._on_bar)
        self._shadow = theme.blurred_shadow(CARD_W, CARD_H, CARD_R, 20, QColor(0, 0, 0, 120))
        self.hide()

    # --- состояние --------------------------------------------------------- #

    def blocking(self):
        return self.isVisible()

    def start(self, version, fraction=0.0, restarting=False):
        self.title = tr("update.card", version=version)
        self.restarting = restarting
        self._bar.stop()
        self._target = self._shown_fraction = max(0.0, min(1.0, fraction))
        self.setGeometry(self.panel.rect())
        if not self.isVisible():
            self._appear = 0.0
            self.show()
            if winapi.animations_enabled():
                self._appear_anim.setStartValue(0.0)
                self._appear_anim.setEndValue(1.0)
                self._appear_anim.start()
            else:
                self._appear = 1.0
        self.raise_()
        self.setFocus()
        self.update()

    def set_progress(self, fraction):
        fraction = max(0.0, min(1.0, float(fraction or 0.0)))
        if fraction <= self._target:
            return
        self._target = fraction
        if not winapi.animations_enabled():
            self._shown_fraction = fraction
            self.update()
            return
        self._bar.stop()
        self._bar.setStartValue(self._shown_fraction)
        self._bar.setEndValue(fraction)
        self._bar.start()

    def set_restarting(self):
        self.restarting = True
        self.set_progress(1.0)
        self.update()

    def finish(self):
        self._appear_anim.stop()
        self._bar.stop()
        self.hide()

    def _on_appear(self, value):
        self._appear = float(value)
        self.update()

    def _on_bar(self, value):
        self._shown_fraction = float(value)
        self.update()

    # --- ввод не пропускаем ------------------------------------------------ #

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        event.accept()

    def keyPressEvent(self, event):
        event.accept()

    # --- отрисовка --------------------------------------------------------- #

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        t = self._appear

        # Затемнение по форме строки, чтобы не залезть в тень вокруг неё.
        panel = QRectF(self.panel.panel_rect())
        shape = QPainterPath()
        shape.addRoundedRect(panel, theme.RADIUS, theme.RADIUS)
        dim = QColor(DIM)
        dim.setAlphaF(DIM.alphaF() * t)
        p.fillPath(shape, dim)

        rise = RISE * (1.0 - t) if winapi.animations_enabled() else 0.0
        card = QRectF(panel.center().x() - CARD_W / 2,
                      panel.center().y() - CARD_H / 2 + rise, CARD_W, CARD_H)
        p.setOpacity(t)
        p.drawImage(QRectF(card.left() - 20, card.top() - 16, self._shadow.width(),
                           self._shadow.height()), self._shadow)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.MENU_BG)
        p.drawRoundedRect(card, CARD_R, CARD_R)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.BORDER, 1))
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), CARD_R - 0.5, CARD_R - 0.5)

        p.setFont(theme.font(15, QFont.Weight.DemiBold))
        p.setPen(theme.TEXT)
        p.drawText(QRectF(card.left() + 20, card.top() + 18, CARD_W - 40, 22),
                   Qt.AlignmentFlag.AlignCenter, self.title)

        bar = QRectF(card.center().x() - BAR_W / 2, card.top() + 54, BAR_W, BAR_H)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 28))
        p.drawRoundedRect(bar, BAR_H / 2, BAR_H / 2)
        if self._shown_fraction > 0:
            filled = QRectF(bar.left(), bar.top(), max(BAR_H, BAR_W * self._shown_fraction),
                            BAR_H)
            p.setBrush(theme.ACCENT)
            p.drawRoundedRect(filled, BAR_H / 2, BAR_H / 2)

        p.setFont(theme.font(12))
        p.setPen(theme.TEXT_DIM)
        below = QRectF(bar.left(), bar.bottom() + 8, BAR_W, 18)
        status = tr("update.restarting") if self.restarting else tr("update.card_downloading")
        p.drawText(below, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, status)
        if not self.restarting:
            p.drawText(below, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       "%d%%" % round(self._target * 100))
