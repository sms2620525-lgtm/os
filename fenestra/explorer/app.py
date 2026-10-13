"""File Explorer - modelled on the Windows 11 File Explorer (tabs, command bar)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import psutil
from PyQt6.QtCore import (QDir, QFileInfo, QIdentityProxyModel, QMimeData, QObject, QSize, Qt,
                          QThread, QTimer, QUrl, pyqtSignal)
from PyQt6.QtGui import QFileSystemModel, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QFileIconProvider,
                             QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                             QInputDialog, QLabel, QLineEdit, QListView, QMenu, QMessageBox, QProgressBar,
                             QPushButton, QScrollArea, QSplitter, QStackedWidget, QTabBar, QToolButton,
                             QTreeView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QWidgetAction)

from ..common import platform as hostos
from ..common import icons, theme
from ..common.window import FluentWindow
from ..common.widgets import human_bytes
from . import fileops

HOME = Path.home()


def xdg_dir(name: str, fallback: str) -> Path:
    """Read ~/.config/user-dirs.dirs (handles localised folder names)."""
    cfg = HOME / ".config/user-dirs.dirs"
    try:
        for line in cfg.read_text().splitlines():
            if line.startswith(f"XDG_{name}_DIR="):
                val = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(HOME))
                return Path(val)
    except OSError:
        pass
    return HOME / fallback


SPECIAL = [
    ("Desktop", "desktop-folder", xdg_dir("DESKTOP", "Desktop")),
    ("Downloads", "downloads-folder", xdg_dir("DOWNLOAD", "Downloads")),
    ("Documents", "documents-folder", xdg_dir("DOCUMENTS", "Documents")),
    ("Pictures", "pictures-folder", xdg_dir("PICTURES", "Pictures")),
    ("Music", "music-folder", xdg_dir("MUSIC", "Music")),
    ("Videos", "videos-folder", xdg_dir("VIDEOS", "Videos")),
]
SPECIAL_ICONS = {str(p): ic for _, ic, p in SPECIAL}

SHELL_HOME, SHELL_PC, SHELL_TRASH, SHELL_NET, SHELL_GALLERY = "shell:home", "shell:thispc", "shell:trash", "shell:network", "shell:gallery"
SHELL_NAMES = {SHELL_HOME: "Home", SHELL_PC: "This PC", SHELL_TRASH: "Recycle Bin", SHELL_NET: "Network",
               SHELL_GALLERY: "Gallery"}
SHELL_ICONS = {SHELL_HOME: "home", SHELL_PC: "monitor", SHELL_TRASH: "trash", SHELL_NET: "monitor",
               SHELL_GALLERY: "photos"}

PINNED_FILE = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "fenestra" / "pinned-folders"
RECENT_FILE = HOME / ".local/share/recently-used.xbel"


def display_name(loc: str) -> str:
    if loc in SHELL_NAMES:
        return SHELL_NAMES[loc]
    if loc.startswith("search:"):
        return f"Search Results in {Path(loc.split(':', 2)[1]).name}"
    if loc == str(HOME):
        return HOME.name
    return Path(loc).name or loc


class IconProvider(QFileIconProvider):
    def icon(self, info):
        if isinstance(info, QFileInfo):
            path = info.absoluteFilePath()
            if info.isDir():
                if path in SPECIAL_ICONS:
                    return icons.icon(SPECIAL_ICONS[path])
                if path == str(HOME):
                    return icons.icon("home")
                return icons.icon("folder")
            return icons.icon(icons.for_filename(info.fileName()))
        if info == QFileIconProvider.IconType.Drive:
            return icons.icon("drive")
        if info == QFileIconProvider.IconType.Computer:
            return icons.icon("monitor")
        return icons.icon("folder")

    def type(self, info):
        return fileops.type_name(Path(info.fileName()), info.isDir())


class WinModel(QIdentityProxyModel):
    """Formats QFileSystemModel columns like Windows (KB sizes, friendly types).

    Logical columns stay Name|Size|Type|Date; the details view moves the
    header sections visually to Name|Date modified|Type|Size.
    """

    HEADERS = {0: "Name", 1: "Size", 2: "Type", 3: "Date modified"}
    SORT_ORDER = [(0, "Name"), (3, "Date modified"), (2, "Type"), (1, "Size")]

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole and section in self.HEADERS:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and index.column() in (1, 3):
            info = self.sourceModel().fileInfo(self.mapToSource(index))
            if index.column() == 3:
                return fileops.fmt_time(info.lastModified().toSecsSinceEpoch())
            if info.isDir():
                return ""
            return f"{(info.size() + 1023) // 1024:,} KB"
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() == 1:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return super().data(index, role)

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.sourceModel().sort(column, order)

    def filePath(self, index):
        return self.sourceModel().filePath(self.mapToSource(index))

    def isDir(self, index):
        return self.sourceModel().isDir(self.mapToSource(index))


# --------------------------------------------------------------------------
class Worker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args
        self.cancel = False

    def run(self):
        try:
            self.fn(*self.args, progress=lambda d, t, n: self.progress.emit(int(d * 1000 / max(1, t)), 1000, n),
                    cancelled=lambda: self.cancel)
            self.finished.emit("")
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(str(exc))


class ProgressDialog(QDialog):
    """Windows-style '% complete' copy dialog."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        self.label = QLabel(title)
        self.label.setObjectName("Subtitle")
        self.name = QLabel("")
        self.name.setObjectName("Secondary")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        for w in (self.label, self.name, self.bar):
            lay.addWidget(w)
        lay.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignRight)

    def update_progress(self, done, total, name):
        self.bar.setValue(done)
        self.label.setText(f"{done // 10}% complete")
        self.name.setText(name)


# --------------------------------------------------------------------------
class AddressBar(QFrame):
    navigate = pyqtSignal(str)

    def __init__(self, p):
        super().__init__()
        self.p = p
        self.setObjectName("Address")
        self.setStyleSheet(f"QFrame#Address {{ background: {p.surface}; border: 1px solid {p.stroke}; border-radius: 4px; }}")
        self.setFixedHeight(32)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(6, 0, 6, 0)
        self.lay.setSpacing(0)
        self.crumbs = QWidget()
        self.crumb_lay = QHBoxLayout(self.crumbs)
        self.crumb_lay.setContentsMargins(0, 0, 0, 0)
        self.crumb_lay.setSpacing(0)
        self.edit = QLineEdit()
        self.edit.setStyleSheet("QLineEdit { border: none; background: transparent; }")
        self.edit.hide()
        self.edit.returnPressed.connect(self._commit)
        self.edit.editingFinished.connect(self._end_edit)
        self.lay.addWidget(self.crumbs, 1)
        self.lay.addWidget(self.edit, 1)
        self.location = ""

    def set_location(self, loc):
        self.location = loc
        while self.crumb_lay.count():
            it = self.crumb_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        ic = QLabel()
        ic.setPixmap(icons.pixmap(self._icon_for(loc), 16))
        self.crumb_lay.addWidget(ic)
        parts = []
        if loc.startswith("shell:") or loc.startswith("search:"):
            parts = [(display_name(loc), loc)]
        else:
            p = Path(loc)
            if p == HOME or HOME in p.parents:
                parts.append((HOME.name, str(HOME)))
                for part in p.relative_to(HOME).parts:
                    parts.append((part, str(Path(parts[-1][1]) / part)))
            else:
                parts.append(("This PC", SHELL_PC))
                acc = Path("/")
                parts.append(("File System (/)", "/"))
                for part in p.parts[1:]:
                    acc = acc / part
                    parts.append((part, str(acc)))
        sep_pm = icons.pixmap("chevron-right", 10, self.p.text_secondary)
        for i, (name, target) in enumerate(parts):
            sep = QLabel()
            sep.setPixmap(sep_pm)
            sep.setContentsMargins(6, 0, 6, 0)
            self.crumb_lay.addWidget(sep)
            b = QPushButton(name)
            b.setObjectName("Flat")
            b.setStyleSheet("QPushButton { padding: 2px 6px; min-height: 0; }")
            b.clicked.connect(lambda _=False, t=target: self.navigate.emit(t))
            self.crumb_lay.addWidget(b)
        self.crumb_lay.addStretch()

    def _icon_for(self, loc):
        if loc in SHELL_ICONS:
            return SHELL_ICONS[loc]
        if loc in SPECIAL_ICONS:
            return SPECIAL_ICONS[loc]
        if loc.startswith("search:"):
            return "folder"
        return "home" if loc == str(HOME) else "folder"

    def mousePressEvent(self, e):
        self.start_edit()

    def start_edit(self):
        self.crumbs.hide()
        self.edit.show()
        self.edit.setText(self.location if not self.location.startswith("shell:") else display_name(self.location))
        self.edit.selectAll()
        self.edit.setFocus()

    def _commit(self):
        text = self.edit.text().strip()
        mapping = {v.lower(): k for k, v in SHELL_NAMES.items()}
        target = mapping.get(text.lower(), os.path.expanduser(text))
        if text.lower() in ("cmd", "powershell", "terminal", "wt"):
            hostos.open_terminal(self.location if os.path.isdir(self.location) else str(HOME))
            target = self.location
        self.navigate.emit(target)
        self._end_edit()

    def _end_edit(self):
        self.edit.hide()
        self.crumbs.show()


# --------------------------------------------------------------------------
class HomePage(QScrollArea):
    open_location = pyqtSignal(str)

    def __init__(self, p):
        super().__init__()
        self.p = p
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget()
        self.lay = QVBoxLayout(w)
        self.lay.setContentsMargins(20, 12, 20, 12)
        self.setWidget(w)
        self.reload()

    def reload(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        t = QLabel("Quick access")
        t.setObjectName("Subtitle")
        self.lay.addWidget(t)
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (name, ic, path) in enumerate(SPECIAL + [(n, "folder", Path(x)) for n, x in pinned_folders()]):
            b = QToolButton()
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setIcon(icons.icon(ic))
            b.setIconSize(QSize(40, 40))
            b.setText(f"{name}\nStored locally")
            b.setFixedSize(220, 60)
            b.clicked.connect(lambda _=False, p=str(path): self.open_location.emit(p))
            grid.addWidget(b, i // 4, i % 4)
        gw = QWidget()
        gw.setLayout(grid)
        self.lay.addWidget(gw, alignment=Qt.AlignmentFlag.AlignLeft)
        t2 = QLabel("Recent")
        t2.setObjectName("Subtitle")
        self.lay.addWidget(t2)
        tree = QTreeWidget()
        tree.setHeaderLabels(["Name", "Date accessed", "File location"])
        tree.setRootIsDecorated(False)
        tree.setColumnWidth(0, 320)
        tree.setColumnWidth(1, 180)
        for path, when in recent_files()[:25]:
            it = QTreeWidgetItem([Path(path).name, when, str(Path(path).parent)])
            it.setIcon(0, icons.icon(icons.for_filename(path)))
            it.setData(0, Qt.ItemDataRole.UserRole, path)
            tree.addTopLevelItem(it)
        tree.itemDoubleClicked.connect(lambda it, _c: open_path(it.data(0, Qt.ItemDataRole.UserRole)))
        tree.setMinimumHeight(260)
        self.lay.addWidget(tree, 1)


def pinned_folders():
    try:
        return [(Path(l).name, l) for l in PINNED_FILE.read_text().splitlines() if l.strip()]
    except OSError:
        return []


def pin_folder(path, pin=True):
    current = [p for _, p in pinned_folders()]
    if pin and path not in current:
        current.append(path)
    if not pin and path in current:
        current.remove(path)
    PINNED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PINNED_FILE.write_text("\n".join(current) + "\n")


def recent_files():
    import re
    import urllib.parse
    try:
        data = RECENT_FILE.read_text(errors="replace")
    except OSError:
        return []
    out = []
    for m in re.finditer(r'<bookmark href="file://([^"]+)"[^>]*?visited="([^"]+)"', data):
        path = urllib.parse.unquote(m.group(1))
        if os.path.exists(path):
            out.append((path, m.group(2)[:16].replace("T", " ")))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def clipboard_has_urls() -> bool:
    md = QApplication.clipboard().mimeData()
    return bool(md and md.hasUrls())


def open_path(path):
    p = str(path)
    if p.lower().endswith((".exe", ".msi", ".bat", ".cmd", ".lnk", ".reg", ".ps1")):
        subprocess.Popen([sys.executable, "-m", "fenestra.compat", "run", p], start_new_session=True)
    elif p.endswith(".desktop"):
        if shutil.which("gtk-launch"):
            subprocess.Popen(["gtk-launch", Path(p).stem])
        else:
            hostos.open_path(p)
    else:
        hostos.open_path(p)


class ThisPCPage(QScrollArea):
    open_location = pyqtSignal(str)

    def __init__(self, p):
        super().__init__()
        self.p = p
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.reload()

    def reload(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 12, 20, 12)
        t = QLabel("Folders")
        t.setObjectName("Subtitle")
        lay.addWidget(t)
        grid = QGridLayout()
        for i, (name, ic, path) in enumerate(SPECIAL):
            b = QToolButton()
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setIcon(icons.icon(ic))
            b.setIconSize(QSize(40, 40))
            b.setText(name)
            b.setFixedSize(220, 56)
            b.clicked.connect(lambda _=False, p=str(path): self.open_location.emit(p))
            grid.addWidget(b, i // 3, i % 3)
        gw = QWidget()
        gw.setLayout(grid)
        lay.addWidget(gw, alignment=Qt.AlignmentFlag.AlignLeft)
        t2 = QLabel("Devices and drives")
        t2.setObjectName("Subtitle")
        lay.addWidget(t2)
        dgrid = QGridLayout()
        letter = ord("C")
        for i, part in enumerate(drives()):
            try:
                u = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            card = QToolButton()
            card.setFixedSize(300, 70)
            card.clicked.connect(lambda _=False, m=part.mountpoint: self.open_location.emit(m))
            cl = QHBoxLayout(card)
            ic = QLabel()
            ic.setPixmap(icons.pixmap("drive", 40))
            ic.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            cl.addWidget(ic)
            col = QVBoxLayout()
            label = "Local Disk" if part.mountpoint == "/" else (Path(part.mountpoint).name or part.mountpoint)
            name = QLabel(f"{label} ({chr(letter)}:)" if part.mountpoint == "/" else f"{label} ({part.mountpoint})")
            letter += 1
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(u.percent))
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            if u.percent > 90:
                bar.setStyleSheet("QProgressBar::chunk { background: #c42b1c; }")
            free = QLabel(f"{human_bytes(u.free)} free of {human_bytes(u.total)}")
            free.setObjectName("Secondary")
            for x in (name, bar, free):
                x.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                col.addWidget(x)
            cl.addLayout(col, 1)
            dgrid.addWidget(card, i // 3, i % 3)
        dw = QWidget()
        dw.setLayout(dgrid)
        lay.addWidget(dw, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch()
        self.setWidget(w)


def drives():
    seen, out = set(), []
    for part in psutil.disk_partitions(all=False):
        if part.mountpoint.startswith(("/snap", "/boot/efi", "/var/lib")) or part.device in seen:
            continue
        if part.fstype in ("squashfs", "overlay", "tmpfs"):
            continue
        seen.add(part.device)
        out.append(part)
    if not out:
        class _P:
            mountpoint, device, fstype = "/", "rootfs", ""
        out.append(_P())
    return out


# --------------------------------------------------------------------------
class ExplorerTab(QWidget):
    location_changed = pyqtSignal(str)
    selection_changed = pyqtSignal()

    def __init__(self, win, start):
        super().__init__()
        self.win = win
        self.p = win.p
        self.back_stack, self.fwd_stack = [], []
        self.location = ""
        self.view_mode = "details"
        self.show_hidden = False

        self.fs = QFileSystemModel(self)
        self.fs.setIconProvider(IconProvider())
        self.fs.setReadOnly(False)
        self.fs.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs)
        self.fs.setRootPath("/")
        self.model = WinModel(self)
        self.model.setSourceModel(self.fs)

        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)

        self.home = HomePage(self.p)
        self.home.open_location.connect(self.navigate)
        self.pc = ThisPCPage(self.p)
        self.pc.open_location.connect(self.navigate)

        self.details = QTreeView()
        self.details.setModel(self.model)
        self.details.setRootIsDecorated(False)
        self.details.setItemsExpandable(False)
        self.details.setSortingEnabled(True)
        self.details.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.details.setUniformRowHeights(True)
        self.details.header().moveSection(3, 1)   # Date modified
        self.details.header().moveSection(3, 2)   # Type before Size
        self.details.setColumnWidth(0, 320)
        self.details.setColumnWidth(3, 170)
        self.details.setColumnWidth(2, 150)
        self.details.setColumnWidth(1, 100)
        self.details.header().setStretchLastSection(False)
        self.details.header().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.icons_view = QListView()
        self.icons_view.setModel(self.model)
        self.icons_view.setViewMode(QListView.ViewMode.IconMode)
        self.icons_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.icons_view.setMovement(QListView.Movement.Static)
        self.icons_view.setWordWrap(True)
        self.icons_view.setUniformItemSizes(True)

        for v in (self.details, self.icons_view):
            v.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            v.setDragEnabled(True)
            v.setAcceptDrops(True)
            v.setDropIndicatorShown(True)
            v.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
            v.setDefaultDropAction(Qt.DropAction.MoveAction)
            v.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed | QAbstractItemView.EditTrigger.SelectedClicked)
            v.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            v.customContextMenuRequested.connect(self.context_menu)
            v.doubleClicked.connect(self.activate)
            v.selectionModel().selectionChanged.connect(lambda *_: self.selection_changed.emit())

        self.trash_view = QTreeWidget()
        self.trash_view.setHeaderLabels(["Name", "Original location", "Date deleted", "Size"])
        self.trash_view.setRootIsDecorated(False)
        self.trash_view.setColumnWidth(0, 260)
        self.trash_view.setColumnWidth(1, 300)
        self.trash_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.trash_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.trash_view.customContextMenuRequested.connect(self.trash_menu)
        self.trash_view.itemSelectionChanged.connect(self.selection_changed.emit)

        self.search_view = QTreeWidget()
        self.search_view.setHeaderLabels(["Name", "Folder", "Date modified", "Size"])
        self.search_view.setRootIsDecorated(False)
        self.search_view.setColumnWidth(0, 280)
        self.search_view.setColumnWidth(1, 320)
        self.search_view.itemDoubleClicked.connect(lambda it, _c: self.activate_path(it.data(0, Qt.ItemDataRole.UserRole)))
        self.search_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.search_view.customContextMenuRequested.connect(self.context_menu)
        self.search_view.itemSelectionChanged.connect(self.selection_changed.emit)

        for w in (self.home, self.pc, self.details, self.icons_view, self.trash_view, self.search_view):
            self.stack.addWidget(w)
        self.navigate(start, record=False)

    # --- navigation -------------------------------------------------------
    def navigate(self, loc, record=True):
        loc = str(loc)
        if not (loc.startswith("shell:") or loc.startswith("search:")):
            if not os.path.isdir(loc):
                if os.path.isfile(loc):
                    open_path(loc)
                    return
                QMessageBox.warning(self, "File Explorer", f"Fenestra can't find '{loc}'. Check the spelling and try again.")
                return
            loc = str(Path(loc).resolve())
        if record and self.location and loc != self.location:
            self.back_stack.append(self.location)
            self.fwd_stack.clear()
        self.location = loc
        self._show()
        self.location_changed.emit(loc)

    def _show(self):
        loc = self.location
        if loc == SHELL_HOME:
            self.home.reload()
            self.stack.setCurrentWidget(self.home)
        elif loc == SHELL_PC:
            self.pc.reload()
            self.stack.setCurrentWidget(self.pc)
        elif loc == SHELL_TRASH:
            self.load_trash()
            self.stack.setCurrentWidget(self.trash_view)
        elif loc in (SHELL_NET, SHELL_GALLERY):
            target = SPECIAL[3][2] if loc == SHELL_GALLERY else Path("/")
            self.location = str(target) if loc == SHELL_GALLERY else self.location
            if loc == SHELL_GALLERY:
                self.set_view("large")
                self._show()
            else:
                self.stack.setCurrentWidget(self.pc)
        elif loc.startswith("search:"):
            self.stack.setCurrentWidget(self.search_view)
        else:
            root = self.fs.setRootPath(loc)
            idx = self.model.mapFromSource(root)
            self.details.setRootIndex(idx)
            self.icons_view.setRootIndex(idx)
            self.stack.setCurrentWidget(self.details if self.view_mode in ("details", "list") else self.icons_view)

    def back(self):
        if self.back_stack:
            self.fwd_stack.append(self.location)
            self.location = self.back_stack.pop()
            self._show()
            self.location_changed.emit(self.location)

    def forward(self):
        if self.fwd_stack:
            self.back_stack.append(self.location)
            self.location = self.fwd_stack.pop()
            self._show()
            self.location_changed.emit(self.location)

    def up(self):
        if self.is_folder():
            parent = str(Path(self.location).parent)
            if parent != self.location:
                self.navigate(parent)
            else:
                self.navigate(SHELL_PC)
        elif self.location != SHELL_HOME:
            self.navigate(SHELL_HOME)

    def refresh(self):
        self._show()

    def is_folder(self):
        return not (self.location.startswith("shell:") or self.location.startswith("search:"))

    # --- views -----------------------------------------------------------
    def set_view(self, mode):
        self.view_mode = mode
        sizes = {"xl": 192, "large": 96, "medium": 48, "small": 16, "tiles": 48, "content": 32}
        if mode in sizes:
            s = sizes[mode]
            self.icons_view.setIconSize(QSize(s, s))
            if mode == "small":
                self.icons_view.setViewMode(QListView.ViewMode.ListMode)
                self.icons_view.setFlow(QListView.Flow.LeftToRight)
                self.icons_view.setWrapping(True)
                self.icons_view.setGridSize(QSize(220, 24))
            elif mode == "tiles":
                self.icons_view.setViewMode(QListView.ViewMode.ListMode)
                self.icons_view.setFlow(QListView.Flow.LeftToRight)
                self.icons_view.setWrapping(True)
                self.icons_view.setGridSize(QSize(260, 64))
            else:
                self.icons_view.setViewMode(QListView.ViewMode.IconMode)
                self.icons_view.setGridSize(QSize(s + 56, s + 48))
        elif mode == "list":
            self.icons_view.setViewMode(QListView.ViewMode.ListMode)
            self.icons_view.setIconSize(QSize(16, 16))
            self.icons_view.setFlow(QListView.Flow.TopToBottom)
            self.icons_view.setWrapping(True)
            self.icons_view.setGridSize(QSize(240, 22))
            self.view_mode = "list-icons"
        if self.is_folder():
            self.stack.setCurrentWidget(self.details if self.view_mode == "details" else self.icons_view)

    def toggle_hidden(self, on):
        self.show_hidden = on
        f = QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs
        if on:
            f |= QDir.Filter.Hidden
        self.fs.setFilter(f)

    def current_view(self):
        w = self.stack.currentWidget()
        return w if w in (self.details, self.icons_view) else None

    def selected_paths(self):
        w = self.stack.currentWidget()
        if w in (self.details, self.icons_view):
            rows = w.selectionModel().selectedRows(0) if w is self.details else \
                [i for i in w.selectionModel().selectedIndexes() if i.column() == 0]
            return [self.model.filePath(i) for i in rows]
        if w is self.trash_view or w is self.search_view:
            return [it.data(0, Qt.ItemDataRole.UserRole) for it in w.selectedItems()]
        return []

    def activate(self, index):
        self.activate_path(self.model.filePath(index))

    def activate_path(self, path):
        if os.path.isdir(path):
            self.navigate(path)
        else:
            open_path(path)

    def item_count(self):
        w = self.stack.currentWidget()
        if w in (self.details, self.icons_view):
            return self.model.rowCount(w.rootIndex())
        if w in (self.trash_view, self.search_view):
            return w.topLevelItemCount()
        return 0

    # --- trash -----------------------------------------------------------
    def load_trash(self):
        self.trash_view.clear()
        for trashed, orig, date in fileops.trash_items():
            size = fileops.total_size([trashed]) if trashed.exists() else 0
            it = QTreeWidgetItem([trashed.name, str(Path(orig).parent), date.replace("T", " "), f"{(size + 1023) // 1024:,} KB"])
            it.setIcon(0, icons.icon("folder" if trashed.is_dir() else icons.for_filename(trashed.name)))
            it.setData(0, Qt.ItemDataRole.UserRole, str(trashed))
            self.trash_view.addTopLevelItem(it)

    def trash_menu(self, pos):
        m = QMenu(self)
        m.addAction("Restore", self.restore_selected)
        m.addAction("Delete", self.delete_trash_selected)
        m.addSeparator()
        m.addAction("Empty Recycle Bin", self.win.empty_trash)
        m.exec(self.trash_view.viewport().mapToGlobal(pos))

    def restore_selected(self):
        for p in self.selected_paths():
            fileops.restore(Path(p))
        self.load_trash()

    def delete_trash_selected(self):
        for p in self.selected_paths():
            fileops.delete_permanently(p)
            (fileops.TRASH / "info" / f"{Path(p).name}.trashinfo").unlink(missing_ok=True)
        self.load_trash()

    # --- search ----------------------------------------------------------
    def search(self, text):
        base = self.location if self.is_folder() else (self.location.split(":", 2)[1] if self.location.startswith("search:") else str(HOME))
        if not text:
            if self.location.startswith("search:"):
                self.navigate(base)
            return
        self.navigate(f"search:{base}:{text}")
        self.search_view.clear()
        q = text.lower()
        count = 0
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".") or self.show_hidden]
            for name in dirs + files:
                if q in name.lower():
                    full = os.path.join(root, name)
                    try:
                        st = os.stat(full)
                    except OSError:
                        continue
                    isdir = os.path.isdir(full)
                    it = QTreeWidgetItem([name, root, fileops.fmt_time(st.st_mtime),
                                          "" if isdir else f"{(st.st_size + 1023) // 1024:,} KB"])
                    it.setIcon(0, icons.icon("folder" if isdir else icons.for_filename(name)))
                    it.setData(0, Qt.ItemDataRole.UserRole, full)
                    self.search_view.addTopLevelItem(it)
                    count += 1
                    if count % 50 == 0:
                        QApplication.processEvents()
                    if count >= 2000:
                        return

    # --- context menu (Windows 11 style) -----------------------------------
    def context_menu(self, pos):
        sender = self.sender()
        paths = self.selected_paths()
        m = QMenu(self)
        if paths:
            # Row of compact icon actions at the top, like Windows 11
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 2, 4, 2)
            for icon_name, tip, fn in (("cut", "Cut", self.win.cut), ("copy", "Copy", self.win.copy),
                                       ("rename", "Rename", self.win.rename), ("share", "Share", self.win.share),
                                       ("delete", "Delete", self.win.delete)):
                b = QToolButton()
                b.setIcon(icons.icon(icon_name, self.p.text))
                b.setToolTip(tip)
                b.setAutoRaise(True)
                b.clicked.connect(lambda _=False, f=fn: (m.close(), f()))
                rl.addWidget(b)
            rl.addStretch()
            wa = QWidgetAction(m)
            wa.setDefaultWidget(row)
            m.addAction(wa)
            m.addSeparator()
            first = paths[0]
            m.addAction(icons.icon("folder-outline", self.p.text), "Open", lambda: self.activate_path(first))
            if os.path.isdir(first):
                m.addAction("Open in new tab", lambda: self.win.new_tab(first))
                m.addAction("Open in new window", lambda: subprocess.Popen([sys.executable, "-m", "fenestra.explorer", first]))
                pinned = first in [p for _, p in pinned_folders()]
                m.addAction(icons.icon("pin", self.p.text), "Unpin from Quick access" if pinned else "Pin to Quick access",
                            lambda: (pin_folder(first, not pinned), self.win.reload_nav()))
                m.addAction(icons.icon("terminal", self.p.text), "Open in Terminal",
                            lambda: hostos.open_terminal(first))
            else:
                ow = m.addMenu("Open with")
                ow.addAction("Choose another app", lambda: hostos.open_path(first))
                if first.lower().endswith((".exe", ".msi", ".bat", ".cmd")):
                    m.addAction(icons.icon("compat"), "Convert to Linux app…",
                                lambda: subprocess.Popen([sys.executable, "-m", "fenestra.compat", "gui", first]))
            if any(p.lower().endswith((".zip", ".tar", ".gz", ".xz", ".bz2", ".tgz")) for p in paths):
                m.addAction("Extract All…", lambda: self.win.extract(paths))
            m.addAction("Compress to ZIP file", lambda: self.win.compress(paths))
            m.addAction("Copy as path", lambda: QApplication.clipboard().setText("\n".join(f'"{p}"' for p in paths)))
            m.addAction(icons.icon("details", self.p.text), "Properties", lambda: self.win.properties(paths))
        else:
            vm = m.addMenu(icons.icon("view", self.p.text), "View")
            self.win.fill_view_menu(vm)
            sm = m.addMenu(icons.icon("sort", self.p.text), "Sort by")
            self.win.fill_sort_menu(sm)
            m.addAction(icons.icon("refresh", self.p.text), "Refresh", self.refresh)
            m.addSeparator()
            pa = m.addAction(icons.icon("paste", self.p.text), "Paste", self.win.paste)
            pa.setEnabled(bool(clipboard_has_urls()))
            nm = m.addMenu(icons.icon("plus", self.p.text), "New")
            self.win.fill_new_menu(nm)
            m.addSeparator()
            m.addAction(icons.icon("terminal", self.p.text), "Open in Terminal",
                        lambda: hostos.open_terminal(self.location if self.is_folder() else str(HOME)))
            m.addAction(icons.icon("details", self.p.text), "Properties",
                        lambda: self.win.properties([self.location]) if self.is_folder() else None)
        view = sender if isinstance(sender, QAbstractItemView) else self.stack.currentWidget()
        m.exec(view.viewport().mapToGlobal(pos))


# --------------------------------------------------------------------------
class DetailsPane(QFrame):
    def __init__(self, p):
        super().__init__()
        self.p = p
        self.setFixedWidth(280)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(160)
        self.name = QLabel()
        self.name.setObjectName("Subtitle")
        self.name.setWordWrap(True)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("Secondary")
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        for w in (self.preview, self.name, self.info):
            lay.addWidget(w)
        lay.addStretch()

    def show_paths(self, paths, location):
        if not paths:
            self.preview.setPixmap(icons.pixmap("folder", 96))
            self.name.setText(display_name(location))
            self.info.setText("Select a single file to get more information and share your cloud content.")
            return
        if len(paths) > 1:
            self.preview.setPixmap(icons.pixmap("file", 96))
            self.name.setText(f"{len(paths)} items selected")
            self.info.setText(f"Size: {human_bytes(fileops.total_size(paths))}")
            return
        path = Path(paths[0])
        self.name.setText(path.name)
        pm = QPixmap()
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp") and path.stat().st_size < 30e6:
            pm.load(str(path))
        if not pm.isNull():
            self.preview.setPixmap(pm.scaled(240, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.preview.setPixmap(icons.pixmap("folder" if path.is_dir() else icons.for_filename(path.name), 96))
        try:
            st = path.stat()
        except OSError:
            self.info.setText("")
            return
        lines = [f"Type: {fileops.type_name(path, path.is_dir())}",
                 f"Size: {human_bytes(st.st_size) if path.is_file() else '—'}",
                 f"Date modified: {fileops.fmt_time(st.st_mtime)}",
                 f"Date created: {fileops.fmt_time(getattr(st, 'st_birthtime', st.st_ctime))}",
                 f"Location: {path.parent}"]
        if path.suffix.lower() in (".txt", ".md", ".py", ".sh", ".json", ".log", ".ini", ".cfg", ".bat") and st.st_size < 200_000:
            try:
                lines.append("\n" + path.read_text(errors="replace")[:600])
            except OSError:
                pass
        self.info.setText("\n".join(lines))


class PropertiesDialog(QDialog):
    def __init__(self, parent, paths):
        super().__init__(parent)
        p0 = Path(paths[0])
        self.setWindowTitle(f"{p0.name if len(paths) == 1 else str(len(paths)) + ' items'} Properties")
        self.setMinimumWidth(400)
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("folder" if p0.is_dir() else icons.for_filename(p0.name), 40))
        head.addWidget(ic)
        name = QLineEdit(p0.name)
        name.setReadOnly(len(paths) > 1)
        head.addWidget(name, 1)
        lay.addLayout(head)
        form = QFormLayout()
        try:
            st = p0.stat()
        except OSError:
            st = None
        size = fileops.total_size(paths)
        files = sum(1 for p in paths for _ in (Path(p).rglob("*") if Path(p).is_dir() else [p]))
        form.addRow("Type:", QLabel(fileops.type_name(p0, p0.is_dir()) if len(paths) == 1 else "Multiple types"))
        form.addRow("Location:", QLabel(str(p0.parent)))
        form.addRow("Size:", QLabel(f"{human_bytes(size)} ({size:,} bytes)"))
        if p0.is_dir():
            form.addRow("Contains:", QLabel(f"{files:,} Files and Folders"))
        if st:
            form.addRow("Created:", QLabel(fileops.fmt_time(st.st_ctime)))
            form.addRow("Modified:", QLabel(fileops.fmt_time(st.st_mtime)))
            form.addRow("Accessed:", QLabel(fileops.fmt_time(st.st_atime)))
            import stat as statmod
            form.addRow("Permissions:", QLabel(statmod.filemode(st.st_mode)))
            try:
                import pwd
                form.addRow("Owner:", QLabel(pwd.getpwuid(st.st_uid).pw_name))
            except KeyError:
                pass
        lay.addLayout(form)
        btn = QPushButton("OK")
        btn.setObjectName("Accent")

        def ok():
            if len(paths) == 1 and name.text() and name.text() != p0.name:
                try:
                    p0.rename(p0.with_name(name.text()))
                except OSError as exc:
                    QMessageBox.warning(self, "Rename", str(exc))
            self.accept()
        btn.clicked.connect(ok)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)


# --------------------------------------------------------------------------
class ExplorerWindow(FluentWindow):
    def __init__(self, p, start=SHELL_HOME):
        super().__init__(p, "File Explorer", None)
        self.titlebar.title.hide()
        self.resize(1180, 740)
        self.setWindowIcon(icons.icon("explorer"))

        # Tabs live in the title bar like Windows 11
        self.tabbar = QTabBar()
        self.tabbar.setTabsClosable(True)
        self.tabbar.setMovable(True)
        self.tabbar.setExpanding(False)
        self.tabbar.setDocumentMode(True)
        self.tabbar.setStyleSheet(
            f"QTabBar::tab {{ min-width: 180px; max-width: 240px; padding: 7px 10px; margin-top: 6px; border-top-left-radius: 8px;"
            f" border-top-right-radius: 8px; background: transparent; border: none; }}"
            f"QTabBar::tab:selected {{ background: {p.surface}; }}"
            f"QTabBar::tab:hover:!selected {{ background: {p.surface_alt}; }}"
            f"QTabBar::close-button {{ image: url({icons.glyph_file('close', p.text_secondary)}); subcontrol-position: right;"
            f" width: 10px; height: 10px; padding: 3px; border-radius: 4px; }}"
            f"QTabBar::close-button:hover {{ background: {p.pressed}; }}")
        self.tabbar.tabCloseRequested.connect(self.close_tab)
        self.tabbar.currentChanged.connect(self.tab_switched)
        self.tabbar.tabMoved.connect(self._tab_moved)
        add = QToolButton()
        add.setIcon(icons.icon("plus", p.text))
        add.setAutoRaise(True)
        add.clicked.connect(lambda: self.new_tab(SHELL_HOME))
        self.titlebar.left.addWidget(self.tabbar)
        self.titlebar.left.addWidget(add)
        self.titlebar.center.addStretch()

        central = QWidget()
        central.setObjectName("ExplorerBody")
        central.setStyleSheet(f"QWidget#ExplorerBody {{ background: {p.surface}; }}")
        self.set_content(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Navigation row
        nav = QHBoxLayout()
        nav.setContentsMargins(8, 6, 8, 6)
        self.btn_back = self._tool("back", "Back (Alt+Left Arrow)", lambda: self.tab.back())
        self.btn_fwd = self._tool("forward", "Forward (Alt+Right Arrow)", lambda: self.tab.forward())
        self.btn_up = self._tool("up", "Up (Alt+Up Arrow)", lambda: self.tab.up())
        self.btn_refresh = self._tool("refresh", "Refresh (F5)", lambda: self.tab.refresh())
        for b in (self.btn_back, self.btn_fwd, self.btn_up, self.btn_refresh):
            nav.addWidget(b)
        self.address = AddressBar(p)
        self.address.navigate.connect(lambda loc: self.tab.navigate(loc))
        nav.addWidget(self.address, 1)
        self.search = QLineEdit()
        self.search.setFixedWidth(260)
        self.search.setFixedHeight(32)
        self.search.addAction(icons.icon("search", p.text_secondary), QLineEdit.ActionPosition.TrailingPosition)
        self.search.returnPressed.connect(lambda: self.tab.search(self.search.text()))
        nav.addWidget(self.search)
        lay.addLayout(nav)

        # Command bar
        cmd = QHBoxLayout()
        cmd.setContentsMargins(8, 2, 8, 6)
        cmd.setSpacing(2)
        self.new_btn = QToolButton()
        self.new_btn.setText(" New ")
        self.new_btn.setIcon(icons.icon("plus", p.accent))
        self.new_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.new_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        nm = QMenu(self.new_btn)
        self.fill_new_menu(nm)
        self.new_btn.setMenu(nm)
        cmd.addWidget(self.new_btn)
        cmd.addWidget(self._sep())
        self.act_buttons = {}
        for icon_name, tip, fn in (("cut", "Cut (Ctrl+X)", self.cut), ("copy", "Copy (Ctrl+C)", self.copy),
                                   ("paste", "Paste (Ctrl+V)", self.paste), ("rename", "Rename (F2)", self.rename),
                                   ("share", "Share", self.share), ("delete", "Delete (Delete)", self.delete)):
            b = self._tool(icon_name, tip, fn)
            cmd.addWidget(b)
            self.act_buttons[icon_name] = b
        cmd.addWidget(self._sep())
        self.sort_btn = self._menu_button("sort", " Sort ", self.fill_sort_menu)
        self.view_btn = self._menu_button("view", " View ", self.fill_view_menu)
        cmd.addWidget(self.sort_btn)
        cmd.addWidget(self.view_btn)
        cmd.addWidget(self._sep())
        self.more_btn = self._menu_button("more", "", self.fill_more_menu)
        cmd.addWidget(self.more_btn)
        cmd.addStretch()
        self.details_btn = QToolButton()
        self.details_btn.setText(" Details")
        self.details_btn.setIcon(icons.icon("details", p.text))
        self.details_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_btn.setCheckable(True)
        self.details_btn.toggled.connect(self.toggle_details)
        cmd.addWidget(self.details_btn)
        lay.addLayout(cmd)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {p.stroke};")
        lay.addWidget(line)

        # Body: navigation pane | tabs | details pane
        self.splitter = QSplitter()
        self.splitter.setHandleWidth(1)
        self.navpane = QTreeWidget()
        self.navpane.setHeaderHidden(True)
        self.navpane.setIndentation(14)
        self.navpane.setMinimumWidth(200)
        self.navpane.itemClicked.connect(self.nav_clicked)
        self.navpane.itemExpanded.connect(self.nav_expand)
        self.navpane.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.navpane.customContextMenuRequested.connect(self.nav_menu)
        self.tabs = QStackedWidget()
        self.details_pane = DetailsPane(p)
        self.details_pane.hide()
        self.splitter.addWidget(self.navpane)
        self.splitter.addWidget(self.tabs)
        self.splitter.addWidget(self.details_pane)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([230, 900, 0])
        lay.addWidget(self.splitter, 1)

        # Status bar
        status = QHBoxLayout()
        status.setContentsMargins(12, 2, 8, 2)
        self.status = QLabel()
        self.status.setObjectName("Secondary")
        status.addWidget(self.status)
        status.addStretch()
        self.btn_view_details = self._tool("list", "Details", lambda: self.set_view("details"))
        self.btn_view_icons = self._tool("grid", "Large icons", lambda: self.set_view("large"))
        status.addWidget(self.btn_view_details)
        status.addWidget(self.btn_view_icons)
        sw = QWidget()
        sw.setLayout(status)
        sw.setFixedHeight(30)
        lay.addWidget(sw)

        self.reload_nav()
        self._shortcuts()
        self.clipboard_cut = False
        self.new_tab(start)

    # --- helpers ------------------------------------------------------------
    def _tool(self, icon_name, tip, fn):
        b = QToolButton()
        b.setIcon(icons.icon(icon_name, self.p.text))
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.setIconSize(QSize(16, 16))
        b.setFixedSize(32, 32)
        b.clicked.connect(fn)
        return b

    def _sep(self):
        s = QFrame()
        s.setFixedSize(1, 20)
        s.setStyleSheet(f"background: {self.p.stroke}; margin: 0 6px;")
        return s

    def _menu_button(self, icon_name, text, filler):
        b = QToolButton()
        b.setText(text)
        b.setIcon(icons.icon(icon_name, self.p.text))
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if text else Qt.ToolButtonStyle.ToolButtonIconOnly)
        b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(b)
        m.aboutToShow.connect(lambda: (m.clear(), filler(m)))
        b.setMenu(m)
        return b

    def _shortcuts(self):
        for seq, fn in (("Ctrl+C", self.copy), ("Ctrl+X", self.cut), ("Ctrl+V", self.paste), ("F2", self.rename),
                        ("Delete", self.delete), ("Shift+Delete", lambda: self.delete(permanent=True)),
                        ("Ctrl+T", lambda: self.new_tab(SHELL_HOME)), ("Ctrl+W", lambda: self.close_tab(self.tabbar.currentIndex())),
                        ("Ctrl+N", lambda: subprocess.Popen([sys.executable, "-m", "fenestra.explorer"])),
                        ("Ctrl+Shift+N", self.new_folder), ("Alt+Left", lambda: self.tab.back()),
                        ("Alt+Right", lambda: self.tab.forward()), ("Alt+Up", lambda: self.tab.up()),
                        ("Backspace", lambda: self.tab.back()), ("F5", lambda: self.tab.refresh()),
                        ("Ctrl+L", self.address.start_edit), ("Alt+D", self.address.start_edit),
                        ("Ctrl+F", self.search.setFocus), ("Ctrl+E", self.search.setFocus),
                        ("Ctrl+A", self.select_all), ("Alt+Return", lambda: self.properties(self.tab.selected_paths() or [self.tab.location])),
                        ("Ctrl+H", lambda: self.tab.toggle_hidden(not self.tab.show_hidden)),
                        ("Ctrl+Tab", lambda: self.tabbar.setCurrentIndex((self.tabbar.currentIndex() + 1) % self.tabbar.count())),
                        ("Alt+P", lambda: self.details_btn.toggle())):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(fn)

    # --- tabs ----------------------------------------------------------------
    @property
    def tab(self) -> ExplorerTab:
        return self.tabs.currentWidget()

    def new_tab(self, loc):
        t = ExplorerTab(self, loc)
        t.location_changed.connect(lambda l, t=t: self.on_location(t, l))
        t.selection_changed.connect(self.update_status)
        self.tabs.addWidget(t)
        idx = self.tabbar.addTab(icons.icon("folder"), display_name(t.location))
        self.tabbar.setTabData(idx, t)
        self.tabbar.setCurrentIndex(idx)
        self.on_location(t, t.location)

    def close_tab(self, idx):
        if self.tabbar.count() <= 1:
            self.close()
            return
        t = self.tabbar.tabData(idx)
        self.tabbar.removeTab(idx)
        self.tabs.removeWidget(t)
        t.deleteLater()

    def _tab_moved(self, *_):
        pass

    def tab_switched(self, idx):
        t = self.tabbar.tabData(idx)
        if t is not None:
            self.tabs.setCurrentWidget(t)
            self.on_location(t, t.location)

    def on_location(self, t, loc):
        for i in range(self.tabbar.count()):
            if self.tabbar.tabData(i) is t:
                self.tabbar.setTabText(i, display_name(loc))
                self.tabbar.setTabIcon(i, icons.icon(self.address._icon_for(loc)))
        if t is not self.tab:
            return
        self.address.set_location(loc)
        self.search.setPlaceholderText(f"Search {display_name(loc)}")
        self.setWindowTitle(f"{display_name(loc)} - File Explorer")
        self.btn_back.setEnabled(bool(t.back_stack))
        self.btn_fwd.setEnabled(bool(t.fwd_stack))
        QTimer.singleShot(200, self.update_status)

    def update_status(self):
        t = self.tab
        if t is None:
            return
        n = t.item_count()
        sel = t.selected_paths()
        text = f"{n} item{'s' if n != 1 else ''}" if t.is_folder() or t.location in (SHELL_TRASH,) or t.location.startswith("search:") else ""
        if sel:
            files = [p for p in sel if os.path.isfile(p)]
            text += f"    {len(sel)} item{'s' if len(sel) != 1 else ''} selected"
            if files and len(files) == len(sel):
                text += f"  {human_bytes(sum(os.path.getsize(f) for f in files))}"
        self.status.setText(text)
        has = bool(sel)
        for k in ("cut", "copy", "rename", "share", "delete"):
            self.act_buttons[k].setEnabled(has)
        self.act_buttons["paste"].setEnabled(clipboard_has_urls() and t.is_folder())
        if self.details_pane.isVisible():
            self.details_pane.show_paths(sel, t.location)

    # --- navigation pane ---------------------------------------------------------
    def reload_nav(self):
        self.navpane.clear()
        p = self.p

        def item(parent, text, icon_name, loc, expandable=False):
            it = QTreeWidgetItem([text])
            it.setIcon(0, icons.icon(icon_name))
            it.setData(0, Qt.ItemDataRole.UserRole, loc)
            if expandable:
                it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            (parent.addChild(it) if parent else self.navpane.addTopLevelItem(it))
            return it

        item(None, "Home", "home", SHELL_HOME)
        item(None, "Gallery", "photos", SHELL_GALLERY)
        sep = QTreeWidgetItem([""])
        sep.setFlags(Qt.ItemFlag.NoItemFlags)
        sep.setSizeHint(0, QSize(10, 8))
        self.navpane.addTopLevelItem(sep)
        for name, ic, path in SPECIAL:
            it = item(None, name, ic, str(path), True)
            it.setToolTip(0, f"{path}\nPinned")
        for name, path in pinned_folders():
            item(None, name, "folder", path, True)
        sep2 = QTreeWidgetItem([""])
        sep2.setFlags(Qt.ItemFlag.NoItemFlags)
        sep2.setSizeHint(0, QSize(10, 8))
        self.navpane.addTopLevelItem(sep2)
        pc = item(None, "This PC", "monitor", SHELL_PC)
        for part in drives():
            label = "Local Disk (C:)" if part.mountpoint == "/" else f"{Path(part.mountpoint).name or part.mountpoint}"
            item(pc, label, "drive", part.mountpoint, True)
        pc.setExpanded(False)
        item(None, "Network", "monitor", SHELL_NET)
        item(None, "Linux", "folder", "/", True)
        item(None, "Recycle Bin", "trash", SHELL_TRASH)
        del p

    def nav_expand(self, it):
        if it.childCount() and it.child(0).data(0, Qt.ItemDataRole.UserRole):
            loaded = True
        else:
            loaded = False
        loc = it.data(0, Qt.ItemDataRole.UserRole)
        if loaded or not loc or loc.startswith("shell:"):
            return
        try:
            subdirs = sorted((d for d in os.scandir(loc) if d.is_dir() and not d.name.startswith(".")),
                             key=lambda d: d.name.lower())
        except OSError:
            return
        for d in subdirs[:300]:
            ch = QTreeWidgetItem([d.name])
            ch.setIcon(0, icons.icon("folder"))
            ch.setData(0, Qt.ItemDataRole.UserRole, d.path)
            ch.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            it.addChild(ch)
        if not subdirs:
            it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)

    def nav_clicked(self, it, _col):
        loc = it.data(0, Qt.ItemDataRole.UserRole)
        if loc:
            self.tab.navigate(loc)

    def nav_menu(self, pos):
        it = self.navpane.itemAt(pos)
        if not it:
            return
        loc = it.data(0, Qt.ItemDataRole.UserRole)
        if not loc:
            return
        m = QMenu(self)
        m.addAction("Open in new tab", lambda: self.new_tab(loc))
        m.addAction("Open in new window", lambda: subprocess.Popen([sys.executable, "-m", "fenestra.explorer", loc]))
        if not loc.startswith("shell:"):
            pinned = loc in [p for _, p in pinned_folders()]
            m.addAction("Unpin from Quick access" if pinned else "Pin to Quick access",
                        lambda: (pin_folder(loc, not pinned), self.reload_nav()))
            m.addAction("Properties", lambda: self.properties([loc]))
        if loc == SHELL_TRASH:
            m.addAction("Empty Recycle Bin", self.empty_trash)
        m.exec(self.navpane.viewport().mapToGlobal(pos))

    # --- menus -----------------------------------------------------------------
    def fill_new_menu(self, m):
        m.addAction(icons.icon("folder"), "Folder", self.new_folder)
        m.addAction(icons.icon("file-text"), "Text Document", lambda: self.new_file("New Text Document", ".txt"))
        m.addAction(icons.icon("file-code"), "Shell Script", lambda: self.new_file("New Script", ".sh", "#!/bin/sh\n"))
        m.addAction(icons.icon("file-doc"), "Document", lambda: self.new_file("New Document", ".odt", None))
        m.addAction(icons.icon("file-sheet"), "Spreadsheet", lambda: self.new_file("New Spreadsheet", ".ods", None))
        m.addAction(icons.icon("file-archive"), "Compressed (zipped) Folder", lambda: self.new_file("New Compressed (zipped) Folder", ".zip", b"PK\x05\x06" + b"\0" * 18))

    def fill_sort_menu(self, m):
        t = self.tab
        if t is None:
            return
        hdr = t.details.header()
        cur, order = hdr.sortIndicatorSection(), hdr.sortIndicatorOrder()
        for i, name in WinModel.SORT_ORDER:
            a = m.addAction(name, lambda i=i: t.details.sortByColumn(i, order))
            a.setCheckable(True)
            a.setChecked(i == cur)
        m.addSeparator()
        for label, o in (("Ascending", Qt.SortOrder.AscendingOrder), ("Descending", Qt.SortOrder.DescendingOrder)):
            a = m.addAction(label, lambda o=o: t.details.sortByColumn(hdr.sortIndicatorSection(), o))
            a.setCheckable(True)
            a.setChecked(o == order)

    def fill_view_menu(self, m):
        t = self.tab
        for label, mode in (("Extra large icons", "xl"), ("Large icons", "large"), ("Medium icons", "medium"),
                            ("Small icons", "small"), ("List", "list"), ("Details", "details"), ("Tiles", "tiles"),
                            ("Content", "content")):
            a = m.addAction(label, lambda mode=mode: self.set_view(mode))
            a.setCheckable(True)
            a.setChecked(t is not None and t.view_mode.startswith(mode))
        m.addSeparator()
        a = m.addAction("Compact view")
        a.setCheckable(True)
        show = m.addMenu("Show")
        for label, checked, fn in (("Navigation pane", self.navpane.isVisible(), self.navpane.setVisible),
                                   ("Details pane", self.details_pane.isVisible(), self.details_btn.setChecked),
                                   ("Hidden items", t.show_hidden if t else False, lambda on: self.tab.toggle_hidden(on))):
            a = show.addAction(label)
            a.setCheckable(True)
            a.setChecked(checked)
            a.toggled.connect(fn)

    def fill_more_menu(self, m):
        m.addAction("Undo", lambda: None).setEnabled(False)
        m.addSeparator()
        m.addAction("Pin to Quick access", lambda: (pin_folder(self.tab.location), self.reload_nav())
                    if self.tab.is_folder() else None)
        m.addAction("Select all", self.select_all)
        m.addAction("Select none", lambda: self.tab.current_view() and self.tab.current_view().clearSelection())
        m.addAction("Invert selection", self.invert_selection)
        m.addSeparator()
        m.addAction("Properties", lambda: self.properties(self.tab.selected_paths() or [self.tab.location]))
        m.addAction("Options", lambda: QMessageBox.information(self, "Folder Options",
                    "Use View > Show to toggle hidden items, panes and compact view."))
        m.addAction("Open in Terminal", lambda: hostos.open_terminal(
            self.tab.location if self.tab.is_folder() else str(HOME)))

    def set_view(self, mode):
        self.tab.set_view(mode)

    def toggle_details(self, on):
        self.details_pane.setVisible(on)
        if on:
            self.splitter.setSizes([230, 700, 280])
            self.update_status()

    # --- file actions -----------------------------------------------------------
    def select_all(self):
        v = self.tab.current_view()
        if v:
            v.selectAll()

    def invert_selection(self):
        v = self.tab.current_view()
        if not v:
            return
        from PyQt6.QtCore import QItemSelection, QItemSelectionModel
        root = v.rootIndex()
        sel = QItemSelection(self.tab.model.index(0, 0, root),
                             self.tab.model.index(self.tab.model.rowCount(root) - 1, 3, root))
        v.selectionModel().select(sel, QItemSelectionModel.SelectionFlag.Toggle)

    def _set_clipboard(self, paths, cut):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(p) for p in paths])
        md.setData("x-special/gnome-copied-files", (("cut" if cut else "copy") + "\n" +
                   "\n".join(QUrl.fromLocalFile(p).toString() for p in paths)).encode())
        QApplication.clipboard().setMimeData(md)
        self.clipboard_cut = cut
        self.update_status()

    def copy(self):
        paths = self.tab.selected_paths()
        if paths:
            self._set_clipboard(paths, False)

    def cut(self):
        paths = self.tab.selected_paths()
        if paths:
            self._set_clipboard(paths, True)

    def paste(self):
        if not self.tab.is_folder():
            return
        md = QApplication.clipboard().mimeData()
        if not md or not md.hasUrls():
            return
        cut = self.clipboard_cut or bytes(md.data("x-special/gnome-copied-files")).startswith(b"cut")
        srcs = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        self.run_transfer(srcs, self.tab.location, cut)
        if cut:
            QApplication.clipboard().clear()

    def run_transfer(self, srcs, dest, move):
        dlg = ProgressDialog(self, ("Moving" if move else "Copying") + f" {len(srcs)} item{'s' if len(srcs) != 1 else ''}")
        thread = QThread(self)
        worker = Worker(fileops.transfer, srcs, dest, move)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(dlg.update_progress)
        dlg.rejected.connect(lambda: setattr(worker, "cancel", True))

        def done(err):
            thread.quit()
            dlg.accept()
            if err:
                QMessageBox.warning(self, "File Explorer", err)
            self.tab.refresh()
        worker.finished.connect(done)
        self._worker = worker
        thread.start()
        QTimer.singleShot(400, lambda: thread.isRunning() and dlg.show())

    def rename(self):
        v = self.tab.current_view()
        if v and v.currentIndex().isValid():
            idx = v.currentIndex().siblingAtColumn(0)
            v.edit(idx)
        elif self.tab.selected_paths():
            p = Path(self.tab.selected_paths()[0])
            name, ok = QInputDialog.getText(self, "Rename", "New name:", text=p.name)
            if ok and name:
                p.rename(p.with_name(name))
                self.tab.refresh()

    def delete(self, permanent=False):
        paths = self.tab.selected_paths()
        if not paths:
            return
        if self.tab.location == SHELL_TRASH:
            self.tab.delete_trash_selected()
            return
        if permanent:
            if QMessageBox.question(self, "Delete Multiple Items" if len(paths) > 1 else "Delete File",
                                    f"Are you sure you want to permanently delete {'these ' + str(len(paths)) + ' items' if len(paths) > 1 else 'this file'}?") \
                    != QMessageBox.StandardButton.Yes:
                return
        errors = []
        for p in paths:
            try:
                fileops.delete_permanently(p) if permanent else fileops.trash(p)
            except OSError as exc:
                errors.append(f"{p}: {exc}")
        if errors:
            QMessageBox.warning(self, "File Explorer", "\n".join(errors))
        self.tab.refresh()

    def share(self):
        paths = self.tab.selected_paths()
        if not paths:
            return
        m = QMenu(self)
        m.addAction("Copy link to clipboard", lambda: QApplication.clipboard().setText(
            "\n".join(QUrl.fromLocalFile(p).toString() for p in paths)))
        if shutil.which("thunderbird") or shutil.which("xdg-email"):
            m.addAction("Email", lambda: subprocess.Popen(["xdg-email", "--attach", paths[0]]))
        if shutil.which("blueman-sendto"):
            m.addAction("Nearby sharing (Bluetooth)", lambda: subprocess.Popen(["blueman-sendto", *paths]))
        m.exec(self.cursor().pos())

    def new_folder(self):
        if not self.tab.is_folder():
            return
        target = fileops.new_name(Path(self.tab.location), "New folder")
        target.mkdir()
        self._edit_new(target)

    def new_file(self, base, suffix, content=""):
        if not self.tab.is_folder():
            return
        target = fileops.new_name(Path(self.tab.location), base, suffix)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content or "")
        self._edit_new(target)

    def _edit_new(self, target):
        def go():
            v = self.tab.current_view()
            if not v:
                return
            idx = self.tab.model.mapFromSource(self.tab.fs.index(str(target)))
            if idx.isValid():
                v.setCurrentIndex(idx)
                v.edit(idx)
        QTimer.singleShot(300, go)

    def empty_trash(self):
        n = len(fileops.trash_items())
        if n and QMessageBox.question(self, "Delete Multiple Items",
                                      f"Are you sure you want to permanently delete these {n} items?") \
                == QMessageBox.StandardButton.Yes:
            fileops.empty_trash()
            if self.tab.location == SHELL_TRASH:
                self.tab.load_trash()

    def compress(self, paths):
        p0 = Path(paths[0])
        dest = fileops.new_name(p0.parent, p0.stem if len(paths) == 1 else p0.parent.name, ".zip")
        try:
            fileops.compress(paths, dest)
        except OSError as exc:
            QMessageBox.warning(self, "Compress", str(exc))
        self.tab.refresh()

    def extract(self, paths):
        for p in map(Path, paths):
            stem = p.name
            for ext in (".tar.gz", ".tar.xz", ".tar.bz2", ".tgz", ".zip", ".tar", ".gz", ".xz"):
                if stem.lower().endswith(ext):
                    stem = stem[: -len(ext)]
                    break
            try:
                fileops.extract(p, fileops.new_name(p.parent, stem))
            except (OSError, ValueError, shutil.ReadError) as exc:
                QMessageBox.warning(self, "Extract", f"{p.name}: {exc}")
        self.tab.refresh()

    def properties(self, paths):
        paths = [p for p in paths if p and not p.startswith(("shell:", "search:"))]
        if paths:
            PropertiesDialog(self, paths).exec()


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("fenestra-explorer")
    p = theme.apply(app)
    start = argv[0] if argv else SHELL_HOME
    if start.startswith("file://"):
        start = QUrl(start).toLocalFile()
    w = ExplorerWindow(p, start)
    w.show()
    return app.exec()
