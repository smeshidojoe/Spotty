import time

import pytest

from conftest import keep

from spotty.core.i18n import tr
from spotty.search import engine
from spotty.search.files import FileIndex
from spotty.search.hidden import Hidden
from spotty.search.usage import CommandHistory, Usage


class FakeCatalog:
    def __init__(self, apps, seen=None):
        self.apps = apps
        self.found = []
        self.version = 0
        self.seen = seen or {}

    def first_seen(self, name):
        return self.seen.get(name.casefold(), 0)


def app(name):
    return {"name": name, "target": name + ".lnk", "kind": "link", "path": ""}


@pytest.fixture
def make(qapp, tmp_path):
    def make(apps, seen=None):
        catalog = FakeCatalog(apps, seen)
        usage = Usage(str(tmp_path / "usage.json"))
        hidden = Hidden(str(tmp_path / "hidden.json"))
        search = engine.SearchEngine(catalog, keep(FileIndex()), usage,
                                     CommandHistory(str(tmp_path / "commands.json")), hidden)
        return search, catalog, usage, hidden
    return make


def section(sections, title):
    return next((items for t, items in sections if t == title), None)


def test_new_app_on_home_and_in_results(make):
    search, _catalog, usage, _hidden = make(
        [app("Blender"), app("Old")], {"blender": time.time() - 60})
    home = search.search("")
    new = section(home, tr("section.new"))
    assert [i.title for i in new] == ["Blender"] and new[0].extra.get("new")
    listed = {i.title: i.extra.get("new", False) for i in section(home, tr("section.apps"))}
    assert listed == {"Blender": True, "Old": False}
    assert section(search.search("blen"), tr("section.apps"))[0].extra.get("new")

    # Запустили — метка снимается.
    usage.record("app:blender")
    assert section(search.search(""), tr("section.new")) is None
    assert not section(search.search("blen"), tr("section.apps"))[0].extra.get("new")


def test_new_label_expires(make):
    search, *_ = make([app("Blender")], {"blender": time.time() - 25 * 3600})
    assert section(search.search(""), tr("section.new")) is None


def test_home_app_list_is_cached(make):
    search, catalog, _usage, hidden = make([app("A"), app("B")])
    first = section(search.search(""), tr("section.apps"))
    assert section(search.search(""), tr("section.apps")) is first
    catalog.version += 1
    assert section(search.search(""), tr("section.apps")) is not first
    items = section(search.search(""), tr("section.apps"))
    hidden.add(items[0])
    assert [i.title for i in section(search.search(""), tr("section.apps"))] == ["B"]


def test_sections_order(make):
    search, *_ = make([app("Calculator Pro")])
    titles = [t for t, _ in search.search("calc")]
    assert titles[0] == tr("section.apps")
    assert titles[-2:] == [tr("section.web"), tr("section.terminal")]
    assert search.search("2+2")[0][0] == tr("section.calc")
