# Google Calendar Widget

Keeps Google Calendar on your Windows desktop like a widget.
It shows the real Google Calendar web app, so you can view, add and edit events and switch between day, week and month views.

> **Unofficial.** Not affiliated with Google; I made it for my own use.
> Google Calendar is a trademark of Google LLC.

## Install

1. Run `GoogleCalendarWidget-Setup.exe`. No admin rights needed.
2. On first launch, sign in to Google inside the widget, move and resize it where you want, then lock it with the 🔒 button.

- The installer is not signed, so Windows may show "Windows protected your PC". Click **More info → Run anyway**.
- If the WebView2 runtime is missing, the installer installs it.
- An older version is removed automatically before installing. Your sign-in and settings are kept.

## Usage

| Feature | How |
|---|---|
| Lock / unlock | 🔒/🔓 button next to the widget, or the tray menu. Locked: no clicks, moving or resizing. Unlocked: move and resize with the title bar. Relocks after 2 minutes without use (hover 🔓 to see the time left). |
| Lock settings | Tray menu → Lock settings: auto-lock on/off, lock after (30 sec to 10 min, or custom), lock when hidden, lock when the PC locks or sleeps |
| Front / back | Click the widget to bring it to the front; click another app to send it back to the desktop. |
| Hide off-screen | ◀/▶ buttons. Click the tab left at the screen edge to bring it back; drag the tab up or down to move it. |
| Language (한국어 / English) | Tray menu → Language / 언어. Starts in the language picked during setup. The calendar itself follows your Google account language. |
| Refresh, Start with Windows, Quit | Right-click the tray icon |

Sign-in and settings are stored in `%LOCALAPPDATA%\GoogleCalendarWidget`.

## Build

Requires Python 3.13 for Windows, [Inno Setup 6](https://jrsoftware.org/isinfo.php) and
`redist\MicrosoftEdgeWebview2Setup.exe` (the [WebView2 bootstrapper](https://go.microsoft.com/fwlink/p/?LinkId=2124703)).

```bat
python -m venv .venv
build.bat
```

This produces `dist\GoogleCalendarWidget-Setup.exe`. During development, run `.venv\Scripts\python.exe widget.py`.

## Third-party libraries

The installer bundles the libraries below, each under its own license.

| Library | Used for | License |
|---|---|---|
| [pywebview](https://github.com/r0x0r/pywebview) | WebView2 window | BSD-3-Clause |
| [pystray](https://github.com/moses-palmer/pystray) | Tray icon | LGPL-3.0 (unmodified) |
| [Pillow](https://github.com/python-pillow/Pillow) | Drawing the icon | MIT-CMU |
| [pythonnet](https://github.com/pythonnet/pythonnet) | Windows Forms buttons and dialogs | MIT |
| [Microsoft Edge WebView2](https://developer.microsoft.com/microsoft-edge/webview2/) | Renders the calendar (installed if missing) | Microsoft Software License Terms |

Built with [PyInstaller](https://pyinstaller.org/) and [Inno Setup](https://jrsoftware.org/isinfo.php).

## Author

Inhu Kim
