"""
Что можно сделать с пунктом выдачи.

Первое действие — по Enter, второе — по Ctrl+Enter, остальные — из меню
Ctrl+K. Порядок в списке и есть приоритет.
"""

import os
from dataclasses import dataclass

from .core.i18n import tr

ENTER = "↵"
PRIMARY = (ENTER,)
SECONDARY = ("Ctrl", ENTER)
COPY = ("Ctrl", "Shift", "C")


@dataclass
class Action:
    id: str
    title: str
    keys: tuple = ()          # подписи клавиш для меню


def secondary_of(actions):
    """
    Действие для Ctrl+Enter — то, что подписано этим сочетанием, а не второе
    по списку: у программы из Магазина нет «от администратора», и вторым
    оказалось бы «Скрыть». Нет такого — главное.
    """
    return next((a for a in actions if a.keys == SECONDARY), actions[0])


def actions_for(item, has_usage=False):
    kind = item.kind
    primary, secondary, copy = PRIMARY, SECONDARY, COPY
    if kind == "app":
        actions = [Action("open", tr("action.open"), primary)]
        # У приложения из Магазина нет файла: ни администратора, ни папки.
        if item.path or item.target.lower().endswith(".lnk"):
            actions.append(Action("admin", tr("action.admin"), secondary))
        if item.path and os.path.exists(item.path):
            actions.append(Action("reveal", tr("action.reveal")))
            actions.append(Action("copy_path", tr("action.copy_path"), copy))
        if has_usage:
            actions.append(Action("forget", tr("action.forget")))
        actions.append(Action("hide", tr("action.hide")))
        return actions
    if kind in ("file", "folder"):
        actions = [Action("open", tr("action.open"), primary),
                   Action("reveal", tr("action.reveal"), secondary),
                   Action("copy_path", tr("action.copy_path"), copy),
                   Action("copy_name", tr("action.copy_name")),
                   Action("terminal_here", tr("action.terminal_here"))]
        if kind == "file" and item.path.lower().endswith((".exe", ".bat", ".cmd", ".lnk")):
            actions.insert(2, Action("admin", tr("action.admin")))
        if has_usage:
            actions.append(Action("forget", tr("action.forget")))
        actions.append(Action("hide", tr("action.hide_folder" if kind == "folder"
                                         else "action.hide")))
        return actions
    if kind in ("web", "link"):
        return [Action("open", tr("action.open_browser"), primary),
                Action("copy_link", tr("action.copy_link"), copy)]
    if kind == "calc":
        return [Action("copy", tr("action.copy"), primary),
                Action("copy_expr", tr("action.copy_expr"), secondary)]
    if kind == "command":
        actions = [Action("run", tr("action.run"), primary),
                   Action("admin", tr("action.admin"), secondary),
                   Action("copy_command", tr("action.copy_command"), copy)]
        if item.extra.get("history"):
            actions.append(Action("forget_command", tr("action.forget_command")))
        return actions
    return [Action("run", tr("action.run"), primary)]


def primary_label(item):
    return tr("primary." + item.kind) if item else ""
