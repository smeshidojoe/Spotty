# -*- mode: python ; coding: utf-8 -*-

import re

# --- версия ----------------------------------------------------------------- #
# Единственный источник — spotty/core/constants.py. Отдельный version_info.txt не
# заводим: он дублировал бы ту же строку и однажды разошёлся бы с реальностью.
_APP_VERSION = re.search(
    r'APP_VERSION\s*=\s*"([^"]+)"',
    open('spotty/core/constants.py', encoding='utf-8').read()).group(1)
_VER_TUPLE = tuple(int(x) for x in (_APP_VERSION.split('.') + ['0'] * 4)[:4])

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
    VarStruct, VSVersionInfo)

_VERSION_RES = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_VER_TUPLE, prodvers=_VER_TUPLE,
                      mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
    kids=[
        StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', 'SmeshidoJoe'),
            StringStruct('FileDescription', 'Spotty'),
            StringStruct('FileVersion', _APP_VERSION),
            StringStruct('InternalName', 'Spotty'),
            StringStruct('LegalCopyright', '© 2026 SmeshidoJoe'),
            StringStruct('OriginalFilename', 'Spotty.exe'),
            StringStruct('ProductName', 'Spotty'),
            StringStruct('ProductVersion', _APP_VERSION),
        ])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])]),
    ])

# Иконка нужна в рантайме (трей): PyInstaller не считает её кодом и сам бы не
# положил. Кладём только её — icon.png и screenshot.png нужны странице проекта,
# а не exe.
_DATAS = [('assets/app.ico', 'assets')]

# В окружении разработчика обычно стоят и другие привязки Qt: PyInstaller не умеет
# класть в сборку два набора сразу и обрывает сборку. Ничего из этого не нужно.
# Pillow — только для tools/make_assets.py, в рантайме не участвует.
_EXCLUDES = [
    'PyQt5', 'PyQt6', 'PySide2', 'shiboken2',
    'matplotlib', 'tkinter', 'IPython', 'notebook', 'pytest',
    'PIL', 'numpy', 'pandas',
    # Тяжёлые куски Qt, которых у нас нет на экране. QtOpenGL (стекло) и
    # QtNetwork (сигнал «покажись» от второго запуска) остаются.
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml',
    'PySide6.QtQuick', 'PySide6.Qt3DCore', 'PySide6.QtMultimedia',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtBluetooth',
    'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtNetworkAuth', 'PySide6.QtPdf',
    'PySide6.QtSvg', 'PySide6.QtOpenGLWidgets',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=_DATAS,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_EXCLUDES,
    noarchive=False,
    optimize=0,
)
# Библиотеки, которые PyInstaller тянет вслед за плагинами Qt, а Spotty они не
# нужны. Без них exe легче вдвое.
#   opengl32sw.dll    — программный OpenGL на 20 МБ для машин без драйвера;
#                       там стекло просто выключится, строка станет тёмной;
#   Quick/Qml         — приходят с плагином экранной клавиатуры;
#   Pdf, Svg          — с плагинами форматов картинок, а у нас только PNG и ICO;
#   *-x64 OpenSSL, tls — шифрование для QtNetwork; нам он нужен только для
#                       локального сокета. Обновления качает Python со своим
#                       OpenSSL (libcrypto-3.dll без -x64), его не трогаем.
_DROP = ('opengl32sw.dll', 'qt6quick', 'qt6qml', 'qt6pdf', 'qt6svg',
         'qt6virtualkeyboard', 'platforminputcontexts', 'qdirect2d',
         '\\qpdf', '\\qsvg', 'libcrypto-3-x64', 'libssl-3-x64', '\\tls\\')
a.binaries = [b for b in a.binaries if not any(d in b[0].lower() for d in _DROP)]
# Переводы стандартных диалогов Qt (6 МБ) — из них видна только подпись
# диалога выбора папки, а она и так приходит от Windows.
a.datas = [d for d in a.datas if '\\translations\\' not in d[0].lower()]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Spotty',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,              # программа живёт в трее, консоль не нужна
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\app.ico'],
    version=_VERSION_RES,
)
