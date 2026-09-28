import json

from spotty.core import config


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_fresh_defaults(tmp_path):
    c = config.Config(str(tmp_path / "none.json"))
    assert c.get("update_mode") == "background"
    assert c.get("fullscreen_guard") is False


def test_v1_file_drops_old_defaults(tmp_path):
    # 0.1.0 записывала все настройки подряд, в том числе старое «notify».
    path = tmp_path / "config.json"
    write(path, {"hotkey": "ctrl+e", "update_mode": "notify", "autostart": True,
                 "glass": True, "web_engine": "yandex"})
    c = config.Config(str(path))
    assert c.get("update_mode") == "background"
    assert c.get("web_engine") == "yandex"
    assert c.get("autostart") is True


def test_saves_only_changed_keys(tmp_path):
    path = tmp_path / "config.json"
    write(path, {"web_engine": "yandex", "update_mode": "notify"})
    c = config.Config(str(path))
    c.set("glass", False)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "web_engine": "yandex", "glass": False, "format": 2}


def test_explicit_choice_in_format_2_is_kept(tmp_path):
    path = tmp_path / "config.json"
    c = config.Config(str(path))
    c.set("update_mode", "notify")
    assert config.Config(str(path)).get("update_mode") == "notify"
