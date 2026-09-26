"""
Полноэкранные программы: игры, плееры, презентации.

Пока такая программа на переднем плане, сочетание вызова принадлежит ей:
Ctrl+E в игре — «присесть» и «взаимодействовать», а не строка поверх игры.
Сочетание на это время снимаем с регистрации, и нажатие доходит до игры само,
как будто Spotty нет.

Браузеры — исключение: на весь экран в них смотрят видео и читают, и строка
там нужна как обычно.

Проверка стоит несколько системных вызовов, поэтому постоянно ничего не
опрашиваем: смотрим при смене активного окна (хук Windows) и ещё раз чуть
позже — игра разворачивается на весь экран не сразу. Пока полноэкранная
программа активна, раз в секунду проверяем, не вышла ли она из этого режима.
"""

import ctypes
import os
import winreg
from ctypes import wintypes

from PySide6.QtCore import QObject, QTimer, Signal

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
MONITOR_DEFAULTTONEAREST = 2
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Игра встаёт на весь экран через секунду-другую после появления окна.
RECHECK_MS = 2000
POLL_MS = 1000

# Рабочий стол и панель задач накрывают экран, но программой не считаются.
_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
# Через это окно проводника Windows переключает активное окно, и на долю
# секунды активным становится оно. Судить по нему рано — ждём настоящее.
_TRANSIENT_CLASSES = {"ForegroundStaging"}

# Браузеры, которые могли не записаться в реестр (портативные копии).
# Tor Browser и форки Firefox работают под именем firefox.exe.
_BROWSERS = {
    "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe",
    "vivaldi.exe", "browser.exe", "iexplore.exe", "chromium.exe", "thorium.exe",
    "waterfox.exe", "librewolf.exe", "floorp.exe", "zen.exe", "palemoon.exe",
    "seamonkey.exe", "maxthon.exe", "whale.exe", "arc.exe", "yandex.exe",
}

_WinEventProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                   wintypes.LONG, wintypes.LONG, wintypes.DWORD,
                                   wintypes.DWORD)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
                                   _WinEventProc, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD]
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsZoomed.argtypes = [wintypes.HWND]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def covers_screen(hwnd):
    """Окно закрывает весь свой монитор, включая панель задач."""
    if user32.IsIconic(hwnd):
        return False
    rect = wintypes.RECT()
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not (monitor and user32.GetWindowRect(hwnd, ctypes.byref(rect))
            and user32.GetMonitorInfoW(monitor, ctypes.byref(info))):
        return False
    screen = info.rcMonitor
    if (rect.left > screen.left or rect.top > screen.top
            or rect.right < screen.right or rect.bottom < screen.bottom):
        return False
    # При автоскрытии панели задач развёрнутое окно тоже занимает весь экран,
    # но это обычное окно с заголовком, а не полноэкранный режим.
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    return not (style & WS_CAPTION == WS_CAPTION and user32.IsZoomed(hwnd))


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def process_path(pid):
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def registered_browsers():
    """
    Браузеры, которые Windows предлагает в «Приложениях по умолчанию».
    Все настоящие браузеры записываются в Clients\\StartMenuInternet.
    """
    found = set()
    places = [(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Clients\StartMenuInternet"),
              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet"),
              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Clients\StartMenuInternet")]
    for root, path in places:
        try:
            key = winreg.OpenKey(root, path)
        except OSError:
            continue
        with key:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(key, index)
                except OSError:
                    break
                index += 1
                try:
                    command = winreg.QueryValue(key, name + r"\shell\open\command")
                except OSError:
                    continue
                exe = _exe_from_command(command)
                if exe:
                    found.add(os.path.normcase(exe))
    return found


def _exe_from_command(command):
    command = command.strip()
    if command.startswith('"'):
        return command[1:].split('"', 1)[0]
    lower = command.lower()
    end = lower.find(".exe")
    return command[:end + 4] if end >= 0 else ""


class FullscreenGuard(QObject):
    """
    Следит, не развёрнута ли на весь экран программа на переднем плане.
    `changed(blocked)` — сочетание вызова пора снять или вернуть.
    """

    changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._blocked = False
        self._hook = None
        self._proc = _WinEventProc(self._on_foreground)   # ссылка живёт, пока жив хук
        self._browsers = None
        self._browser_cache = (None, False)               # (hwnd, pid), браузер ли
        self._recheck = QTimer(self, singleShot=True, interval=RECHECK_MS)
        self._recheck.timeout.connect(self.update)
        self._poll = QTimer(self, interval=POLL_MS)
        self._poll.timeout.connect(self.update)

    def enabled(self):
        return self._enabled

    def blocked(self):
        return self._blocked

    def set_enabled(self, on):
        if on == self._enabled:
            return
        self._enabled = on
        if on:
            self._browsers = None          # браузер могли поставить, пока было выключено
            self._hook = user32.SetWinEventHook(
                EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, self._proc,
                0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
            self.update()
        else:
            if self._hook:
                user32.UnhookWinEvent(self._hook)
                self._hook = None
            self._recheck.stop()
            self._set_blocked(False)

    def update(self):
        """Проверить окно на переднем плане прямо сейчас. Возвращает blocked()."""
        if self._enabled:
            fullscreen = self._foreground_is_fullscreen()
            if fullscreen is not None:
                self._set_blocked(fullscreen)
        return self._blocked

    def _on_foreground(self, _hook, _event, _hwnd, _obj, _child, _thread, _time):
        self.update()
        self._recheck.start()

    def _set_blocked(self, blocked):
        if blocked:
            self._poll.start()
        else:
            self._poll.stop()
        if blocked != self._blocked:
            self._blocked = blocked
            self.changed.emit(blocked)

    def _foreground_is_fullscreen(self):
        """None — активное окно как раз меняется, решать рано."""
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        name = _class_name(hwnd)
        if name in _TRANSIENT_CLASSES:
            return None
        if name in _SHELL_CLASSES or not covers_screen(hwnd):
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return False
        return not self._is_browser(hwnd, pid.value)

    def _is_browser(self, hwnd, pid):
        key, answer = self._browser_cache
        if key == (hwnd, pid):
            return answer
        if self._browsers is None:
            self._browsers = registered_browsers()
        path = process_path(pid)
        # Путь не отдали (процесс под защитой античита) — значит, не браузер.
        answer = bool(path) and (os.path.normcase(path) in self._browsers
                                 or os.path.basename(path).lower() in _BROWSERS)
        self._browser_cache = ((hwnd, pid), answer)
        return answer
