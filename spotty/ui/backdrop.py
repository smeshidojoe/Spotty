"""
Подложка строки: тень, стекло (или сплошной фон), затемнение и кромка.

Стекло считается один раз на показ: снимок экрана под окном -> шейдер из
CopyPasta -> готовая картинка, которую paintEvent только накладывает. Строка
не двигается, поэтому пересчитывать нечего — перерисовка списка стоит столько
же, сколько без стекла. С живым фоном (ui/live_glass.py) новые снимки того же
места приходят, пока строка открыта, и стекло пересчитывается из них.
"""

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QTransform

from ..core import logbook
from ..glass import capture
from ..glass.liquid_glass import GlassParams, OffscreenGlassRenderer
from . import theme

# Тёмное стекло: сильное размытие, чтобы фон не спорил с текстом, и узкая
# фаска с лёгким преломлением — край читается как толща стекла.
PARAMS = GlassParams(radius=theme.RADIUS, blur=34.0, bevel=16.0, refract=10.0,
                     tint=(0.07, 0.07, 0.09), tint_amount=0.18)


def to_physical(screen, rect):
    """
    Логический прямоугольник окна -> физические пиксели рабочего стола.

    Qt 6 держит левый верхний угол каждого экрана в родных координатах, а
    размеры внутри экрана делит на масштаб. Поэтому от угла экрана отступаем
    на логическое смещение, умноженное на масштаб.
    """
    dpr = screen.devicePixelRatio()
    origin = screen.geometry().topLeft()
    return QRect(origin.x() + round((rect.x() - origin.x()) * dpr),
                 origin.y() + round((rect.y() - origin.y()) * dpr),
                 round(rect.width() * dpr), round(rect.height() * dpr))


class Backdrop:
    def __init__(self):
        self.glass_enabled = True
        self._renderer = None
        self._broken = False
        self._glass = None           # QImage всего окна в физических пикселях
        self._shot = None            # (снимок экрана, прямоугольник строки, dpr)
        self._where = None           # (что снимали в физических px, прямоугольник строки, dpr)
        self._dpr = 1.0
        self._shadow = None
        self._shadow_key = None

    def warm_up(self, window_size, panel_rect, dpr=1.0):
        """
        Собрать шейдеры и завести буферы нужного размера заранее: первый показ
        не должен ждать ни компиляции, ни выделения видеопамяти.
        """
        if not self.glass_enabled or self._broken:
            return
        from PySide6.QtGui import QImage
        dummy = QImage(round(window_size.width() * dpr), round(window_size.height() * dpr),
                       QImage.Format.Format_RGB32)
        dummy.fill(QColor(40, 40, 40))
        rect = QRectF(panel_rect.x() * dpr, panel_rect.y() * dpr,
                      panel_rect.width() * dpr, panel_rect.height() * dpr)
        self._render(dummy, rect, dpr)
        self._shadow_image(panel_rect)

    def _render(self, source, panel_rect, dpr):
        if self._renderer is None:
            self._renderer = OffscreenGlassRenderer()
        self._renderer.set_source(source)
        p = PARAMS
        scaled = GlassParams(radius=p.radius * dpr, blur=p.blur * dpr,
                             bevel=p.bevel * dpr, refract=p.refract * dpr,
                             tint=p.tint, tint_amount=p.tint_amount)
        image = self._renderer.render(QSize(source.width(), source.height()),
                                      panel_rect, scaled)
        if image is None:
            # OpenGL недоступен (удалённый рабочий стол, старый драйвер) —
            # дальше рисуем сплошной фон и больше не пытаемся.
            self._broken = True
            logbook.log("стекло недоступно: OpenGL не поднялся")
        return image

    def prepare(self, screen, window_rect, panel_rect):
        """
        Снять экран под окном и посчитать стекло. Вызывать ДО show().

        Снимок делаем и при выключенном стекле (около 10 мс) и держим до
        следующего показа: стекло включают в настройках на открытой строке, а
        снять то, что под ней, тогда уже нельзя, не спрятав её. Исключить окно
        из захвата (WDA_EXCLUDEFROMCAPTURE) тоже не выйдет: у полупрозрачных
        окон Windows эту настройку не принимает — только у собранных через GPU,
        а так строка собирается лишь с живым фоном.
        """
        self._glass = None
        self._shot = None
        self._where = None
        if self._broken:
            return
        try:
            phys = to_physical(screen, window_rect)
            dpr = phys.width() / max(1, window_rect.width())
            rect = QRectF(panel_rect.x() * dpr, panel_rect.y() * dpr,
                          panel_rect.width() * dpr, panel_rect.height() * dpr)
            self._where = (phys, rect, dpr)
            shot = capture.grab(phys.x(), phys.y(), phys.width(), phys.height())
            if shot is None:
                return
            self._shot = (shot, rect, dpr)
            self.rebuild()
        except Exception:
            logbook.exc("стекло")
            self._glass = None

    def live_ready(self):
        """Стекло считается и есть что переснимать — живому фону можно работать."""
        return self.glass_enabled and not self._broken and self._where is not None

    def source_rect(self):
        """Что снимает prepare(): область экрана в физических пикселях."""
        return self._where[0] if self._where else None

    def take_shot(self, shot):
        """Новый снимок того же места — от живого фона."""
        if self._where is None:
            return
        _phys, rect, dpr = self._where
        self._shot = (shot, rect, dpr)
        self.rebuild()

    def rebuild(self):
        """Стекло из последнего снимка — когда его включили на открытой строке."""
        self._glass = None
        if not self.glass_enabled or self._broken or self._shot is None:
            return
        shot, rect, dpr = self._shot
        self._glass = self._render(shot, rect, dpr)
        self._dpr = dpr

    def drop(self):
        self._glass = None

    def set_source_image(self, image, panel_rect, dpr=1.0):
        """Стекло поверх готовой картинки — для скриншотов в README."""
        rect = QRectF(panel_rect.x() * dpr, panel_rect.y() * dpr,
                      panel_rect.width() * dpr, panel_rect.height() * dpr)
        self._glass = self._render(image, rect, dpr)
        self._dpr = dpr

    def _shadow_image(self, panel_rect):
        key = (panel_rect.width(), panel_rect.height())
        if self._shadow_key != key:
            self._shadow = theme.blurred_shadow(panel_rect.width(), panel_rect.height(),
                                                theme.RADIUS, 26, QColor(0, 0, 0, 120))
            self._shadow_key = key
        return self._shadow

    def paint(self, p, panel_rect):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(panel_rect)

        shadow = self._shadow_image(panel_rect)
        p.drawImage(QRectF(panel.x() - 26, panel.y() - 26 + 10,
                           shadow.width(), shadow.height()), shadow)

        path = theme.rounded(panel, theme.RADIUS)
        p.setPen(Qt.PenStyle.NoPen)
        if self._glass is not None:
            # Кисть с картинкой, а не setClipPath: обрезка по пути в Qt не
            # сглаживается, углы вышли бы ступенчатыми. Масштаб 1/dpr — чтобы
            # пиксель стекла лёг ровно в пиксель экрана.
            brush = QBrush(self._glass)
            brush.setTransform(QTransform.fromScale(1 / self._dpr, 1 / self._dpr))
            p.setBrush(brush)
            p.drawPath(path)
            p.setBrush(theme.GLASS_OVERLAY)
        else:
            p.setBrush(theme.SOLID)
        p.drawPath(path)

        # Кромка: светлая линия на полпикселя внутрь — ложится ровно в пиксель.
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.BORDER, 1))
        p.drawPath(theme.rounded(panel.adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS - 0.5))
