"""Settings - modelled on the Windows 11 Settings app."""

import argparse
import getpass
import os
import platform
import shutil
import socket
import subprocess
import sys
import time

import psutil
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFileDialog, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                             QScrollArea, QSlider, QStackedWidget, QVBoxLayout, QWidget)

import fenestra

from ..common import platform as hostos
from ..common import apps as appreg
from ..common import config, icons, theme
from ..common.widgets import NavButton, SettingCard, ToggleSwitch, human_bytes
from ..common.window import FluentWindow

ACCENTS = ["#0067c0", "#0078d4", "#744da9", "#b146c2", "#c30052", "#e81123", "#ca5010", "#ff8c00",
           "#498205", "#107c10", "#038387", "#00b7c3", "#2d7d9a", "#486860", "#525e54", "#68768a"]

PAGES = [
    ("system", "System", "monitor"),
    ("bluetooth", "Bluetooth & devices", "bluetooth"),
    ("network", "Network & internet", "wifi"),
    ("personalization", "Personalization", "photos"),
    ("apps", "Apps", "apps"),
    ("accounts", "Accounts", "user"),
    ("time", "Time & language", "history"),
    ("gaming", "Gaming", "performance"),
    ("accessibility", "Accessibility", "user"),
    ("privacy", "Privacy & security", "lock"),
    ("update", "Fenestra Update", "refresh"),
]


def run(cmd, timeout=3):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


class Page(QScrollArea):
    def __init__(self, title):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QScrollArea { background: transparent; }")
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        self.lay = QVBoxLayout(w)
        self.lay.setContentsMargins(36, 8, 36, 24)
        self.lay.setSpacing(4)
        t = QLabel(title)
        t.setObjectName("Title")
        self.lay.addWidget(t)
        self.lay.addSpacing(12)
        self.setWidget(w)

    def section(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: 600; margin-top: 14px; margin-bottom: 4px;")
        self.lay.addWidget(lbl)

    def add(self, w):
        self.lay.addWidget(w)
        return w

    def finish(self):
        self.lay.addStretch()


class SettingsWindow(FluentWindow):
    def __init__(self, p, page="system"):
        super().__init__(p, "Settings", "settings")
        self.resize(1100, 760)
        body = QWidget()
        self.set_content(body)
        lay = QHBoxLayout(body)
        lay.setContentsMargins(8, 0, 0, 0)
        lay.setSpacing(0)

        # left column: user card + search + navigation
        left = QWidget()
        left.setFixedWidth(300)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 4, 12, 12)
        user = QHBoxLayout()
        av = QLabel()
        av.setPixmap(self._avatar(64))
        user.addWidget(av)
        col = QVBoxLayout()
        name = QLabel(getpass.getuser())
        name.setStyleSheet("font-weight: 600; font-size: 11pt;")
        col.addWidget(name)
        acct = QLabel("Local Account")
        acct.setObjectName("Secondary")
        col.addWidget(acct)
        user.addLayout(col, 1)
        ll.addLayout(user)
        ll.addSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a setting")
        self.search.addAction(icons.icon("search", p.text_secondary), QLineEdit.ActionPosition.TrailingPosition)
        self.search.textChanged.connect(self.filter_nav)
        ll.addWidget(self.search)
        ll.addSpacing(8)
        self.stack = QStackedWidget()
        self.nav = {}
        self.page_index = {}
        group = QButtonGroup(self)
        for key, title, icon_name in PAGES:
            b = NavButton(title, icon_name, p)
            group.addButton(b)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            ll.addWidget(b)
            self.nav[key] = b
        ll.addStretch()
        lay.addWidget(left)
        lay.addWidget(self.stack, 1)

        self.builders = {
            "system": self.page_system, "bluetooth": self.page_bluetooth, "network": self.page_network,
            "personalization": self.page_personalization, "apps": self.page_apps, "accounts": self.page_accounts,
            "time": self.page_time, "gaming": self.page_gaming, "accessibility": self.page_accessibility,
            "privacy": self.page_privacy, "update": self.page_update, "about": self.page_about,
        }
        self.show_page(page if page in self.builders else "system")

    def _avatar(self, size):
        face = os.path.expanduser("~/.face")
        pm = QPixmap(face) if os.path.exists(face) else QPixmap()
        if pm.isNull():
            pm = icons.pixmap("user", size, self.p.text)
        return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    def filter_nav(self, text):
        t = text.lower()
        for key, title, _ in PAGES:
            self.nav[key].setVisible(not t or t in title.lower() or t in key)

    def show_page(self, key):
        if key not in self.page_index:
            page = self.builders[key]()
            self.page_index[key] = self.stack.addWidget(page)
        self.stack.setCurrentIndex(self.page_index[key])
        nav_key = "system" if key == "about" else key
        if nav_key in self.nav:
            self.nav[nav_key].setChecked(True)

    # --- helpers --------------------------------------------------------
    def chevron(self, target):
        b = QPushButton()
        b.setObjectName("Flat")
        b.setIcon(icons.icon("chevron-right", self.p.text_secondary))
        b.clicked.connect(lambda: self.show_page(target) if target in self.builders else subprocess.Popen(target, shell=True))
        return b

    def toggle(self, checked, fn):
        t = ToggleSwitch(self.p, checked)
        t.toggled.connect(fn)
        return t

    # --- pages ----------------------------------------------------------
    def page_system(self):
        pg = Page("System")
        hero = QFrame()
        hero.setObjectName("Card")
        hl = QHBoxLayout(hero)
        pc = QLabel()
        pc.setPixmap(icons.pixmap("monitor", 96))
        hl.addWidget(pc)
        col = QVBoxLayout()
        host = QLabel(socket.gethostname())
        host.setStyleSheet("font-size: 14pt; font-weight: 600;")
        col.addWidget(host)
        model = run(["cat", "/sys/class/dmi/id/product_name"]).strip() or platform.machine()
        m = QLabel(model)
        m.setObjectName("Secondary")
        col.addWidget(m)
        rn = QPushButton("Rename")
        rn.clicked.connect(self.rename_pc)
        col.addWidget(rn, alignment=Qt.AlignmentFlag.AlignLeft)
        hl.addLayout(col, 1)
        pg.add(hero)
        pg.lay.addSpacing(8)
        from ..shell import system as sysctl
        vol, _ = sysctl.get_volume()
        bright = sysctl.get_brightness()
        rows = [
            ("monitor", "Display", "Monitors, brightness, night light, display profile", "xrandr-settings"),
            ("volume", "Sound", f"Volume level {vol}%, output, input, sound devices", "sound"),
            ("bell", "Notifications", "Alerts from apps and system, do not disturb", None),
            ("moon", "Focus", "Reduce distractions", None),
            ("power", "Power & battery", "Sleep, battery usage, battery saver", "power"),
            ("drive", "Storage", "Storage space, drives, configuration rules", "storage"),
            ("taskview", "Multitasking", "Snap windows, desktops, task switching", None),
            ("details", "About", "Device specifications, rename PC, Fenestra specifications", "about"),
        ]
        for ic, title, desc, target in rows:
            if target == "xrandr-settings":
                card = SettingCard(ic, title, desc, self._display_controls(bright), self.p)
            elif target == "sound":
                s = QSlider(Qt.Orientation.Horizontal)
                s.setRange(0, 100)
                s.setValue(vol)
                s.setFixedWidth(200)
                s.valueChanged.connect(sysctl.set_volume)
                card = SettingCard(ic, title, desc, s, self.p)
            elif target == "storage":
                card = SettingCard(ic, title, desc, self.chevron("storage-page"), self.p)
                card.clicked.connect(self.show_storage)
            elif target == "about":
                card = SettingCard(ic, title, desc, self.chevron("about"), self.p)
                card.clicked.connect(lambda: self.show_page("about"))
            elif target == "power":
                card = SettingCard(ic, title, desc, self._power_combo(), self.p)
            else:
                card = SettingCard(ic, title, desc, None, self.p)
            pg.add(card)
        pg.finish()
        return pg

    def _display_controls(self, bright):
        from ..shell import system as sysctl
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(10, 100)
        s.setValue(bright if bright is not None else config.get("brightness"))
        s.setFixedWidth(160)
        s.valueChanged.connect(lambda v: (config.set("brightness", v), sysctl.set_brightness(v)))
        l.addWidget(s)
        res = QComboBox()
        modes = []
        out = run(["xrandr", "--query"])
        current = ""
        for line in out.splitlines():
            if line.startswith("   ") and "x" in line.split()[0]:
                mode = line.split()[0]
                modes.append(mode)
                if "*" in line:
                    current = mode
        res.addItems(modes or ["1920x1080"])
        if current:
            res.setCurrentText(current)

        def set_mode(mode):
            import re
            m = re.search(r"^(\S+) connected", out, re.M)
            if m:
                subprocess.Popen(["xrandr", "--output", m.group(1), "--mode", mode])
        res.currentTextChanged.connect(set_mode)
        l.addWidget(res)
        return w

    def _power_combo(self):
        c = QComboBox()
        c.addItems(["Balanced", "Best power efficiency", "Best performance"])
        profiles = {"Balanced": "balanced", "Best power efficiency": "power-saver", "Best performance": "performance"}
        cur = run(["powerprofilesctl", "get"]).strip()
        for k, v in profiles.items():
            if v == cur:
                c.setCurrentText(k)
        c.currentTextChanged.connect(lambda t: subprocess.Popen(["powerprofilesctl", "set", profiles[t]]))
        return c

    def rename_pc(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Rename your PC", "Your PC name can be a combination of letters, hyphens, and numbers.",
                                        text=socket.gethostname())
        if ok and name:
            subprocess.Popen(["pkexec", "hostnamectl", "set-hostname", name])

    def show_storage(self):
        key = "storage"
        if key not in self.page_index:
            pg = Page("System  ›  Storage")
            for part in psutil.disk_partitions():
                try:
                    u = psutil.disk_usage(part.mountpoint)
                except OSError:
                    continue
                if part.fstype in ("squashfs", "tmpfs", "overlay"):
                    continue
                card = QFrame()
                card.setObjectName("Card")
                cl = QVBoxLayout(card)
                t = QLabel(f"{'Local Disk (C:)' if part.mountpoint == '/' else part.mountpoint}  —  {part.device} ({part.fstype})")
                t.setStyleSheet("font-weight: 600;")
                cl.addWidget(t)
                from PyQt6.QtWidgets import QProgressBar
                bar = QProgressBar()
                bar.setValue(int(u.percent))
                bar.setTextVisible(False)
                cl.addWidget(bar)
                info = QLabel(f"{human_bytes(u.used)} used  ·  {human_bytes(u.free)} free  ·  {human_bytes(u.total)} total")
                info.setObjectName("Secondary")
                cl.addWidget(info)
                pg.add(card)
            pg.section("Storage management")
            clean = QPushButton("Clean up temporary files and package cache")
            clean.clicked.connect(lambda: subprocess.Popen(["pkexec", "sh", "-c", "apt-get clean; journalctl --vacuum-time=7d"]))
            pg.add(SettingCard("delete", "Cleanup recommendations", "Free up space by removing caches and old logs", clean, self.p))
            pg.finish()
            self.page_index[key] = self.stack.addWidget(pg)
        self.stack.setCurrentIndex(self.page_index[key])

    def page_about(self):
        pg = Page("System  ›  About")
        vm = psutil.virtual_memory()
        cpu = "Unknown"
        try:
            for line in open("/proc/cpuinfo"):
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
        os_name = "Linux"
        try:
            for line in open("/etc/os-release"):
                if line.startswith("PRETTY_NAME="):
                    os_name = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        pg.section("Device specifications")
        card = QFrame()
        card.setObjectName("Card")
        g = QGridLayout(card)
        rows = [("Device name", socket.gethostname()), ("Processor", cpu),
                ("Installed RAM", human_bytes(vm.total)), ("System type", f"{platform.architecture()[0]} operating system, {platform.machine()}-based processor"),
                ("Pen and touch", "No pen or touch input is available for this display")]
        for i, (k, v) in enumerate(rows):
            a = QLabel(k)
            a.setObjectName("Secondary")
            b = QLabel(v)
            b.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            g.addWidget(a, i, 0)
            g.addWidget(b, i, 1)
        g.setColumnStretch(1, 1)
        pg.add(card)
        pg.section("Fenestra specifications")
        card2 = QFrame()
        card2.setObjectName("Card")
        g2 = QGridLayout(card2)
        rows2 = [("Edition", "Fenestra OS Home"), ("Version", fenestra.__version__), ("Base system", os_name),
                 ("Kernel", platform.release()), ("Desktop", "Fenestra Shell on Openbox"),
                 ("Windows compatibility", (run(["wine", "--version"]).strip() or "Wine not installed"))]
        for i, (k, v) in enumerate(rows2):
            a = QLabel(k)
            a.setObjectName("Secondary")
            b = QLabel(v)
            b.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            g2.addWidget(a, i, 0)
            g2.addWidget(b, i, 1)
        g2.setColumnStretch(1, 1)
        pg.add(card2)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(
            "\n".join(f"{k}\t{v}" for k, v in rows + rows2)))
        pg.add(copy)
        pg.finish()
        return pg

    def page_bluetooth(self):
        pg = Page("Bluetooth & devices")
        from ..shell import system as sysctl
        pg.add(SettingCard("bluetooth", "Bluetooth", "Discoverable as " + socket.gethostname(),
                           self.toggle(sysctl.bluetooth_state(), sysctl.set_bluetooth), self.p))
        add = QPushButton("Add device")
        add.clicked.connect(lambda: subprocess.Popen(["blueman-manager"]) if shutil.which("blueman-manager") else None)
        pg.add(SettingCard("plus", "Add a device", "Bluetooth, audio, displays, mice, keyboards", add, self.p))
        pg.section("Devices")
        out = run(["bluetoothctl", "devices"])
        for line in out.splitlines()[:20]:
            parts = line.split(" ", 2)
            if len(parts) == 3:
                pg.add(SettingCard("bluetooth", parts[2], parts[1], None, self.p))
        for title, desc, cmd in (("Printers & scanners", "Preferences, troubleshoot", "system-config-printer"),
                                 ("Mouse", "Buttons, mouse pointer speed, scrolling", "lxinput"),
                                 ("Touchpad", "Taps, gestures, scrolling, zooming", "lxinput")):
            b = QPushButton("Open")
            b.clicked.connect(lambda _=False, c=cmd: shutil.which(c) and subprocess.Popen([c]))
            pg.add(SettingCard("monitor", title, desc, b, self.p))
        pg.finish()
        return pg

    def page_network(self):
        pg = Page("Network & internet")
        from ..shell import system as sysctl
        on, ssid = sysctl.wifi_state()
        status = QFrame()
        status.setObjectName("Card")
        sl = QHBoxLayout(status)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("wifi", 48, self.p.accent))
        sl.addWidget(ic)
        col = QVBoxLayout()
        t = QLabel(ssid or "Not connected")
        t.setStyleSheet("font-size: 13pt; font-weight: 600;")
        col.addWidget(t)
        s = QLabel("Connected, secured" if ssid else "You aren't connected to any networks")
        s.setObjectName("Secondary")
        col.addWidget(s)
        sl.addLayout(col, 1)
        pg.add(status)
        pg.lay.addSpacing(8)
        pg.add(SettingCard("wifi", "Wi-Fi", "Connect, manage known networks, metered network",
                           self.toggle(on, sysctl.set_wifi), self.p))
        for ic_name, title, desc in (("monitor", "Ethernet", "Authentication, IP and DNS settings, metered network"),
                                     ("lock", "VPN", "Add, connect, manage"),
                                     ("share", "Mobile hotspot", "Share your internet connection"),
                                     ("airplane", "Airplane mode", "Stop all wireless communication")):
            b = QPushButton("Open")
            b.clicked.connect(lambda: subprocess.Popen(["nm-connection-editor"]) if shutil.which("nm-connection-editor") else None)
            pg.add(SettingCard(ic_name, title, desc, b, self.p))
        pg.section("Advanced network settings")
        addrs = psutil.net_if_addrs()
        for nic, lst in addrs.items():
            if nic == "lo":
                continue
            ipv4 = next((a.address for a in lst if a.family == socket.AF_INET), "-")
            pg.add(SettingCard("monitor", nic, f"IPv4: {ipv4}", None, self.p))
        pg.finish()
        return pg

    def page_personalization(self):
        pg = Page("Personalization")
        preview = QLabel()
        from ..shell import wallpaper
        path = config.get("wallpaper") or wallpaper.cached(1920, 1080, self.p.dark)
        pm = QPixmap(path)
        preview.setPixmap(pm.scaled(360, 200, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                    Qt.TransformationMode.SmoothTransformation))
        preview.setFixedSize(360, 200)
        preview.setStyleSheet("border-radius: 8px;")
        pg.add(preview)
        pg.lay.addSpacing(8)

        mode = QComboBox()
        mode.addItems(["Light", "Dark"])
        mode.setCurrentIndex(1 if config.get("theme") == "dark" else 0)
        mode.currentIndexChanged.connect(lambda i: self.apply_setting("theme", "dark" if i else "light"))
        pg.add(SettingCard("sun", "Choose your mode", "Change the colors that appear in Fenestra and your apps", mode, self.p))

        bg = QPushButton("Browse photos")
        bg.clicked.connect(self.pick_wallpaper)
        pg.add(SettingCard("photos", "Background", "Background image, color, slideshow", bg, self.p))

        accent_card = QFrame()
        accent_card.setObjectName("Card")
        al = QVBoxLayout(accent_card)
        al.addWidget(QLabel("Accent color"))
        grid = QGridLayout()
        for i, color in enumerate(ACCENTS):
            b = QPushButton()
            b.setFixedSize(40, 40)
            sel = color == config.get("accent")
            b.setStyleSheet(f"QPushButton {{ background: {color}; border-radius: 4px; border: {'3px solid ' + self.p.text if sel else 'none'}; }}")
            b.clicked.connect(lambda _=False, c=color: self.apply_setting("accent", c))
            grid.addWidget(b, i // 8, i % 8)
        gw = QWidget()
        gw.setLayout(grid)
        al.addWidget(gw, alignment=Qt.AlignmentFlag.AlignLeft)
        pg.add(accent_card)

        pg.add(SettingCard("efficiency", "Transparency effects", "Windows and surfaces appear translucent",
                           self.toggle(config.get("transparency"), lambda on: self.apply_setting("transparency", on)), self.p))
        align = QComboBox()
        align.addItems(["Center", "Left"])
        align.setCurrentIndex(1 if config.get("taskbar_alignment") == "left" else 0)
        align.currentIndexChanged.connect(lambda i: self.apply_setting("taskbar_alignment", "left" if i else "center"))
        pg.add(SettingCard("taskview", "Taskbar alignment", "Taskbar behaviors", align, self.p))
        pg.add(SettingCard("history", "Show seconds in system tray clock", "Uses more power",
                           self.toggle(config.get("show_seconds"), lambda on: self.apply_setting("show_seconds", on)), self.p))
        pg.finish()
        return pg

    def apply_setting(self, key, value):
        config.set(key, value)
        subprocess.Popen([sys.executable, "-m", "fenestra.shell", "reload"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if key in ("theme", "accent"):
            # Restart Settings with the new palette so the change is visible immediately
            current = next((k for k, i in self.page_index.items() if i == self.stack.currentIndex()), "personalization")
            self.close()
            subprocess.Popen([sys.executable, "-m", "fenestra.settings", "--page", current])

    def pick_wallpaper(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a background", os.path.expanduser("~/Pictures"),
                                              "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.apply_setting("wallpaper", path)

    def page_apps(self):
        pg = Page("Apps")
        search = QLineEdit()
        search.setPlaceholderText("Search apps")
        pg.add(search)
        lst = QListWidget()
        lst.setMinimumHeight(420)
        lst.setIconSize(QSize(32, 32))
        all_apps = appreg.all_apps()

        def fill(text=""):
            lst.clear()
            for a in all_apps:
                if text.lower() in a.name.lower():
                    it = QListWidgetItem(appreg.app_icon(a), a.name)
                    it.setData(Qt.ItemDataRole.UserRole, a.id)
                    lst.addItem(it)
        search.textChanged.connect(fill)
        fill()
        pg.add(lst)
        row = QHBoxLayout()
        un = QPushButton("Uninstall")
        un.clicked.connect(lambda: self.uninstall(lst.currentItem()))
        conv = QPushButton("Run Windows app…")
        conv.clicked.connect(lambda: subprocess.Popen([sys.executable, "-m", "fenestra.compat", "gui"]))
        store = QPushButton("Get more apps")
        store.setObjectName("Accent")
        store.clicked.connect(lambda: appreg.builtin_apps()["store"].launch())
        for b in (store, conv, un):
            row.addWidget(b)
        row.addStretch()
        w = QWidget()
        w.setLayout(row)
        pg.add(w)
        pg.section("Default apps & startup")
        pg.add(SettingCard("startup", "Startup", "Apps that start automatically when you sign in",
                           self.chevron("python3 -m fenestra.taskmgr"), self.p))
        pg.finish()
        return pg

    def uninstall(self, item):
        if not item:
            return
        app_id = item.data(Qt.ItemDataRole.UserRole)
        conv = os.path.expanduser(f"~/.local/share/applications/{app_id}.desktop")
        if app_id.startswith("fenestra-app-") and os.path.exists(conv):
            os.remove(conv)
            item.setHidden(True)
            return
        pkg = run(["dpkg", "-S", f"/usr/share/applications/{app_id}.desktop"]).split(":")[0].strip()
        if pkg:
            hostos.open_terminal(command=f"sudo apt remove {pkg}")

    def page_accounts(self):
        pg = Page("Accounts")
        pg.add(SettingCard("user", getpass.getuser(), "Local account · Administrator" if os.getuid() == 0 or
                           "sudo" in run(["id", "-nG"]) else "Local account", None, self.p))
        pic = QPushButton("Browse files")
        pic.clicked.connect(self.pick_avatar)
        pg.add(SettingCard("photos", "Your info", "Profile picture", pic, self.p))
        pw = QPushButton("Change")
        pw.clicked.connect(lambda: hostos.open_terminal(command="passwd"))
        pg.add(SettingCard("lock", "Sign-in options", "Password, automatic sign-in", pw, self.p))
        add = QPushButton("Add account")
        add.clicked.connect(lambda: hostos.open_terminal(command="sudo adduser"))
        pg.add(SettingCard("users", "Other users", "Device access, work or school users", add, self.p))
        pg.finish()
        return pg

    def pick_avatar(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a picture", os.path.expanduser("~/Pictures"),
                                              "Images (*.png *.jpg *.jpeg)")
        if path:
            shutil.copy(path, os.path.expanduser("~/.face"))

    def page_time(self):
        pg = Page("Time & language")
        now = QLabel(time.strftime("%H:%M  ·  %A, %B %d, %Y"))
        now.setStyleSheet("font-size: 16pt;")
        pg.add(now)
        timer = QTimer(pg)
        timer.timeout.connect(lambda: now.setText(time.strftime("%H:%M  ·  %A, %B %d, %Y")))
        timer.start(10000)
        tz = run(["timedatectl", "show", "-p", "Timezone", "--value"]).strip() or time.tzname[0]
        zones = QComboBox()
        all_zones = run(["timedatectl", "list-timezones"]).split() or [tz]
        zones.addItems(all_zones)
        zones.setCurrentText(tz)
        zones.currentTextChanged.connect(lambda z: subprocess.Popen(["pkexec", "timedatectl", "set-timezone", z]))
        pg.add(SettingCard("history", "Time zone", tz, zones, self.p))
        ntp = "yes" in run(["timedatectl", "show", "-p", "NTP", "--value"])
        pg.add(SettingCard("refresh", "Set time automatically", "Synchronise with internet time servers",
                           self.toggle(ntp, lambda on: subprocess.Popen(["pkexec", "timedatectl", "set-ntp", "true" if on else "false"])), self.p))
        lang = QComboBox()
        langs = {"English (United States)": "en_US.UTF-8", "한국어 (대한민국)": "ko_KR.UTF-8", "日本語": "ja_JP.UTF-8",
                 "中文(简体)": "zh_CN.UTF-8", "Deutsch": "de_DE.UTF-8", "Français": "fr_FR.UTF-8", "Español": "es_ES.UTF-8"}
        lang.addItems(list(langs))
        cur = os.environ.get("LANG", "en_US.UTF-8")
        for k, v in langs.items():
            if v.split(".")[0] == cur.split(".")[0]:
                lang.setCurrentText(k)
        lang.currentTextChanged.connect(lambda k: subprocess.Popen(["pkexec", "localectl", "set-locale", f"LANG={langs[k]}"]))
        pg.add(SettingCard("star", "Fenestra display language", "Apps and system text (applies after sign-in)", lang, self.p))
        ime = QPushButton("Input method")
        ime.clicked.connect(lambda: subprocess.Popen(["fcitx5-configtool"]) if shutil.which("fcitx5-configtool") else None)
        pg.add(SettingCard("rename", "Typing", "Keyboard layouts and input methods (Hangul, Pinyin, ...)", ime, self.p))
        pg.finish()
        return pg

    def page_gaming(self):
        pg = Page("Gaming")
        for ic, title, desc, cmd in (
                ("performance", "Steam", "Play Windows games with Proton", "steam"),
                ("compat", "Lutris", "Install games from GOG, Epic, Battle.net and more", "lutris"),
                ("compat", "Bottles", "Advanced Wine prefix management", "bottles")):
            b = QPushButton("Open" if shutil.which(cmd) else "Install")
            b.clicked.connect(lambda _=False, c=cmd: subprocess.Popen([c]) if shutil.which(c) else
                              hostos.open_terminal(command=f"sudo apt install {c}"))
            pg.add(SettingCard(ic, title, desc, b, self.p))
        gm = shutil.which("gamemoded") is not None
        pg.add(SettingCard("efficiency", "Game Mode", "Optimise the PC for play (Feral GameMode)" +
                           ("" if gm else " — not installed"), self.toggle(gm, lambda _on: None), self.p))
        pg.finish()
        return pg

    def page_accessibility(self):
        pg = Page("Accessibility")
        size = QSlider(Qt.Orientation.Horizontal)
        size.setRange(100, 225)
        size.setValue(100)
        size.setFixedWidth(200)
        pg.add(SettingCard("rename", "Text size", "Make text bigger across the system (applies to new windows)", size, self.p))
        size.valueChanged.connect(lambda v: config.set("text_scale", v))
        for ic, title, desc, cmd in (("view", "Magnifier", "Zoom in parts of the screen", "kmag"),
                                     ("volume", "Narrator", "Screen reader (Orca)", "orca"),
                                     ("rename", "On-screen keyboard", "Type without a physical keyboard", "onboard")):
            b = QPushButton("Open")
            b.clicked.connect(lambda _=False, c=cmd: shutil.which(c) and subprocess.Popen([c]))
            pg.add(SettingCard(ic, title, desc, b, self.p))
        pg.finish()
        return pg

    def page_privacy(self):
        pg = Page("Privacy & security")
        fw = "active" in run(["systemctl", "is-active", "ufw"])
        pg.add(SettingCard("lock", "Firewall & network protection", "Uncomplicated Firewall (ufw)",
                           self.toggle(fw, lambda on: subprocess.Popen(["pkexec", "ufw", "enable" if on else "disable"])), self.p))
        pg.add(SettingCard("history", "Activity history", "Recently used files shown in Start and File Explorer",
                           self.toggle(True, lambda on: on or open(os.path.expanduser("~/.local/share/recently-used.xbel"), "w").close()), self.p))
        for ic, title in (("photos", "Camera"), ("volume", "Microphone"), ("monitor", "Location")):
            pg.add(SettingCard(ic, title, "Apps that can access this device", self.toggle(True, lambda _on: None), self.p))
        pg.finish()
        return pg

    def page_update(self):
        pg = Page("Fenestra Update")
        card = QFrame()
        card.setObjectName("Card")
        cl = QHBoxLayout(card)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("refresh", 48, self.p.accent))
        cl.addWidget(ic)
        self.update_label = QLabel("You're up to date\nLast checked: never")
        cl.addWidget(self.update_label, 1)
        chk = QPushButton("Check for updates")
        chk.setObjectName("Accent")
        chk.clicked.connect(self.check_updates)
        cl.addWidget(chk)
        pg.add(card)
        pg.add(SettingCard("history", "Update history", "Package manager log", self.chevron("x-terminal-emulator -e less /var/log/apt/history.log"), self.p))
        pg.add(SettingCard("settings", "Advanced options", "Delivery optimisation, optional updates",
                           self.chevron("software-properties-gtk"), self.p))
        pg.finish()
        return pg

    def check_updates(self):
        self.update_label.setText("Checking for updates…")
        QApplication.processEvents()
        out = run(["apt", "list", "--upgradable"], timeout=20)
        n = max(0, len([l for l in out.splitlines() if "/" in l]))
        stamp = time.strftime("%Y-%m-%d %H:%M")
        if n:
            self.update_label.setText(f"{n} updates available\nLast checked: {stamp}")
            hostos.open_terminal(command="sudo apt upgrade")
        else:
            self.update_label.setText(f"You're up to date\nLast checked: {stamp}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fenestra-settings")
    ap.add_argument("--page", default="system")
    a = ap.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("fenestra-settings")
    p = theme.apply(app)
    w = SettingsWindow(p, a.page)
    w.show()
    return app.exec()
