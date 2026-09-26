"""
Сборка программы: сервисы, строка, трей, глобальный хоткей и запуск пунктов.
"""

import os
import sys

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QIcon
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication, QFileDialog, QSystemTrayIcon

from . import actions
from .core import autostart, fullscreen, hotkey, i18n, logbook, systheme, winapi
from .core.config import Config
from .core.constants import APP_ICO, APP_ID, APP_NAME, IPC_NAME, IS_FIRST_RUN
from .core.i18n import tr
from .core.launcher import Launcher
from .core.shellicons import IconService
from .search.apps import AppCatalog
from .search.engine import SearchEngine
from .search.files import FileIndex
from .search.hidden import Hidden
from .search.programs import DiskPrograms
from .search.usage import CommandHistory, Usage
from .ui import appicon
from .ui.hud import Hud
from .ui.panel import Panel
from .ui.toast import Toast
from .ui.tray_menu import MenuItem, TrayMenu
from .updates import UpdateService

UPDATE_FIRST_CHECK_MS = 20_000
UPDATE_INTERVAL_MS = 6 * 60 * 60 * 1000
# «Перезапускаю…» на карточке успевает прочитаться до того, как строка исчезнет.
RESTART_DELAY_MS = 450
TOAST_LONG_MS = 8000
# Ярлыки в «Пуске» отслеживаются сразу (см. AppCatalog), а приложения из
# Магазина ярлыков не создают — их подбираем при открытии строки, но не чаще
# раза в десять минут: опрос запускает PowerShell.
APPS_REFRESH_SECONDS = 600
# Обход дисков — когда программа уже поднялась и прогрела строку; дальше раз
# в сутки (сам обход решает, устарел ли список).
DRIVES_FIRST_SCAN_MS = 15_000
DRIVES_CHECK_MS = 60 * 60 * 1000


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
        self.programs = DiskPrograms(self)
        if self.config.get("scan_drives"):
            self.catalog.set_found(self.programs.apps)
        self.files = FileIndex(self)
        self.engine = SearchEngine(self.catalog, self.files, self.usage, self.history,
                                   self.hidden)
        self.engine.web_engine = self.config.get("web_engine")
        self.launcher = Launcher(self)
        self.updates = UpdateService(self)
        self.hud = Hud()
        self.toast = Toast()
        self.panel = Panel(self)

        self.catalog.changed.connect(self._on_apps_changed)
        self.programs.changed.connect(self._on_programs_changed)
        self.files.changed.connect(self.panel.refresh_results)
        self.updates.state.connect(self._on_update_state)
        self.updates.progress.connect(self._on_update_progress)
        self._install_now = False     # человек ждёт установки — карточка в строке
        self._tray_check = False      # проверку начали из трея — отвечаем плашкой
        self._notified_version = ""   # о ней уже показали плашку в этом сеансе
        if self.updates.ready_version():
            # Скачано в прошлый раз и ещё не установлено: кнопка ждёт снова.
            self._on_update_state("ready", self.updates.ready_version())

        self.hotkeys = hotkey.HotkeyManager(self)
        self.hotkeys.install(qapp)
        self.hotkeys.triggered.connect(self._on_hotkey)
        self._recording = False       # в настройках записывают новое сочетание
        self.guard = fullscreen.FullscreenGuard(self)
        self.guard.changed.connect(self._sync_hotkey)

        self._build_tray()
        self._server = QLocalServer(self)
        QLocalServer.removeServer(IPC_NAME)
        self._server.newConnection.connect(self._on_ipc)
        self._server.listen(IPC_NAME)

        self._update_timer = QTimer(self, interval=UPDATE_INTERVAL_MS)
        self._update_timer.timeout.connect(self._auto_check)
        self._drives_timer = QTimer(self, interval=DRIVES_CHECK_MS)
        self._drives_timer.timeout.connect(self._scan_drives_if_stale)

    # --- запуск ------------------------------------------------------------ #

    def start(self):
        self._sync_autostart()
        self.tray.show()
        combo = self.config.get("hotkey")
        if not self.hotkeys.register("toggle", combo):
            logbook.log("хоткей занят:", combo)
            self.toast.show_message(tr("toast.hotkey_busy", hotkey=hotkey.display(combo)),
                                    tr("toast.hotkey_busy_sub"), TOAST_LONG_MS,
                                    on_click=lambda: self.panel.summon("settings"))
        elif IS_FIRST_RUN:
            self.toast.show_message(tr("toast.welcome"),
                                    tr("toast.welcome_sub", hotkey=hotkey.display(combo)),
                                    TOAST_LONG_MS, on_click=self.panel.summon)
        self.guard.set_enabled(bool(self.config.get("fullscreen_guard")))
        self.catalog.refresh()
        self.files.set_roots(self.config.get("folders"))
        self._preload_icons()
        # Прогрев — когда программа уже поднялась: первый вызов строки не
        # должен ждать компиляции шейдеров и шрифтов.
        QTimer.singleShot(300, self.panel.warm_up)
        QTimer.singleShot(UPDATE_FIRST_CHECK_MS, self._auto_check)
        self._update_timer.start()
        QTimer.singleShot(DRIVES_FIRST_SCAN_MS, self._scan_drives_if_stale)
        self._drives_timer.start()

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
        # Меню рисуем сами (ui/tray_menu.py) и показываем по правому клику:
        # setContextMenu не ставим, иначе Windows покажет системное.
        self.menu = TrayMenu()
        self.menu.triggered.connect(self._on_tray_menu)

    @staticmethod
    def _tray_icon():
        """Одноцветная лупа: белая на тёмной панели задач, тёмная на светлой."""
        ink = QColor(systheme.tray_ink())
        icon = QIcon()
        for size in appicon.TRAY_SIZES:
            icon.addPixmap(appicon.tray_pixmap(size, ink))
        return icon

    def _tray_items(self):
        """Пункты собираем при каждом открытии: язык, хоткей и автозапуск могли смениться."""
        items = [MenuItem("open", tr("tray.open"), hotkey.keycaps(self.config.get("hotkey"))),
                 MenuItem("settings", tr("tray.settings")),
                 None]
        if autostart.supported():
            items.append(MenuItem("autostart", tr("settings.autostart"),
                                  checked=self.autostart_enabled()))
        if self.updates.ready_version():
            items.append(MenuItem("restart", tr("update.restart_button")))
        else:
            items.append(MenuItem("update", tr("tray.update")))
        items += [None, MenuItem("quit", tr("tray.quit"))]
        return items

    def _on_tray_menu(self, item_id):
        if item_id == "open":
            self.panel.summon()
        elif item_id == "settings":
            self.panel.summon("settings")
        elif item_id == "autostart":
            self.set_autostart(not self.autostart_enabled())
        elif item_id == "update":
            self._check_from_tray()
        elif item_id == "restart":
            self.restart_and_update()
        elif item_id == "quit":
            self.quit()

    def _on_tray(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Клик в трей сначала снимает фокус со строки, и она закрывается;
            # не открываем её тут же обратно — клик означал «закрой».
            if not self.panel.hidden_recently():
                self.toggle()
        elif reason == QSystemTrayIcon.ActivationReason.Context:
            self.panel.dismiss()
            self.menu.popup(self._tray_items(), QCursor.pos())

    def _on_ipc(self):
        socket = self._server.nextPendingConnection()
        if socket is not None:
            socket.disconnected.connect(socket.deleteLater)
            socket.close()
        self.panel.summon()

    def quit(self):
        self.guard.set_enabled(False)       # иначе вернул бы сочетание на место
        self.hotkeys.unregister_all()
        self.toast.hide()
        self.tray.hide()
        self.qapp.quit()

    # --- строка ------------------------------------------------------------ #

    def _on_hotkey(self, _name):
        # Программа развернулась на весь экран уже после того, как стала
        # активной, и сочетание снять не успели: нажатие отдаём ей.
        if self.guard.update():
            hotkey.pass_through(self.config.get("hotkey"))
            return
        self.toggle()

    def toggle(self):
        if self.panel.locked():
            self.panel.summon()         # идёт установка — только вернуть на передний план
        elif self.panel.isVisible() and self.panel.isActiveWindow():
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
        for app in self.catalog.apps + self.catalog.found:
            self.icons.request("app:" + app["target"], app["target"])

    # --- программы на дисках ----------------------------------------------- #

    def _scan_drives_if_stale(self):
        if self.config.get("scan_drives") and self.programs.stale():
            self.programs.scan()

    def _on_programs_changed(self):
        self.catalog.set_found(self.programs.apps if self.config.get("scan_drives") else [])

    def set_scan_drives(self, on):
        self.config.set("scan_drives", on)
        if on:
            self.catalog.set_found(self.programs.apps)
            self.programs.scan()
        else:
            self.programs.clear()

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
        # У поиска в интернете ключа нет: запрос каждый раз новый, считать нечего.
        if not item.key:
            return None
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
        self.hud.show_text(tr("hud.hidden_folder" if item.kind == "folder" else "hud.hidden"))

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

    def _do_copy_link(self, item, _query):
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
            if self.config.get("scan_drives"):
                self.programs.scan()
            self.panel.dismiss(done=True)
            self.hud.show_text(tr("hud.reindex"))
        elif name == "quit":
            self.quit()
        elif name == "install":
            self.install_update()
        elif name == "restart":
            self.restart_and_update()

    # --- настройки --------------------------------------------------------- #

    def set_hotkey(self, combo):
        old = self.config.get("hotkey")
        if self.hotkeys.register("toggle", combo):
            self.config.set("hotkey", combo)
            return True
        self.hotkeys.register("toggle", old)
        return False

    def suspend_hotkey(self, suspended):
        self._recording = suspended
        self._sync_hotkey()

    def _sync_hotkey(self, *_):
        """
        Сочетание снято, пока его записывают в настройках и пока на переднем
        плане полноэкранная программа (см. core/fullscreen.py), иначе стоит.
        """
        wanted = not self._recording and not self.guard.blocked()
        if wanted == self.hotkeys.is_registered("toggle"):
            return
        if not wanted:
            self.hotkeys.unregister("toggle")
        elif not self.hotkeys.register("toggle", self.config.get("hotkey")):
            logbook.log("хоткей занят:", self.config.get("hotkey"))

    def set_fullscreen_guard(self, on):
        self.config.set("fullscreen_guard", on)
        self.guard.set_enabled(on)

    def autostart_enabled(self):
        return bool(self.config.get("autostart"))

    def set_autostart(self, on):
        self.config.set("autostart", on)
        autostart.set_enabled(on)

    def _sync_autostart(self):
        """
        Как в Knack: настройка — источник истины, и путь к exe переписываем на
        каждом старте — после переустановки в другую папку автозапуск иначе
        указывал бы в пустоту. Настройку берём из реестра, только если её ещё
        нет (галочка установщика) или автозапуск выключили в диспетчере задач —
        это тоже выбор человека.
        В dev-режиме не трогаем ничего: config.json общий с установленным
        Spotty, и dev-запуск выключил бы ему автозапуск.
        """
        if not autostart.supported():
            return
        wanted = self.config.get("autostart")
        if wanted is None or (wanted and autostart.disabled_in_task_manager()):
            wanted = autostart.is_enabled()
            self.config.set("autostart", wanted)
        autostart.set_enabled(wanted)

    def set_glass(self, on):
        self.config.set("glass", on)
        self.panel.set_glass(on)

    def set_web_engine(self, engine):
        self.config.set("web_engine", engine)
        self.engine.web_engine = engine

    def set_auto_update(self, on):
        self.config.set("auto_update", on)
        if on:
            self._auto_check()

    def set_update_mode(self, mode):
        self.config.set("update_mode", mode)
        # Переключили на фон, а версия уже найдена — пусть качается.
        if self._background() and self.updates.latest_available():
            self.toast.close_message("update")
            self.updates.download()

    def set_language(self, code):
        self.config.set("language", code)
        i18n.set_language(code)
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
    #
    # Два режима (настройка update_mode):
    #   notify     — найдено: плашка в углу. Клик по ней, «Установить» в
    #                настройках или пункт в выдаче — карточка в строке: полоса
    #                прогресса, строка заперта, по готовности перезапуск.
    #   background — найдено: качается само, строкой пользуются как обычно. В
    #                конце справа в поле ввода — «Перезапустить и обновить»,
    #                и кнопка ждёт при каждом открытии, пока её не нажмут.
    # «Проверить обновления» в трее всегда качает в фоне и отвечает плашками:
    # строки в этот момент на экране нет, и открывать её ради проверки незачем.

    def _background(self):
        return self.config.get("update_mode") == "background"

    def _auto_check(self):
        if self.config.get("auto_update") and self.updates.supported():
            self.updates.check(silent=True, then_download=self._background())

    def check_updates(self):
        """Кнопка «Проверить» в настройках."""
        self.updates.check(then_download=self._background())

    def _check_from_tray(self):
        if not self.updates.supported():
            self.toast.show_message(tr("update.dev"))
            return
        ready = self.updates.ready_version()
        if ready:
            self._toast_ready(ready)
            return
        self._tray_check = True
        if self.updates.downloading():
            self.toast.show_message(tr("toast.downloading", version=self.updates.downloading()),
                                    tr("toast.downloading_sub"), tag="update")
            return
        self.toast.show_message(tr("toast.checking"), tag="update")
        self.updates.check(then_download=True)

    def install_update(self):
        """Поставить сейчас: карточка с прогрессом в строке, потом перезапуск."""
        if not self.updates.supported():
            self.toast.show_message(tr("update.dev"))
            return
        self.toast.close_message("update")
        if self.updates.ready_version():
            self.restart_and_update()
            return
        self._install_now = True
        version = self.updates.downloading() or self.updates.latest_available()
        self.panel.show_update_card(version, self.updates.fraction()
                                    if self.updates.downloading() else 0.0)
        self.updates.download()

    def restart_and_update(self):
        version = self.updates.ready_version()
        if not version:
            return
        self._install_now = True
        self.toast.close_message("update")
        self.panel.show_update_card(version, 1.0, restarting=True)
        QTimer.singleShot(RESTART_DELAY_MS, self._apply_update)

    def _apply_update(self):
        """
        Сначала помощник, потом выход. Не запустился — программа должна остаться
        целой: карточку убираем, строку отпускаем, говорим, что не вышло.
        """
        if self.updates.start_helper():
            self.hotkeys.unregister_all()
            self.toast.hide()
            self.tray.hide()
            self.updates.exit_now()
            return
        logbook.log("обновление: помощник не запустился")
        self._install_now = False
        self.engine.update_ready = False
        self.panel.set_update_ready("")
        self.panel.hide_update_card()
        self.panel.refresh_results()
        self.toast.show_message(tr("toast.install_failed"), tr("toast.install_failed_sub"),
                                TOAST_LONG_MS)

    def _toast_ready(self, version):
        self.toast.show_message(tr("toast.ready", version=version), tr("toast.ready_sub"),
                                0, on_click=self.restart_and_update, tag="update")

    def _on_update_progress(self, fraction):
        if self._install_now:
            self.panel.update_card.set_progress(fraction)

    def _on_update_state(self, state, version):
        tray = self._tray_check
        if state in ("current", "error", "ready", "failed"):
            self._tray_check = False

        if state == "available":
            self.engine.update_version = version
            self.panel.refresh_results()
            if self._install_now:
                return
            if tray:
                self.toast.show_message(tr("toast.downloading", version=version),
                                        tr("toast.downloading_sub"), tag="update")
            elif (not self._background() and version != self._notified_version
                  and version != self.config.get("update_dismissed_version")):
                # Плашка своя, а не системная: системные уведомления глушит
                # «Фокусировка внимания», и сообщение о версии не доходит.
                self._notified_version = version
                self.toast.show_message(
                    tr("toast.available", version=version), tr("toast.available_sub"), 0,
                    on_click=self.install_update,
                    on_close=lambda: self.config.set("update_dismissed_version", version),
                    tag="update")
        elif state == "downloading":
            if self._install_now:
                self.panel.show_update_card(version, self.updates.fraction())
        elif state == "ready":
            self.engine.update_version = version
            self.engine.update_ready = True
            if self._install_now:
                self.panel.update_card.set_restarting()
                QTimer.singleShot(RESTART_DELAY_MS, self._apply_update)
                return
            self.panel.set_update_ready(version)
            self.panel.refresh_results()
            if tray:
                self._toast_ready(version)
        elif state == "failed":
            # Фоновая загрузка сама по себе сорвалась — молчим: следующая
            # проверка попробует снова. Сказать надо тому, кто ждал.
            if self._install_now or tray:
                self._install_now = False
                self.panel.hide_update_card()
                self.toast.show_message(tr("toast.download_failed"),
                                        tr("toast.download_failed_sub"), TOAST_LONG_MS,
                                        tag="update")
        elif state == "current":
            if tray:
                self.toast.show_message(tr("toast.current"), tag="update")
        elif state == "error":
            if tray:
                self.toast.show_message(tr("toast.check_failed"), tag="update")


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
