"""
Что и как часто запускали — отсюда «Часто используемые» и порядок выдачи.

Два знания:
* частота с поправкой на давность (frecency): десять запусков месяц назад
  весят меньше, чем пять за эту неделю;
* что выбирали на конкретный запрос: если на «c» трижды открыли Chrome, в
  следующий раз «c» сразу выделит его.
"""

import math
import time

from ..core import jsonfile
from ..core.constants import HISTORY_PATH, USAGE_PATH

_MAX_QUERIES = 500
_MAX_COMMANDS = 50
_HALF_LIFE_DAYS = 14.0


class Usage:
    def __init__(self, path=USAGE_PATH):
        self._path = path
        data = jsonfile.load(path, {})
        self._items = data.get("items", {}) if isinstance(data.get("items"), dict) else {}
        self._queries = data.get("queries", {}) if isinstance(data.get("queries"), dict) else {}
        self.version = 0                  # растёт при каждом изменении

    def _save(self):
        self.version += 1
        jsonfile.save(self._path, {"items": self._items, "queries": self._queries})

    def record(self, key, query=""):
        entry = self._items.setdefault(key, {"count": 0, "last": 0})
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last"] = time.time()
        query = query.strip().lower()[:32]
        if query:
            self._queries.pop(query, None)          # в конец: самый свежий
            self._queries[query] = key
            while len(self._queries) > _MAX_QUERIES:
                self._queries.pop(next(iter(self._queries)))
        self._save()

    def forget(self, key):
        self._items.pop(key, None)
        for q in [q for q, k in self._queries.items() if k == key]:
            del self._queries[q]
        self._save()

    def frecency(self, key):
        entry = self._items.get(key)
        if not entry:
            return 0.0
        age_days = max(0.0, (time.time() - entry.get("last", 0)) / 86400.0)
        decay = 0.5 ** (age_days / _HALF_LIFE_DAYS)
        return math.log1p(entry.get("count", 0)) * decay

    def last(self, key):
        """Когда пункт запускали последний раз (time.time()), 0 — никогда."""
        entry = self._items.get(key)
        return float(entry.get("last", 0)) if entry else 0.0

    def counts(self, prefix=""):
        """{ключ: сколько раз запускали} — для ключей с этим началом."""
        return {k: int(e.get("count", 0)) for k, e in self._items.items()
                if k.startswith(prefix)}

    def chosen_for(self, query):
        """Что выбирали на этот запрос или на его начало."""
        query = query.strip().lower()[:32]
        while query:
            key = self._queries.get(query)
            if key:
                return key
            query = query[:-1]
        return None

    def top(self, limit):
        ranked = sorted(self._items, key=self.frecency, reverse=True)
        return [k for k in ranked if self.frecency(k) > 0.05][:limit]


class CommandHistory:
    """Недавние команды терминала, свежие первыми."""

    def __init__(self, path=HISTORY_PATH):
        self._path = path
        self._items = [c for c in jsonfile.load(path, []) if isinstance(c, str)]

    def add(self, command):
        command = command.strip()
        if not command:
            return
        if command in self._items:
            self._items.remove(command)
        self._items.insert(0, command)
        del self._items[_MAX_COMMANDS:]
        jsonfile.save(self._path, self._items)

    def remove(self, command):
        if command in self._items:
            self._items.remove(command)
            jsonfile.save(self._path, self._items)

    def matching(self, prefix, limit=8):
        prefix = prefix.strip().lower()
        return [c for c in self._items if prefix in c.lower()][:limit]
