"""
Запуск пунктов в фоновом потоке.

ShellExecute бывает медленным: приложение из Магазина, файл на сетевом диске,
а окно UAC для «от администратора» и вовсе ждёт, пока человек ответит. Строка
к этому моменту уже закрыта, а главный поток должен оставаться свободным —
иначе повторное нажатие хоткея ждало бы, пока запуск закончится.
"""

import ctypes
import threading

from PySide6.QtCore import QObject, Signal, Slot

from . import logbook

COINIT_APARTMENTTHREADED = 0x2


class Launcher(QObject):
    _finished = Signal(object, object)          # (on_done, результат)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._finished.connect(self._deliver)

    def run(self, job, on_done=None):
        """
        job() — в фоне; on_done(результат) — потом, в главном потоке.
        Результат: True — запущено, False — ошибка, None — человек сам
        отказался (нажал «Нет» в окне UAC).
        """
        threading.Thread(target=self._worker, args=(job, on_done),
                         name="spotty-launch", daemon=True).start()

    def _worker(self, job, on_done):
        # Оболочке нужен COM в однопоточном режиме: часть обработчиков файлов
        # без него не запускается.
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        try:
            result = job()
        except Exception:
            logbook.exc("запуск")
            result = False
        finally:
            ole32.CoUninitialize()
        try:
            self._finished.emit(on_done, result)
        except RuntimeError:
            pass                    # программа уже закрывается

    @Slot(object, object)
    def _deliver(self, on_done, result):
        if on_done is not None:
            on_done(result)
