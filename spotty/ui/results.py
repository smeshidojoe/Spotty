"""
Список результатов: модель, отрисовка строк и сам список.

Строки двух видов — заголовок секции и пункт. Заголовки не выделяются:
стрелки их перепрыгивают. Мышь двигает выделение так же, как клавиатура, —
как в Spotlight, где «наведено» и «выбрано» одно и то же.
"""

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QPoint, QPointF, QRectF,
                            QSize, Qt, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from ..core.i18n import tr
from . import appicon, theme

ROW_ROLE = Qt.ItemDataRole.UserRole + 1
# Нижние строки гаснут к краю, если ниже есть ещё: знак, что список листается.
FADE_PX = 40


class ResultsModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []           # ("header", заголовок) | ("item", Item)

    def set_sections(self, sections):
        self.beginResetModel()
        self.rows = []
        for title, items in sections:
            if not items:
                continue
            self.rows.append(("header", title))
            self.rows.extend(("item", item) for item in items)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == ROW_ROLE:
            return self.rows[index.row()]
        return None

    def flags(self, index):
        if index.isValid() and self.rows[index.row()][0] == "item":
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return Qt.ItemFlag.NoItemFlags

    def is_item(self, row):
        return 0 <= row < len(self.rows) and self.rows[row][0] == "item"


def paint_builtin_icon(p, key, rect):
    """Иконки, которых нет в оболочке: Spotty, калькулятор, глобус."""
    if key == "builtin:spotty":
        appicon.paint(p, rect, edge=True)
        return
    if key == "builtin:web":
        # Браузер по умолчанию не нашёлся — синий глобус.
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.ACCENT)
        p.drawRoundedRect(rect, rect.width() * 0.24, rect.width() * 0.24)
        c, r = rect.center(), rect.width() * 0.3
        p.setPen(QPen(QColor("white"), max(1.2, rect.width() * 0.07)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, r, r)
        p.drawEllipse(c, r * 0.45, r)
        p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
        p.restore()
        return
    if key == "builtin:calc":
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ff9f0a"))
        p.drawRoundedRect(rect, rect.width() * 0.24, rect.width() * 0.24)
        # Знак «=»: две полосы по центру.
        w, h = rect.width() * 0.5, max(1.6, rect.height() * 0.1)
        x = rect.center().x() - w / 2
        p.setBrush(QColor("white"))
        for dy in (-rect.height() * 0.11, rect.height() * 0.11):
            p.drawRoundedRect(QRectF(x, rect.center().y() + dy - h / 2, w, h), h / 2, h / 2)
        p.restore()


class ResultsDelegate(QStyledItemDelegate):
    def __init__(self, view, icons):
        super().__init__(view)
        self.view = view
        self.icons = icons

    def sizeHint(self, option, index):
        kind, _ = index.data(ROW_ROLE)
        return QSize(option.rect.width(), theme.HEADER_H if kind == "header" else theme.ROW_H)

    def paint(self, p, option, index):
        kind, payload = index.data(ROW_ROLE)
        rect = QRectF(option.rect)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setOpacity(self._fade(rect))
        if kind == "header":
            p.setFont(theme.font(12, QFont.Weight.DemiBold))
            p.setPen(theme.TEXT_FAINT)
            p.drawText(rect.adjusted(12, 0, -12, -6),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, payload)
        else:
            self._paint_item(p, rect, payload,
                             bool(option.state & QStyle.StateFlag.State_Selected))
        p.restore()

    def _fade(self, rect):
        bar = self.view.verticalScrollBar()
        if bar.value() >= bar.maximum():
            return 1.0
        height = self.view.viewport().height()
        left = height - rect.center().y()
        return 1.0 if left >= FADE_PX else max(0.15, left / FADE_PX)

    def _paint_item(self, p, rect, item, selected):
        if selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.SELECTION)
            p.drawRoundedRect(rect.adjusted(0, 1, 0, -1), 10, 10)

        icon_rect = QRectF(rect.left() + 12, rect.center().y() - theme.ICON / 2,
                           theme.ICON, theme.ICON)
        self._paint_icon(p, item, icon_rect)

        right = rect.right() - 14
        # Подпись справа: тип пункта.
        accessory = tr("kind." + item.kind)
        p.setFont(theme.font(13))
        fm = p.fontMetrics()
        acc_w = fm.horizontalAdvance(accessory)
        p.setPen(theme.TEXT_FAINT)
        p.drawText(QRectF(right - acc_w, rect.top(), acc_w, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, accessory)
        right -= acc_w + 24

        x = icon_rect.right() + 12
        badge = tr("badge.new") if item.extra.get("new") else ""
        if badge:
            p.setFont(theme.font(11, QFont.Weight.DemiBold))
            badge_w = p.fontMetrics().horizontalAdvance(badge) + 12
            right -= badge_w + 8
        p.setFont(theme.font(14))
        fm = p.fontMetrics()
        title = fm.elidedText(item.title, Qt.TextElideMode.ElideRight, int(right - x))
        p.setPen(theme.TEXT)
        p.drawText(QRectF(x, rect.top(), right - x, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)
        x += fm.horizontalAdvance(title) + 10
        if badge:
            self._paint_badge(p, QRectF(x - 2, rect.center().y() - 9, badge_w, 18), badge)
            x += badge_w + 8
            right += badge_w + 8

        if item.subtitle and right - x > 40:
            p.setFont(theme.font(13))
            fm = p.fontMetrics()
            # Путь режем в середине: начало и имя папки важнее середины.
            sub = fm.elidedText(item.subtitle, Qt.TextElideMode.ElideMiddle, int(right - x))
            p.setPen(theme.TEXT_FAINT)
            p.drawText(QRectF(x, rect.top(), right - x, rect.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, sub)

    @staticmethod
    def _paint_badge(p, rect, text):
        """Метка «Новое»: только что поставленная программа."""
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.BADGE)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setFont(theme.font(11, QFont.Weight.DemiBold))
        p.setPen(theme.BADGE_TEXT)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_icon(self, p, item, rect):
        if item.icon.startswith("builtin:"):
            paint_builtin_icon(p, item.icon, rect)
            return
        px = round(theme.ICON * self.view.devicePixelRatioF())
        pixmap = self.icons.pixmap(item.icon, px)
        if pixmap is None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 16))
            p.drawRoundedRect(rect, 5, 5)
            if self.icons.failed(item.icon):
                # Иконки нет (битый ярлык) — первая буква названия.
                p.setFont(theme.font(12, QFont.Weight.DemiBold))
                p.setPen(theme.TEXT_DIM)
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, item.title[:1].upper())
            else:
                # Пока иконка едет — ровная заглушка того же размера, чтобы
                # текст не прыгал, когда картинка появится.
                self.icons.request(item.icon, item.icon_source, urgent=True)
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))


class ResultsView(QListView):
    """Список без собственного фокуса: клавиатура остаётся у строки ввода."""

    activated_item = Signal(object)
    current_changed = Signal(object)

    def __init__(self, icons, parent=None):
        super().__init__(parent)
        self.model_ = ResultsModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(ResultsDelegate(self, icons))
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalScrollBar().setSingleStep(20)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("QListView { background: transparent; border: none; }"
                           + theme.SCROLLBAR_QSS)
        self._last_mouse = QPoint()
        self.empty_text = tr("empty.nothing")
        self.clicked.connect(self._on_clicked)
        self.selectionModel().currentChanged.connect(
            lambda *_: self.current_changed.emit(self.current_item()))
        icons.ready.connect(lambda _key: self.viewport().update())
        # Затухание нижних строк зависит от прокрутки — перерисовываем на ходу.
        self.verticalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())

    # --- данные ------------------------------------------------------------ #

    def set_sections(self, sections):
        self.model_.set_sections(sections)
        self.select_row(self._next_item(-1, 1))
        self.scrollToTop()

    def current_item(self):
        row = self.currentIndex().row()
        return self.model_.rows[row][1] if self.model_.is_item(row) else None

    def items(self):
        return [payload for kind, payload in self.model_.rows if kind == "item"]

    # --- выделение --------------------------------------------------------- #

    def _next_item(self, row, step):
        row += step
        while 0 <= row < len(self.model_.rows):
            if self.model_.is_item(row):
                return row
            row += step
        return -1

    def select_row(self, row):
        if row < 0:
            self.setCurrentIndex(QModelIndex())
            self.current_changed.emit(None)
            return
        index = self.model_.index(row)
        self.setCurrentIndex(index)
        # Первый пункт секции тянет за собой её заголовок — иначе при прокрутке
        # вверх заголовок так и остаётся за краем.
        if row > 0 and not self.model_.is_item(row - 1):
            self.scrollTo(self.model_.index(row - 1))
        self.scrollTo(index)

    def select_key(self, key):
        """Выделить пункт с этим ключом. False — его нет в выдаче."""
        for row, (kind, payload) in enumerate(self.model_.rows):
            if kind == "item" and (payload.key or payload.target) == key:
                self.select_row(row)
                return True
        return False

    def select_near(self, row):
        """Пункт на месте row, а если там уже пусто — ближайший выше."""
        target = self._next_item(row - 1, 1)
        if target < 0:
            target = self._next_item(min(row, len(self.model_.rows)), -1)
        self.select_row(target)

    def move(self, step):
        row = self.currentIndex().row()
        target = self._next_item(row, step)
        if target >= 0:
            self.select_row(target)

    def page(self, direction):
        rows = max(1, self.viewport().height() // theme.ROW_H - 1)
        row = self.currentIndex().row()
        for _ in range(rows):
            nxt = self._next_item(row, direction)
            if nxt < 0:
                break
            row = nxt
        self.select_row(row)

    # --- мышь -------------------------------------------------------------- #

    def reset_mouse(self):
        """
        Запомнить, где курсор сейчас. Windows присылает «движение» мыши, когда
        окно появляется под неподвижным курсором, — без этого выделение само
        прыгало бы на строку под ним.
        """
        from PySide6.QtGui import QCursor
        self._last_mouse = QCursor.pos()

    def mouseMoveEvent(self, event):
        # Выделяем по движению мыши, а не по положению: иначе при листании
        # клавиатурой выделение перескакивало бы на строку под неподвижным
        # курсором.
        pos = event.globalPosition().toPoint()
        if pos != self._last_mouse:
            self._last_mouse = pos
            index = self.indexAt(event.position().toPoint())
            if index.isValid() and self.model_.is_item(index.row()) \
                    and index != self.currentIndex():
                self.setCurrentIndex(index)
        super().mouseMoveEvent(event)

    def _on_clicked(self, index):
        if self.model_.is_item(index.row()):
            self.activated_item.emit(self.model_.rows[index.row()][1])

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.model_.rowCount() == 0:
            p = QPainter(self.viewport())
            p.setFont(theme.font(14))
            p.setPen(theme.TEXT_FAINT)
            p.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                       self.empty_text)
