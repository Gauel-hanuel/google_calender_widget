"""Pin the Google Calendar web app to the Windows desktop as a widget."""
import ctypes
import io
import json
import math
import time
import traceback
import os
import sys
import webbrowser
import winreg
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlparse

import pystray
import webview
from PIL import Image, ImageDraw

CALENDAR_URL = "https://calendar.google.com/calendar/r"
if getattr(sys, "frozen", False):
    # Frozen exe: keep data in %LOCALAPPDATA%, not next to the exe
    APP_DIR = Path(os.environ["LOCALAPPDATA"]) / "GoogleCalendarWidget"
    APP_DIR.mkdir(parents=True, exist_ok=True)
    # A windowed exe has no stderr, so log to a file
    sys.stdout = sys.stderr = open(APP_DIR / "widget.log", "a", encoding="utf-8", buffering=1)
else:
    APP_DIR = Path(__file__).resolve().parent
# WebView2 profile (keeps the Google sign-in)
PROFILE_DIR = APP_DIR / "profile"
SETTINGS_FILE = APP_DIR / "settings.json"
# Popup links opened inside the widget; the rest (Meet, attachments, ...) go to the default browser
IN_APP_HOSTS = {"accounts.google.com", "calendar.google.com"}
# Tray "Lock settings" defaults. Auto-lock relocks after lock_seconds without use
LOCK_DEFAULTS = {"auto_lock": True, "lock_seconds": 120, "lock_on_hide": False, "lock_on_pc_lock": False}
LOCK_PRESETS = (30, 60, 120, 300, 600)  # seconds
MIN_LOCK_SECONDS = 10  # minimum custom value
LANGUAGES = {"ko": "한국어", "en": "English"}
TEXTS = {
    "ko": {
        "refresh": "새로고침", "lock": "잠금", "unlock": "잠금 해제", "lock_settings": "잠금 설정",
        "autostart": "Windows 시작 시 실행", "quit": "종료",
        "auto_lock": "자동 잠금", "lock_after": "잠금까지 시간", "custom": "직접 설정...",
        "lock_on_hide": "숨기면(◀ ▶) 잠금", "lock_on_pc_lock": "PC를 잠그거나 절전하면 잠금",
        "auto_lock_in": "잠금 ({time} 후 자동 잠금)",
        "minutes": "분", "seconds_idle": "초 동안 안 쓰면 잠금", "ok": "확인", "cancel": "취소",
        "min_unit": "{}분", "sec_unit": "{}초",
    },
    "en": {
        "refresh": "Refresh", "lock": "Lock", "unlock": "Unlock", "lock_settings": "Lock settings",
        "autostart": "Start with Windows", "quit": "Quit",
        "auto_lock": "Auto-lock", "lock_after": "Lock after", "custom": "Custom...",
        "lock_on_hide": "Lock when hidden (◀ ▶)", "lock_on_pc_lock": "Lock when the PC locks or sleeps",
        "auto_lock_in": "Lock (auto-locks in {time})",
        "minutes": "min", "seconds_idle": "sec of inactivity", "ok": "OK", "cancel": "Cancel",
        "min_unit": "{} min", "sec_unit": "{} sec",
    },
}
LOCK_BUTTON_SIZE = 32  # px at 100% scaling, one side button
TAB_SIZE = (26, 64)  # edge tab (w, h) while hidden, px at 100%
SLIDE_SECONDS = 0.35
TAB_DRAG_THRESHOLD = 4  # px at 100%; a bigger move is a drag, not a click

user32 = ctypes.WinDLL("user32", use_last_error=True)
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowLongPtrW.restype = ctypes.c_void_p
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
user32.GetWindowLongPtrW.restype = ctypes.c_void_p
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.CallWindowProcW.restype = LRESULT
user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = ctypes.c_void_p
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.SetWindowRgn.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
user32.MonitorFromWindow.restype = ctypes.c_void_p
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32 = ctypes.WinDLL("gdi32")
gdi32.CreateRectRgn.restype = ctypes.c_void_p

GWL_STYLE, GWL_EXSTYLE, GWLP_HWNDPARENT, GWLP_WNDPROC = -16, -20, -8, -4
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU = 0x00C00000, 0x00040000, 0x00080000
WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00020000, 0x00010000
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x00040000, 0x08000000
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x10, 0x20
HWND_TOP, HWND_BOTTOM = 0, 1
WM_ACTIVATE, WM_ACTIVATEAPP, WM_WINDOWPOSCHANGING, WM_WINDOWPOSCHANGED = 0x0006, 0x001C, 0x0046, 0x0047
WM_DPICHANGED = 0x02E0
WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK = 0x02B1, 0x7
WM_POWERBROADCAST, PBT_APMSUSPEND = 0x0218, 0x4
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
MONITOR_DEFAULTTONEAREST = 2
MONITOR_DEFAULTTONULL = 0


class WINDOWPOS(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("hwndInsertAfter", wintypes.HWND),
                ("x", ctypes.c_int), ("y", ctypes.c_int), ("cx", ctypes.c_int), ("cy", ctypes.c_int),
                ("flags", wintypes.UINT)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


_old_procs = {}
_widget = None


@WNDPROC
def _desktop_wndproc(hwnd, msg, wparam, lparam):
    # Stay at the bottom of the z-order unless raised by a click.
    # While sliding off-screen, ignore DPI changes from the neighboring monitor.
    if msg == WM_DPICHANGED and _widget and _widget.hidden_side and hwnd == _widget.hwnd:
        return 0
    if msg == WM_WINDOWPOSCHANGING and not (_widget and _widget.raised):
        pos = WINDOWPOS.from_address(lparam)
        if not pos.flags & SWP_NOZORDER:
            pos.hwndInsertAfter = HWND_BOTTOM
    result = user32.CallWindowProcW(_old_procs[hwnd], hwnd, msg, wparam, lparam)
    if _widget:
        try:
            _widget.on_window_message(hwnd, msg, wparam)
        except Exception:
            traceback.print_exc()
    return result


def pin_to_desktop(hwnd):
    """Subclass the window so it stays on the desktop layer."""
    _old_procs[hwnd] = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(_desktop_wndproc, ctypes.c_void_p))


def add_ex_style(hwnd, add, remove=0):
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) or 0
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (ex & ~remove) | add)


def system_idle_seconds():
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000


class DesktopWidget:
    def __init__(self, window):
        self.window = window
        self.hwnd = None
        self.locked = False
        self.raised = False
        self.last_active = time.monotonic()
        self.lock_options = dict(LOCK_DEFAULTS)
        self.language = default_language()
        self.icon = None
        self.button_hwnd = None
        self.overlay_hwnd = None
        self.tab_hwnd = None
        self.hidden_side = None  # "left"/"right" while hidden
        self.home = None  # position before hiding
        self.monitor = None
        self._anim = None
        self._lock_ui = None  # keeps WinForms objects alive

    def setup(self):
        """Turn the window into a desktop widget, show it and run the tray icon."""
        try:
            self.window.events.loaded.wait()
            self.hwnd = self.window.native.Handle.ToInt64()
            settings = load_settings()
            self.lock_options = read_lock_options(settings)
            if settings.get("language") in LANGUAGES:
                self.language = settings["language"]

            # Hide from the taskbar and Alt+Tab
            add_ex_style(self.hwnd, WS_EX_TOOLWINDOW, remove=WS_EX_APPWINDOW)
            # Owned by Progman so it survives Win+D
            user32.SetWindowLongPtrW(self.hwnd, GWLP_HWNDPARENT, user32.FindWindowW("Progman", None))
            global _widget
            _widget = self
            pin_to_desktop(self.hwnd)
            # For "lock when the PC locks"
            ctypes.WinDLL("wtsapi32").WTSRegisterSessionNotification(wintypes.HWND(self.hwnd), 0)

            rect = settings.get("rect")
            if not is_visible_rect(rect):  # missing or off-screen
                rect = None
            if rect:
                x, y, w, h = rect
                user32.SetWindowPos(self.hwnd, HWND_BOTTOM, x, y, w, h, SWP_NOACTIVATE)
            # Start locked, or unlocked on first run so it can be placed
            self.set_locked(bool(rect))
            self.window.show()
            from System import Action
            self.window.native.Invoke(Action(self.create_side_controls))
        except Exception:
            traceback.print_exc()
            self.window.destroy()
            return
        self.run_tray()

    def on_window_message(self, hwnd, msg, wparam):
        if msg == WM_ACTIVATE and wparam & 0xFFFF:  # widget or overlay clicked
            self.set_raised(True)
        elif msg == WM_ACTIVATEAPP and not wparam:  # another app clicked
            self.set_raised(False)
        elif msg == WM_WINDOWPOSCHANGED and hwnd == self.hwnd:
            self.follow_widget()
        elif hwnd == self.hwnd and (msg == WM_WTSSESSION_CHANGE and wparam == WTS_SESSION_LOCK
                                    or msg == WM_POWERBROADCAST and wparam == PBT_APMSUSPEND):
            # Lock now so it is locked on return
            if self.lock_options["lock_on_pc_lock"] and not self.locked:
                self.set_locked(True)

    def set_raised(self, raised):
        if self.raised == raised:
            return
        self.raised = raised
        # Owned windows (button, overlay) follow along
        user32.SetWindowPos(self.hwnd, HWND_TOP if raised else HWND_BOTTOM, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def set_locked(self, locked):
        """Locked: borderless, with a near-transparent overlay that swallows input.
        Unlocked: caption and frame for moving and resizing."""
        if locked and not self.locked:
            self.save_rect()
        self.locked = locked
        if not locked:
            self.last_active = time.monotonic()
        style = user32.GetWindowLongPtrW(self.hwnd, GWL_STYLE) or 0
        style &= ~(WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        if not locked:
            style |= WS_CAPTION | WS_THICKFRAME | WS_SYSMENU
        user32.SetWindowLongPtrW(self.hwnd, GWL_STYLE, style)
        user32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        if not self.overlay_hwnd or self.hidden_side:
            return  # fixed up on return
        self.follow_widget()
        user32.ShowWindow(self.overlay_hwnd, SW_SHOWNOACTIVATE if locked else SW_HIDE)
        # Move focus to the overlay so keyboard shortcuts can't edit events
        if locked and user32.GetForegroundWindow() == self.hwnd:
            user32.SetForegroundWindow(self.overlay_hwnd)

    def follow_widget(self):
        """Keep the side buttons and overlay aligned with the widget."""
        r = wintypes.RECT()
        if self.hidden_side or not user32.GetWindowRect(self.hwnd, ctypes.byref(r)):
            return
        flags = SWP_NOZORDER | SWP_NOACTIVATE
        if self.overlay_hwnd:
            user32.SetWindowPos(self.overlay_hwnd, None, r.left, r.top, r.right - r.left, r.bottom - r.top, flags)
        if self.button_hwnd:
            size = self.scaled(LOCK_BUTTON_SIZE)
            x, y = lock_button_pos(r, size)
            user32.SetWindowPos(self.button_hwnd, None, x, y, size, size * 3, flags)

    def scaled(self, px):
        return px * user32.GetDpiForWindow(self.hwnd) // 96

    def slide_out(self, side):
        """Slide off the left/right edge and leave a tab there."""
        r = wintypes.RECT()
        if self.hidden_side or not user32.GetWindowRect(self.hwnd, ctypes.byref(r)):
            return
        info = MONITORINFO(ctypes.sizeof(MONITORINFO))
        user32.GetMonitorInfoW(user32.MonitorFromWindow(self.hwnd, MONITOR_DEFAULTTONEAREST), ctypes.byref(info))
        self.monitor = info.rcMonitor
        if self.lock_options["lock_on_hide"] and not self.locked:
            self.set_locked(True)
        self.home = (r.left, r.top)
        self.hidden_side = side
        user32.ShowWindow(self.button_hwnd, SW_HIDE)
        user32.ShowWindow(self.overlay_hwnd, SW_HIDE)
        target = self.monitor.left - (r.right - r.left) if side == "left" else self.monitor.right
        self.animate(r.left, target, lambda t: t ** 3, self.show_tab)

    def slide_in(self):
        """Slide back to the position before hiding."""
        if not self.hidden_side or self._anim:
            return
        user32.ShowWindow(self.tab_hwnd, SW_HIDE)
        r = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(r))
        self.animate(r.left, self.home[0], lambda t: 1 - (1 - t) ** 3, self.on_returned)

    def animate(self, x0, x1, ease, done):
        """Move horizontally, clipped to the monitor so nothing shows on a neighbor."""
        start = time.perf_counter()
        y = self.home[1]
        m = self.monitor

        def step(*_):
            t = min(1.0, (time.perf_counter() - start) / SLIDE_SECONDS)
            x = round(x0 + (x1 - x0) * ease(t))
            user32.SetWindowPos(self.hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            rgn = gdi32.CreateRectRgn(m.left - x, m.top - y, m.right - x, m.bottom - y)
            user32.SetWindowRgn(self.hwnd, rgn, True)  # the system owns the region
            if t >= 1.0:
                timer.Stop()
                self._anim = None
                done()

        timer = self._forms.Timer()
        timer.Interval = 10
        timer.Tick += lambda *_: run_safely(step)
        self._anim = (timer, step)
        timer.Start()

    def show_tab(self):
        w, h = self.scaled(TAB_SIZE[0]), self.scaled(TAB_SIZE[1])
        m = self.monitor
        x = m.left if self.hidden_side == "left" else m.right - w
        # Dragged height if any, else the widget's top
        y = min(max(load_settings().get("tab_y", self.home[1]), m.top), m.bottom - h)
        self._tab_button.Text = "▶" if self.hidden_side == "left" else "◀"
        user32.SetWindowPos(self.tab_hwnd, None, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)
        user32.ShowWindow(self.tab_hwnd, SW_SHOWNOACTIVATE)

    def on_tab_mouse_down(self):
        p = wintypes.POINT()
        r = wintypes.RECT()
        user32.GetCursorPos(ctypes.byref(p))
        user32.GetWindowRect(self.tab_hwnd, ctypes.byref(r))
        self._tab_drag = {"cursor_y": p.y, "tab_x": r.left, "tab_y": r.top, "moved": False}

    def on_tab_mouse_move(self):
        """Drag the tab up or down; a tiny move is still a click."""
        drag = getattr(self, "_tab_drag", None)
        if not drag or not user32.GetAsyncKeyState(0x01) & 0x8000:  # left button held
            return
        p = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(p))
        dy = p.y - drag["cursor_y"]
        if not drag["moved"] and abs(dy) < self.scaled(TAB_DRAG_THRESHOLD):
            return
        drag["moved"] = True
        h = self.scaled(TAB_SIZE[1])
        y = min(max(drag["tab_y"] + dy, self.monitor.top), self.monitor.bottom - h)
        user32.SetWindowPos(self.tab_hwnd, None, drag["tab_x"], y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def on_tab_mouse_up(self):
        drag = getattr(self, "_tab_drag", None)
        if drag and drag["moved"]:
            r = wintypes.RECT()
            user32.GetWindowRect(self.tab_hwnd, ctypes.byref(r))
            update_settings(tab_y=r.top)

    def on_tab_click(self):
        drag = getattr(self, "_tab_drag", None)
        self._tab_drag = None
        if not (drag and drag["moved"]):
            self.slide_in()

    def on_returned(self):
        user32.SetWindowRgn(self.hwnd, None, True)
        self.hidden_side = None
        self.follow_widget()
        user32.ShowWindow(self.button_hwnd, SW_SHOWNOACTIVATE)
        if self.locked:
            user32.ShowWindow(self.overlay_hwnd, SW_SHOWNOACTIVATE)
        # Bring to front; clicking another app sends it back
        self.set_raised(True)
        user32.SetForegroundWindow(self.overlay_hwnd if self.locked else self.hwnd)

    def create_side_controls(self):
        """Side buttons (lock, hide left, hide right), lock overlay and edge tab. UI thread only."""
        import clr
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Drawing import Bitmap, Color, ContentAlignment, Font, GraphicsUnit, Image, Size
        from System.IO import MemoryStream
        from System.Windows import Forms
        self._forms = Forms

        def small_window(owner):
            form = Forms.Form()
            form.FormBorderStyle = getattr(Forms.FormBorderStyle, "None")
            form.ShowInTaskbar = False
            form.StartPosition = Forms.FormStartPosition.Manual
            hwnd = form.Handle.ToInt64()
            add_ex_style(hwnd, WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            user32.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, owner)  # sits right above the owner
            pin_to_desktop(hwnd)
            return form, hwnd

        def flat_button(on_click, dock=Forms.DockStyle.Fill):
            button = Forms.Button()
            button.Dock = dock
            button.FlatStyle = Forms.FlatStyle.Flat
            button.FlatAppearance.BorderSize = 0
            button.BackColor = Color.White
            button.ForeColor = Color.Black
            button.Click += lambda *_: run_safely(on_click)
            return button

        form, hwnd = small_window(self.hwnd)
        lock_button = flat_button(lambda: self.set_locked(not self.locked), Forms.DockStyle.Top)
        left_button = flat_button(lambda: self.slide_out("left"), Forms.DockStyle.Top)
        right_button = flat_button(lambda: self.slide_out("right"), Forms.DockStyle.Top)
        left_button.Text, right_button.Text = "◀", "▶"
        for b in (right_button, left_button, lock_button):  # Dock.Top stacks the last added on top
            form.Controls.Add(b)
        button = lock_button
        form.Show()

        tab, tab_hwnd = small_window(self.hwnd)
        self._tab_button = flat_button(self.on_tab_click)
        self._tab_button.BackColor = Color.FromArgb(26, 115, 232)
        self._tab_button.ForeColor = Color.White
        self._tab_button.ImageAlign = ContentAlignment.TopCenter
        self._tab_button.TextAlign = ContentAlignment.BottomCenter
        self._tab_button.Padding = Forms.Padding(0, 3, 0, 1)
        self._tab_button.MouseDown += lambda s, e: run_safely(self.on_tab_mouse_down)
        self._tab_button.MouseMove += lambda s, e: run_safely(self.on_tab_mouse_move)
        self._tab_button.MouseUp += lambda s, e: run_safely(self.on_tab_mouse_up)
        tab.Controls.Add(self._tab_button)
        png = io.BytesIO()
        tray_image().save(png, "PNG")
        icon = Image.FromStream(MemoryStream(png.getvalue()))
        self.tab_hwnd = tab_hwnd

        # Lock overlay: 1% opacity, invisible but still gets clicks
        overlay = Forms.Form()
        overlay.FormBorderStyle = getattr(Forms.FormBorderStyle, "None")
        overlay.ShowInTaskbar = False
        overlay.StartPosition = Forms.FormStartPosition.Manual
        overlay.BackColor = Color.White
        overlay.Opacity = 0.01
        overlay_hwnd = overlay.Handle.ToInt64()
        add_ex_style(overlay_hwnd, WS_EX_TOOLWINDOW)  # must activate on click
        user32.SetWindowLongPtrW(overlay_hwnd, GWLP_HWNDPARENT, self.hwnd)
        pin_to_desktop(overlay_hwnd)

        self.button_hwnd, self.overlay_hwnd = hwnd, overlay_hwnd
        self.set_locked(self.locked)

        tooltip = Forms.ToolTip()
        tooltip.InitialDelay = 300
        state = {"text": None, "size": None, "tip": None}

        def tick(*_):
            try:
                # Lock state may change from the tray
                text = "🔒" if self.locked else "🔓"
                if state["text"] != text:
                    button.Text = state["text"] = text
                    button.ForeColor = Color.Black
                # Rescale on DPI change
                size = self.scaled(LOCK_BUTTON_SIZE)
                if state["size"] != size:
                    state["size"] = size
                    icon_px = self.scaled(TAB_SIZE[0]) - self.scaled(6)
                    self._tab_button.Image = Bitmap(icon, Size(icon_px, icon_px * icon.Height // icon.Width))
                    for b in (lock_button, left_button, right_button, self._tab_button):
                        b.Height = size
                        b.Font = Font("Segoe UI Emoji" if b is lock_button else "Segoe UI", size * 0.45,
                                      GraphicsUnit.Pixel)
                tip = self.check_auto_lock()
                if state["tip"] != tip:
                    tooltip.SetToolTip(lock_button, tip)
                    state["tip"] = tip
            except Exception:
                traceback.print_exc()

        timer = Forms.Timer()
        timer.Interval = 250
        timer.Tick += tick
        timer.Start()
        self._lock_ui = (form, tab, overlay, timer, tick, tooltip)

    def check_auto_lock(self):
        """Relock when idle too long; returns the lock button tooltip."""
        if self.locked:
            return self.text("unlock")
        if not self.lock_options["auto_lock"]:
            return self.text("lock")
        # Foreground with recent input counts as use
        if user32.GetForegroundWindow() == self.hwnd and system_idle_seconds() < 1:
            self.last_active = time.monotonic()
        remaining = self.lock_options["lock_seconds"] - (time.monotonic() - self.last_active)
        if remaining <= 0:
            self.set_locked(True)
            return self.text("unlock")
        return self.text("auto_lock_in", time=self.duration(math.ceil(remaining)))

    def text(self, key, **values):
        return TEXTS[self.language][key].format(**values)

    def duration(self, seconds):
        """e.g. "1분 30초" / "1 min 30 sec"."""
        minutes, seconds = divmod(seconds, 60)
        parts = [(minutes, "min_unit"), (seconds, "sec_unit")]
        return " ".join(TEXTS[self.language][unit].format(n) for n, unit in parts if n)

    def set_language(self, language):
        self.language = language
        update_settings(language=language)

    def set_lock_option(self, key, value):
        self.lock_options = {**self.lock_options, key: value}
        update_settings(**{key: value})
        self.last_active = time.monotonic()  # restart the countdown

    def ask_lock_time(self):
        """Custom lock time dialog. UI thread only."""
        Forms = self._forms
        from System import Decimal
        from System.Drawing import Font

        def row(*controls):
            panel = Forms.FlowLayoutPanel()
            panel.AutoSize = True
            panel.WrapContents = False
            for c in controls:
                panel.Controls.Add(c)
            return panel

        def number(maximum, value):
            box = Forms.NumericUpDown()
            box.Maximum, box.Value, box.Width = Decimal(maximum), Decimal(value), 60
            return box

        def label(text):
            lbl = Forms.Label()
            lbl.Text, lbl.AutoSize = text, True
            lbl.Margin = Forms.Padding(0, 6, 8, 0)
            return lbl

        def button(text, result):
            b = Forms.Button()
            b.Text, b.DialogResult = text, result
            b.AutoSize = True
            b.Padding = Forms.Padding(12, 4, 12, 4)
            return b

        minutes, seconds = divmod(self.lock_options["lock_seconds"], 60)
        minute_box, second_box = number(120, minutes), number(59, seconds)
        ok = button(self.text("ok"), Forms.DialogResult.OK)
        cancel = button(self.text("cancel"), Forms.DialogResult.Cancel)
        body = Forms.FlowLayoutPanel()
        body.FlowDirection = Forms.FlowDirection.TopDown
        body.AutoSize = True
        body.Padding = Forms.Padding(16, 12, 16, 20)
        body.Controls.Add(row(minute_box, label(self.text("minutes")), second_box, label(self.text("seconds_idle"))))
        body.Controls.Add(row(ok, cancel))

        dialog = Forms.Form()
        dialog.Text = self.text("lock_after")
        dialog.Font = Font("Segoe UI", 9)
        dialog.FormBorderStyle = Forms.FormBorderStyle.FixedDialog
        dialog.MaximizeBox = dialog.MinimizeBox = dialog.ShowInTaskbar = False
        dialog.StartPosition = Forms.FormStartPosition.CenterScreen
        dialog.TopMost = True
        dialog.AutoSize = True
        dialog.AutoSizeMode = Forms.AutoSizeMode.GrowAndShrink
        dialog.AcceptButton, dialog.CancelButton = ok, cancel
        dialog.Controls.Add(body)
        try:
            if dialog.ShowDialog() == Forms.DialogResult.OK:
                total = Decimal.ToInt32(minute_box.Value) * 60 + Decimal.ToInt32(second_box.Value)
                self.set_lock_option("lock_seconds", max(total, MIN_LOCK_SECONDS))
        finally:
            dialog.Dispose()

    def lock_menu(self):
        def option(key):
            return pystray.MenuItem(lambda _: self.text(key), lambda: self.set_lock_option(key, not self.lock_options[key]),
                                    checked=lambda _: self.lock_options[key])

        def auto_on(_):
            return self.lock_options["auto_lock"]

        def preset(seconds):
            return pystray.MenuItem(lambda _: self.duration(seconds), lambda: self.set_lock_option("lock_seconds", seconds),
                                    checked=lambda _: self.lock_options["lock_seconds"] == seconds,
                                    radio=True, enabled=auto_on)

        def custom_text(_):
            seconds = self.lock_options["lock_seconds"]
            custom = self.text("custom")
            return custom if seconds in LOCK_PRESETS else f"{custom} ({self.duration(seconds)})"

        def open_dialog():
            from System import Action
            self.window.native.BeginInvoke(Action(lambda: run_safely(self.ask_lock_time)))

        return pystray.Menu(
            option("auto_lock"),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _: self.text("lock_after"), None, enabled=False),
            *(preset(s) for s in LOCK_PRESETS),
            pystray.MenuItem(custom_text, open_dialog, radio=True, enabled=auto_on,
                             checked=lambda _: self.lock_options["lock_seconds"] not in LOCK_PRESETS),
            pystray.Menu.SEPARATOR,
            option("lock_on_hide"),
            option("lock_on_pc_lock"),
        )

    def save_rect(self):
        r = wintypes.RECT()
        if not user32.GetWindowRect(self.hwnd, ctypes.byref(r)) or r.right <= r.left:
            return
        x, y = self.home if self.hidden_side else (r.left, r.top)  # original position while hidden
        update_settings(rect=[x, y, r.right - r.left, r.bottom - r.top])

    def run_tray(self):
        def quit_app(icon):
            icon.stop()
            self.window.destroy()

        def language_item(language):
            return pystray.MenuItem(LANGUAGES[language], lambda: self.set_language(language),
                                    checked=lambda _: self.language == language, radio=True)

        self.icon = icon = pystray.Icon("google_calendar_widget", tray_image(), "Google Calendar Widget", pystray.Menu(
            pystray.MenuItem(lambda _: self.text("refresh"), lambda: self.window.evaluate_js("location.reload()")),
            pystray.MenuItem(lambda _: self.text("lock"), lambda: self.set_locked(not self.locked),
                             checked=lambda _: self.locked),
            pystray.MenuItem(lambda _: self.text("lock_settings"), self.lock_menu()),
            pystray.MenuItem("Language / 언어", pystray.Menu(*(language_item(lang) for lang in LANGUAGES))),
            pystray.MenuItem(lambda _: self.text("autostart"), lambda: set_autostart(not autostart_enabled()),
                             checked=lambda _: autostart_enabled()),
            pystray.MenuItem(lambda _: self.text("quit"), quit_app),
        ))
        # Returning False from a closing handler cancels the close
        def on_closing():
            if not self.locked:
                self.save_rect()

        self.window.events.closing += on_closing
        refresh_menu_before_showing(icon)
        icon.run()


def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def update_settings(**changes):
    SETTINGS_FILE.write_text(json.dumps({**load_settings(), **changes}, indent=2), encoding="utf-8")


def read_lock_options(settings):
    """Lock options from settings.json; defaults for missing or bad values."""
    options = {key: settings.get(key, default) for key, default in LOCK_DEFAULTS.items()}
    for key, default in LOCK_DEFAULTS.items():
        if type(options[key]) is not type(default):
            options[key] = default
    options["lock_seconds"] = max(options["lock_seconds"], MIN_LOCK_SECONDS)
    return options


def default_language():
    """Installer language if set, else Korean on Korean Windows, else English."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\GoogleCalendarWidget") as key:
            language = {"korean": "ko", "english": "en"}.get(winreg.QueryValueEx(key, "InstallerLanguage")[0])
        if language:
            return language
    except OSError:
        pass
    LANG_KOREAN = 0x12
    return "ko" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == LANG_KOREAN else "en"


def refresh_menu_before_showing(icon):
    """pystray only rebuilds the menu after a menu click, so rebuild it on every right-click
    (patches a pystray 0.19.5 internal)."""
    from pystray._util import win32 as tray_win32
    show_menu = icon._message_handlers[tray_win32.WM_NOTIFY]

    def on_notify(wparam, lparam):
        if lparam == tray_win32.WM_RBUTTONUP:
            icon.update_menu()
        return show_menu(wparam, lparam)

    icon._message_handlers[tray_win32.WM_NOTIFY] = on_notify


def is_visible_rect(rect):
    """[x, y, w, h] has a size and touches a connected monitor."""
    if not rect or len(rect) != 4 or rect[2] <= 0 or rect[3] <= 0:
        return False
    x, y, w, h = rect
    r = wintypes.RECT(x, y, x + w, y + h)
    return bool(user32.MonitorFromRect(ctypes.byref(r), MONITOR_DEFAULTTONULL))


def run_safely(func):
    """Log errors from WinForms handlers instead of crashing."""
    try:
        func()
    except Exception:
        traceback.print_exc()


def lock_button_pos(r, size, gap=4):
    """Outside top-right, else outside top-left, else inside top-right."""
    for x in (r.right + gap, r.left - gap - size):
        if user32.MonitorFromPoint(wintypes.POINT(x + size // 2, r.top + size // 2), MONITOR_DEFAULTTONULL):
            return x, r.top
    return r.right - size - gap, r.top + gap


def tray_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 8, 60, 60), radius=8, fill="white", outline=(26, 115, 232), width=4)
    d.rectangle((4, 8, 60, 24), fill=(26, 115, 232))
    d.text((24, 30), "31", fill=(26, 115, 232), font_size=22)
    return img


def route_new_window(browser, sender, args):
    """Route target=_blank links: Google sign-in and Calendar stay in the widget, the rest open in the browser."""
    url = str(args.get_Uri())
    if urlparse(url).scheme not in ("http", "https"):
        return  # about:blank etc.
    args.set_Handled(True)
    if urlparse(url).hostname in IN_APP_HOSTS:
        browser.load_url(url)
    else:
        webbrowser.open(url)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "GoogleCalendarWidget"  # also used in installer.iss


def autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # Dev run without a console window
    return f'"{Path(sys.executable).with_name("pythonw.exe")}" "{Path(__file__).resolve()}"'


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_VALUE)[0] == autostart_command()
    except OSError:
        return False


def set_autostart(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass


def already_running():
    """Single instance (autostart + manual launch)."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, "GoogleCalendarWidget.SingleInstance")  # handle lives until exit
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def main():
    if already_running():
        return
    from webview.platforms.edgechromium import EdgeChrome
    EdgeChrome.on_new_window_request = route_new_window  # patches a pywebview 6.2.1 internal
    window = webview.create_window("Google Calendar", CALENDAR_URL, width=900, height=700, hidden=True)
    widget = DesktopWidget(window)
    webview.start(widget.setup, gui="edgechromium", private_mode=False, storage_path=str(PROFILE_DIR))
    # Stop the tray icon however the window was closed
    if widget.icon:
        widget.icon.stop()


if __name__ == "__main__":
    main()
