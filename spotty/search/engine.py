"""
Сборка выдачи: запрос -> секции с пунктами.

Порядок секций постоянный — калькулятор, приложения, команды Spotty, файлы,
интернет, терминал, — чтобы глаз знал, где что искать. Внутри секции — по оценке
совпадения с поправкой на то, как часто пункт запускали.
"""

import os
from dataclasses import dataclass, field

from ..core.i18n import tr
from . import calc, matcher, web

COMMAND_PREFIX = ">"
WEB_PREFIX = "?"
_SUGGESTIONS = 6
_APPS_LIMIT = 9
_FILES_LIMIT = 10
# Расширения, у которых своя иконка у каждого файла, а не общая на тип.
_OWN_ICON = (".exe", ".lnk", ".ico", ".url", ".msc", ".cpl", ".appref-ms")


@dataclass
class Item:
    kind: str                 # app | file | folder | calc | command | internal
    title: str
    subtitle: str = ""
    target: str = ""          # что запускать: путь, shell:AppsFolder\..., команда
    path: str = ""            # настоящий путь на диске, если есть
    key: str = ""             # под этим ключом пункт живёт в статистике запусков
    icon: str = ""            # ключ иконки
    icon_source: str = ""     # откуда оболочке брать иконку
    extra: dict = field(default_factory=dict)


def _short(folder):
    """Папка для подписи: домашняя — как «~»."""
    home = os.path.expanduser("~")
    if folder.lower().startswith(home.lower()):
        return "~" + folder[len(home):]
    return folder


def app_item(app):
    # У найденной на диске программы подписываем папку: «Game» из двух разных
    # папок иначе не различить, и видно, откуда она взялась.
    subtitle = _short(os.path.dirname(app["path"])) if app.get("kind") == "exe" else ""
    return Item("app", app["name"], subtitle=subtitle, target=app["target"],
                path=app.get("path", ""), key="app:" + app["name"].casefold(),
                icon="app:" + app["target"], icon_source=app["target"])


def path_item(path, is_dir=None):
    if is_dir is None:
        is_dir = os.path.isdir(path)
    name = os.path.basename(path.rstrip("\\/")) or path
    parent = _short(os.path.dirname(path.rstrip("\\/")))
    if is_dir:
        icon, source = "folder", path
    else:
        ext = os.path.splitext(path)[1].lower()
        icon = ("file:" + path) if ext in _OWN_ICON or not ext else ("ext:" + ext)
        source = path
    return Item("folder" if is_dir else "file", name, subtitle=parent, target=path,
                path=path, key="file:" + path, icon=icon, icon_source=source)


def _web_icon():
    exe = web.browser_exe()
    return ("exe:" + exe.lower(), exe) if exe else ("builtin:web", "")


def web_items(text, engine):
    """«Открыть сайт», если запрос похож на адрес, и «Искать в …»."""
    icon, source = _web_icon()
    items = []
    link = web.as_link(text)
    if link:
        items.append(Item("link", tr("web.open", site=text), subtitle=link, target=link,
                          icon=icon, icon_source=source))
    engine = engine if engine in web.ENGINES else web.DEFAULT
    items.append(Item("web", tr("web.search." + engine, query=text),
                      target=web.search_url(engine, text), icon=icon, icon_source=source))
    return items


def command_item(command):
    comspec = os.environ.get("ComSpec") or r"C:\Windows\System32\cmd.exe"
    return Item("command", tr("terminal.run", cmd=command), subtitle=tr("terminal.sub"),
                target=command, icon="exe:cmd", icon_source=comspec)


INTERNAL = ("settings", "update", "reindex", "quit")


class SearchEngine:
    def __init__(self, catalog, files, usage, history, hidden):
        self.catalog = catalog
        self.files = files
        self.usage = usage
        self.history = history
        self.hidden = hidden
        self.web_engine = web.DEFAULT
        self.update_version = ""          # не пусто — есть что установить
        self.update_ready = False         # уже скачано — осталось перезапуститься

    # --- вспомогательное --------------------------------------------------- #

    def _internal_items(self):
        items = [Item("internal", tr("internal." + name), target=name,
                      icon="builtin:spotty") for name in INTERNAL]
        if self.update_version:
            items.insert(0, self._install_item())
        return items

    def _install_item(self):
        if self.update_ready:
            return Item("internal", tr("internal.restart", version=self.update_version),
                        subtitle=tr("internal.restart_sub"), target="restart",
                        icon="builtin:spotty")
        return Item("internal", tr("internal.install", version=self.update_version),
                    subtitle=tr("internal.install_sub"), target="install",
                    icon="builtin:spotty")

    def _visible_apps(self, found=True):
        """(ключ, программа) без скрытых. found — и найденные на дисках."""
        for app in self.catalog.apps:
            key = "app:" + app["name"].casefold()
            if key not in self.hidden:
                yield key, app
        if not found:
            return
        for app in self.catalog.found:
            key = "app:" + app["name"].casefold()
            # Скрытая папка прячет и программы, найденные в ней.
            if key not in self.hidden and not self.hidden.hides_path(app["path"]):
                yield key, app

    def _files(self, query, alt):
        skip = self.hidden.hides_path if len(self.hidden) else None
        found = self.files.search(query, _FILES_LIMIT, skip)
        if not found and alt:
            found = self.files.search(alt, _FILES_LIMIT, skip)
        return [path_item(p, d) for _, p, d in found]

    # --- выдача ------------------------------------------------------------ #

    def search(self, text):
        """[(заголовок секции, [Item, ...]), ...]"""
        if text.startswith(COMMAND_PREFIX):
            return self._commands(text[len(COMMAND_PREFIX):].strip())
        if text.startswith(WEB_PREFIX):
            # «?» — только интернет: пункт поиска сразу первый, не надо
            # листать до него мимо программ и файлов.
            query = text[len(WEB_PREFIX):].strip()
            return [(tr("section.web"), web_items(query, self.web_engine))] if query else []
        query = " ".join(text.lower().split())
        if not query:
            return self._home()

        sections = []
        answer = calc.evaluate(text)
        if answer is not None:
            sections.append((tr("section.calc"), [Item(
                "calc", answer, subtitle=text.strip().rstrip("=").strip() + " =",
                target=answer, icon="builtin:calc")]))

        alt = matcher.other_layout(query)
        chosen = self.usage.chosen_for(query)
        ranked = []
        for key, app in self._visible_apps():
            score = matcher.best_score(query, alt, app["name"])
            if app.get("alias"):
                score = max(score, matcher.best_score(query, alt, app["alias"]) * 0.98)
            if score <= 0:
                continue
            if app.get("kind") == "exe":
                score -= 4          # при равном совпадении программа из «Пуска» выше
            score += self.usage.frecency(key) * 6
            if key == chosen:
                score += 40
            ranked.append((score, app["name"].casefold(), app))
        ranked.sort(key=lambda r: (-r[0], r[1]))
        if ranked:
            sections.append((tr("section.apps"),
                             [app_item(a) for _, _, a in ranked[:_APPS_LIMIT]]))

        internal = [(matcher.best_score(query, alt, i.title), i)
                    for i in self._internal_items()]
        internal = [i for s, i in sorted(internal, key=lambda r: -r[0]) if s > 45]
        if internal:
            sections.append((tr("section.commands"), internal))

        if len(query) >= 2:
            found = self._files(query, alt)
            if found:
                sections.append((tr("section.files"), found))

        sections.append((tr("section.web"), web_items(text.strip(), self.web_engine)))
        sections.append((tr("section.terminal"), [command_item(text.strip())]))
        return sections

    def _home(self):
        """Пустой запрос: частые пункты и все приложения по алфавиту."""
        sections = []
        apps = dict(self._visible_apps())
        suggestions = [self._install_item()] if self.update_version else []
        for key in self.usage.top(_SUGGESTIONS * 2):
            if key in apps:
                suggestions.append(app_item(apps[key]))
            elif key.startswith("file:"):
                path = key[5:]
                if not self.hidden.hides_path(path) and os.path.exists(path):
                    suggestions.append(path_item(path))
            if len(suggestions) >= _SUGGESTIONS:
                break
        if suggestions:
            sections.append((tr("section.suggestions"), suggestions))
        sections.append((tr("section.apps"),
                         [app_item(a) for _, a in self._visible_apps(found=False)]))
        return sections

    def _commands(self, command):
        sections = []
        if command:
            sections.append((tr("section.terminal"), [command_item(command)]))
        recent = [c for c in self.history.matching(command) if c != command]
        if recent:
            items = []
            for c in recent:
                item = command_item(c)
                item.title, item.subtitle = c, ""
                item.extra["history"] = True
                items.append(item)
            sections.append((tr("section.history"), items))
        return sections
