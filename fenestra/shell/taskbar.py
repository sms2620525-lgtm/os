"""The taskbar: centred Start/Search/Task View, pinned & running apps, tray and clock."""

import os
import sys

from PyQt6.QtCore import QDateTime, QLocale, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QToolButton, QWidget

from ..common import apps as appreg
from ..common import config, icons, theme, x11
from . import system

HEIGHT = 48


class TaskButton(QToolButton):
    def __init__(self, p, icon: QIcon, tooltip=""):
        super().__init__()
        self.p = p
        self.setIcon(icon)
        self.setIconSize(QSize(24, 24))
        self.setFixedSize(44, 40)
        self.setToolTip(tooltip)
        self.setAutoRaise(True)
        self.running = 0
        self.active = False
        self.setStyleSheet("QToolButton { border: none; background: transparent; }")
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self._hover or self.active:
            c = QColor(self.p.text)
            c.setAlpha(22 if self.active else 14)
            p.setBrush(c)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 4, 4)
        pm = self.icon().pixmap(self.iconSize())
        if self.isDown():
            pm = pm.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        p.drawPixmap(int((self.width() - pm.width()) / 2), int((self.height() - pm.height()) / 2) - 1, pm)
        if self.running:
            w = 16 if self.active else 6
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.p.accent if self.active else self.p.text_secondary))
            p.drawRoundedRect(QRectF((self.width() - w) / 2, self.height() - 4, w, 3), 1.5, 1.5)
        p.end()


class SearchPill(QPushButton):
    def __init__(self, p):
        super().__init__("  Search")
        self.setIcon(icons.icon("search", p.text))
        self.setFixedSize(190, 34)
        self.setStyleSheet(
            f"QPushButton {{ text-align: left; padding-left: 12px; border-radius: 17px; background: {p.surface};"
            f" border: 1px solid {p.stroke}; color: {p.text_secondary}; }}"
            f"QPushButton:hover {{ background: {p.surface_alt}; }}")


class Clock(QToolButton):
    def __init__(self, p):
        super().__init__()
        self.p = p
        self.setAutoRaise(True)
        self.setFixedHeight(40)
        self.setMinimumWidth(80)
        self.setStyleSheet(f"QToolButton {{ border: none; border-radius: 4px; padding: 0 8px; font-size: 8.5pt; }}"
                           f"QToolButton:hover {{ background: {p.surface_alt}; }}")
        self.tick()
        t = QTimer(self)
        t.timeout.connect(self.tick)
        t.start(1000)

    def tick(self):
        now = QDateTime.currentDateTime()
        loc = QLocale()
        fmt = "h:mm:ss AP" if config.get("show_seconds") else "h:mm AP"
        self.setText(f"{loc.toString(now.time(), fmt)}\n{loc.toString(now.date(), 'yyyy-MM-dd')}")
        self.setToolTip(loc.toString(now.date(), QLocale.FormatType.LongFormat))


class TrayButton(QToolButton):
    """Grouped wifi / volume / battery icons (opens Quick Settings)."""

    def __init__(self, p):
        super().__init__()
        self.p = p
        self.setAutoRaise(True)
        self.setFixedHeight(40)
        self.setStyleSheet(f"QToolButton {{ border: none; border-radius: 4px; padding: 0 6px; }}"
                           f"QToolButton:hover {{ background: {p.surface_alt}; }}")
        self.refresh()

    def refresh(self):
        names = ["wifi", "volume"]
        if system.battery():
            names.append("battery")
        size = 16
        pm = QPixmap(len(names) * 26, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        for i, n in enumerate(names):
            painter.drawPixmap(i * 26 + 4, 0, icons.pixmap(n, size, self.p.text))
        painter.end()
        self.setIcon(QIcon(pm))
        self.setIconSize(pm.size())
        vol, muted = system.get_volume()
        wifi_on, ssid = system.wifi_state()
        bat = system.battery()
        tip = [f"{ssid or 'Not connected'}", f"Speakers: {'muted' if muted else str(vol) + '%'}"]
        if bat:
            tip.append(f"Battery: {bat[0]}%")
        self.setToolTip("\n".join(tip))

    def wheelEvent(self, e):
        vol, _ = system.get_volume()
        system.set_volume(vol + (2 if e.angleDelta().y() > 0 else -2))


class Taskbar(QWidget):
    start_clicked = pyqtSignal()
    search_clicked = pyqtSignal()
    taskview_clicked = pyqtSignal()
    widgets_clicked = pyqtSignal()
    quick_clicked = pyqtSignal()
    clock_clicked = pyqtSignal()

    def __init__(self, p, screen, parent=None):
        if parent is None:
            super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                             Qt.WindowType.WindowDoesNotAcceptFocus)
        else:  # windowed mode: child of the Fenestra window
            super().__init__(parent)
        self.p = p
        self.screen_ = screen
        self.embedded = parent is not None
        self.launched = {}   # app id -> Popen (running-state fallback without X11/EWMH)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("fenestra-taskbar")
        g = parent.rect() if parent is not None else screen.geometry()
        self.setGeometry(g.x(), g.y() + g.height() - HEIGHT, g.width(), HEIGHT)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 0, 4)
        lay.setSpacing(4)
        self.widgets_btn = QToolButton()
        self.widgets_btn.setIcon(icons.icon("widgets", p.accent))
        self.widgets_btn.setIconSize(QSize(20, 20))
        self.widgets_btn.setText("  Widgets")
        self.widgets_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.widgets_btn.setAutoRaise(True)
        self.widgets_btn.setFixedHeight(40)
        self.widgets_btn.clicked.connect(self.widgets_clicked.emit)
        lay.addWidget(self.widgets_btn)
        lay.addStretch(1)

        self.start = TaskButton(p, icons.icon("logo"), "Start")
        self.start.clicked.connect(self.start_clicked.emit)
        self.search = SearchPill(p)
        self.search.clicked.connect(self.search_clicked.emit)
        self.taskview = TaskButton(p, icons.icon("taskview", p.text), "Task View")
        self.taskview.clicked.connect(self.taskview_clicked.emit)
        lay.addWidget(self.start)
        lay.addWidget(self.search)
        lay.addWidget(self.taskview)
        self.apps_lay = QHBoxLayout()
        self.apps_lay.setSpacing(4)
        lay.addLayout(self.apps_lay)
        lay.addStretch(1)

        self.overflow = QToolButton()
        self.overflow.setIcon(icons.icon("chevron-up", p.text))
        self.overflow.setAutoRaise(True)
        self.overflow.setFixedSize(28, 40)
        self.overflow.setToolTip("Show hidden icons")
        lay.addWidget(self.overflow)
        self.tray = TrayButton(p)
        self.tray.clicked.connect(self.quick_clicked.emit)
        lay.addWidget(self.tray)
        self.clock = Clock(p)
        self.clock.clicked.connect(self.clock_clicked.emit)
        lay.addWidget(self.clock)
        self.show_desktop = QPushButton()
        self.show_desktop.setFixedSize(8, HEIGHT)
        self.show_desktop.setToolTip("Show desktop")
        self.show_desktop.setStyleSheet(f"QPushButton {{ border: none; border-left: 1px solid {p.stroke}; background: transparent;"
                                        f" border-radius: 0; padding: 0; min-height: 0; }}")
        self._desktop_shown = False
        self.show_desktop.clicked.connect(self.toggle_desktop)
        lay.addWidget(self.show_desktop)

        self.buttons = {}   # key -> TaskButton
        self.apply_alignment()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(700)
        self.tray_timer = QTimer(self)
        self.tray_timer.timeout.connect(self.tray.refresh)
        self.tray_timer.start(15000)
        self.refresh(force=True)

    def apply_alignment(self):
        left = config.get("taskbar_alignment") == "left"
        lay = self.layout()
        lay.setStretch(1, 0 if left else 1)
        self.widgets_btn.setVisible(not left)

    def toggle_desktop(self):
        self._desktop_shown = not self._desktop_shown
        x11.wm().show_desktop(self._desktop_shown)

    def show(self):
        if not self.embedded:
            self._dock()   # tag as DOCK before mapping (see Desktop.show)
        super().show()
        if not self.embedded:
            self.raise_()
            QTimer.singleShot(500, self._dock)

    def _dock(self):
        wm = x11.wm()
        wid = int(self.winId())
        wm.set_type(wid, "DOCK", ("ABOVE", "STICKY", "SKIP_TASKBAR"))
        g = self.screen_.geometry()
        wm.set_strut(wid, HEIGHT, g.width(), g.height())

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), theme.rgba(self.p.taskbar, opaque=not config.get("transparency")))
        p.setPen(QColor(self.p.stroke))
        p.drawLine(0, 0, self.width(), 0)
        p.end()

    # --- app buttons -----------------------------------------------------------
    @staticmethod
    def _keys(app):
        keys = {app.id.lower(), f"fenestra-{app.id}".lower()}
        if app.command:
            keys.add(os.path.basename(app.command[0]).lower())
        return keys

    def refresh(self, force=False):
        builtins = appreg.builtin_apps()
        desktop = {a.id: a for a in appreg.desktop_apps()} if force or not hasattr(self, "_desktop_cache") else self._desktop_cache
        self._desktop_cache = desktop
        pinned = [builtins.get(i) or desktop.get(i) for i in config.get("pinned_taskbar")]
        pinned = [a for a in pinned if a]
        own = os.getpid()
        wins = [w for w in x11.wm().windows() if w.pid != own]
        if not x11.wm().available:
            # macOS / Wayland: treat apps launched from the taskbar as running windows
            for app_id, proc in list(self.launched.items()):
                if proc.poll() is None:
                    wins.append(x11.Window(0, app_id, app_id, proc.pid))
                else:
                    del self.launched[app_id]
        groups, order = {}, []
        for app in pinned:
            key = f"app:{app.id}"
            groups[key] = {"app": app, "wins": []}
            order.append(key)
        for w in wins:
            cls = (w.wm_class or w.title).lower()
            match = next((k for k, g in groups.items() if g["app"] and cls in self._keys(g["app"])), None)
            if match is None:
                match = f"cls:{cls}"
                if match not in groups:
                    groups[match] = {"app": None, "wins": []}
                    order.append(match)
            groups[match]["wins"].append(w)

        for key in list(self.buttons):
            if key not in groups:
                b = self.buttons.pop(key)
                self.apps_lay.removeWidget(b)
                b.deleteLater()
        for idx, key in enumerate(order):
            g = groups[key]
            b = self.buttons.get(key)
            if b is None:
                icon = appreg.app_icon(g["app"]) if g["app"] else self._window_icon(g["wins"][0])
                tip = g["app"].name if g["app"] else (g["wins"][0].title or g["wins"][0].wm_class)
                b = TaskButton(self.p, icon, tip)
                b.clicked.connect(lambda _=False, k=key: self.activate(k))
                b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                b.customContextMenuRequested.connect(lambda _pos, k=key: self.jump_list(k))
                self.buttons[key] = b
            if self.apps_lay.indexOf(b) != idx:
                self.apps_lay.insertWidget(idx, b)
            b.group = g
            b.running = len(g["wins"])
            b.active = any(w.active for w in g["wins"])
            if g["wins"] and not g["app"]:
                b.setToolTip(g["wins"][0].title)
            b.update()

    def _window_icon(self, w):
        img = x11.wm().icon(w.wid)
        if img is not None and not img.isNull():
            return QIcon(QPixmap.fromImage(img))
        ic = QIcon.fromTheme(w.wm_class.lower())
        return ic if not ic.isNull() else icons.icon("file-exe")

    def activate(self, key):
        b = self.buttons.get(key)
        if not b:
            return
        g = b.group
        wins = g["wins"]
        wm = x11.wm()
        if not wins:
            if g["app"]:
                proc = g["app"].launch()
                if proc is not None:
                    self.launched[g["app"].id] = proc
            return
        if wins[0].wid == 0:  # no window manager access: bring the process to front (macOS)
            if sys.platform == "darwin":
                system._bg(["osascript", "-e", 'tell application "System Events" to set frontmost of '
                            f'(first process whose unix id is {wins[0].pid}) to true'])
            return
        if len(wins) == 1:
            w = wins[0]
            if w.active and not w.minimized:
                wm.minimize(w.wid)
            else:
                wm.activate(w.wid)
            return
        # several windows: cycle like Windows does on repeated clicks
        active_idx = next((i for i, w in enumerate(wins) if w.active), -1)
        wm.activate(wins[(active_idx + 1) % len(wins)].wid)

    def jump_list(self, key):
        b = self.buttons.get(key)
        if not b:
            return
        g = b.group
        m = QMenu(self)
        if g["app"]:
            m.addAction(appreg.app_icon(g["app"]), g["app"].name, g["app"].launch)
            pinned = g["app"].id in config.get("pinned_taskbar")

            def toggle_pin(app=g["app"], pinned=pinned):
                lst = [i for i in config.get("pinned_taskbar") if i != app.id]
                if not pinned:
                    lst.append(app.id)
                config.set("pinned_taskbar", lst)
                self.refresh(force=True)
            m.addAction(icons.icon("pin", self.p.text), "Unpin from taskbar" if pinned else "Pin to taskbar", toggle_pin)
        if g["wins"]:
            m.addSeparator()
            label = "Close window" if len(g["wins"]) == 1 else "Close all windows"
            m.addAction(icons.icon("close", self.p.text), label,
                        lambda: [x11.wm().close(w.wid) for w in g["wins"]])
        m.exec(self.cursor().pos())

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction(icons.icon("taskmgr"), "Task Manager", lambda: appreg.builtin_apps()["taskmgr"].launch())
        m.addSeparator()
        m.addAction(icons.icon("settings"), "Taskbar settings", lambda: system.open_settings("personalization"))
        m.exec(e.globalPos())
