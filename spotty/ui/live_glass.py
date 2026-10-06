"""
Живой фон (настройка «Живой фон»): пока строка открыта, то, что под ней,
переснимается 24, 30 или 60 раз в секунду (на выбор), и стекло следует за
видео, прокруткой и окнами под ним. По образцу Snatchr.

Как это устроено:

* Чтобы строка не снимала саму себя, она исключена из захвата экрана
  (WDA_EXCLUDEFROMCAPTURE). Побочный эффект — с живым фоном строки не видно
  на скриншотах и в записи экрана.
* Исключение принимает только окно, собранное через GPU. Полупрозрачное окно
  Qt по умолчанию рисует в памяти и отдаёт системе целиком (layered window) —
  такое Windows из захвата не исключает. На GPU окно переводит любой
  QRhiWidget внутри, даже скрытый 1x1. Тип окна выбирается при создании его
  хендла, поэтому при включении на открытой строке окно пересоздаётся.
* Снимок (~10 мс у GDI) — в фоновом потоке, стекло (обычно ~4 мс, изредка
  до 30) — в главном. Новый кадр не заказываем, пока не готов предыдущий.
  Стекло пересчитываем, только если фон заметно поменялся (на статичном столе
  — ни разу) и в очереди нет нажатий: набор важнее свежести фона.
"""

import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from ..core import logbook, winapi
from ..glass import capture

# Кадров в секунду — на выбор в настройках. Захват GDI ~10 мс в фоновом
# потоке, поэтому 60 — уже около предела: чаще снимок просто не успеет.
RATES = (24, 30, 60)
DEFAULT_RATE = 24
PROBE = 24                    # «фон поменялся?» — сравниваем копии 24x24


class LiveGlass(QObject):
    _frame = Signal(object)   # (снимок, его копия 24x24) из фонового потока

    def __init__(self, window, backdrop):
        super().__init__(window)
        self._win = window
        self._backdrop = backdrop
        self.enabled = False
        self._gpu = None              # скрытый QRhiWidget: окно собирается через GPU
        self._excluded = False
        self._busy = False
        self._probe = None
        self._frame.connect(self._on_frame)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self.set_rate(DEFAULT_RATE)

    @staticmethod
    def supported():
        # Без оконной системы (тесты, offscreen) GPU-окна не бывает.
        return QGuiApplication.platformName() == "windows"

    def gpu(self):
        """Окно собирается через GPU. До первого показа — бесплатно, после —
        только вместе с пересозданием окна (см. Panel.set_live_glass)."""
        if self._gpu is not None or not self.supported():
            return False
        try:
            from PySide6.QtWidgets import QRhiWidget
        except ImportError:
            return False
        self._gpu = QRhiWidget(self._win)
        self._gpu.setFixedSize(1, 1)
        self._gpu.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._gpu.hide()
        return True

    def has_gpu(self):
        return self._gpu is not None

    def set_rate(self, fps):
        fps = fps if fps in RATES else DEFAULT_RATE
        self._timer.setInterval(round(1000 / fps))

    # --- кадры ------------------------------------------------------------- #

    def start(self):
        """Строка показана (или включили настройку на открытой)."""
        if not (self.enabled and self._gpu is not None and self._backdrop.live_ready()):
            self.stop()
            return
        if not self._excluded:
            self._excluded = capture.exclude_from_capture(int(self._win.winId()), True)
            if not self._excluded:
                # Без исключения строка снимала бы саму себя — стекло
                # затягивало бы её же отражением.
                logbook.log("живой фон недоступен: окно не исключается из захвата")
                return
        self._probe = None
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def release(self):
        """Настройку выключили: строка снова видна на скриншотах."""
        self.stop()
        if self._excluded:
            capture.exclude_from_capture(int(self._win.winId()), False)
            self._excluded = False

    def window_recreated(self):
        """Хендл окна новый — исключение из захвата надо ставить заново."""
        self._excluded = False

    def _tick(self):
        if not self._win.isVisible():
            self.stop()
            return
        rect = self._backdrop.source_rect()
        if self._busy or rect is None:
            return
        self._busy = True
        threading.Thread(target=self._grab, args=(rect,), name="live-glass",
                         daemon=True).start()

    def _grab(self, rect):
        frame = None
        try:
            shot = capture.grab(rect.x(), rect.y(), rect.width(), rect.height())
            if shot is not None:
                frame = (shot, shot.scaled(PROBE, PROBE, Qt.AspectRatioMode.IgnoreAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass
        finally:
            self._frame.emit(frame)

    def _on_frame(self, frame):
        self._busy = False
        if frame is None or not self._timer.isActive():
            return
        shot, probe = frame
        if probe == self._probe or winapi.keys_pending():
            return
        self._probe = probe
        self._backdrop.take_shot(shot)
        self._win.update()
