"""
Статистика для страницы «Статистика»: сколько раз открывали строку и что в
ней делали.

Хранятся только суммы — по дням (для графика за месяц) и за всё время.
Текст запроса не сохраняется: от него берётся лишь длина. Файл лежит рядом с
настройками и никуда не отправляется.

Что считаем:
* открытия строки и выполненные действия — по дням и всего;
* действия по типам пунктов: программы, файлы, калькулятор…;
* запуски каждой программы — для «Чаще всего». Первый раз список берётся из
  счётчиков usage.json, они копятся с установки Spotty;
* когда пункт выбрали из выдачи на набранный запрос: сколько букв набрали,
  был ли пункт первым и сколько букв названия печатать не пришлось.
"""

import datetime
import time

from PySide6.QtCore import QObject, QTimer

from ..core import jsonfile
from ..core.constants import STATS_PATH

KINDS = ("app", "file", "folder", "calc", "command", "web", "internal")
_KIND_OF = {"link": "web"}
# Уборка в выдаче, а не работа: в действия не идёт.
_NOT_COUNTED = {"forget", "hide", "forget_command"}
# Пункты, которые ищут по названию, — по ним считается набор.
_NAMED = {"app", "file", "folder", "internal"}
DAYS = 30
_MAX_APPS = 300
# Открытие строки не должно ждать диска: пишем чуть позже, одной записью.
_SAVE_MS = 2000


def _last_days(days):
    """Даты последних days дней — старые первыми, сегодня последним."""
    today = datetime.date.today()
    return [today - datetime.timedelta(days=i) for i in range(days - 1, -1, -1)]


def _int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class Stats(QObject):
    def __init__(self, usage=None, path=STATS_PATH, parent=None):
        super().__init__(parent)
        self._path = path
        self._timer = QTimer(self, singleShot=True, interval=_SAVE_MS)
        self._timer.timeout.connect(self.save)
        data = jsonfile.load(path, {})
        if data:
            self._load(data)
        else:
            self._clear(usage.counts("app:") if usage is not None else {})

    def _clear(self, apps=None):
        self.since = time.time()
        self.days = {}                  # "ГГГГ-ММ-ДД" -> [открытия, действия]
        self.opens = self.actions = 0
        self.kinds = {}
        self.apps = {k: c for k, c in (apps or {}).items() if c > 0}
        self.picks = self.typed = self.first = self.saved = 0

    def _load(self, data):
        self._clear()
        self.since = float(data.get("since") or time.time())
        days = data.get("days") if isinstance(data.get("days"), dict) else {}
        self.days = {d: [_int(v[0]), _int(v[1])] for d, v in days.items()
                     if isinstance(v, list) and len(v) == 2}
        for name in ("opens", "actions", "picks", "typed", "first", "saved"):
            setattr(self, name, _int(data.get(name)))
        for name in ("kinds", "apps"):
            value = data.get(name) if isinstance(data.get(name), dict) else {}
            setattr(self, name, {k: _int(c) for k, c in value.items()})

    def save(self):
        self._timer.stop()
        jsonfile.save(self._path, {
            "since": self.since, "days": self.days, "opens": self.opens,
            "actions": self.actions, "kinds": self.kinds, "apps": self.apps,
            "picks": self.picks, "typed": self.typed, "first": self.first,
            "saved": self.saved})

    def _changed(self):
        # Старые дни графику не нужны.
        if len(self.days) > DAYS:
            for day in sorted(self.days)[:-DAYS]:
                del self.days[day]
        self._timer.start()

    def _today(self):
        return self.days.setdefault(datetime.date.today().isoformat(), [0, 0])

    # --- запись ------------------------------------------------------------ #

    def opened(self):
        self._today()[0] += 1
        self.opens += 1
        self._changed()

    def acted(self, item, action_id, query="", first=False):
        """Выполнено действие над пунктом. first — пункт стоял первым в выдаче."""
        if action_id in _NOT_COUNTED:
            return
        self._today()[1] += 1
        self.actions += 1
        kind = _KIND_OF.get(item.kind, item.kind)
        if kind in KINDS:
            self.kinds[kind] = self.kinds.get(kind, 0) + 1
        if item.kind == "app" and item.key:
            self.apps[item.key] = self.apps.get(item.key, 0) + 1
            if len(self.apps) > _MAX_APPS:
                del self.apps[min(self.apps, key=self.apps.get)]
        query = query.strip()
        if query and item.kind in _NAMED and query[0] not in ">?":
            self.picks += 1
            self.typed += len(query)
            self.first += bool(first)
            self.saved += max(0, len(item.title) - len(query))
        self._changed()

    def reset(self):
        self._clear()
        self.save()

    # --- чтение ------------------------------------------------------------ #

    def period(self, days):
        """(открытия, действия) за последние days дней, включая сегодня."""
        rows = [self.days.get(d.isoformat(), [0, 0]) for d in _last_days(days)]
        return sum(r[0] for r in rows), sum(r[1] for r in rows)

    def daily(self, days=DAYS):
        """[(дата, открытия, действия)] — старые первыми, сегодня последним."""
        return [(d, *self.days.get(d.isoformat(), [0, 0])) for d in _last_days(days)]

    def kinds_ranked(self):
        """[(тип, сколько)] — больше первыми, без нулей."""
        return sorted(((k, c) for k, c in self.kinds.items() if c > 0 and k in KINDS),
                      key=lambda r: -r[1])

    def top_apps(self):
        """[(ключ программы, запуски)] — больше первыми."""
        return sorted(((k, c) for k, c in self.apps.items() if c > 0),
                      key=lambda r: (-r[1], r[0]))

    def letters(self):
        """Сколько букв в среднем набирают до выбора, None — ещё не выбирали."""
        return self.typed / self.picks if self.picks else None

    def first_share(self):
        """Доля выборов первого пункта выдачи (0..1), None — ещё не выбирали."""
        return self.first / self.picks if self.picks else None
