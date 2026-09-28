"""
Программы на дисках — то, чего нет в «Пуске»: портативные утилиты, игры,
программы, поставленные простым копированием папки.

Все локальные диски обходятся в фоне, раз в сутки, потоком с пониженным
приоритетом (и процессора, и диска), и обход стоит, пока открыта строка.
Программу, поставленную установщиком, ждать сутки не нужно: её запись об
удалении появляется в реестре сразу (search/uninstall.py), и Spotty проходит
только её папку — scan_folders. Системные папки (Windows, ProgramData,
корзина, точки восстановления) и заведомо ненужные человеку (кэши,
node_modules, окружения Python) пропускаем целиком — иначе обход шёл бы минуты.
«Загрузки» тоже: там лежат установщики, а не программы.

Почти все найденные exe — служебные: установщики, службы, помощники,
консольные утилиты. Отсев по шагам:
  1. имя похоже на служебное (unins000, crashpad_handler, updater) — мимо;
  2. консольные программы (git, java, ffmpeg) — мимо: без окна их из строки
     не запустить, для этого есть «>». Тип берём из заголовка самого exe;
  3. в каждой папке — одна программа: та, чьё имя похоже на имя папки, иначе
     самая большая;
  4. внутри папки программы (Program Files\\X, AppData\\X, игра в
     steamapps\\common) — только верхний уровень, где есть exe: вложенное —
     её части;
  5. при слиянии со списком из «Пуска» (AppCatalog.set_found) всё, что лежит
     в папке программы из «Пуска», отбрасывается: ярлык у неё уже есть.
Название — из описания в самом exe («OBS Studio» у obs64.exe), имя файла
остаётся запасным для поиска.
"""

import ctypes
import os
import re
import stat
import string
import struct
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

from ..core import background, jsonfile, logbook
from ..core.config import known_folder
from ..core.constants import PROGRAMS_CACHE

RESCAN_SECONDS = 24 * 60 * 60
_MAX_DEPTH = 9
_DRIVE_FIXED = 3
_HIDDEN = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM
_REPARSE = stat.FILE_ATTRIBUTE_REPARSE_POINT
_GUI = 2                                    # IMAGE_SUBSYSTEM_WINDOWS_GUI

# Папки, в которые не заходим, где бы они ни лежали.
_SKIP_NAMES = {
    # система
    "$recycle.bin", "system volume information", "recovery", "perflogs", "config.msi",
    "msocache", "windowsapps", "winsxs", "microsoft", "microsoft.net", "windowspowershell",
    "internet explorer", "common files", "modifiablewindowsapps", "uninstall information",
    "reference assemblies", "microsoft sdks", "windows kits", "microsoft visual studio",
    "dotnet", "msbuild", "hyper-v", "ruxim", "java", "packages", "locallow",
    # разработка
    "node_modules", "__pycache__", "site-packages", "venv", "scripts", "lib", "libexec",
    "usr", "mingw32", "mingw64", "include", "sdk", "samples", "examples", "npm-cache",
    "dist", "build", "obj", "ms-playwright", "tauri", "uv", "pip", "pypoetry", "node-gyp",
    # кэши, журналы, данные браузеров
    "cache", "caches", "code cache", "gpucache", "shadercache", "dxcache", "glcache",
    "d3dscache", "nvidia", "temp", "tmp", "logs", "crashpad", "crashdumps", "crashreports",
    "user data", "profiles", "workshop", "downloading", "pending",
    # установщики и их остатки
    "package cache", "installer", "installers", "redist", "_commonredist",
    "commonredist", "directx", "vcredist", "__macosx",
    # составные части программ
    "resources", "resource", "locales", "plugins", "plug-ins", "extensions",
}

# Имя или описание exe со служебным словом — не программа для человека.
# Внутри слова — только то, что само по себе программой не бывает.
_JUNK_ANYWHERE = re.compile(
    r"unins|uninst|crash|redist|updater|reporter|installer|bootstrap|helper|"
    r"daemon|watchdog|telemetry|sandbox|elevat|notif|inject|sniffer|subprocess|"
    r"setup|service|server|proxy|dump|wrapper|svc|nodejs|"
    r"удал|деинстал|установ|обновл|настройк",
    re.IGNORECASE)
# А эти — только с начала слова: «host» внутри «Ghostwire» — это игра.
_JUNK_WORDS = ("host", "agent", "broker", "stub", "shim", "report", "update", "upgrade",
               "patch", "install", "test", "sample", "example", "driver", "runtime",
               "debug", "diag", "trace", "cli", "console", "compiler", "regist", "regsvr",
               "licen", "activat", "token", "overlay", "hook", "plugin", "container", "cef",
               "repair", "migrat", "bridge", "wizard", "api", "process")
# Среды выполнения: оконные, но сами по себе не программы.
_RUNTIMES = {"python", "pythonw", "java", "javaw", "jp2launcher", "node", "electron",
             "squirrel", "wscript", "cscript", "powershell", "pwsh", "conhost"}

# Описания, по которым программу не узнать: движок игры вместо её названия.
_GENERIC = {
    "game", "launcher", "main", "start", "run", "app", "application", "client", "player",
    "program", "unrealgame", "unity playback engine", "godot engine", "rgss player",
    "rgss2 player", "rgss3 player", "nw.js", "electron", "python", "pythonw", "java",
    "node", "node.js", "todo", "bin", "exe",
}
# Папки-обёртки: их имя ничего не говорит о программе внутри.
_WRAPPERS = {
    "bin", "bin64", "bin32", "binaries", "win64", "win32", "x64", "x86", "64bit", "32bit",
    "app", "application", "release", "dist", "build", "program", "programs", "game",
    "games", "current", "windows", "win", "portable", "x86_64", "amd64",
}
# Движки игр: в описании exe часто движок, а не игра.
_ENGINE = re.compile(r"^(unity|unreal|godot|rgss|ruby game scripting|ren'?py|nw\.js|"
                     r"electron|game ?maker|construct)\b", re.IGNORECASE)
# «MotorSlice-Win64-Shipping» — так Unreal называет exe игры.
_SHIPPING = re.compile(r"[-_](win64|win32)?[-_]?shipping$", re.IGNORECASE)
_VERSION_DIR = re.compile(r"^(app-)?v?\d+(\.\d+)+$", re.IGNORECASE)
_WORD_SPLIT = re.compile(r"[^0-9a-zа-яё]+")
_CAMEL = re.compile(r"(?<=[a-zа-яё])(?=[A-ZА-ЯЁ])|(?<=[A-ZА-ЯЁ])(?=[A-ZА-ЯЁ][a-zа-яё])"
                    r"|(?<=[A-Za-zА-Яа-яЁё])(?=\d)|(?<=\d)(?=[A-Za-zА-Яа-яЁё])")
_TRADEMARK = re.compile(r"\((tm|r|c)\)|[™®©]", re.IGNORECASE)
_BAD_TITLE = re.compile(r"\.exe|[$<>@\\/|{}\[\]]|[\x00-\x1f]", re.IGNORECASE)


# --- куда смотреть ------------------------------------------------------------ #

def fixed_drives():
    kernel = ctypes.WinDLL("kernel32")
    mask = kernel.GetLogicalDrives()
    drives = []
    for i, letter in enumerate(string.ascii_uppercase):
        root = letter + ":\\"
        if mask & (1 << i) and kernel.GetDriveTypeW(root) == _DRIVE_FIXED:
            drives.append(root)
    return drives


def _norm_path(path):
    return os.path.normcase(os.path.normpath(path)) if path else ""


def _skip_paths():
    """Папки, которые пропускаем по полному пути."""
    env = os.environ.get
    paths = {env("SystemRoot") or r"C:\Windows", env("ProgramData") or r"C:\ProgramData",
             known_folder("downloads")}
    return {_norm_path(p) for p in paths if p}


def _package_bases():
    """
    Папки, в которых каждая вложенная папка — отдельная программа. Длинные
    впереди: AppData\\Local\\Programs должна сработать раньше AppData\\Local.
    """
    env = os.environ.get
    bases = {env("ProgramFiles"), env("ProgramFiles(x86)"), env("ProgramW6432"),
             env("LOCALAPPDATA"), env("APPDATA")}
    local = env("LOCALAPPDATA")
    if local:
        bases.add(os.path.join(local, "Programs"))
    return sorted((_norm_path(b) for b in bases if b), key=len, reverse=True)


_BASES = None


def package_root(folder):
    """
    Папка программы, к которой относится папка folder: Program Files\\X,
    AppData\\Local\\X, steamapps\\common\\Игра (в нижнем регистре). None —
    folder вне таких мест: портативная программа.
    """
    global _BASES
    if _BASES is None:
        _BASES = _package_bases()
    folder = _norm_path(folder)
    marker = os.sep + os.path.join("steamapps", "common") + os.sep
    at = folder.find(marker)
    if at >= 0:
        rest = folder[at + len(marker):]
        return folder[:at + len(marker)] + rest.split(os.sep, 1)[0]
    for base in _BASES:
        if folder.startswith(base + os.sep):
            return base + os.sep + folder[len(base) + 1:].split(os.sep, 1)[0]
    return None


# --- что внутри exe ---------------------------------------------------------- #

def _subsystem(path):
    """Подсистема из PE-заголовка: 2 — оконная, 3 — консольная. None — не exe."""
    try:
        with open(path, "rb") as f:
            head = f.read(1024)
            if head[:2] != b"MZ" or len(head) < 0x40:
                return None
            offset = struct.unpack_from("<I", head, 0x3C)[0]
            # Подсистема — в опциональном заголовке, 68 байт от его начала
            # (одинаково в PE32 и PE32+): 4 байта подписи + 20 заголовка файла.
            need = offset + 24 + 70
            if need > len(head):
                f.seek(offset)
                head = f.read(24 + 70)
                offset = 0
            if head[offset:offset + 4] != b"PE\0\0":
                return None
            return struct.unpack_from("<H", head, offset + 24 + 68)[0]
    except (OSError, struct.error):
        return None


_version = None


def _version_dll():
    global _version
    if _version is None:
        dll = ctypes.WinDLL("version")
        dll.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        dll.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                            ctypes.c_void_p]
        dll.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                       ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.POINTER(wintypes.UINT)]
        _version = dll
    return _version


def version_strings(path):
    """{"FileDescription": ..., "ProductName": ...} из ресурса версии exe."""
    dll = _version_dll()
    size = dll.GetFileVersionInfoSizeW(path, None)
    if not size:
        return {}
    buf = ctypes.create_string_buffer(size)
    if not dll.GetFileVersionInfoW(path, 0, size, buf):
        return {}
    ptr, length = ctypes.c_void_p(), wintypes.UINT()
    langs = []
    if dll.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr),
                          ctypes.byref(length)) and length.value >= 4:
        words = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * (length.value // 2))).contents
        langs = ["%04x%04x" % (words[i], words[i + 1]) for i in range(0, len(words) - 1, 2)]
    langs += ["040904b0", "040904e4", "04090000", "041904b0"]
    found = {}
    for field in ("FileDescription", "ProductName"):
        for lang in langs:
            query = "\\StringFileInfo\\%s\\%s" % (lang, field)
            if dll.VerQueryValueW(buf, query, ctypes.byref(ptr), ctypes.byref(length)) \
                    and length.value:
                text = ctypes.wstring_at(ptr, length.value).split("\0", 1)[0].strip()
                if text:
                    found[field] = text
                    break
    return found


# --- отбор ------------------------------------------------------------------- #

def words(name):
    """'RzSDKServer64' -> ['rz', 'sdk', 'server', '64']."""
    return [w for w in _WORD_SPLIT.split(_CAMEL.sub(" ", name).lower()) if w]


def is_junk(name):
    if not name:
        return False
    if _JUNK_ANYWHERE.search(name):
        return True
    return any(w.startswith(_JUNK_WORDS) for w in words(name))


def _norm(text):
    return re.sub(r"[\W_]+", "", text.casefold())


def _meaningful_folder(folder, stop=None):
    """Ближайшая папка с говорящим именем: не bin, не Win64, не app-1.0.9."""
    while folder and folder != stop:
        name = os.path.basename(folder)
        if not name:
            break
        low = name.casefold()
        if low not in _WRAPPERS and not _VERSION_DIR.match(name):
            return name
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return ""


def _affinity(stem, folder_name):
    """Насколько имя exe похоже на имя папки: 3 — совпадает, 0 — ничего общего."""
    a, b = _norm(stem), _norm(folder_name)
    if not a or not b:
        return 0
    if a == b:
        return 3
    if a in b or b in a:
        return 2
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    return 1 if common >= 3 else 0


def _clean(text):
    text = " ".join(_TRADEMARK.sub("", text or "").split()).strip(" .:-–—")
    if not text or len(text) > 48 or _BAD_TITLE.search(text):
        return ""
    if not any(c.isalpha() for c in text):
        return ""
    return text


def _generic(text):
    return text.casefold().strip(" .") in _GENERIC or bool(_ENGINE.match(text))


def title_for(stem, info, folder_name):
    """
    Название программы:
      * описание из exe, если оно про неё («OBS Studio» у obs64);
      * название продукта, если совпадает с именем файла, а описание — про
        движок («Tales of the Moon» при описании «Made by Cella»);
      * имя файла, если так же названа папка (Lightshot.exe в lightshot) —
        описание тогда чаще про внутренний модуль;
      * описание или продукт, если они не безликие;
      * имя файла; имя папки, если и файл назван безлико (Game.exe).
    """
    stem = _SHIPPING.sub("", stem)
    desc = _clean(info.get("FileDescription"))
    product = _clean(info.get("ProductName"))
    key = _norm(stem)
    for candidate in (desc, product):
        if candidate and not _generic(candidate) and key and (
                key in _norm(candidate) or _norm(candidate) in key):
            return candidate
    if _affinity(stem, folder_name) >= 2 and _clean(stem) and not _generic(stem):
        return stem
    for candidate in (desc, product):
        if candidate and not _generic(candidate):
            return candidate
    if not _generic(stem) and _clean(stem):
        return stem
    return folder_name or stem


def _skip_dir(name, path, skip_paths):
    low = name.casefold()
    return (low[:1] in ".$" or low in _SKIP_NAMES or low == "windows"
            or low.startswith(("windows ", "windows."))
            # «Uninstall», «Updater», «Drivers», «Tests» — части чужих программ.
            or is_junk(name) or _norm_path(path) in skip_paths)


def _walk(drives, skip_paths, stop):
    """[(путь, размер)] кандидатов: exe со «человеческим» именем."""
    found = []
    for drive in drives:
        stack = [(drive, 0)]
        while stack:
            background.wait()
            if stop():
                return found
            folder, depth = stack.pop()
            try:
                with os.scandir(folder) as it:
                    entries = list(it)
            except OSError:
                continue
            # Репозиторий — исходники и сборки для отладки, а не программы.
            if any(entry.name == ".git" for entry in entries):
                continue
            for entry in entries:
                name = entry.name
                try:
                    # На Windows атрибуты приходят вместе со списком папки.
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if info.st_file_attributes & _HIDDEN:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if (info.st_file_attributes & _REPARSE or depth >= _MAX_DEPTH
                            or _skip_dir(name, entry.path, skip_paths)):
                        continue
                    stack.append((entry.path, depth + 1))
                elif name[-4:].lower() == ".exe":
                    stem = name[:-4]
                    if stem.casefold() not in _RUNTIMES and not is_junk(stem):
                        found.append((entry.path, info.st_size))
    return found


def scan(stop=lambda: False, roots=None):
    """
    Найти программы на всех локальных дисках или только в папках roots:
    [{"name", "target", ...}].
    """
    started = time.perf_counter()
    candidates = _walk(roots or fixed_drives(), _skip_paths(), stop)
    walked = time.perf_counter()

    # Консольные и служебные по описанию — мимо; остальные группируем по папкам.
    by_folder = {}
    for path, size in candidates:
        if stop():
            return []
        if _subsystem(path) != _GUI:
            continue
        try:
            info = version_strings(path)
        except OSError:
            info = {}
        if is_junk(info.get("FileDescription", "")):
            continue
        by_folder.setdefault(os.path.dirname(path), []).append((path, size, info))

    # В каждой папке — одна программа.
    picked = []
    for folder, items in by_folder.items():
        name = _meaningful_folder(folder)
        root = package_root(folder)
        package_name = os.path.basename(root) if root else ""

        def rank(item):
            stem = os.path.splitext(os.path.basename(item[0]))[0]
            return (max(_affinity(stem, name), _affinity(stem, package_name)), item[1])

        path, _size, info = max(items, key=rank)
        picked.append((path, info, root, name))

    # Внутри папки программы — только верхний уровень, где есть exe.
    top = {}
    for path, _info, root, _name in picked:
        if root:
            depth = path.count(os.sep)
            top[root] = min(top.get(root, depth), depth)
    apps, seen = [], {}
    for path, info, root, name in sorted(picked, key=lambda p: p[0].count(os.sep)):
        if root and path.count(os.sep) > top[root]:
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        title = title_for(stem, info, name)
        key = title.casefold()
        if key in seen:              # две папки с одной программой — берём верхнюю
            continue
        seen[key] = True
        apps.append({"name": title, "target": path, "path": path, "kind": "exe",
                     "alias": stem if _norm(stem) != _norm(title) else ""})
    apps.sort(key=lambda a: a["name"].casefold())
    logbook.log("программы %s: %d из %d exe, обход %.1f с, разбор %.1f с" % (
        "в папках " + ", ".join(roots) if roots else "на дисках", len(apps),
        len(candidates), walked - started, time.perf_counter() - walked))
    return apps


def install_folders(folders):
    """Папки только что поставленных программ, которые стоит пройти."""
    skip = _skip_paths()
    picked = []
    for folder in folders:
        norm = _norm_path(folder)
        if not norm or not os.path.isdir(norm) or norm in picked:
            continue
        if any(norm == s or norm.startswith(s + os.sep) for s in skip):
            continue
        # Папка установки — не весь диск и не вся Program Files.
        if len(norm) <= 3 or norm in _package_bases():
            continue
        picked.append(norm)
    return picked


class DiskPrograms(QObject):
    """Найденное на дисках. Прошлый результат — в кэше: строка готова сразу."""

    started = Signal()
    changed = Signal()
    _folders_done = Signal(object)          # из потока scan_folders

    def __init__(self, parent=None):
        super().__init__(parent)
        data = jsonfile.load(PROGRAMS_CACHE, {})
        data = data if isinstance(data, dict) else {}
        self.apps = [a for a in data.get("apps", [])
                     if isinstance(a, dict) and a.get("name") and a.get("target")]
        self.scanned_at = float(data.get("scanned") or 0)
        # Список получен первым обходом: в нём всё, что стояло до Spotty, и
        # «новыми» эти программы не считаются.
        self.first_scan = False
        self._busy = False
        self._generation = 0
        self._folders_done.connect(self._add)

    def busy(self):
        return self._busy

    def stale(self):
        return time.time() - self.scanned_at > RESCAN_SECONDS

    def scan(self):
        if self._busy:
            return
        self._busy = True
        self._generation += 1
        self.started.emit()
        threading.Thread(target=self._worker, args=(self._generation,),
                         name="spotty-programs", daemon=True).start()

    def scan_folders(self, folders):
        """Пройти только эти папки (программу только что поставили) и дополнить список."""
        folders = install_folders(folders)
        if folders:
            threading.Thread(target=self._folders_worker, args=(folders,),
                             name="spotty-programs-new", daemon=True).start()

    def _folders_worker(self, folders):
        background.low_priority()
        try:
            self._folders_done.emit(scan(roots=folders))
        except Exception:
            logbook.exc("программы в новых папках")

    def _add(self, apps):
        paths = {os.path.normcase(a["path"]) for a in self.apps}
        names = {a["name"].casefold() for a in self.apps}
        new = [a for a in apps if os.path.normcase(a["path"]) not in paths
               and a["name"].casefold() not in names]
        if not new:
            return
        self.apps = sorted(self.apps + new, key=lambda a: a["name"].casefold())
        self.first_scan = False
        jsonfile.save(PROGRAMS_CACHE, {"scanned": self.scanned_at, "apps": self.apps})
        self.changed.emit()

    def clear(self):
        """Поиск по дискам выключили: идущий обход бросаем, список забываем."""
        self._generation += 1
        self._busy = False
        self.apps, self.scanned_at = [], 0.0
        jsonfile.save(PROGRAMS_CACHE, {"scanned": 0, "apps": []})
        self.changed.emit()

    def _worker(self, generation):
        background.low_priority()
        first = not self.scanned_at
        try:
            apps = scan(lambda: generation != self._generation)
        except Exception:
            logbook.exc("программы на дисках")
            apps = None
        if generation != self._generation:
            return
        self._busy = False
        if apps is not None:
            self.apps, self.scanned_at = apps, time.time()
            self.first_scan = first
            jsonfile.save(PROGRAMS_CACHE, {"scanned": self.scanned_at, "apps": apps})
        self.changed.emit()
