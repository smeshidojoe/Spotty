"""
Тонкие обёртки над WinAPI: фокус окна, запуск через оболочку, терминал.

Всё на ctypes: pywin32 ради десятка вызовов тянуть в сборку незачем.
"""

import ctypes
import os
import subprocess
from ctypes import wintypes

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32
# Отдельная загрузка с use_last_error: иначе код ошибки ShellExecuteEx затрёт
# сам ctypes, и отказ в UAC не отличить от настоящей ошибки.
_shell32_err = ctypes.WinDLL("shell32", use_last_error=True)

SW_SHOWNORMAL = 1
ASFW_ANY = -1
CREATE_NEW_CONSOLE = 0x00000010
SPI_GETCLIENTAREAANIMATION = 0x1042
SEE_MASK_NOASYNC = 0x00000100
ERROR_CANCELLED = 1223


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


_shell32_err.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
_shell32_err.ShellExecuteExW.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND


def force_foreground(hwnd):
    """
    Вывести окно на передний план и отдать ему клавиатуру.

    Обычно хватает SetForegroundWindow: процесс, получивший WM_HOTKEY, имеет
    право забрать фокус. Если Windows всё же отказала (бывает после клика в
    трей), на время подцепляемся к очереди ввода окна, которое сейчас в фокусе,
    — тогда запрет не действует.
    """
    hwnd = wintypes.HWND(int(hwnd))
    if user32.SetForegroundWindow(hwnd) and user32.GetForegroundWindow() == hwnd.value:
        return True
    foreground = user32.GetForegroundWindow()
    theirs = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    ours = kernel32.GetCurrentThreadId()
    attached = bool(theirs and theirs != ours
                    and user32.AttachThreadInput(ours, theirs, True))
    try:
        user32.BringWindowToTop(hwnd)
        return bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(ours, theirs, False)


def allow_foreground_for_launched():
    """
    Разрешаем запускаемой программе забрать фокус.

    Пока строка открыта, передний план наш. Без разрешения только что
    запущенное окно Windows может оставить под другим — ради мигающей кнопки на
    панели задач никто Spotty не открывает.
    """
    try:
        user32.AllowSetForegroundWindow(ASFW_ANY)
    except Exception:
        pass


def shell_open(target, params=None, verb=None, cwd=None):
    """
    ShellExecuteEx. verb="runas" — от администратора.
    True — запуск принят, False — ошибка, None — отказ в окне UAC.

    Вызывается из фонового потока (см. launcher), поэтому SEE_MASK_NOASYNC:
    поток завершится сразу после вызова, и запуск должен закончиться до этого.
    """
    allow_foreground_for_launched()
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOASYNC
    info.lpVerb = verb
    info.lpFile = target
    info.lpParameters = params
    info.lpDirectory = cwd
    info.nShow = SW_SHOWNORMAL
    if _shell32_err.ShellExecuteExW(ctypes.byref(info)):
        return True
    return None if ctypes.get_last_error() == ERROR_CANCELLED else False


def reveal(path):
    """Открыть папку в проводнике с выделенным файлом."""
    allow_foreground_for_launched()
    # Строкой, а не списком: explorer разбирает /select,"путь" сам и не
    # понимает кавычки, которые расставил бы list2cmdline.
    try:
        subprocess.Popen('explorer.exe /select,"%s"' % os.path.normpath(path))
        return True
    except OSError:
        return False


def _cmd_line(command):
    # /s + внешние кавычки: cmd снимает ровно первую и последнюю кавычку и не
    # трогает остальные — иначе ломаются команды вида "C:\Program Files\x.exe" arg.
    return '/s /k "%s"' % command


def run_in_terminal(command, cwd=None, admin=False):
    """Выполнить команду в новом окне cmd; окно остаётся открытым."""
    cwd = cwd if cwd and os.path.isdir(cwd) else os.path.expanduser("~")
    comspec = os.environ.get("ComSpec") or "cmd.exe"
    if admin:
        return shell_open(comspec, _cmd_line(command), "runas", cwd)
    allow_foreground_for_launched()
    try:
        subprocess.Popen('"%s" %s' % (comspec, _cmd_line(command)), cwd=cwd,
                         creationflags=CREATE_NEW_CONSOLE)
        return True
    except OSError:
        return False


def open_terminal(cwd):
    comspec = os.environ.get("ComSpec") or "cmd.exe"
    allow_foreground_for_launched()
    try:
        subprocess.Popen('"%s"' % comspec, cwd=cwd, creationflags=CREATE_NEW_CONSOLE)
        return True
    except OSError:
        return False


def animations_enabled():
    """Флажок «Анимация элементов управления» в параметрах быстродействия."""
    value = wintypes.BOOL(True)
    try:
        user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0,
                                     ctypes.byref(value), 0)
    except Exception:
        return True
    return bool(value.value)


def set_app_id(app_id):
    """Свой AppUserModelID: иначе уведомления трея подписаны как python.exe."""
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
    except Exception:
        pass
