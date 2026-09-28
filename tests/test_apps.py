import os
import time

import pytest

from conftest import keep, pump
from spotty.search import apps


def url(path, target="https://example.com"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[InternetShortcut]\nURL=%s\n" % target)


def test_scan_links_parses_only_changed(tmp_path, monkeypatch):
    url(tmp_path / "One.url")
    url(tmp_path / "Vendor" / "Two.url")
    url(tmp_path / "Vendor" / "Uninstall Two.url")             # мусор
    calls = []
    real = apps._parse_link
    monkeypatch.setattr(apps, "_parse_link", lambda p: calls.append(p) or real(p))
    dirs = [(str(tmp_path), True)]

    found, cache = apps.scan_links({}, dirs)
    assert sorted(a["name"] for a in found) == ["One", "Two"]
    assert len(calls) == 3

    calls.clear()
    found, cache = apps.scan_links(cache, dirs)
    assert calls == [] and len(found) == 2

    (tmp_path / "One.url").write_text("[InternetShortcut]\nURL=https://example.org/longer\n")
    found, cache = apps.scan_links(cache, dirs)
    assert calls == [str(tmp_path / "One.url")]


def test_collect_merges_store_apps():
    links = [{"name": "Telegram", "target": "t.lnk", "kind": "link", "path": ""}]
    store = [{"name": "Telegram", "id": "Telegram.Desktop_abc!App"},           # уже есть
             {"name": "Calculator", "id": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"},
             {"name": "Readme", "id": r"C:\x\readme.txt"},                    # документ
             {"name": "Site", "id": "https://example.com"}]
    result = apps.collect(links, store)
    assert [a["name"] for a in result] == ["Calculator", "Telegram"]
    assert result[0]["target"] == "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"


def test_merge_found_drops_start_menu_programs(tmp_path):
    start = [{"name": "Discord", "target": "d.lnk", "kind": "link",
              "path": str(tmp_path / "Discord" / "Update.exe")}]
    found = [{"name": "Discord Helper", "path": str(tmp_path / "Discord" / "app" / "Discord.exe")},
             {"name": "discord", "path": str(tmp_path / "Elsewhere" / "discord.exe")},
             {"name": "Portable", "path": str(tmp_path / "Portable" / "p.exe")}]
    assert [a["name"] for a in apps.merge_found(start, found)] == ["Portable"]


@pytest.fixture
def catalog_dirs(tmp_path, monkeypatch):
    start, desk = tmp_path / "Start", tmp_path / "Desktop"
    (start / "Vendor").mkdir(parents=True)
    desk.mkdir()
    url(start / "Old App.url")
    url(start / "Keeper.url")
    monkeypatch.setattr(apps, "_start_menu_dirs", lambda: [(str(start), True),
                                                           (str(desk), False)])
    monkeypatch.setattr(apps, "_start_apps", lambda: {
        "apps": [], "removable": ["Some.App_abcdefghijklm"]})
    return start, desk, str(tmp_path / "apps.json")


def names(catalog):
    return {a["name"] for a in catalog.apps}


def test_catalog_notices_new_shortcut(qapp, watcher, catalog_dirs):
    start, desk, cache = catalog_dirs
    catalog = keep(apps.AppCatalog(watcher, cache))
    catalog.refresh()
    assert pump(qapp, lambda: names(catalog) == {"Old App", "Keeper"})
    assert catalog.first_seen("Old App") == 0             # было до Spotty
    assert catalog.removable == {"Some.App_abcdefghijklm"}
    assert catalog.store_watched

    url(start / "Vendor" / "New App.url")                  # подпапка, которая уже была
    assert pump(qapp, lambda: "New App" in names(catalog), timeout=8)
    assert time.time() - catalog.first_seen("New App") < 60

    url(desk / "Desk App.url")
    assert pump(qapp, lambda: "Desk App" in names(catalog), timeout=8)

    # Отметки переживают перезапуск.
    again = keep(apps.AppCatalog(None, cache))
    assert again.first_seen("New App") == catalog.first_seen("New App")
    assert again.first_seen("Old App") == 0


def test_reinstall_is_not_new(qapp, watcher, catalog_dirs):
    start, _desk, cache = catalog_dirs
    catalog = keep(apps.AppCatalog(watcher, cache))
    catalog.refresh()
    assert pump(qapp, lambda: names(catalog) == {"Old App", "Keeper"})
    os.remove(start / "Old App.url")
    assert pump(qapp, lambda: "Old App" not in names(catalog), timeout=8)
    # Обновление удалило и вернуло ярлык — программа не новая.
    url(start / "Old App.url")
    assert pump(qapp, lambda: "Old App" in names(catalog), timeout=8)
    assert catalog.first_seen("Old App") == 0


def test_found_programs_baseline(qapp, catalog_dirs):
    _start, _desk, cache = catalog_dirs
    catalog = keep(apps.AppCatalog(None, cache))
    catalog.set_found([{"name": "Tool", "target": "t.exe", "path": "t.exe", "kind": "exe"}],
                      baseline=True)
    assert catalog.first_seen("Tool") == 0
    catalog.set_found(catalog._found_raw + [{"name": "Fresh", "target": "f.exe",
                                             "path": "f.exe", "kind": "exe"}], baseline=False)
    assert catalog.first_seen("Fresh") > 0


def test_reads_old_cache_format(tmp_path):
    import json
    path = tmp_path / "apps.json"
    path.write_text(json.dumps([{"name": "Legacy", "target": "l.lnk", "kind": "link",
                                 "path": ""}]), encoding="utf-8")
    catalog = keep(apps.AppCatalog(None, str(path)))
    assert names(catalog) == {"Legacy"}
    assert catalog.first_seen("Legacy") == 0
