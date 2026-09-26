"""
Сборка программы: сервисы, строка, трей, глобальный хоткей и запуск пунктов.
"""

import os
import sys

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QIcon
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from . import actions
from .core import autostart, hotkey, i18n, logbook, systheme, winapi
from .core.config import Config
from .core.constants import APP_ICO, APP_ID, APP_NAME, IPC_NAME, IS_FIRST_RUN
from .core.i18n import tr
from .core.launcher import Launcher
from .core.shellicons import IconService
from .search.apps import AppCatalog
from .search.engine import SearchEngine
from .search.files import FileIndex
from .search.hidden import Hidden
from .search.usage import CommandHistory, Usage
from .ui import appicon
from .ui.hud import Hud
from .ui.panel import Panel
from .updates import UpdateService

UPDATE_FIRST_CHECK_MS = 20_000
UPDATE_INTERVAL_MS = 6 * 60 * 60 * 1000
# Ярлыки в «Пуске» отслеживаются сразу (см. AppCatalog), а приложения из
# Магазина ярлыков не создают — их подбираем при открытии строки, но не чаще
# раза в десять минут: опрос запускает PowerShell.
APPS_REFRESH_SECONDS = 600


class Spotty(QObject):
    def __init__(self, qapp):
        super().__init__()
        self.qapp = qapp
        self.config = Config()
        i18n.set_language(self.config.get("language"))

        self.usage = Usage()
        self.history = CommandHistory()
        self.hidden = Hidden()
        self.icons = IconService(self)
        self.catalog = AppCatalog(self)
        self.files = FileIndex(self)
        self.engine = SearchEngine(self.catalog, self.files, self.usage, self.history,
                                   self.hidden)
        self.launcher = Launcher(self)
        self.updates = UpdateService(self)
        self.hud = Hud()
        self.panel = Panel(self)

        self.catalog.changed.connect(self._on_apps_changed)
        self.files.changed.connect(self.panel.refresh_results)
        self.updates.state.connect(self._on_update_state)

        self.hotkeys = hotkey.HotkeyManager(self)
        self.hotkeys.install(qapp)
        self.hotkeys.triggered.connect(lambda _name: self.toggle())

        self._build_tray()
        self._server = QLocalServer(self)
        QLocalServer.removeServer(IPC_NAME)
        self._server.newConnection.connect(self._on_ipc)
        self._server.listen(IPC_NAME)

        self._update_timer = QTimer(self, interval=UPDATE_INTERVAL_MS)
        self._update_timer.timeout.connect(self._auto_check)
        self._notified_version = ""

    # --- запуск ------------------------------------------------------------ #

    def start(self):
        self.tray.show()
        combo = self.config.get("hotkey")
        if not self.hotkeys.register("toggle", combo):
            logbook.log("хоткей занят:", combo)
            self.tray.showMessage(APP_NAME, tr("tray.hotkey_busy",
                                               hotkey=hotkey.display(combo)),
                                  self.qapp.windowIcon(), 8000)
        elif IS_FIRST_RUN:
            self.tray.showMessage(APP_NAME, tr("tray.welcome", hotkey=hotkey.display(combo)),
                                  self.qapp.windowIcon(), 8000)
        self.catalog.refresh()
        self.files.set_roots(self.config.get("folders"))
        self._preload_icons()
        # Прогрев — когда программа уже поднялась: первый вызов строки не
        # должен ждать компиляции шейдеров и шрифтов.
        QTimer.singleShot(300, self.panel.warm_up)
        QTimer.singleShot(UPDATE_FIRST_CHECK_MS, self._auto_check)
        self._update_timer.start()

    def _build_tray(self):
        icon = QIcon(APP_ICO) if os.path.isfile(APP_ICO) else QIcon(appicon.pixmap(64))
        self.qapp.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(self._tray_icon(), self)
        self.tray.setToolTip(APP_NAME)
        # Тему панели задач можно переключить на ходу, и белая лупа на светлой
        # панели пропадёт. Qt сообщает о смене — перекрашиваемся.
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(
                lambda _scheme: self.tray.setIcon(self._tray_icon()))
        self.tray.activated.connect(self._on_tray)
        self.tray.messageClicked.connect(lambda: self.panel.summon())
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        self._fill_tray_menu()

    @staticmethod
    def _tray_icon():
        """Одноцветная лупа: белая на тёмной панели задач, тёмная на светлой."""
        ink = QColor(systheme.tray_ink())
        icon = QIcon()
        for size in appicon.TRAY_SIZES:
            icon.addPixmap(appicon.tray_pixmap(size, ink))
        return icon

    def _fill_tray_menu(self):
        self.menu.clear()
        combo = hotkey.display(self.config.get("hotkey"))
        self.menu.addAction(tr("tray.open") + "\t" + combo).triggered.connect(
            lambda: self.panel.summon())
        self.menu.addAction(tr("tray.settings")).triggered.connect(
            lambda: self.panel.summon("settings"))
        self.menu.addAction(tr("tray.update")).triggered.connect(self._check_from_tray)
        self.menu.addSeparator()
        self.menu.addAction(tr("tray.quit")).triggered.connect(self.quit)

    def _on_tray(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Клик в трей сначала снимает фокус со строки, и она закрывается;
            # не открываем её тут же обратно — клик означал «закрой».
            if not self.panel.hidden_recently():
                self.toggle()

    def _on_ipc(self):
        socket = self._server.nextPendingConnection()
        if socket is not None:
            socket.disconnected.connect(socket.deleteLater)
            socket.close()
        self.panel.summon()

    def quit(self):
        self.hotkeys.unregister_all()
        self.tray.hide()
        self.qapp.quit()

    # --- строка ------------------------------------------------------------ #

    def toggle(self):
        if self.panel.isVisible() and self.panel.isActiveWindow():
            self.panel.dismiss()
        else:
            self.panel.summon()

    def on_summon(self):
        self.catalog.refresh(min_interval=APPS_REFRESH_SECONDS)
        self.files.refresh_if_stale()

    def _on_apps_changed(self):
        self._preload_icons()
        self.panel.refresh_results()

    def _preload_icons(self):
        """Иконки всех программ — заранее и в фоне, чтобы список не мигал заглушками."""
        for app in self.catalog.apps:
            self.icons.request("app:" + app["target"], app["target"])

    # --- выполнение действий ----------------------------------------------- #

    def perform(self, item, action_id, query=""):
        if action_id is None:
            action_id = actions.actions_for(item)[0].id
        handler = getattr(self, "_do_" + action_id, None)
        if handler is None:
            logbook.log("неизвестное действие:", action_id)
            return
        try:
            handler(item, query)
        except Exception:
            logbook.exc("действие " + action_id)
            self.hud.show_text(tr("hud.launch_failed"))

    def _launch(self, job, on_ok=None):
        """
        Строка закрывается сразу, а запуск идёт в фоне. ShellExecute бывает
        медленным, окно UAC ждёт ответа — строка, висящая всё это время на
        экране, выглядела бы зависшей.
        """
        # Пока фокус ещё наш: право вывести окно вперёд передаётся запущенной
        # программе, только если его даёт процесс переднего плана.
        winapi.allow_foreground_for_launched()
        self.panel.dismiss(done=True)
        self.launcher.run(job, lambda result: self._launch_done(result, on_ok))

    def _launch_done(self, result, on_ok):
        if result:
            if on_ok is not None:
                on_ok()
        elif result is not None:            # None — «Нет» в окне UAC, это не ошибка
            self.hud.show_text(tr("hud.launch_failed"))

    def _record(self, item, query):
        return lambda: self.usage.record(item.key, query)

    def _copy(self, text):
        QGuiApplication.clipboard().setText(text)
        self.panel.dismiss(done=True)
        self.hud.show_text(tr("hud.copied"))

    def _do_open(self, item, query):
        target = item.target
        self._launch(lambda: winapi.shell_open(target), self._record(item, query))

    def _do_admin(self, item, query):
        command = item.target
        if item.kind == "command":
            self._launch(lambda: winapi.run_in_terminal(command, admin=True),
                         lambda: self.history.add(command))
            return
        # У ярлыка свои аргументы и рабочая папка — запускаем через него.
        target = item.target if item.target.lower().endswith(".lnk") else (item.path or item.target)
        self._launch(lambda: winapi.shell_open(target, verb="runas"), self._record(item, query))

    def _do_reveal(self, item, _query):
        path = item.path
        self._launch(lambda: winapi.reveal(path))

    def _do_copy_path(self, item, _query):
        self._copy(os.path.normpath(item.path))

    def _do_copy_name(self, item, _query):
        self._copy(item.title)

    def _do_terminal_here(self, item, _query):
        folder = item.path if item.kind == "folder" else os.path.dirname(item.path)
        self._launch(lambda: winapi.open_terminal(folder))

    def _do_forget(self, item, _query):
        self.usage.forget(item.key)
        self.panel.refresh_results()
        self.hud.show_text(tr("hud.forgot"))

    def _do_hide(self, item, _query):
        self.hidden.add(item)
        self.panel.refresh_results()
        self.hud.show_text(tr("hud.hidden"))

    def unhide(self, key):
        self.hidden.remove(key)
        self.panel.settings.hidden_changed()

    def _do_copy(self, item, _query):
        self._copy(item.target)

    def _do_copy_expr(self, item, _query):
        self._copy("%s %s" % (item.subtitle, item.target))

    def _do_run(self, item, query):
        if item.kind == "internal":
            self._internal(item.target)
            return
        command = item.target
        self._launch(lambda: winapi.run_in_terminal(command),
                     lambda: self.history.add(command))

    def _do_copy_command(self, item, _query):
        self._copy(item.target)

    def _do_forget_command(self, item, _query):
        self.history.remove(item.target)
        self.panel.refresh_results()

    def _internal(self, name):
        if name == "settings":
            self.panel.set_mode("settings")
        elif name == "update":
            self.panel.set_mode("settings")
            self.updates.check()
        elif name == "reindex":
            self.catalog.refresh()
            self.files.rebuild()
            self.panel.dismiss(done=True)
            self.hud.show_text(tr("hud.reindex"))
        elif name == "quit":
            self.quit()
        elif name == "install":
            self.install_update()

    # --- настройки --------------------------------------------------------- #

    def set_hotkey(self, combo):
        old = self.config.get("hotkey")
        if self.hotkeys.register("toggle", combo):
            self.config.set("hotkey", combo)
            self._fill_tray_menu()
            return True
        self.hotkeys.register("toggle", old)
        return False

    def suspend_hotkey(self, suspended):
        if suspended:
            self.hotkeys.unregister("toggle")
        else:
            self.hotkeys.register("toggle", self.config.get("hotkey"))

    def autostart_enabled(self):
        return autostart.is_enabled()

    def set_autostart(self, on):
        autostart.set_enabled(on)

    def set_glass(self, on):
        self.config.set("glass", on)
        self.panel.set_glass(on)

    def set_auto_update(self, on):
        self.config.set("auto_update", on)
        if on:
            self._auto_check()

    def set_language(self, code):
        self.config.set("language", code)
        i18n.set_language(code)
        self._fill_tray_menu()
        self.panel.retranslate()

    def add_folder(self):
        self.panel.modal = True
        try:
            path = QFileDialog.getExistingDirectory(self.panel, tr("settings.add_folder"))
        finally:
            self.panel.modal = False
            self.panel.summon("settings")
        if not path:
            return
        folders = list(self.config.get("folders"))
        path = os.path.normpath(path)
        if path not in folders:
            folders.append(path)
            self.config.set("folders", folders)
            self.files.set_roots(folders)
            self.panel.settings.folders_changed()

    def remove_folder(self, path):
        folders = [f for f in self.config.get("folders") if f != path]
        self.config.set("folders", folders)
        self.files.set_roots(folders)
        self.panel.settings.folders_changed()

    # --- обновления -------------------------------------------------------- #

    def _auto_check(self):
        if self.config.get("auto_update") and self.updates.supported():
            self.updates.check(silent=True)

    def _check_from_tray(self):
        self.panel.summon("settings")
        self.updates.check()

    def install_update(self):
        self.panel.dismiss()
        self.hud.show_text(tr("hud.downloading"))
        self.updates.install()

    def _on_update_state(self, state, version):
        if state == "available":
            self.engine.update_version = version
            self.panel.refresh_results()
            if version != self._notified_version and not self.panel.isVisible():
                self._notified_version = version
                self.tray.showMessage(APP_NAME, tr("tray.update_available", version=version),
                                      self.qapp.windowIcon(), 8000)
        elif state == "ready":
            if self.updates.start_helper():
                self.hotkeys.unregister_all()
                self.tray.hide()
                self.updates.exit_now()
            else:
                self.hud.show_text(tr("update.error"))


def main():
    winapi.set_app_id(APP_ID)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)
    spotty = Spotty(qapp)
    spotty.start()
    if "--show" in sys.argv:
        QTimer.singleShot(0, spotty.panel.summon)
    return qapp.exec()
