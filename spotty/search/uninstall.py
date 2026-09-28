"""
Удаление программ: деинсталляторы из реестра и приложения Магазина.

Установщик почти любой программы в конце пишет запись в
HKLM/HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall: название,
папку, значок и команду удаления. По ней Spotty:
* находит деинсталлятор для пункта «Удалить программу…» (Ctrl+K);
* узнаёт о только что поставленной программе без ярлыка: новая запись видна
  сразу, и её папку можно пройти, не дожидаясь суточного обхода дисков.

Деинсталлятор подбираем осторожно — ошибка здесь означает удалить не ту
программу. Нужны оба признака: программа лежит в папке записи (или значок
записи — её exe) и название записи говорит о ней же. Иначе ярлык игры,
который запускает steam.exe, «удалял» бы сам Steam.

Приложение Магазина удаляется через Remove-AppxPackage — так же, как из меню
«Пуск». Системные (Калькулятор можно, «Параметры» нельзя) в список удаляемых
не попадают: его отдаёт search/apps.py.
"""

import ctypes
import os
import re
import subprocess
import threading
import winreg
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from ..core import logbook, watch
from . import programs

KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
_ROOTS = ((winreg.HKEY_LOCAL_MACHINE, 0, "HKLM"),
          (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY, "HKLM32"),
          (winreg.HKEY_CURRENT_USER, 0, "HKCU"))
_GUID = re.compile(r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$", re.IGNORECASE)
_STORE = re.compile(r"^shell:AppsFolder\\([^!\\]+_[a-z0-9]{13})![^\\]+$", re.IGNORECASE)
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_SKIP_RELEASE = {"update", "hotfix", "security update", "service pack"}
# Слова, по которым две программы роднить нельзя: производитель, разрядность,
# общие слова вроде «Launcher» и «Player» — они есть у половины программ.
_STOP = {"microsoft", "google", "adobe", "corporation", "corp", "inc", "llc", "ltd",
         "gmbh", "co", "software", "the", "for", "and", "of", "x64", "x86", "amd64",
         "arm64", "bit", "64bit", "32bit", "version", "edition", "update", "user",
         "machine", "setup", "app", "apps", "application", "only", "current", "launcher",
         "player", "manager", "studio", "client", "center", "centre", "tool", "tools",
         "pro", "plus", "free", "portable", "browser", "editor", "viewer", "game", "games",
         "server", "service", "helper", "runtime", "driver", "drivers", "suite",
         "professional", "community", "express", "standard", "home", "premium",
         "ultimate", "installer", "uninstaller", "beta", "preview", "release", "desktop",
         "версия", "разрядная"}
_DEBOUNCE_MS = 3000
CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class Entry:
    id: str                    # «HKLM\\{GUID}» — откуда запись
    name: str
    command: str               # UninstallString
    msi: str = ""              # код продукта установщика Windows
    icon: str = ""             # exe значка, нормализованный
    folders: tuple = ()        # папки программы, нормализованные


def _norm(path):
    return os.path.normcase(os.path.normpath(path))


def _clean(value):
    return os.path.expandvars(str(value or "").strip().strip('"').strip())


def _icon_exe(value):
    """«C:\\X\\app.exe,0» -> путь к exe или ""."""
    text = _clean(value)
    text = re.sub(r",\s*-?\d+$", "", text).strip().strip('"')
    return text if text.lower().endswith(".exe") and os.path.isabs(text) else ""


def command_for(entry):
    """Что запустить, чтобы удалить программу: (файл, параметры)."""
    if entry.msi:
        # У записи MSI в UninstallString часто «/I» — это «Изменить», не «Удалить».
        return "msiexec.exe", "/x " + entry.msi
    return split_command(entry.command)


def split_command(command):
    """UninstallString -> (что запустить, параметры)."""
    text = os.path.expandvars((command or "").strip())
    if text.startswith('"'):
        end = text.find('"', 1)
        if end > 0:
            return text[1:end], text[end + 1:].strip() or None
    if _URL.match(text):
        return text, None                 # steam://uninstall/… — спросит сам Steam
    # Путь без кавычек с пробелами: самый короткий кусок до «.exe», который есть на диске.
    low = text.lower()
    at = low.find(".exe")
    while at >= 0:
        exe = text[:at + 4]
        if os.path.isfile(exe):
            return exe, text[at + 4:].strip() or None
        at = low.find(".exe", at + 1)
    exe, _, rest = text.partition(" ")
    return exe, rest.strip() or None


_generic = None


def _generic_folders():
    """Папки, общие для многих программ: совпадение с ними ничего не значит."""
    global _generic
    if _generic is None:
        env = os.environ.get
        system = env("SystemRoot") or r"C:\Windows"
        folders = {system, os.path.join(system, "System32"), os.path.join(system, "SysWOW64"),
                   env("ProgramData") or r"C:\ProgramData", os.path.expanduser("~"),
                   env("ProgramFiles"), env("ProgramFiles(x86)"), env("ProgramW6432"),
                   env("LOCALAPPDATA"), env("APPDATA"), env("CommonProgramFiles"),
                   env("CommonProgramFiles(x86)")}
        local = env("LOCALAPPDATA")
        if local:
            folders.add(os.path.join(local, "Programs"))
        _generic = {_norm(f) for f in folders if f}
    return _generic


def _program_folder(path):
    norm = _norm(path)
    if len(norm) <= 3 or norm in _generic_folders():
        return ""
    windows = _norm(os.environ.get("SystemRoot") or r"C:\Windows")
    if norm.startswith(windows + os.sep):
        return ""                         # msiexec, rundll32 — не папка программы
    return norm


def read_entries():
    """Все записи об удалении, у которых есть название и команда."""
    entries = []
    for root, view, label in _ROOTS:
        try:
            key = winreg.OpenKey(root, KEY, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with key:
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, index)
                except OSError:
                    break
                index += 1
                entry = _read_entry(key, sub, label)
                if entry is not None:
                    entries.append(entry)
    return entries


def _read_entry(parent, sub, label):
    values = {}
    try:
        with winreg.OpenKey(parent, sub) as key:
            for name in ("DisplayName", "UninstallString", "InstallLocation", "DisplayIcon",
                         "SystemComponent", "WindowsInstaller", "ParentKeyName",
                         "ReleaseType"):
                try:
                    values[name] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    pass
    except OSError:
        return None
    name = str(values.get("DisplayName") or "").strip()
    command = str(values.get("UninstallString") or "").strip()
    if not name or not command or values.get("SystemComponent") == 1:
        return None
    if values.get("ParentKeyName") or \
            str(values.get("ReleaseType") or "").casefold() in _SKIP_RELEASE:
        return None                        # обновление другой программы
    msi = sub.upper() if values.get("WindowsInstaller") == 1 and _GUID.match(sub) else ""
    icon = _icon_exe(values.get("DisplayIcon"))
    folders = set()
    location = _clean(values.get("InstallLocation"))
    candidates = [location] if os.path.isabs(location) else []
    if icon:
        candidates.append(os.path.dirname(icon))
    exe, _ = split_command(command)
    if os.path.isabs(exe):
        candidates.append(os.path.dirname(exe))
    for folder in candidates:
        folder = _program_folder(folder)
        if folder:
            folders.add(folder)
    return Entry(label + "\\" + sub, name, command, msi, _norm(icon) if icon else "",
                 tuple(sorted(folders)))


def _words(text):
    return {w for w in programs.words(text or "")
            if len(w) >= 2 and not w.isdigit() and w not in _STOP}


def _plain(text):
    """Название без версии, разрядности и производителя: для сравнения по имени."""
    return " ".join(w for w in programs.words(text or "")
                    if not w.isdigit() and w not in _STOP)


# --- ярлык установщика Windows (MSI) --------------------------------------- #

def _msi_product(link):
    """Код продукта «объявленного» ярлыка MSI (у него нет пути к exe) или ""."""
    try:
        msi = ctypes.windll.msi
        product = ctypes.create_unicode_buffer(39)
        feature = ctypes.create_unicode_buffer(39)
        component = ctypes.create_unicode_buffer(39)
        if msi.MsiGetShortcutTargetW(ctypes.c_wchar_p(link), product, feature,
                                     component) == 0:
            return product.value.upper()
    except (OSError, AttributeError):
        pass
    return ""


def find(entries, name, alias="", path="", link=""):
    """
    Запись для программы или None.
    name/alias — как программа названа в выдаче, path — её exe (у ярлыка — цель),
    link — сам ярлык.
    """
    if not path and link.lower().endswith(".lnk"):
        code = _msi_product(link)
        if code:
            matches = [e for e in entries if e.msi == code]
            if len(matches) == 1:
                return matches[0]
    names = _words(name) | _words(alias)
    if path and os.path.isabs(path):
        exe = _norm(path)
        folder = os.path.dirname(exe)
        ranked = []
        for entry in entries:
            depth = max((len(d) for d in entry.folders
                         if folder == d or folder.startswith(d + os.sep)), default=0)
            icon = bool(entry.icon) and entry.icon == exe
            if not depth and not icon:
                continue
            overlap = len(names & _words(entry.name))
            if not overlap:
                continue                   # папка та, а программа другая
            ranked.append(((icon, depth, overlap), entry))
        if not ranked:
            return None
        ranked.sort(key=lambda r: r[0], reverse=True)
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            return None                    # две равные — не угадываем
        return ranked[0][1]
    # Пути нет: только по названию, и только если запись одна.
    plain = _plain(name)
    if not plain:
        return None
    matches = [e for e in entries if _plain(e.name) == plain]
    return matches[0] if len(matches) == 1 else None


def store_family(target):
    """«shell:AppsFolder\\Семейство!App» -> семейство пакета или None."""
    match = _STORE.match(target or "")
    return match.group(1) if match else None


def remove_package(family):
    """Удалить приложение Магазина. True — удалено."""
    script = ("$ErrorActionPreference='Stop';"
              "Get-AppxPackage|Where-Object{$_.PackageFamilyName -eq $env:SPOTTY_FAMILY}|"
              "Remove-AppxPackage")
    shell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                         "WindowsPowerShell", "v1.0", "powershell.exe")
    env = dict(os.environ, SPOTTY_FAMILY=family)
    try:
        done = subprocess.run([shell if os.path.isfile(shell) else "powershell",
                               "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, timeout=120, env=env,
                              creationflags=CREATE_NO_WINDOW)
    except Exception:
        logbook.exc("удаление " + family)
        return False
    if done.returncode != 0:
        logbook.log("удаление %s: %s" % (family, done.stderr.decode("utf-8", "replace")[-300:]))
    return done.returncode == 0


class UninstallIndex(QObject):
    """
    Записи об удалении. Перечитываются, когда меняется ключ Uninstall;
    `added(записи)` — появились новые: программу только что поставили.
    """

    added = Signal(object)
    _loaded = Signal(object)
    _poke = Signal()

    def __init__(self, watcher=None, parent=None):
        super().__init__(parent)
        self.entries = []
        self._ids = None                   # None — ещё не читали: первое чтение не «новое»
        self._busy = False
        self._again = False
        self._loaded.connect(self._on_loaded)
        self._timer = QTimer(self, singleShot=True, interval=_DEBOUNCE_MS)
        self._timer.timeout.connect(self.reload)
        self._poke.connect(self._timer.start)
        if watcher is not None:
            for root, view, _label in _ROOTS:
                watcher.watch_key(int(root), KEY, self._poke.emit,
                                  watch.KEY_WOW64_32KEY if view else 0)

    def reload(self):
        if self._busy:
            self._again = True
            return
        self._busy = True
        threading.Thread(target=self._worker, name="spotty-uninstall", daemon=True).start()

    def _worker(self):
        try:
            entries = read_entries()
        except Exception:
            logbook.exc("записи об удалении")
            entries = None
        self._loaded.emit(entries)

    def _on_loaded(self, entries):
        self._busy = False
        if entries is not None:
            new = [] if self._ids is None else [e for e in entries if e.id not in self._ids]
            self.entries, self._ids = entries, {e.id for e in entries}
            if new:
                self.added.emit(new)
        if self._again:
            self._again = False
            self.reload()

    def find_for(self, item):
        """Запись для пункта выдачи (программы) или None."""
        link = item.target if item.target.lower().endswith(".lnk") else ""
        return find(self.entries, item.title, item.extra.get("alias", ""), item.path, link)
