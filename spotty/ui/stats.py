"""
Страница «Статистика» — как и настройки, живёт внутри строки вместо списка.

Цифры собирает search/stats.py; здесь только показ. Цвет у данных один —
синий акцент: везде это «сколько», а не разные сущности, и раскрашивать
типы пунктов в разные цвета незачем — подпись стоит рядом. Подписи и числа —
цветом текста, не цветом столбика.
"""

import datetime

from PySide6.QtCore import QLineF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..core.i18n import language, tr
from . import theme
from .settings import _Card, _label
from .widgets import Button

_TRACK = QColor(255, 255, 255, 12)
_BAR_HOVER = theme.ACCENT.lighter(125)
_RESET_CONFIRM_MS = 4000


# --- числа и даты ----------------------------------------------------------- #

def number(n):
    text = "{:,}".format(int(n))
    return text.replace(",", " ") if language() == "ru" else text


def decimal(x):
    text = "%.1f" % x
    return text.replace(".", ",") if language() == "ru" else text


def percent(share):
    if 0 < share < 0.005:
        return "<1 %" if language() == "ru" else "<1%"
    value = round(share * 100)
    return ("%d %%" if language() == "ru" else "%d%%") % value


def short_date(day):
    month = tr("stats.months").split()[day.month - 1]
    return "%d %s" % (day.day, month) if language() == "ru" else "%s %d" % (month, day.day)


def long_date(day):
    month = tr("stats.months").split()[day.month - 1]
    if language() == "ru":
        return "%d %s %d" % (day.day, month, day.year)
    return "%s %d, %d" % (month, day.day, day.year)


def _bar(p, rect, color, radius=4):
    """Столбик со скруглённым верхом и прямым низом — стоит на оси."""
    radius = min(radius, rect.width() / 2, rect.height())
    path = QPainterPath()
    path.moveTo(rect.left(), rect.bottom())
    path.lineTo(rect.left(), rect.top() + radius)
    path.quadTo(rect.left(), rect.top(), rect.left() + radius, rect.top())
    path.lineTo(rect.right() - radius, rect.top())
    path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + radius)
    path.lineTo(rect.right(), rect.bottom())
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(path)


def _pill(p, rect, color):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)


# --- куски страницы ---------------------------------------------------------- #

class _Totals(QWidget):
    """Таблица: строки «Открытия строки», «Действия»; столбцы — сегодня, 7 дней, всего."""

    COL = 110

    def __init__(self):
        super().__init__()
        self.setFixedHeight(96)
        self.rows = []

    def set_rows(self, rows):
        self.rows = rows
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        right = self.width() - 16
        heads = [tr("stats.today"), tr("stats.week"), tr("stats.total")]
        p.setFont(theme.font(12, QFont.Weight.DemiBold))
        p.setPen(theme.TEXT_FAINT)
        for i, head in enumerate(heads):
            x = right - (len(heads) - i) * self.COL
            p.drawText(QRectF(x, 10, self.COL, 22),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, head)
        for r, (label, values) in enumerate(self.rows):
            top = 36 + r * 28
            p.setFont(theme.font(14))
            p.setPen(theme.TEXT)
            p.drawText(QRectF(14, top, 260, 26),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            p.setFont(theme.font(15, QFont.Weight.DemiBold))
            for i, value in enumerate(values):
                x = right - (len(values) - i) * self.COL
                p.drawText(QRectF(x, top, self.COL, 26),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           number(value))


class _DailyChart(QWidget):
    """
    Открытия строки по дням. Один ряд — легенда не нужна, его называет
    заголовок. Наведение на день показывает его цифры на месте заголовка.
    """

    def __init__(self):
        super().__init__()
        self.setFixedHeight(156)
        self.setMouseTracking(True)
        self.days = []                  # [(дата, открытия, действия)]
        self._hover = -1

    def set_days(self, days):
        self.days = days
        self.update()

    def _plot(self):
        return QRectF(14, 40, self.width() - 28, self.height() - 40 - 30)

    def _slot(self):
        return self._plot().width() / max(1, len(self.days))

    def mouseMoveEvent(self, event):
        plot = self._plot()
        x = event.position().x()
        index = int((x - plot.left()) // self._slot()) if plot.left() <= x < plot.right() else -1
        if index != self._hover:
            self._hover = index
            self.update()

    def leaveEvent(self, _event):
        self._hover = -1
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        plot = self._plot()
        top = max([d[1] for d in self.days] + [1])

        # Заголовок, а при наведении — цифры дня.
        if 0 <= self._hover < len(self.days):
            day, opens, actions = self.days[self._hover]
            title = tr("stats.chart_tip", date=short_date(day), opens=number(opens),
                       actions=number(actions))
            p.setPen(theme.TEXT)
        else:
            title = tr("stats.chart")
            p.setPen(theme.TEXT_DIM)
        p.setFont(theme.font(13, QFont.Weight.Medium))
        p.drawText(QRectF(14, 8, self.width() - 28, 24),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        # Одна линия сетки — на высоте самого большого дня, с его числом.
        p.setPen(theme.HAIRLINE)
        p.drawLine(QLineF(plot.left(), plot.top(), plot.right(), plot.top()))
        p.drawLine(QLineF(plot.left(), plot.bottom(), plot.right(), plot.bottom()))
        p.setFont(theme.font(11))
        p.setPen(theme.TEXT_FAINT)
        p.drawText(QRectF(plot.right() - 80, plot.top() - 16, 80, 14),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, number(top))

        slot = self._slot()
        gap = 2 if slot < 12 else 4
        for i, (_day, opens, _actions) in enumerate(self.days):
            x = plot.left() + i * slot + gap / 2
            if opens:
                h = max(2.0, plot.height() * opens / top)
                color = _BAR_HOVER if i == self._hover else theme.ACCENT
                _bar(p, QRectF(x, plot.bottom() - h, slot - gap, h), color)
            elif i == self._hover:
                _bar(p, QRectF(x, plot.bottom() - 2, slot - gap, 2), theme.TEXT_FAINT, 1)

        # Подписи оси: первый день и сегодня.
        if self.days:
            p.setFont(theme.font(11))
            p.setPen(theme.TEXT_FAINT)
            y = plot.bottom() + 6
            p.drawText(QRectF(plot.left(), y, 120, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       short_date(self.days[0][0]))
            p.drawText(QRectF(plot.right() - 120, y, 120, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       tr("stats.today_short"))


class _Bars(QWidget):
    """
    Строки «подпись — полоска — число». icons — сервис иконок, тогда у строки
    своя иконка (у программ).
    """

    ROW = 32

    def __init__(self, icons=None):
        super().__init__()
        self.icons = icons
        self.rows = []                  # [(подпись, число, справа, иконка, откуда)]
        if icons is not None:
            icons.ready.connect(lambda _key: self.update())

    def set_rows(self, rows):
        self.rows = rows
        self.setFixedHeight(max(1, len(rows)) * self.ROW + 12)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        top_value = max([r[1] for r in self.rows] + [1])
        label_w = 190
        value_w = 96
        bar_left = 14 + label_w + 12
        bar_w = self.width() - bar_left - value_w - 14
        for i, (label, value, right, icon, source) in enumerate(self.rows):
            y = 6 + i * self.ROW
            cy = y + self.ROW / 2
            x = 14
            if self.icons is not None:
                self._icon(p, QRectF(x, cy - 10, 20, 20), icon, source, label)
                x += 28
            p.setFont(theme.font(14))
            p.setPen(theme.TEXT)
            text = p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight,
                                              int(14 + label_w - x))
            p.drawText(QRectF(x, y, 14 + label_w - x, self.ROW),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            track = QRectF(bar_left, cy - 4, bar_w, 8)
            _pill(p, track, _TRACK)
            fill = QRectF(track.left(), track.top(),
                          max(track.height(), bar_w * value / top_value), track.height())
            _pill(p, fill, theme.ACCENT)
            p.setFont(theme.font(13, QFont.Weight.Medium))
            p.setPen(theme.TEXT_DIM)
            p.drawText(QRectF(self.width() - 14 - value_w, y, value_w, self.ROW),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right)

    def _icon(self, p, rect, icon, source, label):
        px = round(rect.width() * self.devicePixelRatioF())
        pixmap = self.icons.pixmap(icon, px)
        if pixmap is None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 16))
            p.drawRoundedRect(rect, 5, 5)
            if self.icons.failed(icon):
                p.setFont(theme.font(11, QFont.Weight.DemiBold))
                p.setPen(theme.TEXT_DIM)
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label[:1].upper())
            else:
                self.icons.request(icon, source)
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))


class _Tiles(QWidget):
    """Три крупных числа с подписями, между ними — тонкие линии."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(84)
        self.tiles = []                 # [(число, подпись)]

    def set_tiles(self, tiles):
        self.tiles = tiles
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        width = self.width() / max(1, len(self.tiles))
        for i, (value, caption) in enumerate(self.tiles):
            x = i * width
            if i:
                p.setPen(theme.HAIRLINE)
                p.drawLine(int(x), 16, int(x), self.height() - 16)
            p.setFont(theme.font(26, QFont.Weight.DemiBold))
            p.setPen(theme.TEXT)
            p.drawText(QRectF(x + 16, 12, width - 32, 36),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, value)
            p.setFont(theme.font(12))
            p.setPen(theme.TEXT_FAINT)
            p.drawText(QRectF(x + 16, 50, width - 32, 20),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, caption)


# --- страница ---------------------------------------------------------------- #

class StatsPage(QScrollArea):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                           + theme.SCROLLBAR_QSS)
        self.viewport().setAutoFillBackground(False)
        self._reset_timer = QTimer(self, singleShot=True, interval=_RESET_CONFIRM_MS)
        self._reset_timer.timeout.connect(self._reset_cancel)
        self._build()

    def _build(self):
        content = QWidget()
        self.column = QVBoxLayout(content)
        self.column.setContentsMargins(16, 10, 16, 16)
        self.column.setSpacing(12)

        activity = _Card()
        self.totals = activity.add(_Totals())
        self.chart = activity.add(_DailyChart())
        self.column.addWidget(activity)

        self.column.addWidget(self._header(tr("stats.kinds")))
        kinds = _Card()
        self.kinds = kinds.add(_Bars())
        self.kinds_empty = kinds.add(self._empty())
        self.column.addWidget(kinds)

        self.column.addWidget(self._header(tr("stats.speed")))
        speed = _Card()
        self.tiles = speed.add(_Tiles())
        self.column.addWidget(speed)

        self.column.addWidget(self._header(tr("stats.top")))
        top = _Card()
        self.top = top.add(_Bars(self.app.icons))
        self.top_empty = top.add(self._empty())
        self.column.addWidget(top)

        footer = QWidget()
        box = QHBoxLayout(footer)
        box.setContentsMargins(4, 4, 0, 0)
        self.since = _label("", 12, theme.TEXT_FAINT)
        box.addWidget(self.since, 1)
        self.reset = Button(tr("stats.reset"))
        self.reset.clicked.connect(self._on_reset)
        box.addWidget(self.reset)
        self.column.addWidget(footer)
        self.column.addStretch(1)
        self.setWidget(content)
        # setWidget включает заливку фона у содержимого — белое поверх стекла.
        content.setAutoFillBackground(False)

    @staticmethod
    def _header(title):
        header = QWidget()
        box = QHBoxLayout(header)
        box.setContentsMargins(4, 6, 0, 0)
        box.addWidget(_label(title, 12, theme.TEXT_FAINT, QFont.Weight.DemiBold))
        return header

    @staticmethod
    def _empty():
        row = QWidget()
        row.setFixedHeight(44)
        box = QHBoxLayout(row)
        box.setContentsMargins(14, 0, 14, 0)
        box.addWidget(_label(tr("stats.empty"), 13, theme.TEXT_DIM))
        return row

    # --- данные ------------------------------------------------------------ #

    def refresh(self):
        """Пересчитать — при каждом открытии страницы."""
        stats = self.app.stats
        today, week = stats.period(1), stats.period(7)
        self.totals.set_rows([
            (tr("stats.opens"), [today[0], week[0], stats.opens]),
            (tr("stats.actions"), [today[1], week[1], stats.actions]),
        ])
        self.chart.set_days(stats.daily())

        kinds = stats.kinds_ranked()
        total = sum(c for _, c in kinds) or 1
        self.kinds.set_rows([(tr("stats.kind." + k), c,
                              "%s · %s" % (number(c), percent(c / total)), "", "")
                             for k, c in kinds])
        self.kinds.setVisible(bool(kinds))
        self.kinds_empty.setVisible(not kinds)

        letters, first = stats.letters(), stats.first_share()
        self.tiles.set_tiles([
            (decimal(letters) if letters is not None else "—", tr("stats.letters")),
            (percent(first) if first is not None else "—", tr("stats.first")),
            (number(stats.saved) if stats.picks else "—", tr("stats.saved")),
        ])

        self.top.set_rows(self._top_rows(stats))
        self.top.setVisible(bool(self.top.rows))
        self.top_empty.setVisible(not self.top.rows)

        self.since.setText(tr("stats.since", date=long_date(
            datetime.date.fromtimestamp(stats.since))))
        self._reset_cancel()
        self.verticalScrollBar().setValue(0)

    def _top_rows(self, stats, limit=10):
        """Десять программ, которые ещё стоят: удалённые пропускаем."""
        catalog = self.app.catalog
        apps = {"app:" + a["name"].casefold(): a for a in catalog.found + catalog.apps}
        rows = []
        for key, count in stats.top_apps():
            app = apps.get(key)
            if app is None or key in self.app.hidden:
                continue
            rows.append((app["name"], count, number(count), "app:" + app["target"],
                         app["target"]))
            if len(rows) == limit:
                break
        return rows

    # --- сброс ------------------------------------------------------------- #

    def _on_reset(self):
        # Первое нажатие спрашивает, второе — сбрасывает.
        if not self._reset_timer.isActive():
            self.reset.setText(tr("stats.reset_sure"))
            self.reset.set_danger(True)
            self._reset_timer.start()
            return
        self.app.stats.reset()
        self.refresh()

    def _reset_cancel(self):
        self._reset_timer.stop()
        self.reset.setText(tr("stats.reset"))
        self.reset.set_danger(False)
