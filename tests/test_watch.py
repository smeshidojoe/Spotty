import os
import shutil
import time
import winreg

from spotty.core import watch


def wait_for(items, timeout=3.0):
    """Обработчики вызываются в потоке наблюдателя — ждём, пока что-то придёт."""
    end = time.monotonic() + timeout
    while time.monotonic() < end and not items:
        time.sleep(0.02)
    time.sleep(0.1)                       # пусть долетит вся пачка
    return bool(items)


def events(batches):
    return [e for batch in batches if batch for e in batch]


def test_sees_files_in_subfolders(watcher, tmp_path):
    vendor = tmp_path / "Vendor"
    vendor.mkdir()
    batches = []
    assert watcher.watch_dir(str(tmp_path), batches.append) is not None
    (vendor / "New App.lnk").write_text("")
    assert wait_for(batches)
    assert (watch.ADDED, str(vendor / "New App.lnk")) in events(batches)


def test_rename_and_remove(watcher, tmp_path):
    batches = []
    watcher.watch_dir(str(tmp_path), batches.append)
    old, new = tmp_path / "a.txt", tmp_path / "b.txt"
    old.write_text("")
    os.rename(old, new)
    new.unlink()
    assert wait_for(batches)
    actions = [a for a, _ in events(batches)]
    assert watch.RENAMED_OLD in actions and watch.RENAMED_NEW in actions
    assert watch.REMOVED in actions


def test_missing_folder_is_not_watched(watcher, tmp_path):
    assert watcher.watch_dir(str(tmp_path / "nope"), lambda e: None) is None


def test_unwatch_stops_events(watcher, tmp_path):
    batches = []
    watcher.unwatch(watcher.watch_dir(str(tmp_path), batches.append))
    time.sleep(0.2)
    (tmp_path / "late.txt").write_text("")
    time.sleep(0.4)
    assert batches == []


def test_deleted_folder_reports_none(watcher, tmp_path):
    folder = tmp_path / "gone"
    folder.mkdir()
    batches = []
    watcher.watch_dir(str(folder), batches.append)
    shutil.rmtree(folder)
    assert wait_for(batches)
    assert None in batches


def test_registry_key(watcher):
    path = r"Software\SpottyTests\Watch"
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path)
    hits = []
    try:
        assert watcher.watch_key(watch.HKCU, path, lambda: hits.append(1)) is not None
        with winreg.CreateKey(key, "{New}") as sub:
            winreg.SetValueEx(sub, "DisplayName", 0, winreg.REG_SZ, "New App")
        assert wait_for(hits)
    finally:
        winreg.DeleteKey(key, "{New}")
        winreg.CloseKey(key)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\SpottyTests")
