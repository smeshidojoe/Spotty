"""Настройки программы: %APPDATA%\\Spotty\\config.json.

Автозапуск хранится здесь и на каждом старте переносится в реестр (см.
Spotty.start). Пока его тут нет (первый запуск), берём из реестра: галочку мог
поставить или снять установщик.
"""

import os

from . import jsonfile
from .constants import CONFIG_PATH


def known_folder(name):
    """Рабочий стол, документы, загрузки — с учётом того, что их могли перенести."""
    ids = {
        "desktop":   "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
        "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
        "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    }
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        guid = uuid.UUID(ids[name])
        buf = ctypes.c_wchar_p()
        folder_id = (ctypes.c_byte * 16).from_buffer_copy(guid.bytes_le)
        shell32 = ctypes.windll.shell32
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p)]
        if shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None,
                                        ctypes.byref(buf)) == 0:
            path = buf.value
            ctypes.windll.ole32.CoTaskMemFree(buf)
            if path:
                return path
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), name.capitalize())


def default_folders():
    return [p for p in (known_folder("desktop"), known_folder("documents"),
                        known_folder("downloads")) if os.path.isdir(p)]


UPDATE_MODES = ("notify", "background")

DEFAULTS = {
    "hotkey": "ctrl+e",
    # Не открывать строку поверх полноэкранных программ (core/fullscreen.py).
    "fullscreen_guard": False,
    "glass": True,
    # Стекло следит за тем, что под строкой, пока она открыта (ui/live_glass.py).
    "live_glass": False,
    "live_fps": 24,              # кадров в секунду у живого фона: 24 | 30 | 60
    "auto_update": True,
    # notify — плашка в углу, установка с полосой прогресса в строке;
    # background — качается само, в строке появляется «Перезапустить и обновить».
    "update_mode": "background",
    "update_dismissed_version": "",   # о ней уже сказали «позже» — не напоминаем
    "language": "en",            # en | ru
    "folders": None,             # None — ещё не настраивали, берём default_folders()
    "scan_drives": True,         # искать программы на всех дисках (search/programs.py)
    "autostart": None,           # None — ещё не решали, берём из реестра
    "web_engine": "google",      # см. search/web.py
}

# В файл пишем только то, что человек менял: тогда новое умолчание в
# следующей версии дойдёт до всех, кто эту настройку не трогал. 0.1.0 писал
# все настройки подряд, и отличить его умолчание от выбора нельзя — такие
# значения считаем умолчаниями.
FORMAT = 2
_V1_DEFAULTS = {"update_mode": "notify"}
_MISSING = object()


def _from_v1(saved):
    return {key: value for key, value in saved.items()
            if value != DEFAULTS.get(key) and value != _V1_DEFAULTS.get(key, _MISSING)}


class Config:
    def __init__(self, path=CONFIG_PATH):
        self._path = path
        saved = jsonfile.load(path, {})
        if not isinstance(saved, dict):
            saved = {}
        if saved.pop("format", 1) < FORMAT:
            saved = _from_v1(saved)
        self._saved = saved
        self._data = dict(DEFAULTS)
        self._data.update(saved)
        if not isinstance(self._data.get("folders"), list):
            self._data["folders"] = default_folders()

    def get(self, key):
        return self._data.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self._saved[key] = value
        jsonfile.save(self._path, dict(self._saved, format=FORMAT))
