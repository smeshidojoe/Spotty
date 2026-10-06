from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from spotty.core import double_tap, hotkey
from spotty.core.double_tap import Detector, GROUPS
from spotty.ui.widgets import HotkeyField

CTRL, LCTRL, RCTRL, C = 0x11, 0xA2, 0xA3, 0x43


def run(events):
    d = Detector(GROUPS["ctrl"])
    return [d.feed(vk, down, t) for vk, down, t in events]


def test_modifier():
    assert double_tap.modifier("ctrl+ctrl") == "ctrl"
    assert double_tap.modifier("Shift + Shift") == "shift"
    assert double_tap.modifier("ctrl+e") is None
    assert double_tap.modifier("win+win") is None
    assert hotkey.parse("ctrl+ctrl") is None
    assert hotkey.display("ctrl+ctrl") == "Ctrl+Ctrl"


def test_double_tap():
    assert run([(LCTRL, 1, 0), (LCTRL, 0, 80), (RCTRL, 1, 200), (RCTRL, 0, 260)])[-1]


def test_autorepeat_is_one_press():
    assert run([(LCTRL, 1, 0), (LCTRL, 1, 30), (LCTRL, 0, 90),
                (LCTRL, 1, 200), (LCTRL, 0, 260)])[-1]


def test_chords_do_not_count():
    # Ctrl+C, Ctrl+V подряд.
    assert not any(run([(LCTRL, 1, 0), (C, 1, 40), (C, 0, 60), (LCTRL, 0, 90),
                        (LCTRL, 1, 150), (0x56, 1, 180), (0x56, 0, 200), (LCTRL, 0, 230)]))
    # Ctrl, затем Ctrl+C.
    assert not any(run([(LCTRL, 1, 0), (LCTRL, 0, 60), (LCTRL, 1, 150),
                        (C, 1, 180), (C, 0, 200), (LCTRL, 0, 230)]))


def test_slow_or_held_does_not_count():
    assert not any(run([(LCTRL, 1, 0), (LCTRL, 0, 60), (LCTRL, 1, 600), (LCTRL, 0, 650)]))
    assert not any(run([(LCTRL, 1, 0), (LCTRL, 0, 500), (LCTRL, 1, 600), (LCTRL, 0, 650)]))


def test_triple_tap_fires_once():
    events = [(CTRL, 1, 0), (CTRL, 0, 50), (CTRL, 1, 100), (CTRL, 0, 150),
              (CTRL, 1, 200), (CTRL, 0, 250)]
    assert run(events) == [False, False, False, True, False, False]


def key(kind, k, repeat=False):
    return QKeyEvent(kind, k, Qt.KeyboardModifier.NoModifier, 0, 0, 0, "", repeat)


def test_field_records_double_modifier(qapp):
    field = HotkeyField("ctrl+e")
    got = []
    field.changed.connect(got.append)
    field._recording = True
    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) * 2:
        if kind == QEvent.Type.KeyPress:
            field.keyPressEvent(key(kind, Qt.Key.Key_Shift))
        else:
            field.keyReleaseEvent(key(kind, Qt.Key.Key_Shift))
    assert got == ["shift+shift"] and not field.is_recording()


def test_field_ignores_single_modifier(qapp):
    field = HotkeyField("ctrl+e")
    got = []
    field.changed.connect(got.append)
    field._recording = True
    field.keyPressEvent(key(QEvent.Type.KeyPress, Qt.Key.Key_Control))
    field.keyReleaseEvent(key(QEvent.Type.KeyRelease, Qt.Key.Key_Control))
    field.keyPressEvent(key(QEvent.Type.KeyPress, Qt.Key.Key_Alt))
    field.keyReleaseEvent(key(QEvent.Type.KeyRelease, Qt.Key.Key_Alt))
    assert got == [] and field.is_recording()


def test_manager_registers_double_tap(qapp):
    manager = hotkey.HotkeyManager()
    assert manager.register("t", "ctrl+ctrl") and manager.is_registered("t")
    manager.unregister("t")
    assert not manager.is_registered("t")
