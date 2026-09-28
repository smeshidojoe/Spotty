"""
Фоновые обходы диска: низкий приоритет и пауза, пока открыта строка.

Обход папок — цикл на Python, и хотя он в своём потоке, интерпретатор у
потоков один на всех: пока обход крутится, главный поток получает время
урывками, и ввод в строке подтормаживает. Поэтому обходы ждут, пока строку
закроют, — человек, который печатает, важнее списка, который обновится на
пару секунд позже.
"""

import ctypes
import threading
from ctypes import wintypes

_THREAD_MODE_BACKGROUND_BEGIN = 0x00010000

_idle = threading.Event()
_idle.set()


def pause():
    """Строку открыли — обходы встают на ближайшей папке."""
    _idle.clear()


def resume():
    _idle.set()


def wait():
    """Вызывать в цикле обхода: вернётся сразу или когда строку закроют."""
    _idle.wait()


def low_priority():
    """Поток с фоновым приоритетом: Windows пропускает вперёд всех остальных,
    в том числе к диску."""
    try:
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentThread.restype = wintypes.HANDLE
        kernel.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
        kernel.SetThreadPriority(kernel.GetCurrentThread(), _THREAD_MODE_BACKGROUND_BEGIN)
    except Exception:
        pass
