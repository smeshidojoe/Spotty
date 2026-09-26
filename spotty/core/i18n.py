"""
Строки интерфейса на двух языках.

`tr("ключ", имя=значение)` — строка на текущем языке с подстановкой {имя}.
Основной язык — английский, русский — второй. Пропущенный перевод подменяется
английским, а не падает.
"""

LANGUAGES = {"en": "English", "ru": "Русский"}
DEFAULT = "en"

_language = DEFAULT

STRINGS = {
    "search.placeholder": {"ru": "Поиск программ, файлов и команд…",
                           "en": "Search for apps, files and commands…"},
    "search.command_hint": {"ru": "Введите команду — она выполнится в новом окне cmd",
                            "en": "Type a command — it runs in a new cmd window"},
    "search.web_hint": {"ru": "Введите, что искать в интернете",
                        "en": "Type what to search for on the web"},

    # Секции списка.
    "section.suggestions": {"ru": "Часто используемые", "en": "Suggestions"},
    "section.apps":        {"ru": "Приложения", "en": "Applications"},
    "section.files":       {"ru": "Файлы и папки", "en": "Files & Folders"},
    "section.calc":        {"ru": "Калькулятор", "en": "Calculator"},
    "section.commands":    {"ru": "Spotty", "en": "Spotty"},
    "section.terminal":    {"ru": "Терминал", "en": "Terminal"},
    "section.web":         {"ru": "Интернет", "en": "Web"},
    "section.history":     {"ru": "Недавние команды", "en": "Recent Commands"},

    # Подпись справа в строке.
    "kind.app":      {"ru": "Приложение", "en": "Application"},
    "kind.file":     {"ru": "Файл", "en": "File"},
    "kind.folder":   {"ru": "Папка", "en": "Folder"},
    "kind.calc":     {"ru": "Калькулятор", "en": "Calculator"},
    "kind.command":  {"ru": "Команда", "en": "Command"},
    "kind.internal": {"ru": "Spotty", "en": "Spotty"},
    "kind.web":      {"ru": "Поиск в интернете", "en": "Web Search"},
    "kind.link":     {"ru": "Ссылка", "en": "Link"},

    # Главное действие — в нижней полосе рядом с ↵.
    "primary.app":     {"ru": "Открыть приложение", "en": "Open Application"},
    "primary.file":    {"ru": "Открыть файл", "en": "Open File"},
    "primary.folder":  {"ru": "Открыть папку", "en": "Open Folder"},
    "primary.calc":    {"ru": "Скопировать ответ", "en": "Copy Answer"},
    "primary.command": {"ru": "Выполнить в терминале", "en": "Run in Terminal"},
    "primary.internal": {"ru": "Выполнить", "en": "Run"},
    "primary.web":     {"ru": "Искать в интернете", "en": "Search the Web"},
    "primary.link":    {"ru": "Открыть ссылку", "en": "Open Link"},
    "footer.actions":  {"ru": "Действия", "en": "Actions"},
    "footer.back":     {"ru": "Назад", "en": "Back"},

    # Меню действий (Ctrl+K).
    "action.open":        {"ru": "Открыть", "en": "Open"},
    "action.run":         {"ru": "Выполнить", "en": "Run"},
    "action.admin":       {"ru": "Запустить от имени администратора",
                           "en": "Run as Administrator"},
    "action.reveal":      {"ru": "Показать в папке", "en": "Show in Folder"},
    "action.copy_path":   {"ru": "Скопировать путь", "en": "Copy Path"},
    "action.copy_name":   {"ru": "Скопировать имя", "en": "Copy Name"},
    "action.terminal_here": {"ru": "Открыть терминал здесь",
                             "en": "Open Terminal Here"},
    "action.forget":      {"ru": "Убрать из часто используемых",
                           "en": "Remove from Suggestions"},
    "action.hide":        {"ru": "Скрыть из результатов", "en": "Hide from Results"},
    "action.hide_folder": {"ru": "Скрыть папку со всем содержимым",
                           "en": "Hide Folder and Its Contents"},
    "action.copy":        {"ru": "Скопировать", "en": "Copy"},
    "action.copy_expr":   {"ru": "Скопировать выражение с ответом",
                           "en": "Copy Expression and Answer"},
    "action.copy_command": {"ru": "Скопировать команду", "en": "Copy Command"},
    "action.forget_command": {"ru": "Удалить из истории", "en": "Remove from History"},
    "action.open_browser": {"ru": "Открыть в браузере", "en": "Open in Browser"},
    "action.copy_link":   {"ru": "Скопировать ссылку", "en": "Copy Link"},

    # Пункты терминала.
    "terminal.run":   {"ru": "Выполнить «{cmd}»", "en": "Run “{cmd}”"},
    "terminal.sub":   {"ru": "в новом окне cmd", "en": "in a new cmd window"},

    # Поиск в интернете. У каждого поисковика своя фраза: по-русски «в Яндексе»,
    # но «в Google» — склонение одной подстановкой не собрать.
    "web.open":              {"ru": "Открыть {site}", "en": "Open {site}"},
    "web.search.google":     {"ru": "Искать «{query}» в Google",
                              "en": "Search Google for “{query}”"},
    "web.search.yandex":     {"ru": "Искать «{query}» в Яндексе",
                              "en": "Search Yandex for “{query}”"},
    "web.search.duckduckgo": {"ru": "Искать «{query}» в DuckDuckGo",
                              "en": "Search DuckDuckGo for “{query}”"},
    "web.search.bing":       {"ru": "Искать «{query}» в Bing",
                              "en": "Search Bing for “{query}”"},
    "web.engine.google":     {"ru": "Google", "en": "Google"},
    "web.engine.yandex":     {"ru": "Яндекс", "en": "Yandex"},
    "web.engine.duckduckgo": {"ru": "DuckDuckGo", "en": "DuckDuckGo"},
    "web.engine.bing":       {"ru": "Bing", "en": "Bing"},

    # Встроенные команды.
    "internal.settings": {"ru": "Настройки Spotty", "en": "Spotty Settings"},
    "internal.update":   {"ru": "Проверить обновления", "en": "Check for Updates"},
    "internal.reindex":  {"ru": "Обновить список файлов и программ",
                          "en": "Refresh Files and Apps"},
    "internal.quit":     {"ru": "Выйти из Spotty", "en": "Quit Spotty"},
    "internal.install":  {"ru": "Установить обновление {version}",
                          "en": "Install Update {version}"},
    "internal.install_sub": {"ru": "Spotty скачает её и перезапустится",
                             "en": "Spotty will download it and restart"},
    "internal.restart":  {"ru": "Перезапустить и обновить до {version}",
                          "en": "Restart and Update to {version}"},
    "internal.restart_sub": {"ru": "Обновление уже скачано",
                             "en": "The update is already downloaded"},

    # Всплывающие подсказки внизу экрана.
    "hud.copied":      {"ru": "Скопировано", "en": "Copied to Clipboard"},
    "hud.reindex":     {"ru": "Списки обновляются…", "en": "Refreshing…"},
    "hud.launch_failed": {"ru": "Не удалось открыть", "en": "Couldn’t open it"},
    "hud.forgot":      {"ru": "Убрано из часто используемых",
                        "en": "Removed from Suggestions"},
    "hud.hidden":      {"ru": "Скрыто. Вернуть можно в настройках",
                        "en": "Hidden. You can bring it back in Settings"},
    "hud.hidden_folder": {"ru": "Папка скрыта вместе с содержимым",
                          "en": "Folder and its contents are hidden"},

    "empty.nothing": {"ru": "Ничего не найдено", "en": "No results"},

    # Настройки.
    "settings.title":      {"ru": "Настройки", "en": "Settings"},
    "settings.hotkey":     {"ru": "Сочетание для вызова", "en": "Hotkey"},
    "settings.hotkey_sub": {"ru": "Нажмите и введите новое сочетание",
                            "en": "Click and press a new shortcut"},
    "settings.hotkey_wait": {"ru": "Нажмите сочетание…", "en": "Press keys…"},
    "settings.hotkey_busy": {"ru": "Сочетание занято другой программой",
                             "en": "Another app already uses this shortcut"},
    "settings.fullscreen_guard": {"ru": "Не открывать поверх полноэкранных программ",
                                  "en": "Ignore in Full-Screen Apps"},
    "settings.fullscreen_guard_sub": {
        "ru": "Сочетание достаётся игре или плееру. Браузеров это не касается",
        "en": "Games and players get the shortcut. Browsers are not affected"},
    "settings.autostart":  {"ru": "Запускать вместе с Windows",
                            "en": "Launch at Startup"},
    "settings.autostart_dev": {"ru": "Работает только в установленной программе",
                               "en": "Works in the installed app only"},
    "settings.glass":      {"ru": "Стеклянный фон", "en": "Glass Background"},
    "settings.glass_sub":  {"ru": "Размытие того, что под строкой",
                            "en": "Blurs what is behind the bar"},
    "settings.web_engine": {"ru": "Поиск в интернете", "en": "Web Search"},
    "settings.web_engine_sub": {"ru": "Или начните запрос с ?",
                                "en": "Or start your query with ?"},
    "settings.scan_drives": {"ru": "Программы на всех дисках",
                             "en": "Apps on All Drives"},
    "settings.scan_drives_sub": {"ru": "Портативные программы и игры, которых нет в «Пуске»",
                                 "en": "Portable apps and games that aren’t in Start"},
    "settings.scan_drives_busy": {"ru": "Просматриваю диски…",
                                  "en": "Looking through drives…"},
    "settings.scan_drives_count": {"ru": "Найдено вне «Пуска»: {count}",
                                   "en": "Found outside Start: {count}"},
    "settings.auto_update": {"ru": "Проверять обновления", "en": "Check for Updates"},
    "settings.update_mode": {"ru": "Новая версия", "en": "New Versions"},
    "settings.update_mode.notify": {"ru": "Сообщать", "en": "Notify Me"},
    "settings.update_mode.background": {"ru": "Скачивать в фоне",
                                        "en": "Download in Background"},
    "settings.update_mode_sub.notify": {
        "ru": "Уведомление в углу, установка — когда скажете",
        "en": "A notice in the corner, install when you choose"},
    "settings.update_mode_sub.background": {
        "ru": "Скачается само, в строке появится кнопка",
        "en": "Downloads on its own, then a button appears"},
    "settings.language":   {"ru": "Язык", "en": "Language"},
    "settings.folders":    {"ru": "Папки для поиска файлов",
                            "en": "Folders to Search"},
    "settings.add_folder": {"ru": "Добавить папку", "en": "Add Folder"},
    "settings.no_folders": {"ru": "Папок нет — файлы не ищутся",
                            "en": "No folders — file search is off"},
    "settings.files_count": {"ru": "В индексе: {count}", "en": "Indexed: {count}"},
    "settings.hidden":     {"ru": "Скрытые из результатов", "en": "Hidden from Results"},
    "settings.no_hidden":  {"ru": "Ничего не скрыто. Скрыть пункт — Ctrl+K в списке",
                            "en": "Nothing hidden. To hide an item, press Ctrl+K on it"},
    "settings.unhide":     {"ru": "Вернуть", "en": "Unhide"},
    "settings.check_now":  {"ru": "Проверить", "en": "Check"},
    "settings.install":    {"ru": "Установить", "en": "Install"},
    "settings.restart":    {"ru": "Перезапустить", "en": "Restart"},
    "settings.version":    {"ru": "Версия {version}", "en": "Version {version}"},

    # Состояния обновления.
    "update.checking":    {"ru": "Проверяю…", "en": "Checking…"},
    "update.current":     {"ru": "Установлена последняя версия",
                           "en": "You’re up to date"},
    "update.available":   {"ru": "Доступна версия {version}",
                           "en": "Version {version} is available"},
    "update.downloading": {"ru": "Скачиваю {version}… {percent}%",
                           "en": "Downloading {version}… {percent}%"},
    "update.ready":       {"ru": "Версия {version} скачана — перезапустите",
                           "en": "Version {version} is downloaded — restart to update"},
    "update.error":       {"ru": "Не удалось проверить", "en": "Couldn’t check"},
    "update.failed":      {"ru": "Не удалось скачать", "en": "Couldn’t download"},
    "update.dev":         {"ru": "В режиме разработки не обновляется",
                           "en": "Updates are off in development mode"},
    # Карточка установки в строке и кнопка в поле ввода.
    "update.card":        {"ru": "Обновление до {version}", "en": "Updating to {version}"},
    "update.card_downloading": {"ru": "Скачиваю…", "en": "Downloading…"},
    "update.restarting":  {"ru": "Перезапускаю…", "en": "Restarting…"},
    "update.restart_button": {"ru": "Перезапустить и обновить",
                              "en": "Restart and Update"},

    # Плашка в углу экрана.
    "toast.welcome":      {"ru": "Spotty работает в трее", "en": "Spotty lives in the tray"},
    "toast.welcome_sub":  {"ru": "Нажмите {hotkey}, чтобы открыть строку",
                           "en": "Press {hotkey} to open the search bar"},
    "toast.hotkey_busy":  {"ru": "Сочетание {hotkey} занято",
                           "en": "{hotkey} is taken by another app"},
    "toast.hotkey_busy_sub": {"ru": "Нажмите, чтобы выбрать другое",
                              "en": "Click to pick another shortcut"},
    "toast.checking":     {"ru": "Проверяю обновления…", "en": "Checking for updates…"},
    "toast.current":      {"ru": "Установлена последняя версия",
                           "en": "You’re on the latest version"},
    "toast.check_failed": {"ru": "Не удалось проверить обновления",
                           "en": "Couldn’t check for updates"},
    "toast.available":    {"ru": "Вышла версия {version}", "en": "Version {version} is out"},
    "toast.available_sub": {"ru": "Нажмите, чтобы обновить", "en": "Click to update"},
    "toast.downloading":  {"ru": "Скачиваю версию {version}",
                           "en": "Downloading version {version}"},
    "toast.downloading_sub": {"ru": "Пользуйтесь Spotty как обычно",
                              "en": "Keep using Spotty as usual"},
    "toast.ready":        {"ru": "Версия {version} скачана", "en": "Version {version} is ready"},
    "toast.ready_sub":    {"ru": "Нажмите, чтобы перезапустить и обновить",
                           "en": "Click to restart and update"},
    "toast.download_failed": {"ru": "Не удалось скачать обновление",
                              "en": "Couldn’t download the update"},
    "toast.download_failed_sub": {"ru": "Проверьте интернет и попробуйте ещё раз",
                                  "en": "Check your connection and try again"},
    "toast.install_failed": {"ru": "Не удалось установить обновление",
                             "en": "Couldn’t install the update"},
    "toast.install_failed_sub": {"ru": "Spotty продолжает работать в прежней версии",
                                 "en": "Spotty keeps running the current version"},

    # Трей.
    "tray.open":     {"ru": "Открыть Spotty", "en": "Open Spotty"},
    "tray.settings": {"ru": "Настройки", "en": "Settings"},
    "tray.update":   {"ru": "Проверить обновления", "en": "Check for Updates"},
    "tray.quit":     {"ru": "Выход", "en": "Quit"},
}


def set_language(code):
    """Неизвестный код (например, «auto» из старых настроек) — английский."""
    global _language
    _language = code if code in LANGUAGES else DEFAULT


def language():
    return _language


def tr(key, **kwargs):
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(_language) or entry.get("en") or key
    return text.format(**kwargs) if kwargs else text
