"""
Иконки программ и файлов из оболочки Windows.

IShellItemImageFactory отдаёт ту же картинку, что показывает проводник: для
ярлыка — без стрелки, для приложения из Магазина — его плитку, для файла — значок
типа. QFileIconProvider так не умеет: у него ярлыки со стрелкой, а приложений
Магазина он не знает вовсе.

Извлечение идёт в отдельном потоке — у некоторых ярлыков оно стоит десятки
миллисекунд, а список должен рисоваться сразу. Готовая картинка приходит
сигналом `ready(ключ)`.
"""

import ctypes
import hashlib
import os
import queue
import threading
import time
import uuid
from ctypes import wintypes

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QBrush, QImage, QPainter, QPainterPath, QPixmap

from . import logbook
from .constants import ICONS_DIR

# Размер, который просим у оболочки. Меньше — и на экране с масштабом 200 %
# иконка поплывёт; больше — лишняя память на сотни программ.
FETCH_PX = 96

SIIGBF_BIGGERSIZEOK = 0x01
SIIGBF_ICONONLY = 0x04
COINIT_APARTMENTTHREADED = 0x2
DIB_RGB_COLORS = 0


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text):
    return _GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


IID_IShellItemImageFactory = _guid("bcc18b79-ba16-442f-80c4-8a59c30c463b")


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BITMAP(ctypes.Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


_shell32 = ctypes.windll.shell32
_gdi32 = ctypes.windll.gdi32
_user32 = ctypes.windll.user32
_ole32 = ctypes.windll.ole32

_shell32.SHCreateItemFromParsingName.argtypes = [
    wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(_GUID),
    ctypes.POINTER(ctypes.c_void_p)]
_shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
_gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
_gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                             wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
                             wintypes.UINT]
_gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

# Методы COM-интерфейса берём из таблицы виртуальных функций по номеру:
# 0-2 — IUnknown (QueryInterface, AddRef, Release), 3 — GetImage.
_Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
_GetImage = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, _SIZE, ctypes.c_int,
                               ctypes.POINTER(wintypes.HBITMAP))


def _method(obj, index, proto):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return proto(vtable[index])


def _hbitmap_to_image(hbitmap):
    info = _BITMAP()
    if not _gdi32.GetObjectW(hbitmap, ctypes.sizeof(info), ctypes.byref(info)):
        return None
    width, height = info.bmWidth, abs(info.bmHeight)
    if width <= 0 or height <= 0:
        return None

    header = _BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(header)
    header.biWidth = width
    header.biHeight = -height            # строки сверху вниз, как у QImage
    header.biPlanes = 1
    header.biBitCount = 32
    buffer = (ctypes.c_ubyte * (width * height * 4))()
    dc = _user32.GetDC(None)
    try:
        lines = _gdi32.GetDIBits(dc, hbitmap, 0, height, buffer,
                                 ctypes.byref(header), DIB_RGB_COLORS)
    finally:
        _user32.ReleaseDC(None, dc)
    if lines != height:
        return None

    data = bytes(buffer)
    # Старые иконки без альфа-канала приходят с нулевой альфой везде — как
    # есть они бы просто не нарисовались. Такие считаем непрозрачными.
    has_alpha = any(data[3::4])
    fmt = (QImage.Format.Format_ARGB32_Premultiplied if has_alpha
           else QImage.Format.Format_RGB32)
    return QImage(data, width, height, width * 4, fmt).copy()


def extract(parsing_name, size=FETCH_PX):
    """Иконка по пути или по имени вида shell:AppsFolder\\<AUMID>. None — не вышло.

    Вызывать из потока, где инициализирован COM.
    """
    factory = ctypes.c_void_p()
    hr = _shell32.SHCreateItemFromParsingName(
        parsing_name, None, ctypes.byref(IID_IShellItemImageFactory),
        ctypes.byref(factory))
    if hr != 0 or not factory:
        return None
    hbitmap = wintypes.HBITMAP()
    try:
        hr = _method(factory, 3, _GetImage)(
            factory, _SIZE(size, size), SIIGBF_ICONONLY | SIIGBF_BIGGERSIZEOK,
            ctypes.byref(hbitmap))
        if hr != 0 or not hbitmap:
            return None
        image = _hbitmap_to_image(hbitmap)
    finally:
        if hbitmap:
            _gdi32.DeleteObject(hbitmap)
        _method(factory, 2, _Release)(factory)
    if image is not None and (image.width() > size or image.height() > size):
        image = image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    return image


def _round_plate(image):
    """
    Плитки приложений Магазина на Windows 10 — квадраты во всю ширину, с
    острыми углами они выглядят заплатками среди остальных иконок. Непрозрачный
    квадрат скругляем, как иконку приложения на macOS.
    """
    w, h = image.width(), image.height()
    if w < 8 or h < 8:
        return image
    corners = (image.pixelColor(0, 0), image.pixelColor(w - 1, 0),
               image.pixelColor(0, h - 1), image.pixelColor(w - 1, h - 1))
    if min(c.alpha() for c in corners) < 250:
        return image
    out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    path = QPainterPath()
    path.addRoundedRect(0, 0, w, h, w * 0.22, h * 0.22)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(image))
    p.drawPath(path)
    p.end()
    return out


# --- кэш на диске ------------------------------------------------------------ #
# Достать иконку из оболочки стоит 10-80 мс, прочитать PNG — меньше
# миллисекунды. Без кэша после перезагрузки первые секунды список пестрел бы
# заглушками.

_CACHE_DAYS = 14


def _cache_path(key):
    return os.path.join(ICONS_DIR, hashlib.sha1(key.encode("utf-8")).hexdigest() + ".png")


def _load_cached(key, source):
    path = _cache_path(key)
    try:
        cached_at = os.path.getmtime(path)
    except OSError:
        return None
    if time.time() - cached_at > _CACHE_DAYS * 86400:
        return None
    # Ярлык или exe поменялся после того, как мы сохранили иконку, — берём заново.
    if not source.lower().startswith("shell:"):
        try:
            if os.path.getmtime(source) > cached_at:
                return None
        except OSError:
            pass
    image = QImage(path)
    return None if image.isNull() else image


def _save_cached(key, image):
    try:
        os.makedirs(ICONS_DIR, exist_ok=True)
        image.save(_cache_path(key), "PNG")
    except OSError:
        pass


class IconService(QObject):
    """Кэш иконок: ключ -> картинка. Недостающие достаёт фоновый поток."""

    ready = Signal(str)
    _loaded = Signal(str, QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._images = {}                 # ключ -> QImage (FETCH_PX)
        self._pixmaps = {}                # (ключ, размер в px) -> QPixmap
        self._pending = set()
        self._urgent = set()
        self._failed = set()
        self._seq = 0
        self._queue = queue.Queue()
        self._loaded.connect(self._store)
        threading.Thread(target=self._worker, name="spotty-icons",
                         daemon=True).start()

    def request(self, key, parsing_name, urgent=False):
        """Поставить иконку в очередь, если её ещё нет."""
        if key in self._images or key in self._failed:
            return
        if key in self._pending and (not urgent or key in self._urgent):
            return
        self._pending.add(key)
        if urgent:
            self._urgent.add(key)
        # Видимые строки — вперёд фоновой прогрузки, и из них свежие первыми:
        # пока пользователь печатает, нужнее то, что на экране сейчас.
        self._seq += 1
        order = (0, -self._seq) if urgent else (1, self._seq)
        self._queue.put((order, key, parsing_name))

    def failed(self, key):
        return key in self._failed

    def pixmap(self, key, px):
        """Готовая иконка нужного размера в пикселях устройства или None."""
        cached = self._pixmaps.get((key, px))
        if cached is not None:
            return cached
        image = self._images.get(key)
        if image is None:
            return None
        # Уменьшаем один раз и честно, с усреднением: при рисовании «на лету»
        # сглаживание билинейное, и уменьшение вчетверо даёт зубцы.
        pixmap = QPixmap.fromImage(image.scaled(
            px, px, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        self._pixmaps[(key, px)] = pixmap
        return pixmap

    def _store(self, key, image):
        self._pending.discard(key)
        self._urgent.discard(key)
        if key in self._images:
            return
        if image.isNull():
            self._failed.add(key)
            return
        self._images[key] = image
        self.ready.emit(key)

    def _worker(self):
        _ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        # Очередь с приоритетом: срочные (видимые) вперёд фоновых.
        backlog = []
        while True:
            if not backlog:
                backlog.append(self._queue.get())
            while True:
                try:
                    backlog.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            backlog.sort(key=lambda job: job[0])
            _, key, name = backlog.pop(0)
            if key in self._images:
                continue                  # уже пришла по более раннему запросу
            try:
                image = _load_cached(key, name)
                if image is None:
                    image = extract(name)
                    if image is not None:
                        image = _round_plate(image)
                        _save_cached(key, image)
            except Exception:
                logbook.exc("иконка " + name)
                image = None
            try:
                self._loaded.emit(key, image if image is not None else QImage())
            except RuntimeError:
                return                    # программа закрывается, сервис уже удалён
