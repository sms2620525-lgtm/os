"""Desktop window: wallpaper and desktop icons (This PC, Recycle Bin, ~/Desktop)."""

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QListView, QListWidget, QListWidgetItem, QMenu, QVBoxLayout, QWidget

from ..common import platform as hostos
from ..common import config, icons, x11
from . import system, wallpaper


class Desktop(QWidget):
    def __init__(self, p, screen, parent=None):
        if parent is None:
            super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnBottomHint)
        else:  # windowed mode: child of the Fenestra window
            super().__init__(parent)
        self.p = p
        self.screen_ = screen
        self.embedded = parent is not None
        self.setWindowTitle("fenestra-desktop")
        self.setGeometry(parent.rect() if parent is not None else screen.geometry())
        self.bg = QPixmap()
        self.load_wallpaper()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 52)
        self.icons = QListWidget()
        self.icons.setViewMode(QListView.ViewMode.IconMode)
        self.icons.setFlow(QListView.Flow.TopToBottom)
        self.icons.setWrapping(True)
        self.icons.setMovement(QListView.Movement.Snap)
        self.icons.setGridSize(QSize(84, 92))
        self.icons.setIconSize(QSize(44, 44))
        self.icons.setWordWrap(True)
        self.icons.setSpacing(2)
        self.icons.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.icons.setFrameShape(QListWidget.Shape.NoFrame)
        self.icons.setStyleSheet(
            "QListWidget { background: transparent; color: white; }"
            "QListWidget::item { color: white; border-radius: 2px; padding: 2px; }"
            "QListWidget::item:hover { background: rgba(255,255,255,0.18); }"
            "QListWidget::item:selected { background: rgba(255,255,255,0.32); border: 1px solid rgba(255,255,255,0.5); }")
        shadow = QGraphicsDropShadowEffect(self.icons)
        shadow.setBlurRadius(6)
        shadow.setOffset(1, 1)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.icons.setGraphicsEffect(shadow)
        self.icons.itemDoubleClicked.connect(self.open_item)
        self.icons.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.icons.customContextMenuRequested.connect(self.menu)
        lay.addWidget(self.icons)

        self.desktop_dir = self._desktop_dir()
        self.desktop_dir.mkdir(parents=True, exist_ok=True)
        self.watcher = QFileSystemWatcher([str(self.desktop_dir)])
        self.watcher.directoryChanged.connect(lambda _: QTimer.singleShot(200, self.reload))
        self.reload()

    @staticmethod
    def _desktop_dir() -> Path:
        from ..explorer.app import SPECIAL
        return SPECIAL[0][2]

    def load_wallpaper(self):
        g = self.rect() if self.embedded else self.screen_.geometry()
        path = config.get("wallpaper")
        if not path or not os.path.exists(path):
            shipped = f"/usr/share/fenestra/wallpaper{'-dark' if self.p.dark else ''}.png"
            path = shipped if os.path.exists(shipped) else wallpaper.cached(g.width(), g.height(), self.p.dark)
        pm = QPixmap(path)
        self.bg = pm.scaled(g.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.embedded:
            self.load_wallpaper()

    def show(self):
        if not self.embedded:
            # The window manager reads the window type only when the window is mapped,
            # so create the native window and tag it before showing it.
            x11.wm().set_type(int(self.winId()), "DESKTOP", ("BELOW", "STICKY", "SKIP_TASKBAR"))
        super().show()
        if not self.embedded:
            self.lower()

    def paintEvent(self, e):
        p = QPainter(self)
        if not self.bg.isNull():
            x = (self.width() - self.bg.width()) // 2
            y = (self.height() - self.bg.height()) // 2
            p.drawPixmap(x, y, self.bg)
        else:
            p.fillRect(self.rect(), QColor("#0063b1"))
        p.end()

    def reload(self):
        self.icons.clear()
        specials = [("This PC", "monitor", "shell:thispc"), ("Recycle Bin", "trash", "shell:trash"),
                    ("Home", "home", str(Path.home()))]
        for name, ic, target in specials:
            it = QListWidgetItem(icons.icon(ic), name)
            it.setData(Qt.ItemDataRole.UserRole, target)
            self.icons.addItem(it)
        try:
            entries = sorted(self.desktop_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            entries = []
        for f in entries:
            if f.name.startswith("."):
                continue
            name = f.name
            icon = icons.icon("folder" if f.is_dir() else icons.for_filename(f.name))
            if f.suffix == ".desktop":
                name, icon = self._desktop_entry(f, icon)
            it = QListWidgetItem(icon, name)
            it.setData(Qt.ItemDataRole.UserRole, str(f))
            it.setToolTip(str(f))
            self.icons.addItem(it)

    @staticmethod
    def _desktop_entry(f, default_icon):
        from PyQt6.QtGui import QIcon
        name, icon = f.stem, default_icon
        try:
            for line in f.read_text(errors="replace").splitlines():
                if line.startswith("Name=") and name == f.stem:
                    name = line[5:]
                elif line.startswith("Icon="):
                    val = line[5:]
                    ic = QIcon(val) if os.path.isabs(val) else QIcon.fromTheme(val)
                    if not ic.isNull():
                        icon = ic
        except OSError:
            pass
        return name, icon

    def open_item(self, item):
        target = item.data(Qt.ItemDataRole.UserRole)
        if target.startswith("shell:") or os.path.isdir(target):
            subprocess.Popen([sys.executable, "-m", "fenestra.explorer", target], start_new_session=True)
        else:
            from ..explorer.app import open_path
            open_path(target)

    def menu(self, pos):
        item = self.icons.itemAt(pos)
        m = QMenu(self)
        if item:
            target = item.data(Qt.ItemDataRole.UserRole)
            m.addAction("Open", lambda: self.open_item(item))
            if not target.startswith("shell:") and target != str(Path.home()):
                m.addAction("Delete", lambda: self._trash(target))
                m.addAction("Rename", lambda: self._rename(target))
            if target == "shell:trash":
                from ..explorer import fileops
                m.addAction("Empty Recycle Bin", fileops.empty_trash)
            m.exec(self.icons.viewport().mapToGlobal(pos))
            return
        view = m.addMenu(icons.icon("view", self.p.text), "View")
        for label, size in (("Large icons", 64), ("Medium icons", 44), ("Small icons", 28)):
            view.addAction(label, lambda s=size: (self.icons.setIconSize(QSize(s, s)),
                                                   self.icons.setGridSize(QSize(s + 40, s + 48))))
        sort = m.addMenu(icons.icon("sort", self.p.text), "Sort by")
        sort.addAction("Name", lambda: self.icons.sortItems())
        m.addAction(icons.icon("refresh", self.p.text), "Refresh", self.reload)
        m.addSeparator()
        new = m.addMenu(icons.icon("plus", self.p.text), "New")
        new.addAction(icons.icon("folder"), "Folder", lambda: self._new("New folder", None))
        new.addAction(icons.icon("file-text"), "Text Document", lambda: self._new("New Text Document", ".txt"))
        m.addSeparator()
        m.addAction(icons.icon("monitor"), "Display settings", lambda: system.open_settings("system"))
        m.addAction(icons.icon("photos"), "Personalize", lambda: system.open_settings("personalization"))
        m.addSeparator()
        m.addAction(icons.icon("terminal"), "Open in Terminal",
                    lambda: hostos.open_terminal(str(self.desktop_dir)))
        m.exec(self.icons.viewport().mapToGlobal(pos))

    def _new(self, base, suffix):
        from ..explorer import fileops
        target = fileops.new_name(self.desktop_dir, base, suffix or "")
        if suffix is None:
            target.mkdir()
        else:
            target.write_text("")

    def _trash(self, target):
        from ..explorer import fileops
        fileops.trash(target)

    def _rename(self, target):
        from PyQt6.QtWidgets import QInputDialog
        p = Path(target)
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=p.name)
        if ok and name and name != p.name:
            p.rename(p.with_name(name))
