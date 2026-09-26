"""
Иконка Spotty — в одном стиле с Knack: плоская чёрная плитка и толстая белая
лупа. Без градиентов и бликов: знак должен читаться и на 16 px, и в трее.

Рисуется кодом, а не хранится картинкой: этим же кодом tools/make_assets.py
собирает app.ico, а в рантайме — значок в трее и у встроенных команд.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

PLATE = QColor("#000000")
GLYPH = QColor("#ffffff")


def _magnifier(p, rect, color, weight=1.0):
    """
    Лупа, вписанная в rect: кольцо сверху слева, ручка вниз направо.
    weight > 1 — толще штрих: на мелких размерах тонкая линия расплывается.
    """
    s = rect.width()
    x0, y0 = rect.x(), rect.y()
    stroke = s * 0.13 * weight
    radius = s * 0.27
    center = QPointF(x0 + s * 0.42, y0 + s * 0.42)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawEllipse(center, radius, radius)
    start = radius + stroke * 0.5
    p.drawLine(QPointF(center.x() + start * 0.7071, center.y() + start * 0.7071),
               QPointF(x0 + s * 0.84, y0 + s * 0.84))


def paint(p, rect, edge=False):
    """
    Иконка приложения в rect: плитка и лупа.
    edge=True — тонкая светлая кромка, чтобы чёрная плитка не терялась на
    тёмном фоне (в списке строки).
    """
    rect = QRectF(rect)
    s = rect.width()
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    tile = rect.adjusted(s * 0.03, s * 0.03, -s * 0.03, -s * 0.03)
    path = QPainterPath()
    path.addRoundedRect(tile, tile.width() * 0.22, tile.width() * 0.22)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(PLATE)
    p.drawPath(path)
    if edge:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 46), 1))
        p.drawPath(path)
    inner = tile.width() * 0.56
    glyph = QRectF(tile.center().x() - inner / 2, tile.center().y() - inner / 2,
                   inner, inner)
    _magnifier(p, glyph, GLYPH, weight=1.25 if s <= 24 else 1.0)
    p.restore()


def pixmap(size):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint(p, QRectF(0, 0, size, size))
    p.end()
    return pm


# --- трей ------------------------------------------------------------------- #

# Размеры, которые Windows спрашивает у значка в трее при разных масштабах.
TRAY_SIZES = (16, 20, 24, 32, 40, 48)
# Доля клетки под знак: соседние значки в трее нарисованы с полями, и лупа во
# всю клетку выглядела бы крупнее остальных. Так же сделано в Knack.
TRAY_GLYPH_RATIO = 0.8


def tray_pixmap(size, color):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    glyph = size * TRAY_GLYPH_RATIO
    offset = (size - glyph) / 2
    _magnifier(p, QRectF(offset, offset, glyph, glyph), color,
               weight=1.35 if size <= 20 else 1.15)
    p.end()
    return pm
