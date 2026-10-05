import datetime
import json

from conftest import keep
from spotty.search.engine import Item
from spotty.search.stats import Stats
from spotty.search.usage import Usage


def app(name, kind="app"):
    return Item(kind, name, key="app:" + name.casefold())


def test_counts_opens_and_actions(qapp, tmp_path):
    stats = keep(Stats(path=str(tmp_path / "stats.json")))
    stats.opened()
    stats.opened()
    stats.acted(app("Telegram"), "open", "tel", first=True)
    stats.acted(Item("calc", "4"), "copy", "2+2")
    stats.acted(Item("link", "Open x.com"), "open", "x.com")
    stats.acted(app("Telegram"), "hide", "tel")          # уборка — не действие
    assert stats.period(1) == (2, 3) and stats.period(7) == (2, 3)
    assert (stats.opens, stats.actions) == (2, 3)
    assert dict(stats.kinds_ranked()) == {"app": 1, "calc": 1, "web": 1}
    assert stats.top_apps() == [("app:telegram", 1)]
    days = stats.daily()
    assert len(days) == 30 and days[-1][0] == datetime.date.today()
    assert days[-1][1:] == (2, 3)


def test_typing_counts_only_named_items(qapp, tmp_path):
    stats = keep(Stats(path=str(tmp_path / "stats.json")))
    assert stats.letters() is None and stats.first_share() is None
    stats.acted(app("Telegram"), "open", " te ", first=True)    # 2 буквы из 8
    stats.acted(app("Chrome"), "open", "chr", first=False)      # 3 из 6
    stats.acted(Item("calc", "4"), "copy", "2+2", first=True)   # не по названию
    stats.acted(Item("command", "dir"), "run", ">dir", first=True)
    stats.acted(app("Paint"), "open", "", first=True)           # с пустого запроса
    assert stats.picks == 2
    assert stats.letters() == 2.5
    assert stats.first_share() == 0.5
    assert stats.saved == (8 - 2) + (6 - 3)


def test_saved_and_reloaded(qapp, tmp_path):
    path = str(tmp_path / "stats.json")
    stats = keep(Stats(path=path))
    stats.opened()
    stats.acted(app("Telegram"), "open", "t", first=True)
    stats.save()
    data = json.loads(open(path, encoding="utf-8").read())
    assert "t" not in json.dumps(data["days"])     # текст запроса не хранится
    again = keep(Stats(path=path))
    assert (again.opens, again.actions, again.saved) == (1, 1, 7)
    assert again.period(1) == (1, 1)


def test_first_run_takes_app_counts_from_usage(qapp, tmp_path):
    usage = Usage(str(tmp_path / "usage.json"))
    for _ in range(3):
        usage.record("app:telegram")
    usage.record("file:C:\notes.txt")
    stats = keep(Stats(usage, path=str(tmp_path / "stats.json")))
    assert stats.top_apps() == [("app:telegram", 3)]
    stats.reset()
    assert stats.top_apps() == [] and stats.opens == 0
    # После сброса файл есть — счётчики usage второй раз не подтягиваются.
    assert keep(Stats(usage, path=str(tmp_path / "stats.json"))).top_apps() == []


def test_old_days_are_dropped(qapp, tmp_path):
    stats = keep(Stats(path=str(tmp_path / "stats.json")))
    for i in range(40):
        stats.days[(datetime.date.today() - datetime.timedelta(days=i + 1)).isoformat()] = [1, 1]
    stats.opened()
    assert len(stats.days) == 30
    assert datetime.date.today().isoformat() in stats.days
