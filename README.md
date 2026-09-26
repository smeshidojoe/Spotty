<div align="center">

<img src="assets/icon.png" width="112" alt="">

# Spotty

**English** · [Русский](README.ru.md)

A quick launcher for Windows — like Spotlight on a Mac.
Press `Ctrl + E`, start typing a name, hit Enter.

<img src="assets/screenshot.png" width="760" alt="Spotty search bar over the desktop">

</div>

## Download

1. Open the [Releases](https://github.com/SmeshidoJoe/Spotty/releases/latest) page.
2. Download `Spotty-Setup-….exe` and run it.
3. No administrator rights needed. The search bar opens right after install.

If Windows shows a blue “Windows protected your PC” window, click
**More info → Run anyway**. This happens with every app that doesn't have a
paid code-signing certificate.

Works on Windows 10 and 11.

## How to use

Spotty lives in the tray, next to the clock. Press **`Ctrl + E`** in any app
and the search bar appears. Type, pick with the arrow keys, launch with Enter.
Close it with `Esc` or by clicking anywhere else.

What you can find:

- **Apps** — everything in the Start menu, including Calculator, Settings and
  other Microsoft Store apps.
- **Files and folders** — from your Desktop, Documents and Downloads.
  You can change the folder list in Settings.
- **Calculator** — type `12*(3+4)^2` and the answer shows up right away.
  Enter copies it.
- **Commands** — start with `>`, for example `> ipconfig /all`. The command
  opens in a new Command Prompt window.

A few more things:

- What you launch often moves up. If you always open Telegram after typing
  “t”, next time it will be first.
- Typed with the wrong keyboard layout? `еудупкфь` still finds Telegram.
- Abbreviations work: `vsc` — Visual Studio Code, `ntpd` — Notepad.

## Keys

| Shortcut | What it does |
|----------|--------------|
| `Ctrl + E` | open or close the search bar (can be changed in Settings) |
| `↑` `↓` | pick an item |
| `Enter` | open |
| `Ctrl + Enter` | second action: run as administrator, or show a file in its folder |
| `Ctrl + K` | all actions for the item: show in folder, copy path, hide from results and more |
| `Ctrl + Shift + C` | copy the path, the command or the calculator answer |
| `Ctrl + ,` | settings |
| `Esc` | clear the search, press again to close |

## Settings

The button in the bottom-left corner of the search bar, `Ctrl + ,`, or a
right-click on the tray icon. There you can:

- change the shortcut that opens Spotty;
- turn launch at startup on or off;
- switch the language between English and Russian;
- turn off the glass background;
- add or remove folders for file search;
- bring back items you hid from results;
- check for updates. Spotty also checks by itself every few hours and offers to
  install a new version in one click.

## Questions

**I need `Ctrl + E` in another app.** While Spotty is running, this shortcut
belongs to it — for example, `Ctrl + E` no longer jumps to the search box in
your browser. Pick another one in Settings, such as `Alt + Space`.

**Spotty says the shortcut is taken.** Another app already uses it — often
another launcher. Close that app or choose a different shortcut in Settings.

**The search bar opens slowly or the glass looks odd.** Turn off “Glass
Background” in Settings — the bar becomes plain dark.

**A file doesn't show up.** Add its folder in Settings. Hidden files and
service folders like `node_modules` and `.git` are skipped on purpose.

**Where are the settings stored?** In `%APPDATA%\Spotty`. The icon and app
list cache lives in `%LOCALAPPDATA%\Spotty`; you can delete it, it will be
rebuilt.

**How do I uninstall it?** Settings → Apps → Spotty → Uninstall. The
uninstaller asks whether to keep your settings.

## For developers

You need Python 3.13.

```bash
pip install -r requirements.txt
```

```bash
python main.py --show
```

Building the exe and the installer:

```bash
pip install pyinstaller pillow
```

```bash
python tools/make_assets.py
```

```bash
pyinstaller --clean --noconfirm Spotty.spec
```

Then open `spotty_setup.iss` in [Inno Setup 6](https://jrsoftware.org/isinfo.php)
and press Compile — the installer appears in `installer_output`.

The version lives in one place — `spotty/core/constants.py`. For self-update,
attach a zip with `Spotty.exe` inside to the GitHub release next to the
installer: that zip is what the app downloads.

The glass is a shader from [CopyPasta](https://github.com/SmeshidoJoe/CopyPasta):
the screen under the bar is captured, blurred on the GPU and refracted along
the edge.
