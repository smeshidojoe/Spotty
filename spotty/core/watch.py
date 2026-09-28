"""
Слежение за папками и ключами реестра — одним фоновым потоком.

Windows сама сообщает об изменениях: ReadDirectoryChangesW — о файлах в папке
(с подпапками или без), RegNotifyChangeKeyValue — о ключе реестра. Поток спит в
WaitForMultipleObjects и просыпается только по событию, процессор не тратит.

QFileSystemWatcher из Qt не подходит: он не видит подпапок, а установщик
кладёт ярлык в «Пуск\\Производитель\\Программа.lnk».

Обработчики вызываются в потоке наблюдателя: в главный поток их результат
переносят сами получатели (сигналом Qt).
"""

import ctypes
import os
import threading
from ctypes import wintypes

from . import logbook

# Что происходит с файлом (FILE_NOTIFY_INFORMATION.Action).
ADDED, REMOVED, MODIFIED, RENAMED_OLD, RENAMED_NEW = 1, 2, 3, 4, 5

_FILE_LIST_DIRECTORY = 0x0001
_SHARE_ALL = 0x7
_OPEN_EXISTING = 3
_FLAG_BACKUP_SEMANTICS = 0x02000000
_FLAG_OVERLAPPED = 0x40000000
_NOTIFY_FILE_NAME = 0x001
_NOTIFY_DIR_NAME = 0x002
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_WAIT_OBJECT_0 = 0
_INFINITE = 0xFFFFFFFF
_MAX_HANDLES = 64                        # MAXIMUM_WAIT_OBJECTS
_BUFFER = 64 * 1024                      # больше сетевые папки не принимают

_KEY_NOTIFY = 0x0010
KEY_WOW64_32KEY = 0x0200                 # 32-битная ветка HKLM (WOW6432Node)
_REG_NOTIFY_NAME = 0x1
_REG_NOTIFY_LAST_SET = 0x4

HKCU = 0x80000001
HKLM = 0x80000002


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_adv = ctypes.WinDLL("advapi32")

_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_k32.CreateEventW.restype = wintypes.HANDLE
_k32.SetEvent.argtypes = [wintypes.HANDLE]
_k32.ResetEvent.argtypes = [wintypes.HANDLE]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
_k32.ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                       wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_void_p]
_k32.ReadDirectoryChangesW.restype = wintypes.BOOL
_k32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                     ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
_k32.GetOverlappedResult.restype = wintypes.BOOL
_k32.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
                                        wintypes.BOOL, wintypes.DWORD]
_k32.WaitForMultipleObjects.restype = wintypes.DWORD
_adv.RegOpenKeyExW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD,
                               wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
_adv.RegOpenKeyExW.restype = ctypes.c_long
_adv.RegNotifyChangeKeyValue.argtypes = [wintypes.HANDLE, wintypes.BOOL, wintypes.DWORD,
                                         wintypes.HANDLE, wintypes.BOOL]
_adv.RegNotifyChangeKeyValue.restype = ctypes.c_long
_adv.RegCloseKey.argtypes = [wintypes.HANDLE]


def _parse(buffer, size):
    """FILE_NOTIFY_INFORMATION подряд -> [(действие, относительный путь)]."""
    events, offset = [], 0
    while offset + 12 <= size:
        nxt, action, length = (int.from_bytes(buffer[offset + i:offset + i + 4], "little")
                               for i in (0, 4, 8))
        name = bytes(buffer[offset + 12:offset + 12 + length]).decode("utf-16-le", "replace")
        events.append((action, name))
        if not nxt:
            break
        offset += nxt
    return events


class _DirWatch:
    """
    Папка. callback(события) — список (действие, полный путь); None — Windows
    не успела передать все изменения (переполнение) или папка пропала:
    получателю надо перечитать её целиком.
    """

    def __init__(self, path, subtree, callback):
        self.path, self.subtree, self.callback = path, subtree, callback
        self.handle = None
        self.event = None
        self.buffer = (ctypes.c_char * _BUFFER)()
        self.overlapped = _OVERLAPPED()

    def open(self):
        handle = _k32.CreateFileW(self.path, _FILE_LIST_DIRECTORY, _SHARE_ALL, None,
                                  _OPEN_EXISTING, _FLAG_BACKUP_SEMANTICS | _FLAG_OVERLAPPED,
                                  None)
        if not handle or handle == _INVALID_HANDLE:
            return False
        self.handle = handle
        self.event = _k32.CreateEventW(None, True, False, None)
        self.overlapped.hEvent = self.event
        if self._arm():
            return True
        self.close()
        return False

    def _arm(self):
        _k32.ResetEvent(self.event)
        return bool(_k32.ReadDirectoryChangesW(
            self.handle, self.buffer, _BUFFER, self.subtree,
            _NOTIFY_FILE_NAME | _NOTIFY_DIR_NAME, None,
            ctypes.byref(self.overlapped), None))

    def fire(self):
        """Событие пришло: разобрать буфер и снова ждать. False — слежение кончилось."""
        size = wintypes.DWORD()
        ok = _k32.GetOverlappedResult(self.handle, ctypes.byref(self.overlapped),
                                      ctypes.byref(size), False)
        if not ok:
            return False
        events = None                     # ноль байт — буфер переполнился
        if size.value:
            base = self.path.rstrip("\\/")
            events = [(action, base + os.sep + name)
                      for action, name in _parse(self.buffer, size.value)]
        # Сначала заново подписываемся, потом зовём получателя: пока он думает,
        # новые изменения копятся у Windows, а не теряются.
        alive = self._arm()
        _call(self.callback, events)
        return alive

    def close(self):
        if self.handle:
            _k32.CancelIoEx(self.handle, None)
            # Дождаться отмены: иначе Windows допишет в буфер, которого уже нет.
            size = wintypes.DWORD()
            _k32.GetOverlappedResult(self.handle, ctypes.byref(self.overlapped),
                                     ctypes.byref(size), True)
            _k32.CloseHandle(self.handle)
            self.handle = None
        if self.event:
            _k32.CloseHandle(self.event)
            self.event = None


class _KeyWatch:
    """Ключ реестра со всеми подключами. callback() — что-то поменялось."""

    def __init__(self, root, subkey, callback, view=0):
        self.root, self.subkey, self.callback, self.view = root, subkey, callback, view
        self.key = None
        self.event = None

    def open(self):
        key = wintypes.HANDLE()
        if _adv.RegOpenKeyExW(self.root, self.subkey, 0, _KEY_NOTIFY | self.view,
                              ctypes.byref(key)) != 0:
            return False
        self.key = key
        self.event = _k32.CreateEventW(None, False, False, None)
        if self._arm():
            return True
        self.close()
        return False

    def _arm(self):
        return _adv.RegNotifyChangeKeyValue(self.key, True,
                                            _REG_NOTIFY_NAME | _REG_NOTIFY_LAST_SET,
                                            self.event, True) == 0

    def fire(self):
        alive = self._arm()
        _call(self.callback)
        return alive

    def close(self):
        if self.key:
            _adv.RegCloseKey(self.key)
            self.key = None
        if self.event:
            _k32.CloseHandle(self.event)
            self.event = None


def _call(callback, *args):
    try:
        callback(*args)
    except Exception:
        logbook.exc("наблюдатель")


class Watcher:
    """
    watch_dir / watch_key возвращают метку для unwatch или None, если следить
    не вышло (папки нет, сетевой диск без уведомлений, ключа нет).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._watches = {}                # метка -> _DirWatch | _KeyWatch
        # Снятые слежения не отпускаем из потока наблюдателя: обработчик держит
        # QObject, и последняя ссылка, отпущенная здесь, удалила бы его не в
        # его потоке — Qt этого не прощает.
        self._dead = []
        self._requests = []               # (метка, объект | None) — для потока
        self._next = 0
        self._wake = _k32.CreateEventW(None, False, False, None)
        self._stopped = False
        self._opened = {}                 # метка -> threading.Event, ответ «открылось ли»
        self._results = {}
        self._thread = threading.Thread(target=self._run, name="spotty-watch", daemon=True)
        self._thread.start()

    def watch_dir(self, path, callback, subtree=True):
        return self._add(_DirWatch(path, subtree, callback))

    def watch_key(self, root, subkey, callback, view=0):
        """view — KEY_WOW64_32KEY, чтобы смотреть 32-битную ветку HKLM."""
        return self._add(_KeyWatch(root, subkey, callback, view))

    def unwatch(self, token):
        if token is None:
            return
        with self._lock:
            self._requests.append((token, None))
        _k32.SetEvent(self._wake)

    def stop(self):
        self._stopped = True
        _k32.SetEvent(self._wake)

    def _add(self, watch):
        # Открываем в потоке наблюдателя: подписка RegNotifyChangeKeyValue живёт,
        # пока жив поток, который её сделал.
        done = threading.Event()
        with self._lock:
            self._next += 1
            token = self._next
            self._opened[token] = done
            self._requests.append((token, watch))
        _k32.SetEvent(self._wake)
        done.wait(5)
        with self._lock:
            self._opened.pop(token, None)
            ok = self._results.pop(token, False)
        return token if ok else None

    def _apply_requests(self):
        with self._lock:
            requests, self._requests = self._requests, []
        for token, watch in requests:
            if watch is None:
                old = self._watches.pop(token, None)
                if old is not None:
                    old.close()
                    self._dead.append(old)
                continue
            ok = len(self._watches) < _MAX_HANDLES - 1 and watch.open()
            if ok:
                self._watches[token] = watch
            with self._lock:
                self._results[token] = ok
                done = self._opened.get(token)
            if done is not None:
                done.set()

    def _run(self):
        while not self._stopped:
            self._apply_requests()
            tokens = list(self._watches)
            handles = (wintypes.HANDLE * (len(tokens) + 1))(
                self._wake, *(self._watches[t].event for t in tokens))
            result = _k32.WaitForMultipleObjects(len(tokens) + 1, handles, False, _INFINITE)
            index = result - _WAIT_OBJECT_0
            if not 1 <= index <= len(tokens):
                continue                  # разбудили ради новых меток или остановки
            token = tokens[index - 1]
            watch = self._watches[token]
            if not watch.fire():
                # Папку удалили или ключ пропал: больше не ждём. Получатель
                # папки узнаёт об этом по None и перечитает её сам.
                watch.close()
                self._dead.append(self._watches.pop(token))
                if isinstance(watch, _DirWatch):
                    _call(watch.callback, None)
        for watch in self._watches.values():
            watch.close()
