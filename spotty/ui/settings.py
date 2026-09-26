"""
Страница настроек — живёт внутри той же строки, вместо списка результатов.

Отдельное окно пришлось бы двигать по экрану, а стекло считается снимком того,
что под окном, — у неподвижной строки оно всегда честное. Всё применяется
сразу, кнопки «Сохранить» нет.
"""

import os

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..core import autostart
from ..core.config import DEFAULTS, UPDATE_MODES
from ..core.constants import APP_VERSION
from ..core.i18n import DEFAULT, LANGUAGES, tr
from ..search import web
from . import theme
from .widgets import Button, HotkeyField, Segmented, Toggle


def _label(text, px=14, color=theme.TEXT, weight=QFont.Weight.Normal):
    label = QLabel(text)
    label.setFont(theme.font(px, weight))
    label.setStyleSheet("color: rgba(%d,%d,%d,%d); background: transparent;"
                        % (color.red(), color.green(), color.blue(), color.alpha()))
    return label


class _ElidedLabel(QWidget):
    """Путь, обрезанный посередине: начало и имя папки важнее середины."""

    def __init__(self, text, px=13, color=theme.TEXT):
        super().__init__()
        self.text = text
        self.color = color
        self.setFont(theme.font(px))
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setToolTip(text)

    def sizeHint(self):
        return QSize(40, self.fontMetrics().height())

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.color)
        text = self.fontMetrics().elidedText(self.text, Qt.TextElideMode.ElideMiddle,
                                             self.width())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   text)


class _RemoveButton(QAbstractButton):
    def __init__(self):
        super().__init__()
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse() or self.isDown():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 40 if self.isDown() else 24))
            p.drawEllipse(QRectF(self.rect()))
        p.setPen(QPen(theme.TEXT_DIM, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c = QRectF(self.rect()).center()
        p.drawLine(QPointF(c.x() - 4, c.y() - 4), QPointF(c.x() + 4, c.y() + 4))
        p.drawLine(QPointF(c.x() + 4, c.y() - 4), QPointF(c.x() - 4, c.y() + 4))


class _Card(QWidget):
    """Группа строк на светлой подложке, между строками — тонкие линии."""

    def __init__(self):
        super().__init__()
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(0)

    def add(self, widget):
        self.box.addWidget(widget)
        return widget

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 12))
        p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        p.setPen(QPen(theme.HAIRLINE, 1))
        for i in range(self.box.count() - 1):
            widget = self.box.itemAt(i).widget()
            if widget is not None and widget.isVisible():
                y = widget.geometry().bottom() + 0.5
                p.drawLine(QPointF(14, y), QPointF(self.width() - 14, y))


def _row(title, subtitle="", control=None, height=52):
    row = QWidget()
    row.setFixedHeight(height)
    box = QHBoxLayout(row)
    box.setContentsMargins(14, 0, 12, 0)
    box.setSpacing(12)
    text = QVBoxLayout()
    text.setSpacing(1)
    text.addStretch(1)
    text.addWidget(_label(title, 14))
    if subtitle:
        row.subtitle = _label(subtitle, 12, theme.TEXT_FAINT)
        text.addWidget(row.subtitle)
    text.addStretch(1)
    box.addLayout(text, 1)
    if control is not None:
        box.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    return row


class SettingsPage(QScrollArea):
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
        self._build()
        app.files.changed.connect(self._update_count)
        app.updates.state.connect(self._update_state)
        app.updates.progress.connect(self._update_progress)
        app.programs.started.connect(self._update_drives)
        app.catalog.changed.connect(self._update_drives)

    # --- построение -------------------------------------------------------- #

    def _build(self):
        content = QWidget()
        content.setAutoFillBackground(False)
        self.column = QVBoxLayout(content)
        self.column.setContentsMargins(16, 10, 16, 16)
        self.column.setSpacing(12)
        config = self.app.config

        general = _Card()
        self.hotkey = HotkeyField(config.get("hotkey"))
        self.hotkey.changed.connect(self._on_hotkey)
        self.hotkey.recording.connect(self.app.suspend_hotkey)
        self.hotkey_row = general.add(_row(tr("settings.hotkey"), tr("settings.hotkey_sub"),
                                           self.hotkey))
        self.fullscreen_guard = Toggle(config.get("fullscreen_guard"))
        self.fullscreen_guard.toggled.connect(self.app.set_fullscreen_guard)
        general.add(_row(tr("settings.fullscreen_guard"), tr("settings.fullscreen_guard_sub"),
                         self.fullscreen_guard))
        self.autostart = Toggle(self.app.autostart_enabled())
        self.autostart.toggled.connect(self.app.set_autostart)
        # Из исходников в автозапуск прописался бы python.exe — там выключено.
        self.autostart.setEnabled(autostart.supported())
        general.add(_row(tr("settings.autostart"),
                         "" if autostart.supported() else tr("settings.autostart_dev"),
                         self.autostart))
        current = config.get("language")
        self.language = Segmented(list(LANGUAGES.items()),
                                  current if current in LANGUAGES else DEFAULT)
        self.language.changed.connect(self.app.set_language)
        general.add(_row(tr("settings.language"), control=self.language))
        self.column.addWidget(general)

        look = _Card()
        self.glass = Toggle(config.get("glass"))
        self.glass.toggled.connect(self.app.set_glass)
        look.add(_row(tr("settings.glass"), tr("settings.glass_sub"), self.glass))
        self.column.addWidget(look)

        search = _Card()
        engine = config.get("web_engine")
        self.web_engine = Segmented([(key, tr("web.engine." + key)) for key in web.ENGINES],
                                    engine if engine in web.ENGINES else web.DEFAULT)
        self.web_engine.changed.connect(self.app.set_web_engine)
        search.add(_row(tr("settings.web_engine"), tr("settings.web_engine_sub"),
                        self.web_engine))
        self.scan_drives = Toggle(config.get("scan_drives"))
        self.scan_drives.toggled.connect(self.app.set_scan_drives)
        self.drives_row = search.add(_row(tr("settings.scan_drives"), " ", self.scan_drives))
        self._update_drives()
        self.column.addWidget(search)

        updates = _Card()
        self.auto_update = Toggle(config.get("auto_update"))
        self.auto_update.toggled.connect(self.app.set_auto_update)
        updates.add(_row(tr("settings.auto_update"), control=self.auto_update))
        mode = config.get("update_mode")
        self.update_mode = Segmented([(m, tr("settings.update_mode." + m)) for m in UPDATE_MODES],
                                     mode if mode in UPDATE_MODES else DEFAULTS["update_mode"])
        self.update_mode.changed.connect(self._on_update_mode)
        self.mode_row = updates.add(_row(tr("settings.update_mode"),
                                         tr("settings.update_mode_sub." + self.update_mode.current),
                                         self.update_mode))
        self.update_button = Button(tr("settings.check_now"))
        self.update_button.clicked.connect(self._on_update_button)
        self.update_row = updates.add(_row(tr("settings.version", version=APP_VERSION),
                                           " ", self.update_button))
        self.column.addWidget(updates)

        self.column.addWidget(self._folders_header())
        self.folders = _Card()
        self.column.addWidget(self.folders)
        self._fill_folders()

        self.column.addWidget(self._header(tr("settings.hidden")))
        self.hidden = _Card()
        self.column.addWidget(self.hidden)
        self._fill_hidden()
        self.column.addStretch(1)
        self.setWidget(content)
        # setWidget сам включает заливку фона у содержимого — страница стала
        # бы белой поверх стекла.
        content.setAutoFillBackground(False)
        self._update_state(*self.app.updates.last_state())

    @staticmethod
    def _header(title):
        header = QWidget()
        box = QHBoxLayout(header)
        box.setContentsMargins(4, 6, 0, 0)
        box.addWidget(_label(title, 12, theme.TEXT_FAINT, QFont.Weight.DemiBold))
        box.addStretch(1)
        return header

    def _folders_header(self):
        header = self._header(tr("settings.folders"))
        box = header.layout()
        self.count = _label("", 12, theme.TEXT_FAINT)
        box.addWidget(self.count)
        add = Button(tr("settings.add_folder"))
        add.clicked.connect(self.app.add_folder)
        box.addSpacing(8)
        box.addWidget(add)
        self._update_count()
        return header

    @staticmethod
    def _clear(card):
        while card.box.count():
            widget = card.box.takeAt(0).widget()
            if widget is not None:
                # Удалится только в цикле событий — до тех пор старая строка
                # рисовалась бы поверх новой.
                widget.hide()
                widget.deleteLater()

    def _fill_hidden(self):
        self._clear(self.hidden)
        entries = self.app.hidden.items()
        if not entries:
            self.hidden.add(_row(tr("settings.no_hidden"), height=44))
        for entry in entries:
            row = QWidget()
            row.setFixedHeight(48)
            box = QHBoxLayout(row)
            box.setContentsMargins(14, 0, 12, 0)
            box.setSpacing(12)
            text = QVBoxLayout()
            text.setSpacing(1)
            text.addStretch(1)
            text.addWidget(_ElidedLabel(entry["title"], 14))
            # У программы из «Пуска» путь — ярлык, он ничего не скажет;
            # пишем, что это программа. У файла — где он лежит.
            where = (tr("kind.app") if entry["kind"] == "app"
                     else os.path.normpath(entry.get("path", "")))
            text.addWidget(_ElidedLabel(where, 12, theme.TEXT_FAINT))
            text.addStretch(1)
            box.addLayout(text, 1)
            unhide = Button(tr("settings.unhide"))
            unhide.clicked.connect(lambda _=False, k=entry["key"]: self.app.unhide(k))
            box.addWidget(unhide, 0, Qt.AlignmentFlag.AlignVCenter)
            self.hidden.add(row)
        self.hidden.update()

    def hidden_changed(self):
        self._fill_hidden()

    def _fill_folders(self):
        self._clear(self.folders)
        folders = self.app.config.get("folders")
        if not folders:
            self.folders.add(_row(tr("settings.no_folders"), height=44))
        for path in folders:
            row = QWidget()
            row.setFixedHeight(40)
            box = QHBoxLayout(row)
            box.setContentsMargins(14, 0, 8, 0)
            box.addWidget(_ElidedLabel(os.path.normpath(path)), 1)
            remove = _RemoveButton()
            remove.clicked.connect(lambda _=False, p=path: self.app.remove_folder(p))
            box.addWidget(remove)
            self.folders.add(row)
        self.folders.update()

    # --- обновление по событиям -------------------------------------------- #

    def refresh(self):
        """Перечитать настройки — при каждом открытии страницы."""
        config = self.app.config
        self.hotkey.set_combo(config.get("hotkey"))
        self.fullscreen_guard.set_silently(config.get("fullscreen_guard"))
        self.autostart.set_silently(self.app.autostart_enabled())
        self.glass.set_silently(config.get("glass"))
        self.auto_update.set_silently(config.get("auto_update"))
        self.scan_drives.set_silently(config.get("scan_drives"))
        self._update_drives()
        self._fill_folders()
        self._fill_hidden()
        self._update_count()
        self.verticalScrollBar().setValue(0)

    def folders_changed(self):
        self._fill_folders()

    def _on_hotkey(self, combo):
        ok = self.app.set_hotkey(combo)
        self.hotkey.set_combo(self.app.config.get("hotkey"))
        self.hotkey_row.subtitle.setText(
            tr("settings.hotkey_sub") if ok else tr("settings.hotkey_busy"))
        color = theme.TEXT_FAINT if ok else theme.DANGER
        self.hotkey_row.subtitle.setStyleSheet(
            "color: rgba(%d,%d,%d,%d); background: transparent;"
            % (color.red(), color.green(), color.blue(), color.alpha()))

    def _update_count(self):
        self.count.setText(tr("settings.files_count", count=len(self.app.files)))

    def _update_drives(self):
        if not self.app.config.get("scan_drives"):
            text = tr("settings.scan_drives_sub")
        elif self.app.programs.busy():
            text = tr("settings.scan_drives_busy")
        else:
            text = tr("settings.scan_drives_count", count=len(self.app.catalog.found))
        self.drives_row.subtitle.setText(text)

    def _on_update_mode(self, mode):
        self.mode_row.subtitle.setText(tr("settings.update_mode_sub." + mode))
        self.app.set_update_mode(mode)

    def _on_update_button(self):
        updates = self.app.updates
        if updates.ready_version():
            self.app.restart_and_update()
        elif updates.latest_available():
            self.app.install_update()
        else:
            self.app.check_updates()

    def _update_progress(self, fraction):
        version = self.app.updates.downloading()
        if version:
            self.update_row.subtitle.setText(tr("update.downloading", version=version,
                                                percent=round(fraction * 100)))

    def _update_state(self, state, version):
        updates = self.app.updates
        if not updates.supported():
            text = tr("update.dev")
        elif state == "downloading":
            text = tr("update.downloading", version=version,
                      percent=round(updates.fraction() * 100))
        elif state:
            text = tr("update." + state, version=version)
        else:
            text = " "
        self.update_row.subtitle.setText(text)
        if updates.ready_version():
            label = tr("settings.restart")
        elif updates.latest_available():
            label = tr("settings.install")
        else:
            label = tr("settings.check_now")
        self.update_button.setText(label)
        self.update_button.setEnabled(updates.supported()
                                      and state not in ("checking", "downloading"))
        self.update_button.updateGeometry()
