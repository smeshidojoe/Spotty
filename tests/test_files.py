import array
import ctypes
import os
import random
import shutil

import pytest

from conftest import keep, pump
from spotty.search import files


def snapshot(paths):
    """Индекс в памяти из списка путей — без обхода диска."""
    names, folder, isdir, folders, entered = [], array.array("I"), bytearray(), [], {}
    for path in paths:
        parent = os.path.dirname(path) + os.sep
        if parent not in folders:
            folders.append(parent)
            entered[os.path.normcase(parent.rstrip(os.sep))] = len(folders) - 1
        names.append(os.path.basename(path))
        folder.append(folders.index(parent))
        isdir.append(False)
    return files._Snapshot(names, folder, isdir, folders, entered)


def index_of(paths):
    index = keep(files.FileIndex())
    index._snap = snapshot(paths)
    return index


def found(index, query, **kw):
    return [os.path.basename(p) for _, p, _ in index.search(query, **kw)]


def test_ranking():
    index = index_of([r"C:\a\b\c\deep report.txt", r"C:\a\report.txt", r"C:\a\myreport.txt",
                      r"C:\a\report", r"C:\a\notes.txt"])
    assert found(index, "report") == ["report", "report.txt", "deep report.txt", "myreport.txt"]
    assert found(index, "report deep") == ["deep report.txt"]
    assert found(index, "zzz") == []


def test_skip_hidden_paths():
    index = index_of([r"C:\secret\report.txt", r"C:\open\report.txt"])
    assert index.search("report", skip=lambda p: p.startswith("C:\\secret"))[0][1] == \
        r"C:\open\report.txt"


def test_astral_and_special_letters():
    # Эмодзи хранится отдельно, «İ» в нижнем регистре длиннее — имена не съезжают.
    index = index_of([r"C:\x\🦈 shark.txt", r"C:\x\İstanbul.txt", r"C:\x\zeta.txt"])
    assert index.search("shark")[0][1] == r"C:\x\🦈 shark.txt"
    assert found(index, "zeta") == ["zeta.txt"]
    assert found(index, "stanbul") == ["İstanbul.txt"]


def test_narrowing_gives_same_results():
    random.seed(7)
    syllables = ["te", "le", "gram", "doc", "re", "ad", "me", "pho", "to", "x", "an", "na"]
    paths = [r"C:\f%d\%s.txt" % (i % 40, "".join(random.choice(syllables)
                                                   for _ in range(random.randint(1, 4))))
             for i in range(3000)]
    narrowed = index_of(paths)
    for query in ["t", "te", "tel", "tele", "teleg", "telegr", "r", "re", "rea", "read",
                  "an", "ann", "anna"]:
        fresh = index_of(paths)
        fresh._snap = narrowed._snap
        assert narrowed.search(query, 10) == fresh.search(query, 10), query


def test_too_many_matches_keeps_best():
    paths = [r"C:\f\xtex%d.txt" % i for i in range(files._NARROW_MAX + 500)]
    paths.append(r"C:\f\te.txt")
    assert found(index_of(paths), "te")[0] == "te.txt"


def hide(path):
    ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2)


def make_tree(root):
    for rel in ["Report 2024.pdf", "notes.txt", r"sub\deep\readme.md", r".dot\file.txt",
                r"node_modules\lib.js", "hidden.txt"]:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    hide(root / "hidden.txt")


@pytest.fixture
def index(qapp, watcher, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    make_tree(root)
    index = keep(files.FileIndex(watcher))
    index.set_roots([str(root)])
    assert pump(qapp, lambda: len(index) > 0)
    return index, root


def has(index, query, name):
    return name in found(index, query)


def test_walk_skips_hidden_and_service(index):
    index, _root = index
    assert has(index, "readme", "readme.md")
    assert has(index, "report 2024", "Report 2024.pdf")
    assert not has(index, "file", "file.txt")          # в папке с точкой
    assert not has(index, "lib", "lib.js")             # node_modules
    assert not has(index, "hidden", "hidden.txt")      # скрытый


def test_live_changes(qapp, index, tmp_path):
    index, root = index
    (root / "sub" / "fresh plan.txt").write_text("")
    assert pump(qapp, lambda: has(index, "fresh", "fresh plan.txt"))

    os.rename(root / "notes.txt", root / "diary.txt")
    assert pump(qapp, lambda: has(index, "diary", "diary.txt"))
    assert not has(index, "notes", "notes.txt")

    (root / "Report 2024.pdf").unlink()
    assert pump(qapp, lambda: not has(index, "report", "Report 2024.pdf"))

    # Папку перенесли целиком — Windows сообщает только о ней самой.
    outside = tmp_path / "outside" / "album"
    outside.mkdir(parents=True)
    (outside / "photo 1.jpg").write_text("")
    shutil.move(str(outside), str(root / "album"))
    assert pump(qapp, lambda: has(index, "photo", "photo 1.jpg"))

    shutil.rmtree(root / "sub")
    assert pump(qapp, lambda: not has(index, "readme", "readme.md")
                and not has(index, "fresh", "fresh plan.txt"))

    (root / ".dot" / "secret.txt").write_text("")
    (root / "album" / "photo 2.jpg").write_text("")
    assert pump(qapp, lambda: has(index, "photo", "photo 2.jpg"))
    assert not has(index, "secret", "secret.txt")


def test_changes_survive_rebuild(qapp, index):
    index, root = index
    (root / "later.txt").write_text("")
    assert pump(qapp, lambda: has(index, "later", "later.txt"))
    (root / "notes.txt").unlink()
    assert pump(qapp, lambda: not has(index, "notes", "notes.txt"))
    old = index._snap
    index.rebuild()
    assert pump(qapp, lambda: index._snap is not old)
    assert found(index, "later") == ["later.txt"]      # ровно один раз
    assert not has(index, "notes", "notes.txt")
