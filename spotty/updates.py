"""
Проверка и установка обновлений — обёртка над core/updater (перенесено из Knack).

Сеть и распаковка идут в отдельном потоке: сходить к GitHub и скачать десяток
мегабайт на потоке интерфейса значит подвесить строку.
"""

import os
import threading

from PySide6.QtCore import QObject, Signal

from .core import logbook, updater


class UpdateService(QObject):
    """
    `state(ключ, версия)` — что происходит: checking, current, available,
    downloading, ready, error. Настройки и трей показывают это словами.
    """

    state = Signal(str, str)
    progress = Signal(float)        # доля скачанного 0..1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        self._latest = {}
        self._installing = False
        self._last = ("", "")
        self.state.connect(lambda s, v: setattr(self, "_last", (s, v)))

    def supported(self):
        """В режиме разработки подменять нечего — обновляемся только собранными."""
        return updater.is_frozen()

    def last_state(self):
        return self._last

    def latest_available(self):
        """Версия, которую можно поставить, или пустая строка."""
        return self._latest.get("version", "") if self._latest.get("status") == "available" \
            else ""

    # --- проверка ------------------------------------------------------------ #

    def check(self, then_install=False, silent=False):
        if self._busy:
            return
        self._busy = True
        if not silent:
            self.state.emit("checking", "")
        threading.Thread(target=self._check_worker, args=(then_install, silent),
                         name="spotty-update", daemon=True).start()

    def _check_worker(self, then_install, silent):
        try:
            result = updater.check()
        except Exception as error:
            logbook.exc("update check")
            result = {"status": "error", "error": str(error)}

        self._latest = result
        status = result.get("status")
        if status == "available":
            self.state.emit("available", result.get("version", ""))
            if then_install and result.get("url"):
                self._download_worker(result)
                return
        elif status == "current":
            if not silent:
                self.state.emit("current", result.get("version", ""))
        else:
            logbook.log("обновление: не удалось проверить —", result.get("error"))
            if not silent:
                self.state.emit("error", "")
        self._installing = False
        self._busy = False

    # --- установка ------------------------------------------------------------ #

    def install(self):
        """Качает найденное обновление; по готовности — state("ready")."""
        if self._installing:
            return
        self._installing = True
        if self._busy or self._latest.get("status") != "available":
            self._busy = False
            self.check(then_install=True)
            return
        self._busy = True
        threading.Thread(target=self._download_worker, args=(self._latest,),
                         name="spotty-update", daemon=True).start()

    def _download_worker(self, result):
        version = result.get("version", "")
        try:
            self.state.emit("downloading", version)
            self.progress.emit(0.0)
            updater.download(result.get("url"), on_progress=self.progress.emit)
        except Exception:
            logbook.exc("update download")
            self.state.emit("error", version)
            self._busy = False
            self._installing = False
            return
        self._busy = False
        self.state.emit("ready", version)

    # --- применение ----------------------------------------------------------- #

    @staticmethod
    def start_helper():
        """Запускает помощника, который подменит exe. True — пошло."""
        return bool(updater.restart_to_update())

    @staticmethod
    def exit_now():
        """
        Обрывает процесс, освобождая свой exe.

        Обычный выход тут не годится: пока процесс жив, его файл заблокирован, и
        помощник будет ждать впустую.
        """
        os._exit(0)
