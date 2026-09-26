"""
Сборка выдачи: запрос -> секции с пунктами.

Порядок секций постоянный — калькулятор, приложения, команды Spotty, файлы,
терминал, — чтобы глаз знал, где что искать. Внутри секции — по оценке
совпадения с поправкой на то, как часто пункт запускали.
"""

import os
from dataclasses import dataclass, field

from ..core.i18n import tr
from . import calc, matcher

COMMAND_PREFIX = ">"
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


def app_item(app):
    return Item("app", app["name"], target=app["target"], path=app.get("path", ""),
                key="app:" + app["name"].casefold(),
                icon="app:" + app["target"], icon_source=app["target"])


def path_item(path, is_dir=None):
    if is_dir is None:
        is_dir = os.path.isdir(path)
    name = os.path.basename(path.rstrip("\\/")) or path
    parent = os.path.dirname(path.rstrip("\\/"))
    home = os.path.expanduser("~")
    if parent.lower().startswith(home.lower()):
        parent = "~" + parent[len(home):]
    if is_dir:
        icon, source = "folder", path
    else:
        ext = os.path.splitext(path)[1].lower()
        icon = ("file:" + path) if ext in _OWN_ICON or not ext else ("ext:" + ext)
        source = path
    return Item("folder" if is_dir else "file", name, subtitle=parent, target=path,
                path=path, key="file:" + path, icon=icon, icon_source=source)


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
        self.update_version = ""          # не пусто — есть что установить

    # --- вспомогательное --------------------------------------------------- #

    def _internal_items(self):
        items = [Item("internal", tr("internal." + name), target=name,
                      icon="builtin:spotty") for name in INTERNAL]
        if self.update_version:
            items.insert(0, self._install_item())
        return items

    def _install_item(self):
        return Item("internal", tr("internal.install", version=self.update_version),
                    subtitle=tr("internal.install_sub"), target="install",
                    icon="builtin:spotty")

    def _visible_apps(self):
        """(ключ, программа) без скрытых."""
        for app in self.catalog.apps:
            key = "app:" + app["name"].casefold()
            if key not in self.hidden:
                yield key, app

    def _files(self, query, alt):
        # Скрытые выкидываем после поиска, поэтому просим с запасом — иначе
        # каждый скрытый файл съедал бы место в выдаче.
        limit = _FILES_LIMIT + len(self.hidden)
        found = self.files.search(query, limit)
        if not found and alt:
            found = self.files.search(alt, limit)
        items = [path_item(p, d) for _, p, d in found]
        return [i for i in items if i.key not in self.hidden][:_FILES_LIMIT]

    # --- выдача ------------------------------------------------------------ #

    def search(self, text):
        """[(заголовок секции, [Item, ...]), ...]"""
        if text.startswith(COMMAND_PREFIX):
            return self._commands(text[len(COMMAND_PREFIX):].strip())
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
            elif key.startswith("file:") and key not in self.hidden:
                path = key[5:]
                if os.path.exists(path):
                    suggestions.append(path_item(path))
            if len(suggestions) >= _SUGGESTIONS:
                break
        if suggestions:
            sections.append((tr("section.suggestions"), suggestions))
        sections.append((tr("section.apps"), [app_item(a) for a in apps.values()]))
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
