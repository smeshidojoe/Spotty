"""
Свой индекс файлов и папок.

Обходим выбранные папки в фоне и держим имена в памяти. Поиск идёт не циклом
по списку, а поиском подстроки в одной большой строке со всеми именами через
«\\n»: str.find работает на C и проходит сотни тысяч имён за миллисекунды,
тогда как цикл на Python на каждое нажатие клавиши заметно тормозил бы.

Памяти индекс берёт немного: имена лежат двумя сплошными строками (как есть и
в нижнем регистре), а путь собирается из номера папки и имени только для тех
файлов, что попали в выдачу.

После обхода индекс не перестраивается по таймеру: Windows сообщает об
изменениях в папках (core/watch.py), и новые, переименованные и удалённые
файлы ложатся поверх готового индекса. Полный переобход — только если слежение
не работает (сетевая папка) или Windows не успела передать все изменения.
"""

import array
import bisect
import heapq
import os
import stat
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..core import background, logbook, watch

# Папки, в которых нечего искать человеку, а файлов — сотни тысяч.
_SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".hg", ".svn", "venv", ".venv",
    "site-packages", ".idea", ".vs", ".vscode", ".gradle", ".cache", ".tox",
    ".mypy_cache", ".pytest_cache", "$recycle.bin", "system volume information",
}
_HIDDEN = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM
_REPARSE = stat.FILE_ATTRIBUTE_REPARSE_POINT
_MAX_DEPTH = 10
_MAX_ENTRIES = 400_000

# Папку, за которой Windows не следит, переобходим раз в 20 минут; за которой
# следит — раз в сутки, на всякий случай.
_UNWATCHED_SECONDS = 20 * 60
_WATCHED_SECONDS = 24 * 60 * 60
_CHECK_MS = 5 * 60 * 1000
# Изменений поверх индекса больше этого — пора переобойти: их ищем циклом.
_DELTA_MAX = 5000
# Список всех имён с подстрокой держим, если он не длиннее этого: следующая
# буква ищет только среди них.
_NARROW_MAX = 2000
# Короткий запрос («te») встречается в десятках тысяч имён. Оцениваем первые
# _SCAN_CAP и столько же тех, что с него начинаются, — они всё равно выше в
# выдаче. Ещё буква — и совпадений станет сотни.
_SCAN_CAP = 800
_PREFIX_CAP = 800
_CHANGED_MS = 300
# Windows не успела передать все изменения — переобходим, но не сразу: при
# лавине записей (игра качается на диск) переполнение приходит раз за разом.
_OVERFLOW_MS = 30_000


def _norm(path):
    return os.path.normcase(path)


def _tree(root, level, stop, pausable=True):
    """
    Папки, в которые заходит индекс: (папка, её уровень, [(имя, папка ли)]).
    Скрытое, служебное и точки соединения («Мои рисунки» в Документах ведут в
    чужие папки или закрыты) пропускаем.
    """
    stack = [(root, level)]
    while stack:
        if pausable:
            background.wait()
        if stop():
            return
        folder, depth = stack.pop()
        try:
            it = os.scandir(folder)
        except OSError:
            continue
        entries = []
        with it:
            for entry in it:
                name = entry.name
                if name.startswith(".") or name.lower() in _SKIP_DIRS:
                    continue
                try:
                    # На Windows атрибуты приходят вместе со списком папки —
                    # отдельного обращения к диску тут нет.
                    info = entry.stat(follow_symlinks=False)
                    if info.st_file_attributes & _HIDDEN:
                        continue
                    is_dir = entry.is_dir(follow_symlinks=False)
                    if is_dir and info.st_file_attributes & _REPARSE:
                        continue
                except OSError:
                    continue
                entries.append((name, is_dir))
                if is_dir and depth < _MAX_DEPTH:
                    stack.append((entry.path, depth + 1))
        yield folder, depth, entries


def _lower(name):
    """Нижний регистр той же длины: «İ» даёт две буквы, и сдвинулись бы все имена."""
    low = name.lower()
    if len(low) == len(name):
        return low
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in name)


class _Snapshot:
    """
    Обойдённые папки. Не меняется после сборки — поиск из главного потока
    читает его без блокировок.
      names/lower — "\\n" + имена через "\\n" + "\\n", как есть и в нижнем регистре;
      starts[i]   — где в них начинается имя i (последний — за концом);
      folder[i]   — номер папки имени i в folders (с разделителем на конце);
      entered     — папки, в которые индекс заходит: нормализованный путь -> номер.
    """

    def __init__(self, names, folder, isdir, folders, entered):
        # Одна буква вне основной плоскости (эмодзи) делает всю строку вчетверо
        # тяжелее. Такие имена храним отдельно, а в строке — заменитель.
        self.astral = {}
        joined = "\n" + "\n".join(names) + "\n"
        if len(joined) > 2 and max(joined) > "￿":
            for i, name in enumerate(names):
                if max(name) > "￿":
                    self.astral[i] = name
                    names[i] = "".join(c if c <= "￿" else "�" for c in name)
            joined = "\n" + "\n".join(names) + "\n"
        self.names = joined
        self.lower = joined.lower()
        if len(self.lower) != len(joined):
            self.lower = "\n" + "\n".join(_lower(n) for n in names) + "\n"
        starts = array.array("I")
        pos = 1
        for name in names:
            starts.append(pos)
            pos += len(name) + 1
        starts.append(pos)
        self.starts = starts
        self.folder = folder
        self.isdir = isdir
        self.folders = folders
        self.depths = array.array("H", (f.count(os.sep) for f in folders))
        self.entered = entered

    def __len__(self):
        return len(self.starts) - 1

    def name(self, i):
        return self.astral.get(i) or self.names[self.starts[i]:self.starts[i + 1] - 1]

    def path(self, i):
        return self.folders[self.folder[i]] + self.name(i)


def _build(roots, stop):
    names, folder, isdir, folders, entered = [], array.array("I"), bytearray(), [], {}
    for root in roots:
        for path, _level, entries in _tree(root, 0, stop):
            if len(names) >= _MAX_ENTRIES:
                break
            index = len(folders)
            folders.append(path if path.endswith(os.sep) else path + os.sep)
            entered[_norm(path)] = index
            for name, is_dir in entries:
                names.append(name)
                folder.append(index)
                isdir.append(is_dir)
    if stop():
        return None
    background.wait()
    return _Snapshot(names, folder, isdir, folders, entered)


def _score(name, phrase, offset):
    dot = name.rfind(".")
    stem = name[:dot] if dot > 0 else name
    if stem == phrase or name == phrase:
        score = 100.0
    elif offset == 0:
        score = 85.0
    elif not name[offset - 1].isalnum():
        score = 75.0                       # с начала слова
    else:
        score = 55.0
    # Короткие имена ближе к запросу, чем длинные с тем же вхождением.
    return score - min(len(name), 60) * 0.1


class FileIndex(QObject):
    changed = Signal()
    _ops = Signal(object)                 # из потока наблюдателя
    _overflow = Signal()
    _built = Signal(object, int, int)     # из потока обхода

    def __init__(self, watcher=None, parent=None):
        super().__init__(parent)
        self._watcher = watcher
        self._roots = []
        self._tokens = []
        self._unwatched = False
        self._snap = _Snapshot([], array.array("I"), bytearray(), [], {})
        # Изменения поверх индекса. Отметка — номер пачки: после переобхода
        # остаются только те, что пришли, пока он шёл.
        self._stamp = 0
        self._delta = {}                  # путь (norm) -> (имя lower, путь, папка ли, глубина, отметка)
        self._removed = {}                # путь (norm) -> отметка
        self._dropped = {}                # "путь\\" удалённой папки -> отметка
        self._more_entered = {}           # новые папки -> отметка
        self._narrow = []                 # [(снимок, ключ, номера имён)] — последние поиски
        self._generation = 0
        self._busy = False
        self._built_at = 0.0
        self._dirty = False
        self._ops.connect(self._apply)
        self._overflow.connect(self._mark_dirty)
        self._built.connect(self._swap)
        self._changed_timer = QTimer(self, singleShot=True, interval=_CHANGED_MS)
        self._changed_timer.timeout.connect(self.changed.emit)
        self._check_timer = QTimer(self, interval=_CHECK_MS)
        self._check_timer.timeout.connect(self._check)
        self._check_timer.start()
        self._dirty_timer = QTimer(self, singleShot=True, interval=_OVERFLOW_MS)
        self._dirty_timer.timeout.connect(self._check)

    def __len__(self):
        return len(self._snap) + len(self._delta)

    # --- обход ------------------------------------------------------------- #

    def set_roots(self, roots):
        roots = [os.path.normpath(r) for r in roots if r and os.path.isdir(r)]
        if roots == self._roots:
            return
        self._roots = roots
        self._watch()
        self.rebuild()

    def _watch(self):
        for token in self._tokens:
            self._watcher.unwatch(token)
        self._tokens = []
        self._unwatched = False
        if self._watcher is None:
            self._unwatched = bool(self._roots)
            return
        for root in self._roots:
            token = self._watcher.watch_dir(
                root, lambda events, root=root: self._on_events(root, events))
            if token is None:
                self._unwatched = True
            else:
                self._tokens.append(token)

    def _check(self):
        age = time.monotonic() - self._built_at
        limit = _UNWATCHED_SECONDS if self._unwatched else _WATCHED_SECONDS
        if self._dirty or age > limit:
            self.rebuild()

    def rebuild(self):
        """
        Переобойти папки в фоне. Старый индекс работает, пока строится новый;
        пока открыта строка, обход стоит (core/background.py).
        """
        self._generation += 1
        self._built_at = time.monotonic()
        self._dirty = False
        generation, roots = self._generation, list(self._roots)
        self._busy = True
        threading.Thread(target=self._worker, args=(generation, roots, self._stamp),
                         name="spotty-files", daemon=True).start()

    def _worker(self, generation, roots, stamp):
        background.low_priority()
        started = time.perf_counter()
        try:
            # Если за время обхода папки поменяли, этот обход уже никому не нужен.
            snap = _build(roots, lambda: generation != self._generation)
        except Exception:
            logbook.exc("индекс файлов")
            return
        if snap is None or generation != self._generation:
            return
        # Подменяем в главном потоке: там же ложатся изменения из наблюдателя.
        self._built.emit(snap, stamp, generation)
        logbook.log("индекс файлов: %d за %.1f с" % (len(snap), time.perf_counter() - started))

    def _swap(self, snap, stamp, generation):
        if generation != self._generation:
            return                          # пока ехал сигнал, начали новый обход
        # Изменения, пришедшие до начала обхода, в нём уже учтены.
        self._delta = {k: v for k, v in self._delta.items() if v[4] >= stamp}
        self._removed = {k: v for k, v in self._removed.items() if v >= stamp}
        self._dropped = {k: v for k, v in self._dropped.items() if v >= stamp}
        self._more_entered = {k: v for k, v in self._more_entered.items() if v >= stamp}
        self._snap = snap
        self._narrow = []
        self._busy = False
        self.changed.emit()

    # --- изменения в папках ------------------------------------------------ #

    def _on_events(self, root, events):
        """Поток наблюдателя: события -> операции для главного потока."""
        if events is None:
            self._overflow.emit()
            return
        prefix = root.rstrip("\\/") + os.sep
        ops = []
        for action, path in events:
            parts = path[len(prefix):].split(os.sep)
            if any(p.startswith(".") or p.lower() in _SKIP_DIRS for p in parts):
                continue
            level = len(parts) - 1                # уровень папки, где лежит путь
            if level > _MAX_DEPTH:
                continue
            if action in (watch.REMOVED, watch.RENAMED_OLD):
                ops.append(("remove", path))
                continue
            if action not in (watch.ADDED, watch.RENAMED_NEW):
                continue
            try:
                info = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            if info.st_file_attributes & _HIDDEN:
                continue
            is_dir = stat.S_ISDIR(info.st_mode)
            if is_dir and info.st_file_attributes & _REPARSE:
                continue
            ops.append(("add", path, is_dir, level))
            # Папку перенесли целиком — Windows сообщает только о ней самой.
            if is_dir and level < _MAX_DEPTH:
                for folder, depth, entries in _tree(path, level + 1, lambda: False,
                                                    pausable=False):
                    base = folder if folder.endswith(os.sep) else folder + os.sep
                    ops.extend(("add", base + name, d, depth) for name, d in entries)
        if ops:
            self._ops.emit(ops)

    def _entered(self, folder):
        return folder in self._snap.entered or folder in self._more_entered

    def _apply(self, ops):
        self._stamp += 1
        stamp = self._stamp
        for op in ops:
            path = op[1]
            key = _norm(path)
            if op[0] == "add":
                _, _, is_dir, level = op
                if not self._entered(_norm(os.path.dirname(path))):
                    continue                    # внутри скрытой или служебной папки
                self._removed.pop(key, None)
                self._delta[key] = (_lower(os.path.basename(path)), path, is_dir,
                                    path.count(os.sep), stamp)
                if is_dir and level < _MAX_DEPTH:
                    self._more_entered[key] = stamp
                continue
            self._delta.pop(key, None)
            self._removed[key] = stamp
            if self._entered(key):
                # Удалили папку: всё внутри неё — тоже.
                inside = key + os.sep
                self._dropped[inside] = stamp
                for table in (self._delta, self._more_entered):
                    for k in [k for k in table if k.startswith(inside)]:
                        del table[k]
                self._more_entered.pop(key, None)
        if len(self._delta) > _DELTA_MAX:
            self._mark_dirty()
        self._changed_timer.start()

    def _mark_dirty(self):
        self._dirty = True
        if not self._dirty_timer.isActive():
            self._dirty_timer.start()

    # --- поиск ------------------------------------------------------------- #

    def _candidates(self, snap, key):
        """Номера имён с подстрокой key: полный список или первые из многих."""
        base = None
        for s, k, found in self._narrow:
            if s is snap and k in key and (base is None or len(found) < len(base)):
                base = found
        lower, starts = snap.lower, snap.starts
        if base is not None:
            # Дописали букву: подходят только те, что подходили раньше.
            found = [i for i in base if key in lower[starts[i]:starts[i + 1] - 1]]
            self._remember(snap, key, found)
            return found
        found = []
        pos = lower.find(key, 1)
        while pos >= 0:
            i = bisect.bisect_right(starts, pos) - 1
            found.append(i)
            if len(found) > _NARROW_MAX:
                break
            # Следующее имя: повторы в этом не нужны.
            pos = lower.find(key, starts[i + 1])
        else:
            self._remember(snap, key, found)
            return found
        # Совпадений слишком много: берём первые и все, что с key начинаются.
        found = found[:_SCAN_CAP]
        seen = set(found)
        needle = "\n" + key
        pos = lower.find(needle)
        extra = 0
        while pos >= 0 and extra < _PREFIX_CAP:
            i = bisect.bisect_right(starts, pos + 1) - 1
            if i not in seen:
                found.append(i)
                extra += 1
            pos = lower.find(needle, pos + 1)
        return found

    def _remember(self, snap, key, found):
        self._narrow = [n for n in self._narrow if n[1] != key][-3:] + [(snap, key, found)]

    def search(self, query, limit=12, skip=None):
        """
        [(оценка, путь, папка ли)] по убыванию оценки.
        skip(путь) -> True — пропустить (скрытое). Проверяется до отбора
        лучших: иначе скрытая папка с сотней совпадений съедала бы выдачу.
        """
        snap = self._snap
        tokens = query.lower().split()
        if not tokens:
            return []
        # Ищем по самому длинному слову запроса — у него меньше всего совпадений,
        # остальные слова проверяем уже на найденных.
        key = max(tokens, key=len)
        others = [t for t in tokens if t is not key]
        phrase = " ".join(tokens)
        delta, removed = self._delta, self._removed
        dropped = tuple(self._dropped)
        check = bool(skip or delta or removed or dropped)
        lower, starts, folder, depths = snap.lower, snap.starts, snap.folder, snap.depths
        found = []
        for i in (self._candidates(snap, key) if len(snap) else ()):
            name = lower[starts[i]:starts[i + 1] - 1]
            if others and not all(t in name for t in others):
                continue
            path = None
            if check:
                path = snap.path(i)
                if skip and skip(path):
                    continue
                if delta or removed or dropped:
                    norm = _norm(path)
                    if norm in removed or norm in delta or (dropped and norm.startswith(dropped)):
                        continue
            # Из двух одинаковых имён ближе то, что лежит неглубоко.
            score = _score(name, phrase, name.find(key)) - depths[folder[i]] * 0.4
            found.append((score, i, path))
        for name, path, is_dir, depth, _stamp in delta.values():
            if key not in name or (others and not all(t in name for t in others)):
                continue
            if skip and skip(path):
                continue
            found.append((_score(name, phrase, name.find(key)) - depth * 0.4, -1,
                          (path, is_dir)))
        best = heapq.nlargest(limit, found, key=lambda r: r[0])
        result = []
        for score, i, extra in best:
            if i < 0:
                result.append((score, extra[0], extra[1]))
            else:
                result.append((score, extra or snap.path(i), bool(snap.isdir[i])))
        return result
