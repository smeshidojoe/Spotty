"""
Скрытые пункты — то, что убрали из выдачи через Ctrl+K → «Скрыть».

Скрытая папка прячет и всё, что в ней лежит: убирают папку обычно потому, что
её содержимое мешает в выдаче, а не ради одной строки с её именем.

Кроме ключа храним название и путь: в настройках надо показать, что именно
скрыто, даже если программы уже нет в «Пуске» или файл переехал.
"""

import os

from ..core import jsonfile
from ..core.constants import HIDDEN_PATH


class Hidden:
    def __init__(self, path=HIDDEN_PATH):
        self._path = path
        data = jsonfile.load(path, [])
        self._items = [e for e in data if isinstance(e, dict) and e.get("key")] \
            if isinstance(data, list) else []
        self._index()

    def _index(self):
        self._keys = {e["key"].casefold() for e in self._items}
        # «C:\a\b\» — с разделителем на конце, чтобы «C:\a\b» не прятала «C:\a\bc».
        self._folders = tuple(os.path.normpath(e["path"]).casefold().rstrip("\\/") + os.sep
                              for e in self._items
                              if e.get("kind") == "folder" and e.get("path"))

    def __contains__(self, key):
        return bool(key) and key.casefold() in self._keys

    def __len__(self):
        return len(self._items)

    def hides_path(self, path):
        """Файл или папка скрыты — сами или потому, что лежат в скрытой папке."""
        folded = path.casefold()
        return ("file:" + folded) in self._keys or (
            bool(self._folders) and folded.startswith(self._folders))

    def items(self):
        """Свежескрытые первыми."""
        return list(self._items)

    def add(self, item):
        if not item.key or item.key in self:
            return
        self._items.insert(0, {"key": item.key, "title": item.title, "kind": item.kind,
                               "path": item.path or item.target})
        self._index()
        jsonfile.save(self._path, self._items)

    def remove(self, key):
        folded = key.casefold()
        self._items = [e for e in self._items if e["key"].casefold() != folded]
        self._index()
        jsonfile.save(self._path, self._items)
