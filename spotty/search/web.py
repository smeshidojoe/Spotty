"""
Поиск в интернете — идея из ueli: в выдаче пункт «Искать в Google “запрос”»,
а если запрос похож на адрес сайта — ещё и «Открыть github.com».

Подсказки поисковика по мере ввода не берём: это отправка каждого нажатия
клавиши поисковику, а строку открывают и чтобы найти свои файлы.
"""

import ctypes
import re
import time
from ctypes import wintypes
from urllib.parse import quote_plus

# Порядок — как в настройках.
ENGINES = {
    "google":     "https://www.google.com/search?q={}",
    "yandex":     "https://yandex.ru/search/?text={}",
    "duckduckgo": "https://duckduckgo.com/?q={}",
    "bing":       "https://www.bing.com/search?q={}",
}
DEFAULT = "google"


def search_url(engine, query):
    return ENGINES.get(engine, ENGINES[DEFAULT]).format(quote_plus(query))


# --- похоже ли на адрес ----------------------------------------------------- #

_LINK = re.compile(
    r"^(?:[a-z][a-z0-9+.-]*://\S+"                       # со схемой — как есть
    r"|(?:localhost|\d{1,3}(?:\.\d{1,3}){3}"              # localhost, IP
    r"|(?:[a-z0-9-]+\.)+[a-z]{2,24})"                     # домен с зоной из букв
    r"(?::\d{1,5})?(?:[/?#]\S*)?)$", re.IGNORECASE)

# «report.txt» по форме — домен в зоне .txt. Такие окончания — файлы, если
# после имени нет пути: «notes.md» — файл, «notes.md/about» — уже сайт.
_FILE_EXT = {
    "txt", "md", "log", "ini", "cfg", "json", "xml", "csv", "yml", "yaml", "toml",
    "exe", "msi", "bat", "cmd", "ps1", "lnk", "dll", "sys", "py", "js", "ts",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "pdf", "rtf", "odt",
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "ico", "psd", "tif", "tiff",
    "mp3", "wav", "flac", "ogg", "m4a", "mp4", "mkv", "avi", "mov", "webm",
    "zip", "rar", "7z", "tar", "gz", "iso",
}


def as_link(text):
    """Адрес, который можно открыть в браузере, или None."""
    text = text.strip()
    if not text or " " in text or "\\" in text or not _LINK.match(text):
        return None
    if "://" in text:
        return text
    host = re.split(r"[/:?#]", text, maxsplit=1)[0].lower()
    tail = text[len(host):]
    if not tail.startswith("/") and host.rsplit(".", 1)[-1] in _FILE_EXT:
        return None
    # У локального адреса и IP шифрования обычно нет.
    local = host == "localhost" or host.replace(".", "").isdigit()
    return ("http://" if local else "https://") + text


# --- браузер по умолчанию --------------------------------------------------- #

_ASSOCF_IS_PROTOCOL = 0x00001000
_ASSOCSTR_EXECUTABLE = 2
_BROWSER_TTL = 60.0
_browser = (0.0, None)


def browser_exe():
    """
    exe браузера по умолчанию — ради его иконки у пунктов поиска. Спрашиваем
    систему не чаще раза в минуту: пункт строится на каждое нажатие.
    """
    global _browser
    checked, exe = _browser
    if time.monotonic() - checked < _BROWSER_TTL:
        return exe
    exe = None
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        hr = ctypes.windll.shlwapi.AssocQueryStringW(
            _ASSOCF_IS_PROTOCOL, _ASSOCSTR_EXECUTABLE, "https", "open",
            buf, ctypes.byref(size))
        if hr == 0 and buf.value:
            exe = buf.value
    except Exception:
        pass
    _browser = (time.monotonic(), exe)
    return exe
