"""
Свой индекс файлов и папок.

Обходим выбранные папки в фоне и держим имена в памяти. Поиск идёт не циклом
по списку, а поиском подстроки в одной большой строке со всеми именами через
«\\n»: str.find работает на C и проходит сотни тысяч имён за миллисекунды,
тогда как цикл на Python на каждое нажатие клавиши заметно тормозил бы.
"""

import bisect
import os
import stat
import threading
import time

from PySide6.QtCore import QObject, Signal

from ..core import logbook

# Папки, в которых нечего искать человеку, а файлов — сотни тысяч.
_SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".hg", ".svn", "venv", ".venv",
    "site-packages", ".idea", ".vs", ".vscode", ".gradle", ".cache", ".tox",
    ".mypy_cache", ".pytest_cache", "$recycle.bin", "system volume information",
}
_HIDDEN = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM
_MAX_DEPTH = 10
_MAX_ENTRIES = 400_000
_REFRESH_SECONDS = 20 * 60


def _walk(roots, stop):
    """(имена, пути, папка ли) по всем корням — обход без рекурсии."""
    names, paths, dirs = [], [], []
    for root in roots:
        stack = [(root, 0)]
        while stack:
            if stop() or len(names) >= _MAX_ENTRIES:
                return names, paths, dirs
            folder, depth = stack.pop()
            try:
                entries = os.scandir(folder)
            except OSError:
                continue
            with entries:
                for entry in entries:
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
                        # Точки соединения («Мои рисунки» в Документах и т. п.)
                        # ведут в чужие папки или закрыты — не заходим.
                        if is_dir and info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                            continue
                    except OSError:
                        continue
                    names.append(name)
                    paths.append(entry.path)
                    dirs.append(is_dir)
                    if is_dir and depth < _MAX_DEPTH:
                        stack.append((entry.path, depth + 1))
    return names, paths, dirs


class FileIndex(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._roots = []
        # (пути, папка ли, blob, starts): blob — "\n" + имена в нижнем регистре
        # через "\n", starts — где в нём начинается каждое имя. Всё в одном
        # кортеже: замена — одно присваивание, и поиск из главного потока не
        # увидит новые пути со старыми именами.
        self._data = ([], [], "", [])
        self._generation = 0
        self._busy = False
        self._built_at = 0.0

    def __len__(self):
        return len(self._data[0])

    def set_roots(self, roots):
        roots = [os.path.normpath(r) for r in roots if r and os.path.isdir(r)]
        if roots != self._roots:
            self._roots = roots
            self.rebuild()

    def refresh_if_stale(self):
        if time.monotonic() - self._built_at > _REFRESH_SECONDS:
            self.rebuild()

    def rebuild(self):
        """Переобойти папки в фоне. Старый индекс работает, пока строится новый."""
        self._generation += 1
        self._built_at = time.monotonic()
        generation, roots = self._generation, list(self._roots)
        if not roots:
            self._swap([], [], [])
            return
        self._busy = True
        threading.Thread(target=self._worker, args=(generation, roots),
                         name="spotty-files", daemon=True).start()

    def _worker(self, generation, roots):
        started = time.perf_counter()
        try:
            # Если за время обхода папки поменяли, этот обход уже никому не нужен.
            names, paths, dirs = _walk(roots, lambda: generation != self._generation)
        except Exception:
            logbook.exc("индекс файлов")
            return
        if generation != self._generation:
            return
        self._swap(names, paths, dirs)
        logbook.log("индекс файлов: %d за %.1f с" % (
            len(paths), time.perf_counter() - started))

    def _swap(self, names, paths, dirs):
        starts, pos = [], 1
        for name in names:
            starts.append(pos)
            pos += len(name) + 1
        blob = "\n" + "\n".join(n.lower() for n in names) + "\n"
        self._data = (paths, dirs, blob, starts)
        self._busy = False
        self.changed.emit()

    def search(self, query, limit=12):
        """[(оценка, путь, папка ли)] по убыванию оценки."""
        paths, dirs, blob, starts = self._data
        tokens = query.lower().split()
        if not tokens or not paths:
            return []
        # Ищем по самому длинному слову запроса — у него меньше всего совпадений,
        # остальные слова проверяем уже на найденных.
        key = max(tokens, key=len)
        others = [t for t in tokens if t is not key]
        found = {}
        pos = blob.find(key, 1)
        while pos >= 0 and len(found) < 3000:
            index = bisect.bisect_right(starts, pos) - 1
            if index not in found:
                start = starts[index]
                end = blob.find("\n", start)
                name = blob[start:end]
                if all(t in name for t in others):
                    # Из двух одинаковых имён ближе то, что лежит неглубоко.
                    found[index] = (self._score(name, tokens, pos - start)
                                    - paths[index].count(os.sep) * 0.4)
            # Следующее имя: прыгаем за конец текущего, повторы в нём не нужны.
            pos = blob.find(key, blob.find("\n", pos) + 1)
        best = sorted(found.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        return [(score, paths[i], dirs[i]) for i, score in best]

    @staticmethod
    def _score(name, tokens, offset):
        stem = os.path.splitext(name)[0]
        if stem == " ".join(tokens) or name == " ".join(tokens):
            score = 100.0
        elif offset == 0:
            score = 85.0
        elif not name[offset - 1].isalnum():
            score = 75.0                       # с начала слова
        else:
            score = 55.0
        # Короткие имена ближе к запросу, чем длинные с тем же вхождением.
        return score - min(len(name), 60) * 0.1
