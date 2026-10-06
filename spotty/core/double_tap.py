"""
Двойное нажатие модификатора: Ctrl, Ctrl — как в Listary и Everything.

RegisterHotKey одиночный модификатор не регистрирует, поэтому нажатия
слушаем через Raw Input (RIDEV_INPUTSINK): Windows присылает копию каждого
нажатия в очередь нашего скрытого окна, даже когда Spotty не впереди.

Не низкоуровневый хук (WH_KEYBOARD_LL) — намеренно. Хук стоит на пути
каждого нажатия в системе: Windows ждёт его ответа, и пока Python занят
(главный поток держит GIL в долгом вызове), клавиатура тормозит везде — до
~300 мс на нажатие, потом Windows и вовсе молча снимает хук. Raw Input
ничего не ждёт: если мы заняты, сообщения просто копятся в очереди, а
нажатия идут дальше без задержки. Ничего не съедаем и не меняем.

Считается только «чистое» нажатие: модификатор нажали и отпустили, ничего
больше не нажимая, быстро. Ctrl+C, Ctrl+V подряд — не двойной Ctrl.
Срабатываем на отпускании второго нажатия: до него ещё может прийти буква.
"""

import ctypes
import threading
from ctypes import wintypes

WM_INPUT = 0x00FF
WM_QUIT = 0x0012
RID_INPUT = 0x10000003
RIM_TYPEKEYBOARD = 1
RI_KEY_BREAK = 0x01
RIDEV_REMOVE = 0x00000001
RIDEV_INPUTSINK = 0x00000100
HWND_MESSAGE = -3

# Левая, правая и «общая» клавиша — одна группа: Ctrl слева, Ctrl справа
# считаются одним и тем же модификатором. Win нет: одиночный Win открывает
# «Пуск», а съедать нажатия мы не умеем и не хотим.
GROUPS = {
    "ctrl": {0x11, 0xA2, 0xA3},
    "shift": {0x10, 0xA0, 0xA1},
    "alt": {0x12, 0xA4, 0xA5},
}
MOUSE_BUTTONS = (0x01, 0x02, 0x04, 0x05, 0x06)

TAP_MS = 300        # дольше держали — это не «нажатие», а «зажатие»
GAP_MS = 400        # от отпускания первого до нажатия второго

# Нажатия, которые прислала программа через SendInput (в том числе мы сами
# в hotkey.pass_through), не считаем. Тесты выключают, чтобы нажимать сами.
SKIP_INJECTED = True


class _RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class _RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class _RAWKEYBOARD(ctypes.Structure):
    _fields_ = [("MakeCode", wintypes.USHORT), ("Flags", wintypes.USHORT),
                ("Reserved", wintypes.USHORT), ("VKey", wintypes.USHORT),
                ("Message", wintypes.UINT), ("ExtraInformation", wintypes.ULONG)]


class _RAWINPUT(ctypes.Structure):
    _fields_ = [("header", _RAWINPUTHEADER), ("keyboard", _RAWKEYBOARD)]


_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                    wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(_RAWINPUTDEVICE), wintypes.UINT,
                                            wintypes.UINT]
_user32.GetRawInputData.restype = wintypes.UINT
_user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
                                    ctypes.POINTER(wintypes.UINT), wintypes.UINT]
_user32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                wintypes.UINT]
_user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM,
                                       wintypes.LPARAM]
_user32.GetAsyncKeyState.restype = ctypes.c_short


def modifier(combo):
    """'ctrl+ctrl' -> 'ctrl'. Не двойной модификатор — None."""
    parts = [p for p in str(combo).lower().replace(" ", "").split("+") if p]
    parts = ["ctrl" if p == "control" else p for p in parts]
    if len(parts) == 2 and parts[0] == parts[1] and parts[0] in GROUPS:
        return parts[0]
    return None


class Detector:
    """Ловит двойное чистое нажатие по потоку событий (vk, нажата?, время мс)."""

    def __init__(self, keys):
        self.keys = keys
        self.reset()

    def reset(self):
        self._held = False
        self._clean = False
        self._down = 0
        self._taps = 0
        self._last_up = 0

    def feed(self, vk, down, time):
        """True — только что закончилось второе нажатие."""
        if vk not in self.keys:
            if down:
                # Любая другая клавиша рвёт серию: это было сочетание.
                self._clean = False
                self._taps = 0
            return False
        if down:
            if self._held:
                return False                # автоповтор, пока держат
            self._held, self._clean, self._down = True, True, time
            if self._taps and time - self._last_up > GAP_MS:
                self._taps = 0
            return False
        if not self._held:
            return False
        self._held = False
        if not self._clean or time - self._down > TAP_MS:
            self._taps = 0
            return False
        if self._taps:
            self._taps = 0
            return True
        self._taps, self._last_up = 1, time
        return False

    def spoil(self):
        """Пока держали модификатор, кликнули мышью — это Ctrl+клик."""
        self._clean = False
        self._taps = 0


class DoubleTap:
    """Скрытое окно с Raw Input в своём потоке; `callback()` зовётся оттуда."""

    def __init__(self, combo, callback):
        self._detector = Detector(GROUPS[modifier(combo)])
        self._callback = callback
        self._thread = None
        self._thread_id = 0
        self._ok = False

    def start(self):
        """True — слушаем."""
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,),
                                        name="double-tap", daemon=True)
        self._thread.start()
        ready.wait(2)
        return self._ok

    def stop(self):
        if self._thread is None:
            return
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(1)
        self._thread = None

    def _run(self, ready):
        self._thread_id = _kernel32.GetCurrentThreadId()
        # Окно только для сообщений: невидимо, в Alt+Tab и на панели задач
        # не появляется. Готовый класс STATIC — регистрировать свой не нужно.
        hwnd = _user32.CreateWindowExW(0, "STATIC", "Spotty double tap", 0, 0, 0, 0, 0,
                                       HWND_MESSAGE, None, None, None)
        device = _RAWINPUTDEVICE(0x01, 0x06, RIDEV_INPUTSINK, hwnd)   # клавиатура
        self._ok = bool(hwnd) and bool(_user32.RegisterRawInputDevices(
            ctypes.byref(device), 1, ctypes.sizeof(device)))
        ready.set()
        if self._ok:
            msg = wintypes.MSG()
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_INPUT:
                    self._on_input(msg.lParam, msg.time)
                # WM_INPUT тоже отдаём окну: DefWindowProc освобождает данные.
                _user32.DispatchMessageW(ctypes.byref(msg))
            device = _RAWINPUTDEVICE(0x01, 0x06, RIDEV_REMOVE, None)
            _user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device))
        if hwnd:
            _user32.DestroyWindow(hwnd)

    def _on_input(self, handle, time):
        try:
            data = _RAWINPUT()
            size = wintypes.UINT(ctypes.sizeof(data))
            got = _user32.GetRawInputData(handle, RID_INPUT, ctypes.byref(data),
                                          ctypes.byref(size),
                                          ctypes.sizeof(_RAWINPUTHEADER))
            if got in (0, 0xFFFFFFFF) or data.header.dwType != RIM_TYPEKEYBOARD:
                return
            if SKIP_INJECTED and not data.header.hDevice:
                return                      # SendInput: устройства нет
            down = not data.keyboard.Flags & RI_KEY_BREAK
            if not down and any(_user32.GetAsyncKeyState(b) & 0x8000
                                for b in MOUSE_BUTTONS):
                self._detector.spoil()
            if self._detector.feed(data.keyboard.VKey, down, time):
                self._callback()
        except Exception:
            pass
