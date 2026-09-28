import os
import winreg

import pytest

from spotty.search import uninstall
from spotty.search.uninstall import Entry


def norm(path):
    return os.path.normcase(os.path.normpath(str(path)))


def test_split_command(tmp_path):
    exe = tmp_path / "My App" / "uninst.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    assert uninstall.split_command('"C:\\A B\\u.exe" /S') == ("C:\\A B\\u.exe", "/S")
    assert uninstall.split_command("%s --remove now" % exe) == (str(exe), "--remove now")
    assert uninstall.split_command("steam://uninstall/480") == ("steam://uninstall/480", None)
    assert uninstall.split_command("MsiExec.exe /X{1}") == ("MsiExec.exe", "/X{1}")


def test_msi_uses_uninstall_switch():
    entry = Entry("HKLM\\{X}", "App", "MsiExec.exe /I{X}", msi="{X}")
    assert uninstall.command_for(entry) == ("msiexec.exe", "/x {X}")


def test_store_family():
    assert uninstall.store_family(
        "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App") == \
        "Microsoft.WindowsCalculator_8wekyb3d8bbwe"
    assert uninstall.store_family("shell:AppsFolder\\Microsoft.Windows.Explorer") is None
    assert uninstall.store_family(r"C:\x\app.lnk") is None


@pytest.fixture
def vendor(tmp_path):
    return tmp_path / "Programs"


def test_finds_by_folder_and_name(vendor):
    discord = Entry("HKCU\\Discord", "Discord", "Update.exe --uninstall",
                    folders=(norm(vendor / "Discord"),))
    other = Entry("HKCU\\Other", "Other", "u.exe", folders=(norm(vendor / "Other"),))
    found = uninstall.find([other, discord], "Discord", path=str(vendor / "Discord" / "Update.exe"))
    assert found is discord


def test_launcher_shortcut_does_not_uninstall_launcher(vendor):
    # Ярлык игры запускает steam.exe — удалить по нему можно только Steam, а это не та программа.
    steam = Entry("HKLM\\Steam", "Steam", "uninstall.exe", icon=norm(vendor / "Steam" / "steam.exe"),
                  folders=(norm(vendor / "Steam"),))
    assert uninstall.find([steam], "Hollow Knight",
                          path=str(vendor / "Steam" / "steam.exe")) is None


def test_vendor_folder_is_not_enough(vendor):
    edge = Entry("HKLM\\Edge", "Microsoft Edge", "setup.exe",
                 folders=(norm(vendor / "Microsoft"),))
    assert uninstall.find([edge], "Microsoft Teams",
                          path=str(vendor / "Microsoft" / "Teams" / "teams.exe")) is None
    assert uninstall.find([edge], "Microsoft Edge",
                          path=str(vendor / "Microsoft" / "Edge" / "msedge.exe")) is edge


def test_equal_candidates_are_not_guessed(vendor):
    a = Entry("HKLM\\A", "Foo", "a.exe", folders=(norm(vendor / "Foo"),))
    b = Entry("HKLM\\B", "Foo Tools", "b.exe", folders=(norm(vendor / "Foo"),))
    assert uninstall.find([a, b], "Foo", path=str(vendor / "Foo" / "foo.exe")) is None


def test_by_name_without_path():
    paint = Entry("HKLM\\P", "paint.net 5.0.13", "u.exe")
    assert uninstall.find([paint], "Paint.NET") is paint
    python = [Entry("HKLM\\1", "Python 3.12 (64-bit)", "u"), Entry("HKLM\\2", "Python 3.13", "u")]
    assert uninstall.find(python, "Python") is None


def test_read_entry_from_registry(tmp_path):
    path = r"Software\SpottyTests\Uninstall"
    guid = "{11111111-2222-3333-4444-555555555555}"
    folder = tmp_path / "Cool App"
    folder.mkdir()
    parent = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path)
    try:
        with winreg.CreateKey(parent, guid) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Cool App 1.0")
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, "MsiExec.exe /I" + guid)
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(folder))
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(folder / "cool.exe") + ",0")
            winreg.SetValueEx(key, "WindowsInstaller", 0, winreg.REG_DWORD, 1)
        with winreg.CreateKey(parent, "Hidden") as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Runtime")
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, "x.exe")
            winreg.SetValueEx(key, "SystemComponent", 0, winreg.REG_DWORD, 1)
        entry = uninstall._read_entry(parent, guid, "HKCU")
        assert entry.name == "Cool App 1.0"
        assert entry.msi == guid
        assert entry.icon == norm(folder / "cool.exe")
        assert entry.folders == (norm(folder),)
        assert uninstall._read_entry(parent, "Hidden", "HKCU") is None
    finally:
        winreg.DeleteKey(parent, guid)
        winreg.DeleteKey(parent, "Hidden")
        winreg.CloseKey(parent)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\SpottyTests")


def test_index_reports_only_new_entries(qapp):
    from conftest import keep
    index = keep(uninstall.UninstallIndex())
    added = []
    index.added.connect(added.append)
    first = [Entry("HKLM\\A", "A", "a")]
    index._busy = True
    index._on_loaded(first)
    assert added == []                     # первое чтение — то, что уже стояло
    index._busy = True
    index._on_loaded(first + [Entry("HKLM\\B", "B", "b")])
    assert [e.name for e in added[0]] == ["B"]
