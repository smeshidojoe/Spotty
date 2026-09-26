"""
Список установленных программ.

Два источника:
* ярлыки меню «Пуск» (общего и своего) и рабочего стола — у них есть путь,
  поэтому работают «Показать в папке» и запуск от администратора;
* Get-StartApps — всё, что Windows показывает в «Пуске», включая приложения
  Магазина (Калькулятор, Параметры, Терминал), у которых ярлыков нет. Они
  запускаются через shell:AppsFolder\\<AppID>.

Сбор идёт в фоне (PowerShell отвечает около секунды), а прошлый список лежит
в кэше — строка готова к работе сразу после запуска.
"""

import ctypes
import json
import os
import re
import subprocess
import threading
import time

from PySide6.QtCore import QFileInfo, QFileSystemWatcher, QObject, QTimer, Signal

from ..core import jsonfile, logbook
from ..core.constants import APPS_CACHE

_LINK_EXT = (".lnk", ".url", ".appref-ms")
# Мусор из меню «Пуск»: деинсталляторы, справка, сайты производителя.
_JUNK = re.compile(r"(un-?install|деинсталл|удалить|удаление|readme|read me|"
                   r"release notes|documentation|web ?site|веб-сайт|on the web|"
                   r"web pages|homepage|www\.|help file|manual|user ?guide|руководство|"
                   r"license|лицензи)", re.IGNORECASE)
_DOC_TARGET = (".txt", ".htm", ".html", ".chm", ".pdf", ".rtf", ".md", ".hlp",
               ".ini", ".log", ".xml", ".json")
# Во что может смотреть ярлык программы. Ярлык на видео или папку с рабочего
# стола — это файл, его найдёт поиск по файлам.
_RUNNABLE = (".exe", ".bat", ".cmd", ".com", ".msc", ".cpl", ".vbs", ".ps1",
             ".jar", ".appref-ms")
# «Проект - Ярлык» -> «Проект».
_SHORTCUT_SUFFIX = re.compile(r"\s+-\s+(ярлык|shortcut)$", re.IGNORECASE)
CREATE_NO_WINDOW = 0x08000000


def _start_menu_dirs():
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    appdata = os.environ.get("APPDATA", "")
    public = os.environ.get("PUBLIC", r"C:\Users\Public")
    from ..core.config import known_folder
    return [
        (os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs"), True),
        (os.path.join(program_data, r"Microsoft\Windows\Start Menu\Programs"), True),
        (known_folder("desktop"), False),
        (os.path.join(public, "Desktop"), False),
    ]


class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", ctypes.c_void_p), ("iIcon", ctypes.c_int),
                ("dwAttributes", ctypes.c_ulong),
                ("szDisplayName", ctypes.c_wchar * 260),
                ("szTypeName", ctypes.c_wchar * 80)]


_SHGFI_DISPLAYNAME = 0x200


def _display_name(path, fallback):
    """
    Имя, под которым ярлык показывает проводник.

    Системные ярлыки лежат под английскими именами («Notepad.lnk»), а
    русское «Блокнот» берётся из desktop.ini. Без этого строка искала бы
    «Блокнот» только по-английски.
    """
    info = _SHFILEINFOW()
    try:
        if ctypes.windll.shell32.SHGetFileInfoW(
                ctypes.c_wchar_p(path), 0, ctypes.byref(info),
                ctypes.sizeof(info), _SHGFI_DISPLAYNAME):
            name = info.szDisplayName.strip()
            if name:
                return os.path.splitext(name)[0] if name.lower().endswith(
                    _LINK_EXT) else name
    except OSError:
        pass
    return fallback


def _scan_links():
    apps = []
    for root, recursive in _start_menu_dirs():
        if not os.path.isdir(root):
            continue
        walker = os.walk(root) if recursive else [(root, [], os.listdir(root))]
        for folder, _dirs, files in walker:
            for file in files:
                stem, ext = os.path.splitext(file)
                if ext.lower() not in _LINK_EXT or _JUNK.search(stem):
                    continue
                path = os.path.join(folder, file)
                target = ""
                if ext.lower() == ".lnk":
                    # Qt сам разбирает ярлык через IShellLink. Пустая цель —
                    # «объявленный» ярлык установщика MSI или папка оболочки
                    # вроде «Панели управления»: это программы, оставляем.
                    target = QFileInfo(path).symLinkTarget()
                    if target and not target.lower().endswith(_RUNNABLE):
                        continue
                name = _SHORTCUT_SUFFIX.sub("", _display_name(path, stem))
                if _JUNK.search(name):
                    continue
                # Английское имя файла остаётся запасным: «notepad» тоже
                # найдёт «Блокнот».
                alias = _SHORTCUT_SUFFIX.sub("", stem)
                apps.append({"name": name, "target": path, "kind": "link",
                             "path": target,
                             "alias": alias if alias != name else ""})
    return apps


def _start_apps():
    """Get-StartApps через PowerShell: [{"name", "id"}]."""
    shell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                         "WindowsPowerShell", "v1.0", "powershell.exe")
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
              "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(
            [shell if os.path.isfile(shell) else "powershell", "-NoProfile",
             "-NonInteractive", "-Command", script],
            capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
        data = json.loads(out.stdout.decode("utf-8", "replace") or "[]")
    except Exception:
        logbook.exc("Get-StartApps")
        return []
    if isinstance(data, dict):
        data = [data]
    return [{"name": d.get("Name") or "", "id": d.get("AppID") or ""}
            for d in data if isinstance(d, dict)]


def collect():
    apps = _scan_links()
    seen = {a["name"].casefold() for a in apps}
    for entry in _start_apps():
        name, app_id = entry["name"].strip(), entry["id"].strip()
        if not name or not app_id or name.casefold() in seen or _JUNK.search(name):
            continue
        if app_id.lower().endswith(_DOC_TARGET) or "://" in app_id:
            continue
        seen.add(name.casefold())
        # Классическая программа без ярлыка отдаёт путь прямо в AppID.
        path = app_id if os.path.isabs(app_id) and os.path.isfile(app_id) else ""
        apps.append({"name": name, "target": "shell:AppsFolder\\" + app_id,
                     "kind": "shell", "path": path})

    # Один и тот же ярлык часто лежит и в «Пуске», и на рабочем столе.
    unique = {}
    for app in apps:
        unique.setdefault(app["name"].casefold(), app)
    return sorted(unique.values(), key=lambda a: a["name"].casefold())


class AppCatalog(QObject):
    """
    Список программ. Пересобирается при старте, когда меняются папки «Пуска»
    (установщики кладут туда ярлыки) и изредка при открытии строки — на случай
    приложений из Магазина, которые ярлыков не создают.
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.apps = [a for a in jsonfile.load(APPS_CACHE, [])
                     if isinstance(a, dict) and a.get("name") and a.get("target")]
        self._busy = False
        self._last = 0.0
        # Установщик пишет ярлыки пачкой — ждём, пока закончит, и собираем раз.
        self._debounce = QTimer(self, singleShot=True, interval=3000)
        self._debounce.timeout.connect(self.refresh)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _path: self._debounce.start())
        for root, recursive in _start_menu_dirs():
            if recursive and os.path.isdir(root):
                self._watcher.addPath(root)

    def refresh(self, min_interval=0.0):
        """Пересобрать список в фоне. min_interval — не чаще, чем раз в N секунд."""
        if self._busy or time.monotonic() - self._last < min_interval:
            return
        self._busy = True
        self._last = time.monotonic()
        threading.Thread(target=self._worker, name="spotty-apps", daemon=True).start()

    def _worker(self):
        try:
            import ctypes
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)
            apps = collect()
        except Exception:
            logbook.exc("список программ")
            apps = None
        self._busy = False
        if apps:
            changed = apps != self.apps
            self.apps = apps
            jsonfile.save(APPS_CACHE, apps)
            if changed:
                self.changed.emit()
