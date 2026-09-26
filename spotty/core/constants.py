import os
import sys

APP_NAME    = "Spotty"
APP_VERSION = "0.1.0"

GITHUB_REPO   = "SmeshidoJoe/Spotty"
DEVELOPER_URL = "https://github.com/SmeshidoJoe"

# Идентификатор для Windows: под ним группируются уведомления и панель задач.
APP_ID = "SmeshidoJoe.Spotty"

# Именованный мьютекс защиты от второго запуска (см. main.py). Тот же знает
# установщик — по нему он закрывает программу перед заменой exe.
INSTANCE_MUTEX = "Spotty-Single-Instance-Mutex"

# Локальный сокет, через который второй запуск просит первый показать строку.
IPC_NAME = "Spotty-IPC"

# В сборке PyInstaller ресурсы лежат во временной папке _MEIPASS, в разработке —
# в корне репозитория.
if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ASSETS_DIR = os.path.join(BASE_DIR, "assets")
APP_ICO    = os.path.join(ASSETS_DIR, "app.ico")

# Настройки и статистика запусков — в %APPDATA%\Spotty, кэш — в %LOCALAPPDATA%.
_ROAMING = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
_LOCAL = os.environ.get("LOCALAPPDATA") or _ROAMING
APP_DIR   = os.path.join(_ROAMING, APP_NAME)
CACHE_DIR = os.path.join(_LOCAL, APP_NAME)

CONFIG_PATH  = os.path.join(APP_DIR, "config.json")
USAGE_PATH   = os.path.join(APP_DIR, "usage.json")        # что и как часто запускали
HISTORY_PATH = os.path.join(APP_DIR, "commands.json")     # история команд терминала
HIDDEN_PATH  = os.path.join(APP_DIR, "hidden.json")       # скрытые из выдачи пункты
LOG_PATH     = os.path.join(APP_DIR, "spotty.log")
APPS_CACHE   = os.path.join(CACHE_DIR, "apps.json")       # список программ с прошлого раза
ICONS_DIR    = os.path.join(CACHE_DIR, "icons")           # иконки программ и типов файлов

# Первый ли это запуск — снимаем до того, как что-либо создаст APP_DIR.
IS_FIRST_RUN = not os.path.isdir(APP_DIR)
