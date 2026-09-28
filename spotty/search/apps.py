"""
Список установленных программ.

Два источника:
* ярлыки меню «Пуск» (общего и своего) и рабочего стола — у них есть путь,
  поэтому работают «Показать в папке» и запуск от администратора;
* Get-StartApps — всё, что Windows показывает в «Пуске», включая приложения
  Магазина (Калькулятор, Параметры, Терминал), у которых ярлыков нет. Они
  запускаются через shell:AppsFolder\\<AppID>.

Прошлый список лежит в кэше — строка готова к работе сразу после запуска.
Дальше он обновляется сам, по событиям Windows (core/watch.py):
* ярлык появился или пропал в «Пуске» (в любой подпапке) или на рабочем
  столе — перечитываем ярлыки. Разобранные ярлыки помним по времени изменения
  файла: заново разбираются только новые, и пересборка занимает десятки
  миллисекунд, а не секунду;
* поменялся список приложений Магазина в реестре — спрашиваем Get-StartApps
  (PowerShell отвечает около секунды, поэтому только тогда).
Установщик пишет пачкой — ждём пару секунд тишины и собираем раз.

Заодно помним, когда какую программу увидели впервые: только что
поставленная сутки ходит с меткой «Новое», пока её не запустят.
"""

import ctypes
import json
import os
import re
import subprocess
import threading
import time

from PySide6.QtCore import QFileInfo, QObject, QTimer, Signal

from ..core import jsonfile, logbook, watch
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

# Здесь Windows записывает приложения Магазина, установленные пользователю.
_PACKAGES_KEY = (r"Software\Classes\Local Settings\Software\Microsoft\Windows"
                 r"\CurrentVersion\AppModel\Repository\Packages")
_LINKS_DEBOUNCE_MS = 2000
_STORE_DEBOUNCE_MS = 3000

# Метка «Новое»: сутки после установки, пока программу ни разу не запустили.
NEW_SECONDS = 24 * 60 * 60
# Пропавшую программу помним неделю: обновление нередко удаляет и заново
# кладёт ярлык, и обновлённая программа не должна выглядеть только что
# поставленной.
_FORGET_SECONDS = 7 * 24 * 60 * 60


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


def _link_files(root, recursive):
    """[(путь, время изменения, размер)] ярлыков в папке."""
    found, stack = [], [root]
    while stack:
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if recursive:
                            stack.append(entry.path)
                        continue
                    if os.path.splitext(entry.name)[1].lower() not in _LINK_EXT:
                        continue
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                found.append((entry.path, info.st_mtime_ns, info.st_size))
    return found


def _parse_link(path):
    """Ярлык -> программа или None (деинсталлятор, справка, ярлык на документ)."""
    stem, ext = os.path.splitext(os.path.basename(path))
    if _JUNK.search(stem):
        return None
    target = ""
    if ext.lower() == ".lnk":
        # Qt сам разбирает ярлык через IShellLink. Пустая цель — «объявленный»
        # ярлык установщика MSI или папка оболочки вроде «Панели управления»:
        # это программы, оставляем.
        target = QFileInfo(path).symLinkTarget()
        if target and not target.lower().endswith(_RUNNABLE):
            return None
    name = _SHORTCUT_SUFFIX.sub("", _display_name(path, stem))
    if _JUNK.search(name):
        return None
    # Английское имя файла остаётся запасным: «notepad» тоже найдёт «Блокнот».
    alias = _SHORTCUT_SUFFIX.sub("", stem)
    return {"name": name, "target": path, "kind": "link", "path": target,
            "alias": alias if alias != name else ""}


def scan_links(cache, dirs=None):
    """
    Ярлыки из «Пуска» и с рабочих столов: (программы, новый кэш).
    cache: путь -> [время изменения, размер, программа или None]. Ярлык, у
    которого не поменялись ни время, ни размер, заново не разбираем — это и
    есть почти всё время сборки.
    """
    apps, fresh = [], {}
    for root, recursive in dirs or _start_menu_dirs():
        if not os.path.isdir(root):
            continue
        for path, mtime, size in _link_files(root, recursive):
            old = cache.get(path)
            if isinstance(old, list) and len(old) == 3 and old[:2] == [mtime, size]:
                app = old[2]
            else:
                app = _parse_link(path)
            fresh[path] = [mtime, size, app]
            if app:
                apps.append(app)
    return apps, fresh


def _start_apps():
    """
    Get-StartApps и приложения Магазина, которые можно удалить:
    {"apps": [{"name", "id"}], "removable": [семейство пакета]} или None.
    """
    shell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                         "WindowsPowerShell", "v1.0", "powershell.exe")
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
              "$a=@(Get-StartApps|Select-Object Name,AppID);"
              "$r=@(try{Get-AppxPackage|Where-Object{-not $_.NonRemovable -and "
              "$_.SignatureKind -ne 'System' -and -not $_.IsFramework}|"
              "ForEach-Object{$_.PackageFamilyName}}catch{});"
              "@{apps=$a;removable=$r}|ConvertTo-Json -Compress -Depth 3")
    try:
        out = subprocess.run(
            [shell if os.path.isfile(shell) else "powershell", "-NoProfile",
             "-NonInteractive", "-Command", script],
            capture_output=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        data = json.loads(out.stdout.decode("utf-8", "replace") or "{}")
    except Exception:
        logbook.exc("Get-StartApps")
        return None
    if not isinstance(data, dict):
        return None
    apps = data.get("apps") or []
    if isinstance(apps, dict):
        apps = [apps]
    removable = data.get("removable") or []
    if isinstance(removable, str):
        removable = [removable]
    return {"apps": [{"name": d.get("Name") or "", "id": d.get("AppID") or ""}
                     for d in apps if isinstance(d, dict)],
            "removable": [r for r in removable if isinstance(r, str)]}


def collect(links, start_apps):
    apps = list(links)
    seen = {a["name"].casefold() for a in apps}
    for entry in start_apps:
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


def _key(text):
    return re.sub(r"[\W_]+", "", (text or "").casefold())


def merge_found(apps, found):
    """
    Программы с дисков (search/programs.py) без тех, что уже есть в «Пуске».

    Мало сравнить путь: у программы из «Пуска» рядом лежат её же помощники,
    а Discord из «Пуска» запускается через Update.exe, хотя на диске найден
    Discord.exe. Поэтому отбрасываем всё, что лежит в папке программы из
    «Пуска», и всё, чья папка или название совпадает с её названием.
    """
    from . import programs

    names, owners = set(), set()
    for app in apps:
        names.add(_key(app["name"]))
        if app.get("alias"):
            names.add(_key(app["alias"]))
        path = app.get("path") or ""
        if os.path.isabs(path):
            folder = os.path.dirname(path)
            owners.add(programs.package_root(folder) or os.path.normcase(folder))
    kept = []
    for app in found:
        folder = os.path.dirname(app["path"])
        root = programs.package_root(folder)
        norm = os.path.normcase(folder)
        if (_key(app["name"]) in names or _key(app.get("alias")) in names
                or (root and _key(os.path.basename(root)) in names)
                or any(norm == o or norm.startswith(o + os.sep) for o in owners)):
            continue
        kept.append(app)
    return kept


def _valid(app):
    return isinstance(app, dict) and bool(app.get("name")) and bool(app.get("target"))


class AppCatalog(QObject):
    """
    Список программ из «Пуска» и Магазина.

    `found` — программы, найденные на дисках и отсутствующие в «Пуске»: их
    ищут наравне с остальными, но в общий список на пустом запросе они не
    попадают — их там были бы сотни.

    `removable` — семейства пакетов Магазина, которые можно удалить.
    `version` растёт при каждом изменении списка — по нему строка знает, что
    готовую выдачу пора пересобрать.
    """

    changed = Signal()
    _done = Signal(object)                # из потока сборки
    _poke = Signal(bool)                  # из наблюдателя: True — Магазин, False — ярлыки

    def __init__(self, watcher=None, cache_path=None, parent=None):
        super().__init__(parent)
        self._path = cache_path or APPS_CACHE
        data = jsonfile.load(self._path, {})
        if not data:
            # Кэш версии 0.1.1 — просто список программ.
            data = {"apps": jsonfile.load(self._path, [])}
        self.apps = [a for a in data.get("apps") or [] if _valid(a)]
        links = data.get("links")
        self._links = links if isinstance(links, dict) else {}
        store = data.get("store")
        self._store = store if isinstance(store, dict) else None
        self.removable = set((self._store or {}).get("removable") or [])
        seen = data.get("seen")
        if isinstance(seen, dict):
            self._seen = {k: v for k, v in seen.items()
                          if isinstance(v, list) and len(v) == 2}
        else:
            # Кэша с отметками ещё нет: всё, что уже было, — не новое.
            now = time.time()
            self._seen = {a["name"].casefold(): [0, now] for a in self.apps}
        self.found = []
        self._found_raw = []
        self.version = 0
        self._busy = False
        self._again = None                # во время сборки попросили ещё одну
        self._last_store = 0.0
        self._done.connect(self._on_done)
        self._links_timer = QTimer(self, singleShot=True, interval=_LINKS_DEBOUNCE_MS)
        self._links_timer.timeout.connect(lambda: self.refresh(store=False))
        self._store_timer = QTimer(self, singleShot=True, interval=_STORE_DEBOUNCE_MS)
        self._store_timer.timeout.connect(lambda: self.refresh(store=True))
        self._poke.connect(lambda store: (self._store_timer if store
                                          else self._links_timer).start())
        self.store_watched = False
        if watcher is not None:
            self._watch(watcher)

    def _watch(self, watcher):
        for root, recursive in _start_menu_dirs():
            if not os.path.isdir(root):
                continue
            if recursive:
                watcher.watch_dir(root, lambda _events: self._poke.emit(False))
            else:
                # На рабочем столе лежит всё подряд — нас касаются только ярлыки.
                watcher.watch_dir(root, self._on_desktop, subtree=False)
        self.store_watched = watcher.watch_key(
            watch.HKCU, _PACKAGES_KEY, lambda: self._poke.emit(True)) is not None

    def _on_desktop(self, events):
        if events is None or any(path.lower().endswith(_LINK_EXT) for _, path in events):
            self._poke.emit(False)

    # --- сборка ------------------------------------------------------------ #

    def refresh(self, store=True, min_interval=0.0):
        """
        Пересобрать список в фоне. store — заодно спросить Магазин (секунда
        PowerShell); min_interval — спрашивать его не чаще, чем раз в N секунд.
        """
        if store and time.monotonic() - self._last_store < min_interval:
            return
        if self._busy:
            self._again = bool(self._again) or store
            return
        self._busy = True
        if store:
            self._last_store = time.monotonic()
        threading.Thread(target=self._worker,
                         args=(dict(self._links), store or self._store is None, self._store),
                         name="spotty-apps", daemon=True).start()

    def _worker(self, cache, ask_store, store):
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)
            links, cache = scan_links(cache)
            if ask_store:
                store = _start_apps() or store
            apps = collect(links, (store or {}).get("apps") or [])
        except Exception:
            logbook.exc("список программ")
            self._done.emit(None)
            return
        self._done.emit((apps, cache, store))

    def _on_done(self, result):
        self._busy = False
        if result and result[0]:
            apps, self._links, self._store = result
            self.removable = set((self._store or {}).get("removable") or [])
            changed = apps != self.apps
            self.apps = apps
            self.found = merge_found(apps, self._found_raw)
            self._note_seen(baseline=False)
            self._save()
            if changed:
                self.version += 1
                self.changed.emit()
        if self._again is not None:
            store, self._again = self._again, None
            self.refresh(store)

    def set_found(self, found, baseline=True):
        """
        Программы с дисков. baseline — список первый (первый обход дисков или
        кэш при запуске): ничего из него не считается только что поставленным.
        """
        self._found_raw = list(found)
        self.found = merge_found(self.apps, self._found_raw)
        self._note_seen(baseline)
        self._save()
        self.version += 1
        self.changed.emit()

    def _save(self):
        jsonfile.save(self._path, {"format": 2, "apps": self.apps, "links": self._links,
                                   "store": self._store, "seen": self._seen})

    # --- новые программы --------------------------------------------------- #

    def _note_seen(self, baseline):
        now = time.time()
        # Самый первый список — это то, что уже стояло до Spotty.
        baseline = baseline or not self._seen
        present = {a["name"].casefold() for a in self.apps + self._found_raw}
        for key in present:
            entry = self._seen.get(key)
            if entry:
                entry[1] = now
            else:
                self._seen[key] = [0 if baseline else now, now]
        for key in [k for k, (_, last) in self._seen.items()
                    if k not in present and now - last > _FORGET_SECONDS]:
            del self._seen[key]

    def first_seen(self, name):
        """Когда программу увидели впервые; 0 — была с самого начала."""
        entry = self._seen.get(name.casefold())
        return entry[0] if entry else 0
