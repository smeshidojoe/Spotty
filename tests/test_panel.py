import pytest

from conftest import keep, pump
from spotty.search import apps
from spotty.search.uninstall import Entry


@pytest.fixture(scope="module")
def instance(qapp, tmp_path_factory):
    # Свой пустой «Пуск»: тестовый Spotty не должен следить за настоящим.
    real = apps._start_menu_dirs
    apps._start_menu_dirs = lambda: []
    try:
        from spotty.app import Spotty
        s = Spotty(qapp)
    finally:
        apps._start_menu_dirs = real
    keep(s)
    yield s, tmp_path_factory.mktemp("panel")
    s.panel.hide()
    s.tray.hide()


@pytest.fixture
def spotty(instance):
    s, folder = instance
    s.catalog.apps = [{"name": "Cool App", "target": str(folder / "Cool App.lnk"),
                       "kind": "link", "path": str(folder / "Cool" / "cool.exe")}]
    s.catalog.version += 1
    s.uninstaller.entries = [Entry(r"HKCU\Cool", "Cool App 1.0", '"%s" /S' % (
        folder / "Cool" / "uninstall.exe"), folders=(str(folder / "Cool").lower(),))]
    s.panel.menu.close_menu()
    yield s
    s.panel.dismiss()


def menu_ids(s):
    return [a.id for a in s.panel.menu.actions_]


def test_uninstall_asks_first(spotty, monkeypatch, qapp):
    started = []
    monkeypatch.setattr("spotty.core.winapi.shell_open",
                        lambda target, params=None, verb=None, cwd=None:
                        started.append((target, params)) or True)
    panel = spotty.panel
    panel.summon()
    panel.input.setText("cool")
    assert panel.current().title == "Cool App"

    panel.toggle_actions()
    assert menu_ids(spotty)[-1] == "uninstall"
    panel._on_menu_action("uninstall")
    assert menu_ids(spotty) == ["uninstall_confirm", "cancel"]
    assert panel.menu.actions_[0].danger
    assert started == []

    panel._on_menu_action("cancel")
    assert not panel.menu.is_open() and started == []

    panel.toggle_actions()
    panel._on_menu_action("uninstall")
    panel.menu.activate()                  # Enter — первый пункт, «Удалить»
    assert pump(qapp, lambda: started)
    assert started[0][0].endswith("uninstall.exe") and started[0][1] == "/S"


def test_no_uninstall_without_entry(spotty):
    spotty.uninstaller.entries = []
    panel = spotty.panel
    panel.summon()
    panel.input.setText("cool")
    panel.toggle_actions()
    assert "uninstall" not in menu_ids(spotty)


def test_typing_ahead_skips_intermediate_search(spotty, monkeypatch, qapp):
    searched = []
    real = spotty.engine.search
    monkeypatch.setattr(spotty.engine, "search", lambda text: searched.append(text) or real(text))
    pending = [True]
    monkeypatch.setattr("spotty.core.winapi.keys_pending", lambda: pending[0])
    panel = spotty.panel
    panel.summon()
    searched.clear()
    panel.input.setText("c")
    panel.input.setText("co")
    assert searched == []                  # следующая буква уже в очереди
    pending[0] = False
    assert pump(qapp, lambda: searched == ["co"])
