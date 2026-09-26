"""Журнал в %APPDATA%\\Spotty\\spotty.log — у exe без консоли другого способа
узнать, что пошло не так, нет."""

import datetime
import os
import traceback

from .constants import LOG_PATH

_MAX_BYTES = 512 * 1024


def log(*parts):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        # Файл не растёт бесконечно: перевалил за предел — начинаем заново.
        if os.path.isfile(LOG_PATH) and os.path.getsize(LOG_PATH) > _MAX_BYTES:
            os.remove(LOG_PATH)
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (stamp, " ".join(str(p) for p in parts)))
    except OSError:
        pass


def exc(where):
    log("ошибка в", where + ":\n" + traceback.format_exc())
