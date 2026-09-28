"""
Общее для тестов.

Spotty пишет настройки в %APPDATA%\\Spotty, а кэш — в %LOCALAPPDATA%\\Spotty.
Тесты не должны трогать настоящие, поэтому обе переменные подменяются на
временную папку ещё до того, как импортируется что-либо из spotty: пути
считаются при импорте (spotty/core/constants.py).
"""

import ctypes
import os
import shutil
import sys
import tempfile
import time

# Упавший тест не должен оставлять на экране окно «Ошибка приложения» —
# пусть процесс просто завершится с кодом ошибки.
ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)

_TMP = tempfile.mkdtemp(prefix="spotty-tests-")
os.environ["APPDATA"] = os.path.join(_TMP, "Roaming")
os.environ["LOCALAPPDATA"] = os.path.join(_TMP, "Local")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import spotty.core.constants as constants  # noqa: E402

# Иначе тестовый Spotty отобрал бы канал «покажись» у настоящего.
constants.IPC_NAME = "Spotty-IPC-tests"


@pytest.fixture(scope="session", autouse=True)
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def pump(qapp, until=lambda: False, timeout=5.0):
    """Крутить цикл событий, пока until() не станет истинным. Возвращает until()."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if until():
            return True
        time.sleep(0.02)
    qapp.processEvents()
    return until()


# QObject с фоновыми потоками держим до конца процесса, как в самой программе:
# последняя ссылка, отпущенная из чужого потока, удалила бы его не там, где он
# живёт, и процесс упал бы посреди следующего теста.
_KEEP = []


def keep(obj):
    _KEEP.append(obj)
    return obj


@pytest.fixture
def watcher():
    from spotty.core.watch import Watcher
    w = keep(Watcher())
    yield w
    w.stop()


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
