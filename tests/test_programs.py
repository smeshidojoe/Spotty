import os
import struct

from conftest import keep, pump
from spotty.search import programs


def fake_exe(path, subsystem=2):
    """Самый короткий exe, по которому видно подсистему: 2 — оконная, 3 — консоль."""
    head = bytearray(0x200)
    head[0:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x80)
    head[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", head, 0x80 + 24 + 68, subsystem)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(head))


def test_words_and_junk():
    assert programs.words("RzSDKServer64") == ["rz", "sdk", "server", "64"]
    assert programs.is_junk("unins000")
    assert programs.is_junk("crashpad_handler")
    # «host» внутри слова — это игра, а не служба.
    assert not programs.is_junk("Ghostwire")


def test_title():
    assert programs.title_for("obs64", {"FileDescription": "OBS Studio"}, "obs-studio") == "OBS Studio"
    # Движок вместо названия — берём папку.
    assert programs.title_for("Game", {"FileDescription": "Unity Player"}, "Tales") == "Tales"
    assert programs.title_for("MotorSlice-Win64-Shipping", {}, "MotorSlice") == "MotorSlice"


def test_package_root_steam():
    folder = os.path.join("D:\\", "Games", "steamapps", "common", "Hollow", "bin")
    assert programs.package_root(folder) == os.path.normcase(
        os.path.join("D:\\", "Games", "steamapps", "common", "Hollow"))


def test_subsystem(tmp_path):
    fake_exe(tmp_path / "gui.exe", 2)
    fake_exe(tmp_path / "cli.exe", 3)
    (tmp_path / "text.exe").write_text("not a program")
    assert programs._subsystem(str(tmp_path / "gui.exe")) == 2
    assert programs._subsystem(str(tmp_path / "cli.exe")) == 3
    assert programs._subsystem(str(tmp_path / "text.exe")) is None


def make_tree(root):
    fake_exe(root / "CoolApp" / "CoolApp.exe")
    fake_exe(root / "CoolApp" / "unins000.exe")                 # служебный
    fake_exe(root / "CoolApp" / "tool.exe", 3)                  # консольный
    fake_exe(root / "Other" / "Game.exe")                       # безликое имя
    fake_exe(root / "repo" / "debug.exe")                       # git-репозиторий
    (root / "repo" / ".git").mkdir()


def test_scan_folder(tmp_path):
    make_tree(tmp_path)
    apps = programs.scan(roots=[str(tmp_path)])
    names = sorted(a["name"] for a in apps)
    assert names == ["CoolApp", "Other"]


def test_install_folders(tmp_path):
    windows = os.environ.get("SystemRoot") or r"C:\Windows"
    picked = programs.install_folders([str(tmp_path), windows, "C:\\", str(tmp_path / "nope")])
    assert picked == [os.path.normcase(str(tmp_path))]


def test_scan_folders_adds_to_list(qapp, tmp_path):
    make_tree(tmp_path)
    disk = keep(programs.DiskPrograms())
    disk.apps = [{"name": "Other", "target": "x", "path": "x", "kind": "exe"}]
    changed = []
    disk.changed.connect(lambda: changed.append(1))
    disk.scan_folders([str(tmp_path)])
    assert pump(qapp, lambda: changed)
    # «Other» уже был — второй раз не добавляется.
    assert sorted(a["name"] for a in disk.apps) == ["CoolApp", "Other"]
    assert disk.first_scan is False
