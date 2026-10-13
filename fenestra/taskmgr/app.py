"""Task Manager - modelled on the Windows 11 (22H2+) Task Manager."""

import os
import signal
import subprocess
import sys
import time

import psutil
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QFont, QKeySequence
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QFrame, QGridLayout,
                             QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                             QMenu, QMessageBox, QPushButton, QScrollArea, QStackedWidget,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QCheckBox)

from ..common import platform as hostos
from ..common import icons, theme, x11
from ..common.widgets import Graph, NavButton, human_bytes, human_rate
from ..common.window import FluentWindow
from . import sysinfo

PAGES = [
    ("Processes", "apps"),
    ("Performance", "performance"),
    ("App history", "history"),
    ("Startup apps", "startup"),
    ("Users", "users"),
    ("Details", "details"),
    ("Services", "services"),
]

STATUS_MAP = {"running": "", "sleeping": "", "disk-sleep": "", "stopped": "Suspended", "zombie": "Not responding",
              "idle": "", "tracing-stop": "Suspended", "dead": "Not responding"}


def heat(value, maximum, dark):
    """Windows-style yellow→orange heat map background for resource cells."""
    t = max(0.0, min(1.0, value / maximum if maximum else 0))
    if dark:
        base = QColor(70, 60, 20)
        hot = QColor(140, 90, 10)
    else:
        base = QColor(255, 244, 196)
        hot = QColor(255, 167, 38)
    if t < 0.002:
        return None
    t = 0.15 + 0.85 * t
    return QColor(round(base.red() + (hot.red() - base.red()) * t),
                  round(base.green() + (hot.green() - base.green()) * t),
                  round(base.blue() + (hot.blue() - base.blue()) * t))


class SortItem(QTreeWidgetItem):
    """Sorts on numeric data stored in UserRole when present."""

    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a = self.data(col, Qt.ItemDataRole.UserRole)
        b = other.data(col, Qt.ItemDataRole.UserRole)
        if a is not None and b is not None:
            try:
                return float(a) < float(b)
            except (TypeError, ValueError):
                return str(a) < str(b)
        return self.text(col).lower() < other.text(col).lower()


class PageHeader(QWidget):
    def __init__(self, title, actions=()):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 8, 16, 8)
        t = QLabel(title)
        f = t.font()
        f.setPointSizeF(13)
        f.setWeight(QFont.Weight.DemiBold)
        t.setFont(f)
        lay.addWidget(t)
        lay.addStretch()
        self.buttons = {}
        for name, icon_name in actions:
            b = QPushButton(f"  {name}")
            b.setObjectName("Flat")
            b.setIcon(icons.icon(icon_name, theme.palette().text))
            lay.addWidget(b)
            self.buttons[name] = b


# --------------------------------------------------------------------------
class ProcessesPage(QWidget):
    COLS = ["Name", "Status", "CPU", "Memory", "Disk", "Network"]

    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.header = PageHeader("Processes", [("Run new task", "plus"), ("End task", "close"),
                                                ("Efficiency mode", "efficiency"), ("View", "more")])
        self.header.buttons["Run new task"].clicked.connect(win.run_new_task)
        self.header.buttons["End task"].clicked.connect(self.end_task)
        self.header.buttons["Efficiency mode"].clicked.connect(self.toggle_efficiency)
        lay.addWidget(self.header)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self.COLS))
        self.tree.setHeaderLabels(self.COLS)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(self.COLS)):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            self.tree.setColumnWidth(i, 100)
        h.setStretchLastSection(False)
        h.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        h.setMinimumHeight(48)
        h.sectionClicked.connect(self.sort_by)
        self.sort_col, self.sort_desc = 0, False
        self.apps_root = QTreeWidgetItem(["Apps"])
        self.bg_root = QTreeWidgetItem(["Background processes"])
        for r in (self.apps_root, self.bg_root):
            f = r.font(0)
            f.setWeight(QFont.Weight.DemiBold)
            r.setFont(0, f)
            r.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(r)
            r.setExpanded(True)
        self.items = {}       # key -> item (app group key 'app:name' or pid)
        lay.addWidget(self.tree)

    def sort_by(self, col):
        if col == self.sort_col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col, self.sort_desc = col, col != 0
        self.refresh(self.win.last_procs)

    def _set_row(self, it, name, status, cpu, mem, disk, net, icon=None, maxima=None):
        dark = self.win.p.dark
        vals = [name, status, f"{cpu:.1f}%", f"{mem / 1048576:.1f} MB", f"{disk / 1048576:.1f} MB/s", "0 Mbps"]
        nums = [name.lower(), status, cpu, mem, disk, net]
        for c, (v, n) in enumerate(zip(vals, nums)):
            if it.text(c) != v:
                it.setText(c, v)
            it.setData(c, Qt.ItemDataRole.UserRole, n)
            if c >= 2:
                it.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mx = maxima or {}
        for c, val, m in ((2, cpu, 100.0), (3, mem, mx.get("mem", 1)), (4, disk, mx.get("disk", 50e6)), (5, net, 1e6)):
            col = heat(val, m, dark)
            it.setBackground(c, col if col else QColor(0, 0, 0, 0))
        if icon is not None and it.data(0, Qt.ItemDataRole.DecorationRole) is None:
            it.setIcon(0, icon)

    def refresh(self, procs):
        if not procs:
            return
        total_mem = psutil.virtual_memory().total
        maxima = {"mem": total_mem * 0.25, "disk": 50e6}
        q = self.win.search.text().strip().lower()
        if q:
            procs = [p for p in procs if q in p.name.lower() or q in str(p.pid) or q in p.user.lower()]
        apps, bg = {}, []
        for p in procs:
            if p.is_app:
                apps.setdefault(p.window_title and p.name or p.name, []).append(p)
            else:
                bg.append(p)
        seen = set()
        exe_icon = icons.icon("file-exe")
        # Apps grouped by process name
        for name, group in apps.items():
            key = f"app:{name}"
            seen.add(key)
            it = self.items.get(key)
            if it is None:
                it = SortItem()
                self.apps_root.addChild(it)
                self.items[key] = it
            cpu = sum(p.cpu for p in group)
            mem = sum(p.mem for p in group)
            disk = sum(p.disk for p in group)
            title = next((p.window_title for p in group if p.window_title), "")
            label = f"{title or name}" + (f" ({len(group)})" if len(group) > 1 else "")
            status = "Efficiency mode" if any(p.efficiency for p in group) else \
                STATUS_MAP.get(group[0].status, "")
            self._set_row(it, label, status, cpu, mem, disk, 0, exe_icon, maxima)
            it.setData(0, Qt.ItemDataRole.UserRole + 1, [p.pid for p in group])
            # children
            existing = {it.child(i).data(0, Qt.ItemDataRole.UserRole + 1)[0]: it.child(i) for i in range(it.childCount())}
            if len(group) > 1:
                for p in group:
                    ch = existing.pop(p.pid, None)
                    if ch is None:
                        ch = SortItem()
                        it.addChild(ch)
                    self._set_row(ch, p.name, STATUS_MAP.get(p.status, ""), p.cpu, p.mem, p.disk, 0, exe_icon, maxima)
                    ch.setData(0, Qt.ItemDataRole.UserRole + 1, [p.pid])
            for ch in existing.values():
                it.removeChild(ch)
        for p in bg:
            key = p.pid
            seen.add(key)
            it = self.items.get(key)
            if it is None:
                it = SortItem()
                self.bg_root.addChild(it)
                self.items[key] = it
            status = "Efficiency mode" if p.efficiency else STATUS_MAP.get(p.status, "")
            self._set_row(it, p.name, status, p.cpu, p.mem, p.disk, 0, exe_icon, maxima)
            it.setData(0, Qt.ItemDataRole.UserRole + 1, [p.pid])
        for key in list(self.items):
            if key not in seen:
                it = self.items.pop(key)
                (it.parent() or self.tree.invisibleRootItem()).removeChild(it)
        self.apps_root.setText(0, f"Apps ({self.apps_root.childCount()})")
        self.bg_root.setText(0, f"Background processes ({self.bg_root.childCount()})")
        order = Qt.SortOrder.DescendingOrder if self.sort_desc else Qt.SortOrder.AscendingOrder
        for root in (self.apps_root, self.bg_root):
            root.sortChildren(self.sort_col, order)
        # Header shows machine totals like Windows: "23%\nCPU"
        cpu = psutil.cpu_percent()
        vm = psutil.virtual_memory()
        disk = sum(v["active"] for v in self.win.last_disks.values()) / max(1, len(self.win.last_disks)) if self.win.last_disks else 0
        labels = ["Name", "Status", f"{cpu:.0f}%\nCPU", f"{vm.percent:.0f}%\nMemory", f"{disk:.0f}%\nDisk", "0%\nNetwork"]
        self.tree.setHeaderLabels(labels)

    def selected_pids(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole + 1) or [] if it else []

    def end_task(self):
        self.win.kill(self.selected_pids())

    def toggle_efficiency(self):
        for pid in self.selected_pids():
            try:
                p = psutil.Process(pid)
                p.nice(0 if p.nice() >= 19 else 19)
            except psutil.Error as exc:
                QMessageBox.warning(self, "Task Manager", f"Unable to change priority: {exc}")
                break

    def context_menu(self, pos):
        pids = self.selected_pids()
        if not pids:
            return
        m = QMenu(self)
        m.addAction("Switch to", lambda: self.win.switch_to(pids))
        m.addAction("End task", self.end_task)
        m.addAction("Efficiency mode", self.toggle_efficiency)
        m.addSeparator()
        m.addAction("Create memory dump file", lambda: self.win.dump(pids[0]))
        m.addAction("Go to details", lambda: self.win.goto_details(pids[0]))
        m.addAction("Open file location", lambda: self.win.open_location(pids[0]))
        m.addAction("Search online", lambda: self.win.search_online(pids[0]))
        m.addAction("Properties", lambda: self.win.properties(pids[0]))
        m.exec(self.tree.viewport().mapToGlobal(pos))


# --------------------------------------------------------------------------
class PerfTile(QPushButton):
    """Left side mini-graph tile on the Performance page."""

    def __init__(self, title, color, palette):
        super().__init__()
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setFixedHeight(70)
        self.setStyleSheet(f"QPushButton {{ border: none; background: transparent; border-radius: 6px; text-align:left; padding: 0; min-height: 70px; }}"
                           f"QPushButton:hover {{ background: {palette.surface_alt}; }}"
                           f"QPushButton:checked {{ background: {palette.selection}; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        self.graph = Graph(color, samples=40, grid=False)
        self.graph.setFixedSize(70, 46)
        self.graph.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self.graph)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = QLabel(title)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.sub = QLabel("")
        self.sub.setObjectName("Secondary")
        self.sub.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.sub2 = QLabel("")
        self.sub2.setObjectName("Secondary")
        self.sub2.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        for w in (self.title, self.sub, self.sub2):
            col.addWidget(w)
        lay.addLayout(col, 1)


class PerfDetail(QWidget):
    """Right side: big graph + statistics grid."""

    def __init__(self, title, subtitle, color, series=1, maximum=100.0, ylabel="% Utilization"):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 8, 20, 12)
        top = QHBoxLayout()
        t = QLabel(title)
        f = t.font()
        f.setPointSizeF(18)
        f.setWeight(QFont.Weight.DemiBold)
        t.setFont(f)
        top.addWidget(t)
        top.addStretch()
        self.subtitle = QLabel(subtitle)
        f2 = self.subtitle.font()
        f2.setPointSizeF(11)
        self.subtitle.setFont(f2)
        top.addWidget(self.subtitle)
        lay.addLayout(top)
        axis = QHBoxLayout()
        self.ylabel = QLabel(ylabel)
        self.ylabel.setObjectName("Secondary")
        axis.addWidget(self.ylabel)
        axis.addStretch()
        self.ymax = QLabel("100%" if maximum else "")
        self.ymax.setObjectName("Secondary")
        axis.addWidget(self.ymax)
        lay.addLayout(axis)
        self.graph = Graph(color, samples=60, maximum=maximum, series=series)
        self.graph.setMinimumHeight(240)
        lay.addWidget(self.graph, 3)
        axis2 = QHBoxLayout()
        l1 = QLabel("60 seconds")
        l1.setObjectName("Secondary")
        l2 = QLabel("0")
        l2.setObjectName("Secondary")
        axis2.addWidget(l1)
        axis2.addStretch()
        axis2.addWidget(l2)
        lay.addLayout(axis2)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(28)
        self.grid.setVerticalSpacing(2)
        lay.addLayout(self.grid)
        lay.addStretch(1)
        self.stats = {}
        self._row = 0

    def stat(self, key, big=True, col=0):
        lab = QLabel(key)
        lab.setObjectName("Secondary")
        val = QLabel("-")
        if big:
            f = val.font()
            f.setPointSizeF(14)
            val.setFont(f)
        r = len([k for k in self.stats if self.stats[k][1] == col]) * 2
        self.grid.addWidget(lab, r, col)
        self.grid.addWidget(val, r + 1, col)
        self.stats[key] = (val, col)

    def set(self, key, text):
        if key in self.stats:
            self.stats[key][0].setText(text)


class PerformancePage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        p = win.p
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        hdr = PageHeader("Performance", [("Run new task", "plus"), ("More", "more")])
        hdr.buttons["Run new task"].clicked.connect(win.run_new_task)
        lay.addWidget(hdr)
        body = QHBoxLayout()
        lay.addLayout(body, 1)
        side = QVBoxLayout()
        side.setContentsMargins(8, 0, 0, 0)
        side.setSpacing(4)
        self.stack = QStackedWidget()
        self.tiles = {}
        self.details = {}
        self.group = QButtonGroup(self)

        def add(key, title, color, detail):
            tile = PerfTile(title, color, p)
            self.group.addButton(tile)
            idx = self.stack.addWidget(detail)
            tile.clicked.connect(lambda: self.stack.setCurrentIndex(idx))
            side.addWidget(tile)
            self.tiles[key] = tile
            self.details[key] = detail

        cpu = PerfDetail("CPU", sysinfo.cpu_model(), "#1191ff")
        for k in ("Utilization", "Speed", "Processes", "Threads", "Handles", "Up time"):
            cpu.stat(k, col=0 if k in ("Utilization", "Processes", "Up time") else (1 if k in ("Speed", "Threads") else 2))
        info_keys = ("Base speed:", "Sockets:", "Cores:", "Logical processors:", "Virtualization:", "L1/L2/L3 cache:")
        for k in info_keys:
            cpu.stat(k, big=False, col=3)
        add("cpu", "CPU", "#1191ff", cpu)

        mem = PerfDetail("Memory", human_bytes(psutil.virtual_memory().total).replace(".0", "") , "#9a41c8", ylabel="Memory usage")
        for k in ("In use", "Available", "Committed", "Cached", "Swap used", "Swap total"):
            mem.stat(k, col=0 if k in ("In use", "Committed", "Swap used") else 1)
        for k in ("Speed:", "Slots used:", "Form factor:", "Hardware reserved:"):
            mem.stat(k, big=False, col=2)
        add("mem", "Memory", "#9a41c8", mem)

        self.disk_keys = []
        for i, name in enumerate(sorted(win.sampler.disks().keys())):
            d = PerfDetail(f"Disk {i} ({name})", self._disk_model(name), "#4da60c", ylabel="Active time")
            for k in ("Active time", "Average response time", "Read speed", "Write speed"):
                d.stat(k, col=0 if k in ("Active time", "Read speed") else 1)
            for k in ("Capacity:", "Formatted:", "System disk:", "Type:"):
                d.stat(k, big=False, col=2)
            add(f"disk:{name}", f"Disk {i} ({name})", "#4da60c", d)
            self.disk_keys.append(name)

        self.net_keys = []
        for name in sorted(win.sampler.network().keys()):
            kind = "Wi-Fi" if name.startswith("wl") else "Ethernet"
            d = PerfDetail(kind, name, "#c1660b", series=2, maximum=None, ylabel="Throughput")
            for k in ("Send", "Receive"):
                d.stat(k, col=0)
            for k in ("Adapter name:", "Connection type:", "IPv4 address:", "IPv6 address:"):
                d.stat(k, big=False, col=1)
            add(f"net:{name}", kind, "#c1660b", d)
            self.net_keys.append(name)

        self.gpus = sysinfo.gpu_info()
        for i, (name, _) in enumerate(self.gpus):
            d = PerfDetail(f"GPU {i}", name, "#1e7fc7", ylabel="3D")
            for k in ("Utilization", "Driver:"):
                d.stat(k, big=k == "Utilization")
            add(f"gpu:{i}", f"GPU {i}", "#1e7fc7", d)

        side.addStretch()
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(250)
        scroll = QScrollArea()
        scroll.setWidget(sw)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(262)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body.addWidget(scroll)
        body.addWidget(self.stack, 1)
        self.tiles["cpu"].setChecked(True)
        self._static_info()

    def _disk_model(self, name):
        for f in (f"/sys/block/{name}/device/model", f"/sys/block/{name}/device/name"):
            try:
                return open(f).read().strip()
            except OSError:
                pass
        return name

    def _static_info(self):
        cpu = self.details["cpu"]
        f = sysinfo.cpu_freq()
        cpu.set("Base speed:", f"{(f.max or f.current) / 1000:.2f} GHz" if f else "-")
        phys = psutil.cpu_count(logical=False) or 1
        cpu.set("Cores:", str(phys))
        cpu.set("Logical processors:", str(psutil.cpu_count()))
        sockets = set()
        flags = ""
        try:
            for line in open("/proc/cpuinfo"):
                if line.startswith("physical id"):
                    sockets.add(line.split(":")[1].strip())
                elif line.startswith("flags") and not flags:
                    flags = line
        except OSError:
            pass
        cpu.set("Sockets:", str(max(1, len(sockets))))
        cpu.set("Virtualization:", "Enabled" if (" vmx" in flags or " svm" in flags) else "Not capable")
        caches = []
        for idx in (0, 2, 3):
            try:
                caches.append(open(f"/sys/devices/system/cpu/cpu0/cache/index{idx}/size").read().strip())
            except OSError:
                caches.append("-")
        cpu.set("L1/L2/L3 cache:", " / ".join(caches))
        mem = self.details["mem"]
        mem.set("Speed:", "-")
        mem.set("Slots used:", "-")
        mem.set("Form factor:", "-")
        mem.set("Hardware reserved:", "-")
        root_dev = ""
        for part in psutil.disk_partitions():
            if part.mountpoint == "/":
                root_dev = os.path.basename(part.device)
        for name in self.disk_keys:
            d = self.details[f"disk:{name}"]
            try:
                sectors = int(open(f"/sys/block/{name}/size").read())
                d.set("Capacity:", human_bytes(sectors * 512))
                rot = open(f"/sys/block/{name}/queue/rotational").read().strip()
                d.set("Type:", "HDD" if rot == "1" else "SSD")
            except OSError:
                pass
            d.set("System disk:", "Yes" if root_dev.startswith(name) else "No")
            usage = sum(psutil.disk_usage(pp.mountpoint).total for pp in psutil.disk_partitions()
                        if os.path.basename(pp.device).startswith(name))
            d.set("Formatted:", human_bytes(usage) if usage else "-")
        addrs = psutil.net_if_addrs()
        import socket
        for name in self.net_keys:
            d = self.details[f"net:{name}"]
            d.set("Adapter name:", name)
            d.set("Connection type:", "802.11" if name.startswith("wl") else "Ethernet")
            for a in addrs.get(name, []):
                if a.family == socket.AF_INET:
                    d.set("IPv4 address:", a.address)
                elif a.family == socket.AF_INET6:
                    d.set("IPv6 address:", a.address.split("%")[0])
        for i, _ in enumerate(self.gpus):
            d = self.details[f"gpu:{i}"]
            try:
                drv = os.path.basename(os.readlink(f"/sys/class/drm/card{i}/device/driver"))
            except OSError:
                drv = "-"
            d.set("Driver:", drv)

    def refresh(self):
        w = self.win
        util, per, freq = w.last_cpu
        t = self.tiles["cpu"]
        t.graph.push(util)
        t.sub.setText(f"{util:.0f}%  {freq / 1000:.2f} GHz")
        d = self.details["cpu"]
        d.graph.push(util)
        d.set("Utilization", f"{util:.0f}%")
        d.set("Speed", f"{freq / 1000:.2f} GHz")
        n_proc, n_thr, n_fd = w.counts
        d.set("Processes", str(n_proc))
        d.set("Threads", str(n_thr))
        d.set("Handles", str(n_fd))
        d.set("Up time", sysinfo.uptime())

        vm, sw = w.last_mem
        used = vm.total - vm.available
        t = self.tiles["mem"]
        t.graph.push(vm.percent)
        t.sub.setText(f"{used / 2**30:.1f}/{vm.total / 2**30:.1f} GB ({vm.percent:.0f}%)")
        d = self.details["mem"]
        d.graph.push(vm.percent)
        d.set("In use", human_bytes(used))
        d.set("Available", human_bytes(vm.available))
        d.set("Committed", f"{(used + sw.used) / 2**30:.1f}/{(vm.total + sw.total) / 2**30:.1f} GB")
        d.set("Cached", human_bytes(getattr(vm, "cached", 0) + getattr(vm, "buffers", 0)))
        d.set("Swap used", human_bytes(sw.used))
        d.set("Swap total", human_bytes(sw.total))

        for name in self.disk_keys:
            s = w.last_disks.get(name)
            if not s:
                continue
            t = self.tiles[f"disk:{name}"]
            t.graph.push(s["active"])
            t.sub.setText("SSD" if "nvme" in name else "Disk")
            t.sub2.setText(f"{s['active']:.0f}%")
            d = self.details[f"disk:{name}"]
            d.graph.push(s["active"])
            d.set("Active time", f"{s['active']:.0f}%")
            d.set("Read speed", human_bytes(s["read"]) + "/s")
            d.set("Write speed", human_bytes(s["write"]) + "/s")
            d.set("Average response time", "-")

        for name in self.net_keys:
            s = w.last_net.get(name)
            if not s:
                continue
            t = self.tiles[f"net:{name}"]
            t.graph.push(s["recv"] / 1024, s["sent"] / 1024)
            t.sub.setText(name)
            t.sub2.setText(f"S: {human_rate(s['sent'])} R: {human_rate(s['recv'])}")
            d = self.details[f"net:{name}"]
            d.graph.push(s["recv"] / 1024, s["sent"] / 1024)
            d.set("Send", human_rate(s["sent"]))
            d.set("Receive", human_rate(s["recv"]))
            d.ymax.setText(human_rate(max(max(d.graph.data[0]), max(d.graph.data[1])) * 1024 * 1.15))

        for i, (_, busy) in enumerate(sysinfo.gpu_info()):
            if f"gpu:{i}" not in self.tiles:
                continue
            v = busy or 0.0
            self.tiles[f"gpu:{i}"].graph.push(v)
            self.tiles[f"gpu:{i}"].sub.setText(f"{v:.0f}%" if busy is not None else "n/a")
            self.details[f"gpu:{i}"].graph.push(v)
            self.details[f"gpu:{i}"].set("Utilization", f"{v:.0f}%" if busy is not None else "n/a")


# --------------------------------------------------------------------------
class TablePage(QWidget):
    """Generic page with header + sortable flat table."""

    def __init__(self, win, title, cols, actions=()):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.header = PageHeader(title, actions)
        lay.addWidget(self.header)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(cols)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(0, 240)
        lay.addWidget(self.tree)
        self.items = {}

    def upsert(self, key, values, nums=None, icon=None):
        it = self.items.get(key)
        if it is None:
            it = SortItem()
            self.tree.addTopLevelItem(it)
            self.items[key] = it
            if icon is not None:
                it.setIcon(0, icon)
        for c, v in enumerate(values):
            if it.text(c) != str(v):
                it.setText(c, str(v))
            if nums and c < len(nums) and nums[c] is not None:
                it.setData(c, Qt.ItemDataRole.UserRole, nums[c])
        return it

    def prune(self, keep):
        for k in list(self.items):
            if k not in keep:
                it = self.items.pop(k)
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(it))


class AppHistoryPage(TablePage):
    def __init__(self, win):
        super().__init__(win, "App history", ["Name", "CPU time", "Network", "Metered network", "Tile updates"],
                         [("Delete usage history", "delete")])
        self.header.buttons["Delete usage history"].clicked.connect(self.clear)
        self.base = {}

    def clear(self):
        self.base = {p.name: p.cpu_time for p in self.win.last_procs}

    def refresh(self, procs):
        agg = {}
        me = os.environ.get("USER")
        for p in procs:
            if p.user == me:
                agg[p.name] = agg.get(p.name, 0.0) + p.cpu_time
        for name, t in agg.items():
            t = max(0.0, t - self.base.get(name, 0.0))
            h, rem = divmod(int(t), 3600)
            m, s = divmod(rem, 60)
            self.upsert(name, [name, f"{h}:{m:02d}:{s:02d}", "0 MB", "0 MB", "0 MB"], [name, t], icons.icon("file-exe"))
        self.prune(set(agg))


class StartupPage(TablePage):
    def __init__(self, win):
        super().__init__(win, "Startup apps", ["Name", "Publisher", "Status", "Startup impact"],
                         [("Enable", "startup"), ("Disable", "close"), ("Properties", "details")])
        self.header.buttons["Enable"].clicked.connect(lambda: self.set_enabled(True))
        self.header.buttons["Disable"].clicked.connect(lambda: self.set_enabled(False))
        self.header.buttons["Properties"].clicked.connect(self.props)
        self.reload()

    def reload(self):
        self.apps = {a.file: a for a in sysinfo.startup_apps()}
        for f, a in self.apps.items():
            self.upsert(os.path.basename(f), [a.name, a.publisher, "Enabled" if a.enabled else "Disabled",
                                               "Not measured"], icon=icons.icon("startup", self.win.p.text))
        self.prune({os.path.basename(f) for f in self.apps})

    def _current(self):
        it = self.tree.currentItem()
        if not it:
            return None
        key = next((k for k, v in self.items.items() if v is it), None)
        return next((a for f, a in self.apps.items() if os.path.basename(f) == key), None)

    def set_enabled(self, on):
        a = self._current()
        if a:
            sysinfo.set_startup_enabled(a, on)
            self.reload()

    def props(self):
        a = self._current()
        if a:
            QMessageBox.information(self, a.name, f"Command: {a.command}\nFile: {a.file}")

    def refresh(self, procs):
        pass


class UsersPage(TablePage):
    def __init__(self, win):
        super().__init__(win, "Users", ["User", "Status", "CPU", "Memory", "Disk", "Network"],
                         [("Disconnect", "close"), ("Manage user accounts", "users")])
        self.header.buttons["Manage user accounts"].clicked.connect(
            lambda: subprocess.Popen([sys.executable, "-m", "fenestra.settings", "--page", "accounts"]))

    def refresh(self, procs):
        keep = set()
        for name, status, a in sysinfo.users_summary(procs):
            keep.add(name)
            self.upsert(name, [f"{name} ({a['n']})", status, f"{a['cpu']:.1f}%", f"{a['mem'] / 1048576:.1f} MB",
                               f"{a['disk'] / 1048576:.1f} MB/s", "0 Mbps"],
                        [name, status, a["cpu"], a["mem"], a["disk"], 0], icons.icon("user", self.win.p.text))
        self.prune(keep)


class DetailsPage(TablePage):
    def __init__(self, win):
        super().__init__(win, "Details", ["Name", "PID", "Status", "User name", "CPU", "Memory (private)",
                                          "Threads", "Architecture", "Command line"],
                         [("Run new task", "plus"), ("End task", "close")])
        self.header.buttons["Run new task"].clicked.connect(win.run_new_task)
        self.header.buttons["End task"].clicked.connect(self.end)
        self.tree.customContextMenuRequested.connect(self.menu)
        self.arch = os.uname().machine

    def refresh(self, procs):
        q = self.win.search.text().strip().lower()
        keep = set()
        for p in procs:
            if q and q not in p.name.lower() and q not in str(p.pid):
                continue
            keep.add(p.pid)
            status = "Suspended" if p.status == "stopped" else ("Not responding" if p.status == "zombie" else "Running")
            self.upsert(p.pid, [p.name, p.pid, status, p.user, f"{p.cpu:02.0f}", f"{p.mem // 1024:,} K",
                                p.threads, self.arch, p.cmdline],
                        [p.name.lower(), p.pid, status, p.user, p.cpu, p.mem, p.threads, None, None])
        self.prune(keep)

    def current_pid(self):
        it = self.tree.currentItem()
        return int(it.text(1)) if it else None

    def end(self):
        pid = self.current_pid()
        if pid:
            self.win.kill([pid])

    def menu(self, pos):
        pid = self.current_pid()
        if not pid:
            return
        m = QMenu(self)
        m.addAction("End task", self.end)
        m.addAction("End process tree", lambda: self.win.kill_tree(pid))
        pr = m.addMenu("Set priority")
        for label, val in (("Realtime", -20), ("High", -10), ("Above normal", -5), ("Normal", 0),
                           ("Below normal", 5), ("Low", 19)):
            pr.addAction(label, lambda v=val: self.win.renice(pid, v))
        m.addAction("Set affinity", lambda: self.win.affinity(pid))
        m.addSeparator()
        m.addAction("Suspend process", lambda: self.win.signal(pid, signal.SIGSTOP))
        m.addAction("Resume process", lambda: self.win.signal(pid, signal.SIGCONT))
        m.addAction("Open file location", lambda: self.win.open_location(pid))
        m.addAction("Properties", lambda: self.win.properties(pid))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def select_pid(self, pid):
        it = self.items.get(pid)
        if it:
            self.tree.setCurrentItem(it)
            self.tree.scrollToItem(it)


class ServicesPage(TablePage):
    def __init__(self, win):
        super().__init__(win, "Services", ["Name", "PID", "Description", "Status"],
                         [("Start", "startup"), ("Stop", "close"), ("Restart", "refresh")])
        for action in ("Start", "Stop", "Restart"):
            self.header.buttons[action].clicked.connect(lambda _=False, a=action.lower(): self.act(a))
        self.tree.setColumnWidth(2, 380)
        self.tree.customContextMenuRequested.connect(self.menu)
        self.loaded = 0.0

    def refresh(self, procs):
        if time.monotonic() - self.loaded < 5:
            return
        self.loaded = time.monotonic()
        keep = set()
        for s in sysinfo.services():
            keep.add(s.name)
            self.upsert(s.name, [s.name, s.pid, s.description, s.status],
                        [s.name, int(s.pid or 0), s.description, s.status], icons.icon("services", self.win.p.text))
        self.prune(keep)

    def act(self, action):
        it = self.tree.currentItem()
        if it:
            sysinfo.service_action(it.text(0), action)
            self.loaded = 0

    def menu(self, pos):
        m = QMenu(self)
        for a in ("Start", "Stop", "Restart"):
            m.addAction(a, lambda a=a.lower(): self.act(a))
        m.exec(self.tree.viewport().mapToGlobal(pos))


# --------------------------------------------------------------------------
class TaskManager(FluentWindow):
    def __init__(self, p):
        super().__init__(p, "Task Manager", "taskmgr")
        self.resize(1080, 720)
        self.sampler = sysinfo.Sampler()
        self.last_procs = []
        self.last_disks = {}
        self.last_net = {}
        self.last_cpu = (0.0, [], 0.0)
        self.last_mem = psutil.virtual_memory(), psutil.swap_memory()
        self.counts = (0, 0, 0)

        central = QWidget()
        self.set_content(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar: hamburger, icon, name, centred search box (as in 22H2)
        menu_btn = QPushButton()
        menu_btn.setObjectName("Flat")
        menu_btn.setIcon(icons.icon("menu", p.text))
        menu_btn.clicked.connect(self.toggle_nav)
        self.titlebar.left.insertWidget(0, menu_btn)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a name, publisher, or PID to search")
        self.search.setFixedWidth(420)
        self.search.addAction(icons.icon("search", p.text_secondary), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda: self.tick(force_ui=True))
        self.titlebar.center.addStretch()
        self.titlebar.center.addWidget(self.search)
        self.titlebar.center.addStretch()

        body = QHBoxLayout()
        body.setSpacing(0)
        root.addLayout(body, 1)
        self.nav = QWidget()
        nl = QVBoxLayout(self.nav)
        nl.setContentsMargins(4, 4, 4, 8)
        nl.setSpacing(2)
        self.stack = QStackedWidget()
        self.pages = [ProcessesPage(self), PerformancePage(self), AppHistoryPage(self), StartupPage(self),
                      UsersPage(self), DetailsPage(self), ServicesPage(self)]
        self.nav_buttons = []
        for i, ((title, icon_name), page) in enumerate(zip(PAGES, self.pages)):
            b = NavButton(title, icon_name, p)
            b.clicked.connect(lambda _=False, i=i: self.show_page(i))
            nl.addWidget(b)
            self.nav_buttons.append(b)
            self.stack.addWidget(page)
        nl.addStretch()
        sb = NavButton("Settings", "settings", p)
        sb.clicked.connect(self.settings_dialog)
        nl.addWidget(sb)
        self.nav.setFixedWidth(200)
        body.addWidget(self.nav)
        content = QFrame()
        content.setObjectName("Card")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.stack)
        body.addWidget(content, 1)
        self.nav_buttons[0].setChecked(True)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        del_act = QAction(self)
        del_act.setShortcut(QKeySequence("Delete"))
        del_act.triggered.connect(self.delete_key)
        self.addAction(del_act)
        self.tick()

    # ------------------------------------------------------------------
    def toggle_nav(self):
        collapsed = self.nav.width() > 60
        self.nav.setFixedWidth(48 if collapsed else 200)
        for b, (title, _) in zip(self.nav_buttons, PAGES):
            b.setText("" if collapsed else title)

    def show_page(self, i):
        self.nav_buttons[i].setChecked(True)
        self.stack.setCurrentIndex(i)
        self.tick(force_ui=True)

    def delete_key(self):
        page = self.stack.currentWidget()
        if isinstance(page, ProcessesPage):
            page.end_task()
        elif isinstance(page, DetailsPage):
            page.end()

    def tick(self, force_ui=False):
        if not force_ui or not self.last_procs:
            app_pids, titles = set(), {}
            for w in x11.wm().windows():
                if w.pid:
                    app_pids.add(w.pid)
                    titles.setdefault(w.pid, w.title)
            self.last_procs = self.sampler.processes(app_pids, titles)
            self.last_cpu = self.sampler.cpu()
            self.last_mem = self.sampler.memory()
            self.last_disks = self.sampler.disks()
            self.last_net = self.sampler.network()
            n_thr = sum(p.threads for p in self.last_procs)
            self.counts = (len(self.last_procs), n_thr, self.counts[2] if self.counts[2] else sysinfo.counts()[2])
        page = self.stack.currentWidget()
        if isinstance(page, PerformancePage):
            page.refresh()
        else:
            # performance graphs must keep their history even when hidden
            self.pages[1].refresh()
            page.refresh(self.last_procs)

    # --- actions ----------------------------------------------------------
    def kill(self, pids):
        for pid in pids:
            try:
                psutil.Process(pid).terminate()
            except psutil.AccessDenied:
                if QMessageBox.question(self, "Task Manager", "Access denied. Retry as administrator?") \
                        == QMessageBox.StandardButton.Yes:
                    subprocess.call(["pkexec", "kill", str(pid)])
                return
            except psutil.NoSuchProcess:
                pass
        QTimer.singleShot(1500, lambda: [self._force(pid) for pid in pids])

    def _force(self, pid):
        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass

    def kill_tree(self, pid):
        try:
            parent = psutil.Process(pid)
            self.kill([c.pid for c in parent.children(recursive=True)] + [pid])
        except psutil.Error:
            pass

    def renice(self, pid, val):
        try:
            psutil.Process(pid).nice(val)
        except psutil.AccessDenied:
            subprocess.call(["pkexec", "renice", str(val), "-p", str(pid)])
        except psutil.Error as exc:
            QMessageBox.warning(self, "Task Manager", str(exc))

    def affinity(self, pid):
        try:
            p = psutil.Process(pid)
            cur = ",".join(map(str, p.cpu_affinity()))
        except (psutil.Error, AttributeError) as exc:
            QMessageBox.warning(self, "Task Manager", str(exc))
            return
        text, ok = QInputDialog.getText(self, "Processor affinity", "Allowed CPUs (comma separated):", text=cur)
        if ok:
            try:
                p.cpu_affinity([int(x) for x in text.split(",") if x.strip()])
            except (psutil.Error, ValueError) as exc:
                QMessageBox.warning(self, "Task Manager", str(exc))

    def signal(self, pid, sig):
        try:
            os.kill(pid, sig)
        except OSError as exc:
            QMessageBox.warning(self, "Task Manager", str(exc))

    def switch_to(self, pids):
        for w in x11.wm().windows():
            if w.pid in pids:
                x11.wm().activate(w.wid)
                return

    def dump(self, pid):
        out = os.path.expanduser(f"~/{psutil.Process(pid).name()}-{pid}.core")
        subprocess.Popen(["gcore", "-o", out, str(pid)])
        QMessageBox.information(self, "Task Manager", f"Writing memory dump to {out}")

    def goto_details(self, pid):
        self.nav_buttons[5].setChecked(True)
        self.show_page(5)
        self.pages[5].select_pid(pid)

    def open_location(self, pid):
        try:
            exe = psutil.Process(pid).exe()
        except psutil.Error:
            return
        subprocess.Popen([sys.executable, "-m", "fenestra.explorer", os.path.dirname(exe)])

    def search_online(self, pid):
        try:
            name = psutil.Process(pid).name()
        except psutil.Error:
            return
        hostos.open_path(f"https://duckduckgo.com/?q={name}+process")

    def properties(self, pid):
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                txt = (f"Name: {p.name()}\nPID: {pid}\nExecutable: {p.exe()}\nCommand: {' '.join(p.cmdline())}\n"
                       f"User: {p.username()}\nStarted: {time.ctime(p.create_time())}\nThreads: {p.num_threads()}\n"
                       f"Priority (nice): {p.nice()}\nWorking dir: {p.cwd()}")
        except psutil.Error as exc:
            txt = str(exc)
        QMessageBox.information(self, "Properties", txt)

    def run_new_task(self):
        dlg = RunDialog(self)
        dlg.exec()

    def settings_dialog(self):
        m = QMenu(self)
        for label, ms in (("High (0.5 s)", 500), ("Normal (1 s)", 1000), ("Low (4 s)", 4000), ("Paused", 0)):
            a = m.addAction(f"Real time update speed: {label}")
            a.triggered.connect(lambda _=False, ms=ms: self.timer.start(ms) if ms else self.timer.stop())
        top = m.addAction("Always on top")
        top.setCheckable(True)
        top.setChecked(bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        top.triggered.connect(self.toggle_on_top)
        m.exec(self.cursor().pos())

    def toggle_on_top(self, on):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()


class RunDialog(QMessageBox):
    """'Create new task' dialog."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Create new task")
        self.setText("Type the name of a program, folder, document, or Internet resource, and Fenestra will open it for you.")
        self.edit = QLineEdit()
        self.admin = QCheckBox("Create this task with administrative privileges.")
        lay = self.layout()
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.addWidget(self.edit)
        bl.addWidget(self.admin)
        lay.addWidget(box, lay.rowCount(), 0, 1, lay.columnCount())
        self.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        self.buttonClicked.connect(lambda b: self.standardButton(b) == QMessageBox.StandardButton.Ok and self.go())

    def go(self):
        text = self.edit.text().strip()
        if not text:
            return
        import shlex
        try:
            argv = shlex.split(text)
        except ValueError:
            argv = [text]
        if argv[0].lower().endswith((".exe", ".msi", ".bat", ".cmd")):
            argv = [sys.executable, "-m", "fenestra.compat", "run"] + argv
        elif os.path.exists(os.path.expanduser(argv[0])) and not os.access(os.path.expanduser(argv[0]), os.X_OK):
            argv = ["open" if hostos.IS_MAC else "xdg-open", os.path.expanduser(argv[0])]
        if self.admin.isChecked():
            argv = ["pkexec"] + argv
        try:
            subprocess.Popen(argv, start_new_session=True)
        except OSError as exc:
            QMessageBox.warning(self.parent(), "Create new task", f"Fenestra cannot find '{text}'.\n{exc}")


def main(argv=None):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("fenestra-taskmgr")
    p = theme.apply(app)
    w = TaskManager(p)
    w.show()
    return app.exec()
