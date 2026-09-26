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

    # Секции списка.
    "section.suggestions": {"ru": "Часто используемые", "en": "Suggestions"},
    "section.apps":        {"ru": "Приложения", "en": "Applications"},
    "section.files":       {"ru": "Файлы и папки", "en": "Files & Folders"},
    "section.calc":        {"ru": "Калькулятор", "en": "Calculator"},
    "section.commands":    {"ru": "Spotty", "en": "Spotty"},
    "section.terminal":    {"ru": "Терминал", "en": "Terminal"},
    "section.history":     {"ru": "Недавние команды", "en": "Recent Commands"},

    # Подпись справа в строке.
    "kind.app":      {"ru": "Приложение", "en": "Application"},
    "kind.file":     {"ru": "Файл", "en": "File"},
    "kind.folder":   {"ru": "Папка", "en": "Folder"},
    "kind.calc":     {"ru": "Калькулятор", "en": "Calculator"},
    "kind.command":  {"ru": "Команда", "en": "Command"},
    "kind.internal": {"ru": "Spotty", "en": "Spotty"},

    # Главное действие — в нижней полосе рядом с ↵.
    "primary.app":     {"ru": "Открыть приложение", "en": "Open Application"},
    "primary.file":    {"ru": "Открыть файл", "en": "Open File"},
    "primary.folder":  {"ru": "Открыть папку", "en": "Open Folder"},
    "primary.calc":    {"ru": "Скопировать ответ", "en": "Copy Answer"},
    "primary.command": {"ru": "Выполнить в терминале", "en": "Run in Terminal"},
    "primary.internal": {"ru": "Выполнить", "en": "Run"},
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
    "action.copy":        {"ru": "Скопировать", "en": "Copy"},
    "action.copy_expr":   {"ru": "Скопировать выражение с ответом",
                           "en": "Copy Expression and Answer"},
    "action.copy_command": {"ru": "Скопировать команду", "en": "Copy Command"},
    "action.forget_command": {"ru": "Удалить из истории", "en": "Remove from History"},

    # Пункты терминала.
    "terminal.run":   {"ru": "Выполнить «{cmd}»", "en": "Run “{cmd}”"},
    "terminal.sub":   {"ru": "в новом окне cmd", "en": "in a new cmd window"},

    # Встроенные команды.
    "internal.settings": {"ru": "Настройки Spotty", "en": "Spotty Settings"},
    "internal.update":   {"ru": "Проверить обновления", "en": "Check for Updates"},
    "internal.reindex":  {"ru": "Обновить список файлов и программ",
                          "en": "Refresh Files and Apps"},
    "internal.quit":     {"ru": "Выйти из Spotty", "en": "Quit Spotty"},
    "internal.install":  {"ru": "Установить обновление {version}",
                          "en": "Install Update {version}"},
    "internal.install_sub": {"ru": "Spotty перезапустится",
                             "en": "Spotty will restart"},

    # Всплывающие подсказки внизу экрана.
    "hud.copied":      {"ru": "Скопировано", "en": "Copied to Clipboard"},
    "hud.reindex":     {"ru": "Списки обновляются…", "en": "Refreshing…"},
    "hud.downloading": {"ru": "Скачиваю обновление…", "en": "Downloading update…"},
    "hud.launch_failed": {"ru": "Не удалось открыть", "en": "Couldn’t open it"},
    "hud.forgot":      {"ru": "Убрано из часто используемых",
                        "en": "Removed from Suggestions"},
    "hud.hidden":      {"ru": "Скрыто. Вернуть можно в настройках",
                        "en": "Hidden. You can bring it back in Settings"},

    "empty.nothing": {"ru": "Ничего не найдено", "en": "No results"},

    # Настройки.
    "settings.title":      {"ru": "Настройки", "en": "Settings"},
    "settings.hotkey":     {"ru": "Сочетание для вызова", "en": "Hotkey"},
    "settings.hotkey_sub": {"ru": "Нажмите и введите новое сочетание",
                            "en": "Click and press a new shortcut"},
    "settings.hotkey_wait": {"ru": "Нажмите сочетание…", "en": "Press keys…"},
    "settings.hotkey_busy": {"ru": "Сочетание занято другой программой",
                             "en": "Another app already uses this shortcut"},
    "settings.autostart":  {"ru": "Запускать вместе с Windows",
                            "en": "Launch at Startup"},
    "settings.glass":      {"ru": "Стеклянный фон", "en": "Glass Background"},
    "settings.glass_sub":  {"ru": "Размытие того, что под строкой",
                            "en": "Blurs what is behind the bar"},
    "settings.auto_update": {"ru": "Проверять обновления", "en": "Check for Updates"},
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
    "settings.version":    {"ru": "Версия {version}", "en": "Version {version}"},

    # Состояния обновления.
    "update.checking":    {"ru": "Проверяю…", "en": "Checking…"},
    "update.current":     {"ru": "Установлена последняя версия",
                           "en": "You’re up to date"},
    "update.available":   {"ru": "Доступна версия {version}",
                           "en": "Version {version} is available"},
    "update.downloading": {"ru": "Скачиваю {version}…", "en": "Downloading {version}…"},
    "update.ready":       {"ru": "Перезапускаю…", "en": "Restarting…"},
    "update.error":       {"ru": "Не удалось проверить", "en": "Couldn’t check"},
    "update.dev":         {"ru": "В режиме разработки не обновляется",
                           "en": "Updates are off in development mode"},

    # Трей.
    "tray.open":     {"ru": "Открыть Spotty", "en": "Open Spotty"},
    "tray.settings": {"ru": "Настройки", "en": "Settings"},
    "tray.update":   {"ru": "Проверить обновления", "en": "Check for Updates"},
    "tray.quit":     {"ru": "Выход", "en": "Quit"},
    "tray.welcome":  {"ru": "Spotty работает в трее. Нажмите {hotkey}, чтобы открыть строку.",
                      "en": "Spotty lives in the tray. Press {hotkey} to open it."},
    "tray.hotkey_busy": {"ru": "Сочетание {hotkey} занято другой программой. "
                               "Выберите другое в настройках.",
                         "en": "{hotkey} is taken by another app. "
                               "Pick another one in Settings."},
    "tray.update_available": {"ru": "Доступна новая версия {version}. "
                                    "Откройте строку, чтобы установить.",
                              "en": "Version {version} is available. "
                                    "Open Spotty to install it."},
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
