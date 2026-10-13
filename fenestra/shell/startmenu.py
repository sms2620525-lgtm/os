"""Start menu: pinned grid, recommended files, All apps list and search."""

import getpass
import os
import pwd
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMenu, QPushButton, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ..common import platform as hostos
from ..common import apps as appreg
from ..common import config, icons, theme
from . import system


class Flyout(QFrame):
    """Base class: frameless translucent popup with rounded corners and acrylic tint."""

    closed = pyqtSignal()
    autohide = True   # hide when another window gets focus

    def __init__(self, p, radius=8):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.p = p
        self.radius = radius
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1, self.height() - 1, self.radius, self.radius)
        painter.fillPath(path, theme.rgba(self.p.flyout, opaque=not config.get("transparency")))
        painter.setPen(QColor(self.p.stroke))
        painter.drawPath(path)
        painter.end()

    def changeEvent(self, e):
        # Close when focus moves elsewhere (like Windows flyouts)
        from PyQt6.QtCore import QEvent
        if self.autohide and e.type() == QEvent.Type.ActivationChange and not self.isActiveWindow() and self.isVisible():
            self.hide()
            self.closed.emit()
        super().changeEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
            self.closed.emit()
        else:
            super().keyPressEvent(e)

    def popup_at(self, x, y):
        self.move(int(x), int(y))
        self.show()
        self.raise_()
        self.activateWindow()


class AppTile(QToolButton):
    def __init__(self, app, p, size=(96, 84)):
        super().__init__()
        self.app = app
        self.setText(app.name)
        self.setIcon(appreg.app_icon(app))
        self.setIconSize(QSize(32, 32))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setFixedSize(*size)
        self.setAutoRaise(True)
        self.setStyleSheet(f"QToolButton {{ border-radius: 4px; padding: 6px 2px; font-size: 8.5pt; }}"
                           f"QToolButton:hover {{ background: {p.surface_alt}; }}")


def user_display_name():
    try:
        gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0]
        return gecos or getpass.getuser()
    except KeyError:
        return getpass.getuser()


class StartMenu(Flyout):
    launched = pyqtSignal()

    def __init__(self, p, taskbar=None):
        super().__init__(p, radius=8)
        self.taskbar = taskbar
        self.setFixedSize(642, 726)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(32, 28, 32, 12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search for apps, settings, and documents")
        self.search.setFixedHeight(36)
        self.search.addAction(icons.icon("search", p.text_secondary), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setStyleSheet(f"QLineEdit {{ border-radius: 18px; padding-left: 10px; background: {p.surface}; }}")
        self.search.textChanged.connect(self.on_search)
        self.search.returnPressed.connect(self.launch_first)
        bl.addWidget(self.search)
        bl.addSpacing(18)

        self.pages = QStackedWidget()
        bl.addWidget(self.pages, 1)
        root.addWidget(body, 1)

        # --- main page: Pinned + Recommended
        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        hdr = QHBoxLayout()
        t = QLabel("Pinned")
        t.setStyleSheet("font-weight: 600; font-size: 10.5pt;")
        hdr.addWidget(t)
        hdr.addStretch()
        allb = QPushButton("All apps  ›")
        allb.setStyleSheet("QPushButton { padding: 2px 10px; font-size: 8.5pt; }")
        allb.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        hdr.addWidget(allb)
        ml.addLayout(hdr)
        self.pinned_grid = QGridLayout()
        self.pinned_grid.setSpacing(0)
        gw = QWidget()
        gw.setLayout(self.pinned_grid)
        ml.addWidget(gw)
        ml.addSpacing(12)
        hdr2 = QHBoxLayout()
        t2 = QLabel("Recommended")
        t2.setStyleSheet("font-weight: 600; font-size: 10.5pt;")
        hdr2.addWidget(t2)
        hdr2.addStretch()
        more = QPushButton("More  ›")
        more.setStyleSheet("QPushButton { padding: 2px 10px; font-size: 8.5pt; }")
        more.clicked.connect(lambda: self._open(appreg.builtin_apps()["explorer"]))
        hdr2.addWidget(more)
        ml.addLayout(hdr2)
        self.recommended = QGridLayout()
        self.recommended.setHorizontalSpacing(12)
        rw = QWidget()
        rw.setLayout(self.recommended)
        ml.addWidget(rw)
        ml.addStretch()
        self.pages.addWidget(main)

        # --- all apps
        allp = QWidget()
        al = QVBoxLayout(allp)
        al.setContentsMargins(0, 0, 0, 0)
        h3 = QHBoxLayout()
        t3 = QLabel("All apps")
        t3.setStyleSheet("font-weight: 600; font-size: 10.5pt;")
        h3.addWidget(t3)
        h3.addStretch()
        back = QPushButton("‹  Back")
        back.setStyleSheet("QPushButton { padding: 2px 10px; font-size: 8.5pt; }")
        back.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        h3.addWidget(back)
        al.addLayout(h3)
        self.all_list = QListWidget()
        self.all_list.setIconSize(QSize(24, 24))
        self.all_list.setStyleSheet("QListWidget { background: transparent; }")
        self.all_list.itemClicked.connect(self._item_launch)
        self.all_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.all_list.customContextMenuRequested.connect(self._all_menu)
        al.addWidget(self.all_list)
        self.pages.addWidget(allp)

        # --- search results
        sp = QWidget()
        sl = QVBoxLayout(sp)
        sl.setContentsMargins(0, 0, 0, 0)
        t4 = QLabel("Best match")
        t4.setStyleSheet("font-weight: 600;")
        sl.addWidget(t4)
        self.results = QListWidget()
        self.results.setIconSize(QSize(32, 32))
        self.results.setStyleSheet("QListWidget { background: transparent; } QListWidget::item { padding: 6px; }")
        self.results.itemClicked.connect(self._item_launch)
        sl.addWidget(self.results)
        self.pages.addWidget(sp)

        # --- bottom bar: user + power
        bar = QFrame()
        bar.setFixedHeight(64)
        rgba = p.surface
        bar.setStyleSheet(f"QFrame {{ background: {rgba}; border-top: 1px solid {p.stroke};"
                          f" border-bottom-left-radius: 8px; border-bottom-right-radius: 8px; }}")
        bb = QHBoxLayout(bar)
        bb.setContentsMargins(48, 0, 48, 0)
        user = QToolButton()
        user.setIcon(icons.icon("user", p.text))
        user.setIconSize(QSize(28, 28))
        user.setText("  " + user_display_name())
        user.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        user.setAutoRaise(True)
        user.setStyleSheet("QToolButton { border: none; padding: 6px 10px; border-radius: 4px; }")
        um = QMenu(user)
        um.addAction("Change account settings", lambda: (self.hide(), system.open_settings("accounts")))
        um.addAction("Lock", lambda: (self.hide(), system.power("lock")))
        um.addAction("Sign out", lambda: system.power("signout"))
        user.setMenu(um)
        user.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        bb.addWidget(user)
        bb.addStretch()
        pw = QToolButton()
        pw.setIcon(icons.icon("power", p.text))
        pw.setIconSize(QSize(16, 16))
        pw.setFixedSize(40, 40)
        pw.setAutoRaise(True)
        pw.setStyleSheet("QToolButton { border: none; border-radius: 4px; }")
        pm = QMenu(pw)
        pm.addAction(icons.icon("lock", p.text), "Lock", lambda: (self.hide(), system.power("lock")))
        pm.addAction(icons.icon("moon", p.text), "Sleep", lambda: system.power("sleep"))
        pm.addAction(icons.icon("power", p.text), "Shut down", lambda: system.power("shutdown"))
        pm.addAction(icons.icon("refresh", p.text), "Restart", lambda: system.power("restart"))
        pw.setMenu(pm)
        pw.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        bb.addWidget(pw)
        root.addWidget(bar)
        self.reload()

    # ------------------------------------------------------------------
    def reload(self):
        builtins = appreg.builtin_apps()
        self.all = appreg.all_apps()
        by_id = {a.id: a for a in self.all}
        while self.pinned_grid.count():
            w = self.pinned_grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        pinned = [by_id.get(i) or builtins.get(i) for i in config.get("pinned_start")]
        for n, app in enumerate([a for a in pinned if a][:18]):
            tile = AppTile(app, self.p)
            tile.clicked.connect(lambda _=False, a=app: self._open(a))
            tile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tile.customContextMenuRequested.connect(lambda _pos, a=app: self._pinned_menu(a))
            self.pinned_grid.addWidget(tile, n // 6, n % 6)

        while self.recommended.count():
            w = self.recommended.takeAt(0).widget()
            if w:
                w.deleteLater()
        from ..explorer.app import recent_files
        recent = recent_files()[:6]
        if not recent:
            lbl = QLabel("The more you use your device, the more we'll show your new apps and recent files here.")
            lbl.setWordWrap(True)
            lbl.setObjectName("Secondary")
            self.recommended.addWidget(lbl, 0, 0, 1, 2)
        for n, (path, when) in enumerate(recent):
            b = QToolButton()
            b.setIcon(icons.icon(icons.for_filename(path)))
            b.setIconSize(QSize(32, 32))
            b.setText(f"{Path(path).name}\n{when}")
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setFixedSize(270, 54)
            b.setAutoRaise(True)
            b.setStyleSheet(f"QToolButton {{ text-align: left; border-radius: 4px; font-size: 8.5pt; }}"
                            f"QToolButton:hover {{ background: {self.p.surface_alt}; }}")
            b.clicked.connect(lambda _=False, pth=path: (self.hide(), hostos.open_path(pth)))
            self.recommended.addWidget(b, n // 2, n % 2)

        self.all_list.clear()
        letter = None
        for app in self.all:
            first = app.name[:1].upper()
            first = first if first.isalpha() else "#"
            if first != letter:
                letter = first
                h = QListWidgetItem(letter)
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                f = h.font()
                f.setBold(True)
                h.setFont(f)
                h.setForeground(QColor(self.p.text))
                self.all_list.addItem(h)
            it = QListWidgetItem(appreg.app_icon(app), app.name)
            it.setData(Qt.ItemDataRole.UserRole, app.id)
            self.all_list.addItem(it)

    def _app_by_id(self, app_id):
        return next((a for a in self.all if a.id == app_id), None)

    def _open(self, app, *args):
        self.hide()
        app.launch(*args)
        self.launched.emit()

    def _item_launch(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, str) and data.startswith("cmd:"):
            self.hide()
            subprocess.Popen(data[4:], shell=True, start_new_session=True)
            return
        if isinstance(data, str) and data.startswith("url:"):
            self.hide()
            hostos.open_path(data[4:])
            return
        if isinstance(data, str) and data.startswith("file:"):
            self.hide()
            hostos.open_path(data[5:])
            return
        app = self._app_by_id(data)
        if app:
            self._open(app)

    def _pinned_menu(self, app):
        m = QMenu(self)
        m.addAction("Open", lambda: self._open(app))
        m.addAction("Unpin from Start", lambda: self._unpin(app))
        pinned_tb = app.id in config.get("pinned_taskbar")
        m.addAction("Unpin from taskbar" if pinned_tb else "Pin to taskbar", lambda: self._pin_taskbar(app, not pinned_tb))
        m.exec(self.cursor().pos())

    def _all_menu(self, pos):
        it = self.all_list.itemAt(pos)
        app = self._app_by_id(it.data(Qt.ItemDataRole.UserRole)) if it else None
        if not app:
            return
        m = QMenu(self)
        m.addAction("Pin to Start", lambda: self._pin_start(app))
        pinned_tb = app.id in config.get("pinned_taskbar")
        m.addAction("Unpin from taskbar" if pinned_tb else "Pin to taskbar", lambda: self._pin_taskbar(app, not pinned_tb))
        m.exec(self.all_list.viewport().mapToGlobal(pos))

    def _unpin(self, app):
        lst = [i for i in config.get("pinned_start") if i != app.id]
        config.set("pinned_start", lst)
        self.reload()

    def _pin_start(self, app):
        lst = config.get("pinned_start")
        if app.id not in lst:
            config.set("pinned_start", lst + [app.id])
        self.reload()

    def _pin_taskbar(self, app, pin):
        lst = [i for i in config.get("pinned_taskbar") if i != app.id]
        if pin:
            lst.append(app.id)
        config.set("pinned_taskbar", lst)
        if self.taskbar:
            self.taskbar.refresh(force=True)

    # --- search -------------------------------------------------------------
    SETTINGS_KEYWORDS = {
        "display": "system", "sound": "system", "wifi": "network", "wi-fi": "network", "bluetooth": "bluetooth",
        "background": "personalization", "theme": "personalization", "dark": "personalization",
        "update": "update", "apps": "apps", "users": "accounts", "account": "accounts", "time": "time",
        "language": "time", "privacy": "privacy", "about": "about",
    }

    def on_search(self, text):
        text = text.strip()
        if not text:
            self.pages.setCurrentIndex(0)
            return
        self.pages.setCurrentIndex(2)
        self.results.clear()
        q = text.lower()
        scored = []
        for app in self.all:
            name = app.name.lower()
            if name.startswith(q):
                scored.append((0, app))
            elif q in name:
                scored.append((1, app))
            elif q in app.keywords.lower():
                scored.append((2, app))
        for _, app in sorted(scored, key=lambda x: (x[0], x[1].name.lower()))[:8]:
            it = QListWidgetItem(appreg.app_icon(app), f"{app.name}\nApp")
            it.setData(Qt.ItemDataRole.UserRole, app.id)
            self.results.addItem(it)
        for key, page in self.SETTINGS_KEYWORDS.items():
            if key.startswith(q) or q.startswith(key):
                it = QListWidgetItem(icons.icon("settings"), f"{key.capitalize()} settings\nSystem settings")
                it.setData(Qt.ItemDataRole.UserRole, f"cmd:{sys.executable} -m fenestra.settings --page {page}")
                self.results.addItem(it)
        # files in home (shallow, fast)
        hits = 0
        for root, dirs, files in os.walk(Path.home()):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if root.count(os.sep) - str(Path.home()).count(os.sep) > 3:
                dirs[:] = []
            for f in files:
                if q in f.lower():
                    full = os.path.join(root, f)
                    it = QListWidgetItem(icons.icon(icons.for_filename(f)), f"{f}\n{root}")
                    it.setData(Qt.ItemDataRole.UserRole, f"file:{full}")
                    self.results.addItem(it)
                    hits += 1
                    if hits >= 6:
                        break
            if hits >= 6:
                break
        if self.results.count() == 0 or text.startswith(("http", "www.")) or " " in text:
            it = QListWidgetItem(icons.icon("browser"), f"{text} - See web results\nSearch the web")
            import urllib.parse
            it.setData(Qt.ItemDataRole.UserRole, f"url:https://duckduckgo.com/?q={urllib.parse.quote(text)}")
            self.results.addItem(it)
        if self.results.count():
            self.results.setCurrentRow(0)

    def launch_first(self):
        it = self.results.currentItem() or (self.results.item(0) if self.results.count() else None)
        if it:
            self._item_launch(it)

    def toggle(self, x, y):
        if self.isVisible():
            self.hide()
            return
        self.search.clear()
        self.pages.setCurrentIndex(0)
        self.popup_at(x, y)
        self.search.setFocus()

    def keyPressEvent(self, e):
        # Typing anywhere goes to the search box, like Windows
        if e.text() and e.text().isprintable() and not self.search.hasFocus():
            self.search.setFocus()
            self.search.setText(self.search.text() + e.text())
            return
        super().keyPressEvent(e)
