"""
Автозапуск при старте Windows через HKCU\\...\\CurrentVersion\\Run.

Без прав администратора. В dev-режиме (не собранный exe) реестр не трогаем,
иначе в автозапуск прописался бы python.exe.

Источник истины — настройка в config.json, как в Knack (см. Spotty.start):
путь к exe переписывается на каждом старте, поэтому после переустановки в
другую папку автозапуск не указывает в пустоту.

Отдельно — диспетчер задач. Его «Отключить» не удаляет запись из Run, а
ставит флажок в StartupApproved\\Run: запись есть, но Windows её не
запускает. Такую запись считаем выключенной, а включая, флажок снимаем.
"""

import os
import sys

from .constants import APP_NAME

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
_NAME = APP_NAME


def supported():
    """В dev-режиме автозапуск не настраивается — регистрировать нечего."""
    return bool(getattr(sys, "frozen", False))


def _registered():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _NAME)
        return True
    except OSError:
        return False


def disabled_in_task_manager():
    """Запись есть, но её выключили в диспетчере задач (первый байт нечётный)."""
    if not supported():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_KEY) as k:
            data, _type = winreg.QueryValueEx(k, _NAME)
        return bool(data) and data[0] % 2 == 1
    except OSError:
        return False


def is_enabled():
    """Windows действительно запустит Spotty при входе."""
    return supported() and _registered() and not disabled_in_task_manager()


def _clear_approval(winreg):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, _NAME)
    except OSError:
        pass


def set_enabled(on):
    """True при успехе (и в dev, где регистрировать нечего)."""
    if not supported():
        return True
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            if on:
                exe = os.path.abspath(sys.executable)
                winreg.SetValueEx(k, _NAME, 0, winreg.REG_SZ, f'"{exe}"')
            else:
                try:
                    winreg.DeleteValue(k, _NAME)
                except FileNotFoundError:
                    pass
        # Флажок диспетчера задач снимаем в обоих случаях: при включении он
        # иначе оставил бы запись мёртвой, при выключении — висел бы сиротой.
        _clear_approval(winreg)
        return True
    except OSError:
        return False
