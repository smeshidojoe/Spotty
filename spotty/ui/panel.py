"""
Сама строка: поле ввода, список результатов, нижняя полоса.

Показывается мгновенно, без анимации появления: её вызывают с клавиатуры
десятки раз в день, и любая задержка между нажатием и готовым полем читается
как тормоза (так же сделано в Raycast). По той же причине список обновляется
на каждое нажатие без задержки — поиск укладывается в пару миллисекунд.

Строка закрывается, когда теряет фокус, по Esc и после запуска пункта. Кроме
одного случая: пока ставится обновление, она заперта карточкой с прогрессом
(ui/update_card.py) — см. locked().
"""

import time

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QFont, QGuiApplication, QPainter, QPalette, QPen
from PySide6.QtWidgets import QLineEdit, QWidget

from ..actions import actions_for, primary_label, secondary_of
from ..core import winapi
from ..core.i18n import tr
from ..search.engine import COMMAND_PREFIX, WEB_PREFIX
from . import theme
from .actions_menu import ActionsMenu
from .backdrop import Backdrop
from .footer import Footer
from .results import ResultsView
from .settings import SettingsPage
from .update_card import UpdateCard
from .widgets import Button

# Виртуальные коды клавиш Windows — одинаковые при любой раскладке.
VK_C, VK_K, VK_N, VK_P, VK_COMMA = 0x43, 0x4B, 0x4E, 0x50, 0xBC

# Верх строки — на этой доле высоты экрана.
PANEL_TOP = 0.34

# Через сколько секунд после закрытия строка открывается с пустым запросом.
# Если вернуться быстрее, прежний запрос остаётся, выделенным целиком. Это
# только когда строку закрыли, ничего не выбрав (Esc, клик мимо): после запуска
# пункта запрос своё отработал, и строка всегда открывается пустой.
KEEP_QUERY_SECONDS = 60

# Стекло, включённое в настройках, считается после анимации переключателя (180 мс).
GLASS_AFTER_TOGGLE_MS = 200


class SearchField(QLineEdit):
    """Поле ввода без рамки и фона — фон рисует сама строка."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrame(False)
        self.setFont(theme.font(20))
        self.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.setStyleSheet(
            "QLineEdit { background: transparent; border: none; color: rgba(255,255,255,240);"
            " selection-background-color: rgba(10,132,255,150); }")
        self.setPlaceholderText(tr("search.placeholder"))
        # Цвет подсказки в пустом поле стилем не задаётся — только палитрой.
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, theme.TEXT_FAINT)
        self.setPalette(palette)


class Panel(QWidget):
    def __init__(self, app):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.app = app
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Spotty")
        self.mode = "search"
        self.modal = False            # открыт системный диалог — не закрываться
        self._hidden_at = 0.0
        self._clear_next = False      # пункт выполнен — в следующий раз пустой запрос
        self._last_text = None

        self.backdrop = Backdrop()
        self.backdrop.glass_enabled = app.config.get("glass")

        self.input = SearchField(self)
        self.input.textChanged.connect(self._on_text)
        self.input.installEventFilter(self)

        self.results = ResultsView(app.icons, self)
        self.results.activated_item.connect(lambda item: self.perform(item, None))
        self.results.current_changed.connect(self._on_current)

        self.settings = SettingsPage(app, self)
        self.settings.hide()

        self.footer = Footer(self)
        self.footer.primary_clicked.connect(lambda: self.perform(self.current(), None))
        self.footer.actions_clicked.connect(self.toggle_actions)
        self.footer.settings_clicked.connect(lambda: self.set_mode("settings"))
        self.footer.back_clicked.connect(lambda: self.set_mode("search"))

        self.menu = ActionsMenu(self)
        self.menu.triggered.connect(self._on_menu_action)

        # Скачанное в фоне обновление ждёт этой кнопки справа от поля ввода —
        # при каждом открытии строки, пока её не нажмут.
        self.update_ready = ""
        self.update_button = Button(tr("update.restart_button"), self, accent=True)
        self.update_button.clicked.connect(self.app.restart_and_update)
        self.update_button.hide()
        self.update_card = UpdateCard(self)

        self.resize(theme.PANEL_W + theme.SHADOW * 2, theme.PANEL_H + theme.SHADOW * 2)
        self._layout()

    # --- геометрия --------------------------------------------------------- #

    def panel_rect(self):
        s = theme.SHADOW
        return QRect(s, s, theme.PANEL_W, theme.PANEL_H)

    def _layout(self):
        panel = self.panel_rect()
        x, y, w = panel.x(), panel.y(), panel.width()
        right = 20
        if self.update_button.isVisibleTo(self):
            size = self.update_button.sizeHint()
            self.update_button.setGeometry(x + w - 16 - size.width(),
                                           y + (theme.SEARCH_H - size.height()) // 2,
                                           size.width(), size.height())
            right = 16 + size.width() + 12
        self.input.setGeometry(x + 52, y + 8, w - 52 - right, theme.SEARCH_H - 16)
        body = QRect(x + theme.LIST_PAD, y + theme.SEARCH_H + 1,
                     w - theme.LIST_PAD * 2,
                     theme.PANEL_H - theme.SEARCH_H - theme.FOOTER_H - 2)
        self.results.setGeometry(body)
        self.settings.setGeometry(QRect(x + 1, body.y(), w - 2, body.height()))
        self.footer.setGeometry(x + 1, panel.bottom() + 1 - theme.FOOTER_H, w - 2,
                                theme.FOOTER_H)

    # --- показ и скрытие --------------------------------------------------- #

    def warm_up(self):
        """
        Один невидимый прогон отрисовки при старте программы.

        Самый первый показ иначе тратит почти секунду: шейдеры, буферы стекла,
        тень, шрифты и кэш глифов создаются по первому требованию. Пусть это
        случится, пока строку никто не ждёт.
        """
        screen = QGuiApplication.primaryScreen()
        self.backdrop.warm_up(self.size(), self.panel_rect(), screen.devicePixelRatio())
        self._refresh(force=True)
        self.grab()

    def summon(self, mode="search"):
        """Показать строку на экране под курсором."""
        if self.isVisible():
            if not self.locked():
                self.set_mode(mode)
            self._activate()
            return
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.setGeometry(self._place(screen))

        # Стекло снимаем, пока окна ещё нет на экране — поэтому в снимок оно не
        # попадает само.
        self.backdrop.prepare(screen, self.geometry(), self.panel_rect())

        if self._clear_next or time.monotonic() - self._hidden_at > KEEP_QUERY_SECONDS:
            self.input.clear()
            self._clear_next = False
        self.set_mode(mode)
        self._refresh(force=True)
        self.input.selectAll()
        self.results.reset_mouse()
        self.show()
        self._activate()
        self.app.on_summon()

    def _place(self, screen):
        """
        Где стоит окно: по центру по горизонтали, верх строки — на трети
        высоты экрана. Там же, где поле ueli: взгляд туда привык.
        Если строка не влезает (низкий экран), поднимаем её.
        """
        full, area = screen.geometry(), screen.availableGeometry()
        w, h = self.width(), self.height()
        x = area.x() + (area.width() - w) // 2
        top = full.y() + int(full.height() * PANEL_TOP)
        top = min(top, area.bottom() - theme.PANEL_H - 16)
        top = max(top, area.y() + 16)
        return QRect(x, top - theme.SHADOW, w, h)

    def _activate(self):
        self.raise_()
        self.activateWindow()
        winapi.force_foreground(int(self.winId()))
        if self.locked():
            self.update_card.setFocus()
        elif self.mode == "search":
            self.input.setFocus()

    def dismiss(self, done=False):
        """
        Спрятать строку. done=True — пункт выполнен: запрос сотрётся.
        Стираем при следующем показе, а не здесь: сейчас главный поток занят
        запуском, и лишний поиск по пустому запросу ему ни к чему.
        """
        if done:
            self._clear_next = True
        if not self.isVisible() or self.locked():
            return
        self.menu.close_menu()
        self.settings.hotkey.stop()
        self.hide()
        self._hidden_at = time.monotonic()

    def hidden_recently(self, seconds=0.3):
        """Строку только что закрыла потеря фокуса — клик в трей не должен
        тут же открыть её снова."""
        return time.monotonic() - self._hidden_at < seconds

    def event(self, event):
        if event.type() == QEvent.Type.WindowDeactivate and not self.modal:
            # Даём Qt доиграть смену фокуса: при открытии собственного
            # диалога деактивация приходит раньше, чем выставится modal.
            QTimer.singleShot(0, self._dismiss_if_inactive)
        return super().event(event)

    def _dismiss_if_inactive(self):
        if not self.modal and not self.isActiveWindow():
            self.dismiss()

    # --- обновление -------------------------------------------------------- #

    def locked(self):
        """Идёт установка обновления: строку не закрыть и не потрогать."""
        return self.update_card.blocking()

    def show_update_card(self, version, fraction=0.0, restarting=False):
        if not self.isVisible():
            self.summon(self.mode)
        self.menu.close_menu()
        self.settings.hotkey.stop()
        self.update_card.start(version, fraction, restarting)
        self._sync_update_button()
        self._activate()

    def hide_update_card(self):
        """Установка сорвалась — строка снова обычная."""
        if not self.locked():
            return
        self.update_card.finish()
        self._sync_update_button()
        if self.isVisible():
            self._activate()

    def set_update_ready(self, version):
        """Скачано в фоне — справа в поле ввода появляется кнопка перезапуска."""
        self.update_ready = version
        self._sync_update_button()

    def _sync_update_button(self):
        show = bool(self.update_ready) and self.mode == "search" and not self.locked()
        if show != self.update_button.isVisibleTo(self):
            self.update_button.setVisible(show)
            self._layout()

    # --- режимы ------------------------------------------------------------ #

    def set_mode(self, mode):
        back_from_settings = self.isVisible() and self.mode != "search" and mode == "search"
        self.mode = mode
        self.menu.close_menu()
        searching = mode == "search"
        if back_from_settings:
            # В настройках могли вернуть скрытый пункт — выдача устарела.
            self._refresh(force=True)
        self.input.setVisible(searching)
        self.results.setVisible(searching)
        self.settings.setVisible(not searching)
        self._sync_update_button()
        self.footer.set_mode(mode)
        if searching:
            self.input.setFocus()
        else:
            self.settings.refresh()
            self.setFocus()
        self.update()

    def retranslate(self):
        self.input.setPlaceholderText(tr("search.placeholder"))
        self.update_button.setText(tr("update.restart_button"))
        # Страницу настроек проще собрать заново, чем переписывать каждую подпись.
        old = self.settings
        self.settings = SettingsPage(self.app, self)
        self._layout()
        self.settings.setVisible(old.isVisible())
        # Удалится только в цикле событий — до тех пор рисовалась бы поверх новой.
        old.hide()
        old.deleteLater()
        if self.settings.isVisible():
            self.settings.refresh()
        self._refresh(force=True)
        self.footer.update()
        self.update()

    def set_glass(self, on):
        self.backdrop.glass_enabled = on
        if not self.isVisible():
            return
        if on:
            # Включили на открытой строке: стекло считается из снимка, который
            # сделан перед показом, — прятать строку ради нового не нужно.
            # Считаем после того, как доедет ручка переключателя: если стекло
            # было выключено с запуска, первый расчёт поднимает OpenGL и
            # собирает шейдеры (до полсекунды), и ручка замерла бы на полпути.
            QTimer.singleShot(GLASS_AFTER_TOGGLE_MS, self._glass_on)
        else:
            self.backdrop.drop()
            self.update()

    def _glass_on(self):
        if self.backdrop.glass_enabled and self.isVisible():
            self.backdrop.rebuild()
            self.update()

    # --- поиск ------------------------------------------------------------- #

    def _on_text(self, _text):
        self._refresh()
        # Значок слева меняется между лупой и приглашением терминала.
        panel = self.panel_rect()
        self.update(QRect(panel.left(), panel.top(), 52, theme.SEARCH_H))

    def _refresh(self, force=False):
        text = self.input.text()
        if not force and text == self._last_text:
            return
        self._last_text = text
        self.menu.close_menu()
        # Пустой режим команды или интернета — не «ничего не найдено», а
        # подсказка, что вводить.
        if text.startswith(COMMAND_PREFIX):
            self.results.empty_text = tr("search.command_hint")
        elif text.startswith(WEB_PREFIX):
            self.results.empty_text = tr("search.web_hint")
        else:
            self.results.empty_text = tr("empty.nothing")
        self.results.set_sections(self.app.engine.search(text))
        self._on_current(self.results.current_item())

    def refresh_results(self):
        """
        Данные поменялись (новый список программ, индекс файлов) — пересобрать
        выдачу, не сбивая выделение: если выбранный пункт остался, он и выбран,
        а если пропал (его скрыли) — выбран тот, что встал на его место.
        """
        if not self.isVisible() or self.mode != "search":
            return
        current = self.current()
        row = self.results.currentIndex().row()
        self._refresh(force=True)
        if current is not None and not self.results.select_key(current.key or current.target):
            self.results.select_near(row)

    def current(self):
        return self.results.current_item()

    def _on_current(self, item):
        self.footer.set_primary(primary_label(item), item is not None)

    # --- действия ---------------------------------------------------------- #

    def perform(self, item, action_id):
        if item is None:
            return
        self.menu.close_menu()
        self.app.perform(item, action_id, self.input.text())

    def toggle_actions(self):
        if self.menu.is_open():
            self.menu.close_menu()
            return
        item = self.current()
        if item is None:
            return
        actions = actions_for(item, self.app.usage.frecency(item.key) > 0)
        footer = self.footer.geometry()
        self.menu.open(actions, footer.right() - 4, footer.top() + 2)

    def _on_menu_action(self, action_id):
        item = self.current()
        self.menu.close_menu()
        if item is not None:
            self.app.perform(item, action_id, self.input.text())

    # --- клавиатура -------------------------------------------------------- #

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            return self._key(event)
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        # Сюда попадают нажатия в режиме настроек (поле ввода скрыто).
        if event.key() == Qt.Key.Key_Escape:
            if not self.settings.hotkey.is_recording():
                self.set_mode("search")
            return
        super().keyPressEvent(event)

    def _key(self, event):
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        enter = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        # Буквенные сочетания сверяем по физической клавише: на русской
        # раскладке Ctrl+K приходит от Qt как Ctrl+Л.
        vk = event.nativeVirtualKey()

        def combo(letter_vk, qt_key):
            return ctrl and (vk == letter_vk or key == qt_key)

        if self.menu.is_open():
            if key == Qt.Key.Key_Escape or combo(VK_K, Qt.Key.Key_K):
                self.menu.close_menu()
            elif key == Qt.Key.Key_Up:
                self.menu.move_selection(-1)
            elif key == Qt.Key.Key_Down:
                self.menu.move_selection(1)
            elif enter:
                self.menu.activate()
            return True        # пока меню открыто, в поле ввода ничего не идёт

        if key == Qt.Key.Key_Escape:
            if self.input.text():
                self.input.clear()
            else:
                self.dismiss()
            return True
        if key == Qt.Key.Key_Down or combo(VK_N, Qt.Key.Key_N):
            self.results.move(1)
            return True
        if key == Qt.Key.Key_Up or combo(VK_P, Qt.Key.Key_P):
            self.results.move(-1)
            return True
        if key == Qt.Key.Key_PageDown:
            self.results.page(1)
            return True
        if key == Qt.Key.Key_PageUp:
            self.results.page(-1)
            return True
        if combo(VK_K, Qt.Key.Key_K):
            self.toggle_actions()
            return True
        if combo(VK_COMMA, Qt.Key.Key_Comma):
            self.set_mode("settings")
            return True
        if enter:
            item = self.current()
            if item is not None:
                actions = actions_for(item)
                action = secondary_of(actions) if ctrl else actions[0]
                self.perform(item, action.id)
            return True
        if shift and combo(VK_C, Qt.Key.Key_C):
            item = self.current()
            if item is not None:
                ids = [a.id for a in actions_for(item)]
                for wanted in ("copy_path", "copy_command", "copy_link", "copy"):
                    if wanted in ids:
                        self.perform(item, wanted)
                        break
            return True
        return False

    # --- отрисовка --------------------------------------------------------- #

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(self.panel_rect())
        self.backdrop.paint(p, self.panel_rect())

        # Линии под полем ввода и над нижней полосой.
        p.setPen(QPen(theme.HAIRLINE, 1))
        y = panel.top() + theme.SEARCH_H + 0.5
        p.drawLine(QPointF(panel.left() + 1, y), QPointF(panel.right() - 1, y))
        y = panel.bottom() - theme.FOOTER_H + 0.5
        p.drawLine(QPointF(panel.left() + 1, y), QPointF(panel.right() - 1, y))

        center_y = panel.top() + theme.SEARCH_H / 2
        if self.mode == "search":
            command = self.input.text().startswith(COMMAND_PREFIX)
            if command:
                # В режиме команды вместо лупы — приглашение терминала.
                p.setFont(theme.font(18, QFont.Weight.DemiBold))
                p.setPen(theme.TEXT_DIM)
                p.drawText(QRectF(panel.left() + 18, panel.top(), 24, theme.SEARCH_H),
                           Qt.AlignmentFlag.AlignCenter, "›_")
            else:
                theme.magnifier(p, QPointF(panel.left() + 30, center_y), 18, theme.TEXT_DIM)
        else:
            # Заголовок настроек со стрелкой «назад».
            p.setPen(QPen(theme.TEXT_DIM, 1.8, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            cx = panel.left() + 28
            p.drawPolyline([QPointF(cx + 4, center_y - 7), QPointF(cx - 3, center_y),
                            QPointF(cx + 4, center_y + 7)])
            p.setFont(theme.font(18, QFont.Weight.DemiBold))
            p.setPen(theme.TEXT)
            p.drawText(QRectF(panel.left() + 52, panel.top(), 400, theme.SEARCH_H),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       tr("settings.title"))

    def mousePressEvent(self, event):
        # Клик по стрелке «назад» в заголовке настроек.
        if self.mode == "settings":
            panel = self.panel_rect()
            if QRect(panel.left(), panel.top(), 52, theme.SEARCH_H).contains(
                    event.position().toPoint()):
                self.set_mode("search")
                return
        if self.menu.is_open() and not self.menu.geometry().contains(
                event.position().toPoint()):
            self.menu.close_menu()
        super().mousePressEvent(event)
