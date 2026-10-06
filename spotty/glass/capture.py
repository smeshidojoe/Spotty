"""
Снимок области экрана через GDI BitBlt.

Строка снимает то, что под ней, ДО показа окна — поэтому своё окно в снимок не
попадает и исключать его из захвата (WDA_EXCLUDEFROMCAPTURE) не нужно. Как
следствие, строка остаётся видимой для скриншотов и записи экрана. Исключение
нужно только живому фону (ui/live_glass.py): он снимает экран при открытой
строке.

Координаты — физические пиксели виртуального рабочего стола: процесс Qt 6
работает в режиме Per-Monitor DPI Aware v2, и GDI отдаёт экран без
масштабирования.
"""

import ctypes
from ctypes import wintypes

from PySide6.QtGui import QImage

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP
_gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                    ctypes.POINTER(ctypes.c_void_p),
                                    wintypes.HANDLE, wintypes.DWORD]
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                          wintypes.DWORD]
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.DeleteDC.argtypes = [wintypes.HDC]
_user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]


def exclude_from_capture(hwnd, on=True):
    """
    Спрятать окно от снимков экрана и записи (Windows 10 2004+). На экране
    оно остаётся. Полупрозрачное окно, которое Qt рисует сам, эту настройку
    не принимает — только собранное через GPU. True — получилось.
    """
    return bool(_user32.SetWindowDisplayAffinity(
        hwnd, WDA_EXCLUDEFROMCAPTURE if on else WDA_NONE))


def grab(x, y, width, height):
    """Область экрана в физических пикселях -> QImage (RGB32) или None."""
    if width <= 0 or height <= 0:
        return None
    screen_dc = _user32.GetDC(None)
    mem_dc = _gdi32.CreateCompatibleDC(screen_dc)
    header = _BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(header)
    header.biWidth = width
    header.biHeight = -height                  # сверху вниз
    header.biPlanes = 1
    header.biBitCount = 32
    bits = ctypes.c_void_p()
    bitmap = _gdi32.CreateDIBSection(mem_dc, ctypes.byref(header), DIB_RGB_COLORS,
                                     ctypes.byref(bits), None, 0)
    try:
        if not bitmap or not bits:
            return None
        old = _gdi32.SelectObject(mem_dc, bitmap)
        # Без CAPTUREBLT: с ним на части машин на время снимка мигает курсор,
        # а при включённом DWM прозрачные окна попадают в снимок и так.
        ok = _gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, x, y, SRCCOPY)
        _gdi32.SelectObject(mem_dc, old)
        if not ok:
            return None
        buffer = (ctypes.c_ubyte * (width * height * 4)).from_address(bits.value)
        # BitBlt отдаёт BGRX — ровно Format_RGB32. copy() обязателен: буфер
        # принадлежит DIB-секции и умрёт вместе с ней ниже.
        return QImage(buffer, width, height, width * 4,
                      QImage.Format.Format_RGB32).copy()
    finally:
        if bitmap:
            _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(None, screen_dc)
