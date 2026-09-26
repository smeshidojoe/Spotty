"""
Глобальный хоткей через RegisterHotKey.

Без сторонних пакетов и без низкоуровневых хуков клавиатуры: сочетание
регистрирует сама Windows, а WM_HOTKEY прилетает в очередь сообщений потока
(hWnd = NULL) — Qt прогоняет её через nativeEventFilter, оттуда и ловим.
"""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

MOD_ALT     = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT   = 0x0004
MOD_WIN     = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312

_MODS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "super": MOD_WIN, "meta": MOD_WIN,
}

_KEYS = {
    "space": 0x20, "esc": 0x1B, "escape": 0x1B, "tab": 0x09,
    "enter": 0x0D, "return": 0x0D, "backspace": 0x08, "insert": 0x2D,
    "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD,
    "\\": 0xDC, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
}
for _i in range(1, 25):
    _KEYS["f%d" % _i] = 0x6F + _i


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd",    wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam",  wintypes.WPARAM),
        ("lParam",  wintypes.LPARAM),
        ("time",    wintypes.DWORD),
        ("pt_x",    wintypes.LONG),
        ("pt_y",    wintypes.LONG),
    ]


def parse(combo):
    """'ctrl+alt+k' -> (mods, vk). Возвращает None, если разобрать не вышло."""
    mods, vk = 0, None
    for part in str(combo).lower().replace(" ", "").split("+"):
        if not part:
            continue
        if part in _MODS:
            mods |= _MODS[part]
        elif part in _KEYS:
            vk = _KEYS[part]
        elif len(part) == 1 and (part.isdigit() or ("a" <= part <= "z")):
            vk = ord(part.upper())
        else:
            return None
    if vk is None or mods == 0:
        return None            # без модификатора хоткей перехватил бы обычную клавишу
    return mods, vk


class HotkeyManager(QObject, QAbstractNativeEventFilter):
    """Регистрирует сочетания и превращает WM_HOTKEY в сигнал `triggered(name)`."""

    triggered = Signal(str)

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._by_id = {}       # id -> имя
        self._by_name = {}     # имя -> id
        self._next_id = 1
        self._installed = False

    def install(self, app):
        if not self._installed:
            app.installNativeEventFilter(self)
            self._installed = True

    def register(self, name, combo):
        """Перерегистрирует сочетание под именем `name`. True — получилось."""
        self.unregister(name)
        parsed = parse(combo)
        if parsed is None:
            return False
        mods, vk = parsed
        hk_id = self._next_id
        self._next_id += 1
        try:
            ok = ctypes.windll.user32.RegisterHotKey(
                None, hk_id, mods | MOD_NOREPEAT, vk)
        except Exception:
            ok = False
        if not ok:
            return False       # сочетание занято другой программой
        self._by_id[hk_id] = name
        self._by_name[name] = hk_id
        return True

    def unregister(self, name):
        hk_id = self._by_name.pop(name, None)
        if hk_id is None:
            return
        self._by_id.pop(hk_id, None)
        try:
            ctypes.windll.user32.UnregisterHotKey(None, hk_id)
        except Exception:
            pass

    def unregister_all(self):
        for name in list(self._by_name):
            self.unregister(name)

    def is_registered(self, name):
        return name in self._by_name

    def nativeEventFilter(self, event_type, message):
        if event_type != b"windows_generic_MSG":
            return False, 0
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
        except (TypeError, ValueError):
            return False, 0
        if msg.message == WM_HOTKEY:
            name = self._by_id.get(int(msg.wParam))
            if name:
                self.triggered.emit(name)
                return True, 0
        return False, 0


# --- возврат нажатия программе ----------------------------------------------- #

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
# Клавиши из «серого» блока: без флага игра приняла бы их за цифровой блок.
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E}


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    # Нужна только ради размера объединения: SendInput сверяет cbSize.
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def pass_through(combo):
    """
    Отдать уже перехваченное нажатие окну на переднем плане.

    RegisterHotKey съедает нажатие основной клавиши, модификаторы программа
    получила сама. Сочетание к этому моменту снято с регистрации, поэтому
    повторяем нажатие — и оно доходит как обычное. Отпускание придёт от
    клавиатуры само; если клавишу уже отпустили, отпускаем и мы, иначе она
    «залипла» бы в игре.
    """
    parsed = parse(combo)
    if parsed is None:
        return
    vk = parsed[1]
    user32 = ctypes.windll.user32
    user32.GetAsyncKeyState.restype = ctypes.c_short
    flags = KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0
    scan = user32.MapVirtualKeyW(vk, 0)
    events = [flags]
    if not user32.GetAsyncKeyState(vk) & 0x8000:
        events.append(flags | KEYEVENTF_KEYUP)
    inputs = (_INPUT * len(events))()
    for item, event_flags in zip(inputs, events):
        item.type = INPUT_KEYBOARD
        item.ki = _KEYBDINPUT(vk, scan, event_flags, 0, 0)
    user32.SendInput(len(events), inputs, ctypes.sizeof(_INPUT))


# --- отображение и запись сочетаний ------------------------------------------ #

_PRETTY = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift",
           "win": "Win", "super": "Win", "meta": "Win", "space": "Space",
           "esc": "Esc", "escape": "Esc", "tab": "Tab", "enter": "Enter",
           "return": "Enter", "backspace": "Backspace", "insert": "Ins",
           "delete": "Del", "home": "Home", "end": "End",
           "pageup": "PgUp", "pagedown": "PgDn",
           "left": "←", "up": "↑", "right": "→", "down": "↓"}


def keycaps(combo):
    """'ctrl+e' -> ['Ctrl', 'E'] — подписи клавиш для отрисовки."""
    parts = [p for p in str(combo).lower().replace(" ", "").split("+") if p]
    return [_PRETTY.get(p, p.upper()) for p in parts]


def display(combo):
    return "+".join(keycaps(combo))


def from_qt(key, modifiers, vk=0):
    """
    Нажатие в Qt -> строка вида 'ctrl+shift+k' или None.

    None — если нажат один модификатор (ждём основную клавишу) или клавиша не
    из тех, что умеет регистрировать parse(). Буквы и цифры берём по
    виртуальному коду `vk`: на русской раскладке Qt отдаёт кириллицу, а
    RegisterHotKey работает с физической клавишей.
    """
    from PySide6.QtCore import Qt

    key = int(key)
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        name = chr(vk).lower()
    elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        name = chr(key).lower()
    elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        name = "f%d" % (key - Qt.Key.Key_F1 + 1)
    else:
        name = {
            Qt.Key.Key_Space: "space", Qt.Key.Key_Tab: "tab",
            Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter",
            Qt.Key.Key_Backspace: "backspace", Qt.Key.Key_Insert: "insert",
            Qt.Key.Key_Delete: "delete", Qt.Key.Key_Home: "home",
            Qt.Key.Key_End: "end", Qt.Key.Key_PageUp: "pageup",
            Qt.Key.Key_PageDown: "pagedown", Qt.Key.Key_Left: "left",
            Qt.Key.Key_Up: "up", Qt.Key.Key_Right: "right",
            Qt.Key.Key_Down: "down", Qt.Key.Key_QuoteLeft: "`",
            Qt.Key.Key_Minus: "-", Qt.Key.Key_Equal: "=",
            Qt.Key.Key_BracketLeft: "[", Qt.Key.Key_BracketRight: "]",
            Qt.Key.Key_Backslash: "\\", Qt.Key.Key_Semicolon: ";",
            Qt.Key.Key_Apostrophe: "'", Qt.Key.Key_Comma: ",",
            Qt.Key.Key_Period: ".", Qt.Key.Key_Slash: "/",
        }.get(key)
    if name is None:
        return None
    mods = []
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        mods.append("ctrl")
    if modifiers & Qt.KeyboardModifier.AltModifier:
        mods.append("alt")
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        mods.append("shift")
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        mods.append("win")
    if not mods:
        return None
    return "+".join(mods + [name])
