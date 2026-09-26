"""
Генератор картинок проекта:

    assets/app.ico         — иконка exe и трея (9 размеров)
    assets/icon.png        — иконка 1024x1024 для страницы на GitHub
    assets/screenshot.png  — строка поверх обоев, для README

Иконку рисует тот же код, что и в рантайме (spotty/ui/appicon.py), поэтому
файл и программа не разъезжаются. Каждый размер ico рендерится отдельно, а не
ужимается из 1024: ужатая версия на 16x16 превращается в кашу.

На скриншоте только стандартные программы Windows, файлы не ищутся — чтобы в
картинку не попало ничего с машины того, кто её собирает.

    python tools/make_assets.py
    (нужен Pillow: pip install pillow — только для записи .ico)
"""

import io
import os
import random
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets")
sys.path.insert(0, ROOT)

# Настройки, кэш и статистика скриншота — во временной папке, не в профиле.
import spotty.core.constants as C  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="spotty-assets-")
C.APP_DIR = _TMP
C.CONFIG_PATH = os.path.join(_TMP, "config.json")
C.USAGE_PATH = os.path.join(_TMP, "usage.json")
C.HISTORY_PATH = os.path.join(_TMP, "commands.json")
C.HIDDEN_PATH = os.path.join(_TMP, "hidden.json")
C.LOG_PATH = os.path.join(_TMP, "spotty.log")
C.APPS_CACHE = os.path.join(_TMP, "apps.json")
C.PROGRAMS_CACHE = os.path.join(_TMP, "programs.json")
C.ICONS_DIR = os.path.join(_TMP, "icons")
C.IS_FIRST_RUN = False

from PySide6.QtCore import QBuffer, QIODevice, QRectF, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ICO_SIZES = [256, 128, 64, 48, 40, 32, 24, 20, 16]
SHOT_W, SHOT_H = 1180, 700

# Что показать в списке: стандартные программы, которые есть в любой Windows.
# Только английские названия — скриншот идёт в английский README.
DEMO_APPS = ["Calculator", "Notepad", "Paint", "File Explorer", "Settings",
             "Command Prompt", "Task Manager", "Snipping Tool", "Windows PowerShell",
             "Microsoft Edge", "Microsoft Store", "Control Panel", "Photos",
             "Sticky Notes", "Voice Recorder", "Clock", "Camera", "Calendar"]
DEMO_SUGGESTIONS = ["Microsoft Edge", "Notepad", "Calculator", "File Explorer",
                    "Windows PowerShell"]


def _png_bytes(pixmap):
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    buf.close()
    return bytes(buf.data())


def write_icons():
    from PIL import Image

    from spotty.ui import appicon

    frames = [Image.open(io.BytesIO(_png_bytes(appicon.pixmap(s)))).convert("RGBA")
              for s in ICO_SIZES]
    ico = os.path.join(OUT_DIR, "app.ico")
    frames[0].save(ico, format="ICO", sizes=[(f.width, f.height) for f in frames],
                   append_images=frames[1:])
    appicon.pixmap(1024).save(os.path.join(OUT_DIR, "icon.png"))
    print("app.ico, icon.png")


def wallpaper(w, h):
    """Тёмные обои с косыми полосами света — как на референсе."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor("#2b2d33"))
    g.setColorAt(1, QColor("#0d0e11"))
    p.fillRect(img.rect(), g)
    rnd = random.Random(7)
    for _ in range(14):
        x = rnd.uniform(-0.3, 1.1) * w
        width = rnd.uniform(40, 220)
        c = rnd.randint(120, 245)
        grad = QLinearGradient(x, 0, x + width, 0)
        grad.setColorAt(0, QColor(c, c, c, 0))
        grad.setColorAt(0.5, QColor(c, c, c, rnd.randint(90, 200)))
        grad.setColorAt(1, QColor(c, c, c, 0))
        p.save()
        p.translate(x, h / 2)
        p.rotate(-35)
        p.translate(-x, -h / 2)
        p.fillRect(QRectF(x, -h, width, h * 3), grad)
        p.restore()
    p.end()
    return img


def write_screenshot(app):
    from spotty.app import Spotty
    from spotty.search import apps as apps_mod
    from spotty.search.engine import app_item

    spotty = Spotty(app)
    spotty.files.set_roots([])
    wanted = {n.casefold() for n in DEMO_APPS}
    spotty.catalog.apps = [a for a in apps_mod.collect() if a["name"].casefold() in wanted]
    for name in reversed(DEMO_SUGGESTIONS):
        for a in spotty.catalog.apps:
            if a["name"] == name:
                spotty.usage.record(app_item(a).key)
    for a in spotty.catalog.apps:
        spotty.icons.request("app:" + a["target"], a["target"], urgent=True)

    panel = spotty.panel
    wall = wallpaper(SHOT_W, SHOT_H)
    x0, y0 = (SHOT_W - panel.width()) // 2, (SHOT_H - panel.height()) // 2
    panel.backdrop.set_source_image(wall.copy(x0, y0, panel.width(), panel.height()),
                                    panel.panel_rect())
    panel._refresh(force=True)
    panel.grab()            # первый проход запрашивает иконки видимых строк

    def shoot():
        img = QImage(wall)
        p = QPainter(img)
        p.drawPixmap(x0, y0, panel.grab())
        p.end()
        img.save(os.path.join(OUT_DIR, "screenshot.png"))
        print("screenshot.png")
        app.quit()

    QTimer.singleShot(4000, shoot)
    app.exec()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    write_icons()
    if "--no-screenshot" not in sys.argv:
        write_screenshot(app)


if __name__ == "__main__":
    main()
