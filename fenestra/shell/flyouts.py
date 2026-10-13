"""Quick Settings, Notification Center/Calendar and Task View flyouts."""

import time

from PyQt6.QtCore import QDate, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QCalendarWidget, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget, QInputDialog, QLineEdit)

from ..common import config, icons, x11
from . import system
from .startmenu import Flyout


class QuickToggle(QWidget):
    """Windows 11 quick-settings tile: split button + label underneath."""

    toggled = pyqtSignal(bool)

    def __init__(self, p, icon_name, label, checked=False, has_more=False):
        super().__init__()
        self.p = p
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.btn = QToolButton()
        self.btn.setCheckable(True)
        self.btn.setChecked(checked)
        self.btn.setIcon(icons.icon(icon_name, p.text))
        self.btn.setIconSize(QSize(16, 16))
        self.btn.setFixedSize(96, 48)
        self.icon_name = icon_name
        self.btn.toggled.connect(self._restyle)
        self.btn.toggled.connect(self.toggled.emit)
        self.label = QLabel(label)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("font-size: 8.5pt;")
        lay.addWidget(self.btn, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.label)
        self._restyle(checked)

    def _restyle(self, on):
        p = self.p
        if on:
            self.btn.setStyleSheet(f"QToolButton {{ background: {p.accent}; border: 1px solid {p.accent}; border-radius: 4px; }}")
            self.btn.setIcon(icons.icon(self.icon_name, p.accent_text))
        else:
            self.btn.setStyleSheet(f"QToolButton {{ background: {p.surface}; border: 1px solid {p.stroke}; border-radius: 4px; }}"
                                   f"QToolButton:hover {{ background: {p.surface_alt}; }}")
            self.btn.setIcon(icons.icon(self.icon_name, p.text))

    def set_checked(self, on):
        self.btn.blockSignals(True)
        self.btn.setChecked(on)
        self.btn.blockSignals(False)
        self._restyle(on)


class QuickSettings(Flyout):
    def __init__(self, p):
        super().__init__(p)
        self.setFixedSize(360, 410)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        controls = QWidget()
        lay = QVBoxLayout(controls)
        lay.setContentsMargins(24, 24, 24, 12)
        outer.addWidget(controls, 1)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(14)
        wifi_on, ssid = system.wifi_state()
        self.wifi = QuickToggle(p, "wifi", ssid or "Wi-Fi", wifi_on)
        self.wifi.toggled.connect(system.set_wifi)
        self.wifi.btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.wifi.btn.customContextMenuRequested.connect(self.wifi_menu)
        self.bt = QuickToggle(p, "bluetooth", "Bluetooth", system.bluetooth_state())
        self.bt.toggled.connect(system.set_bluetooth)
        self.plane = QuickToggle(p, "airplane", "Airplane mode", False)
        self.plane.toggled.connect(system.airplane)
        self.saver = QuickToggle(p, "efficiency", "Energy saver", False)
        self.saver.toggled.connect(lambda on: system._bg(["powerprofilesctl", "set", "power-saver" if on else "balanced"]))
        self.night = QuickToggle(p, "moon", "Night light", config.get("night_light"))
        self.night.toggled.connect(lambda on: (config.set("night_light", on), system.set_night_light(on)))
        self.access = QuickToggle(p, "user", "Accessibility", False)
        self.access.toggled.connect(lambda on: (self.access.set_checked(False), system.open_settings("accessibility")))
        for i, t in enumerate((self.wifi, self.bt, self.plane, self.saver, self.night, self.access)):
            grid.addWidget(t, i // 3, i % 3)
        lay.addLayout(grid)
        lay.addSpacing(16)

        def slider_row(icon_name, value, fn):
            row = QHBoxLayout()
            ic = QToolButton()
            ic.setIcon(icons.icon(icon_name, p.text))
            ic.setAutoRaise(True)
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, 100)
            s.setValue(value)
            s.valueChanged.connect(fn)
            row.addWidget(ic)
            row.addWidget(s, 1)
            lay.addLayout(row)
            return ic, s

        b = system.get_brightness()
        self.bright_icon, self.bright = slider_row("sun", b if b is not None else config.get("brightness"), system.set_brightness)
        vol, _muted = system.get_volume()
        self.vol_icon, self.vol = slider_row("volume", vol, system.set_volume)
        self.vol_icon.clicked.connect(system.toggle_mute)
        lay.addStretch()

        footer = QWidget()
        footer.setObjectName("QsFooter")
        footer.setFixedHeight(48)
        footer.setStyleSheet(f"QWidget#QsFooter {{ background: {p.surface}; border-top: 1px solid {p.stroke};"
                             " border-bottom-left-radius: 8px; border-bottom-right-radius: 8px; }")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 0, 12, 0)
        bat = system.battery()
        self.battery = QLabel(f"{bat[0]}%{' (plugged in)' if bat[1] else ''}" if bat else "")
        fl.addWidget(self.battery)
        fl.addStretch()
        gear = QToolButton()
        gear.setIcon(icons.icon("settings"))
        gear.setToolTip("All settings")
        gear.setAutoRaise(True)
        gear.clicked.connect(lambda: (self.hide(), system.open_settings()))
        fl.addWidget(gear)
        outer.addWidget(footer)

    def wifi_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        m = QMenu(self)
        nets = system.wifi_networks()
        if not nets:
            m.addAction("No networks found").setEnabled(False)
        for n in nets[:12]:
            label = f"{'✓ ' if n['active'] else ''}{n['ssid']}  ({n['signal']}%){' 🔒' if n['secure'] else ''}"
            m.addAction(label, lambda n=n: self.connect(n))
        m.addSeparator()
        m.addAction("Network & internet settings", lambda: (self.hide(), system.open_settings("network")))
        m.exec(self.wifi.btn.mapToGlobal(pos))

    def connect(self, net):
        pw = None
        if net["secure"] and not net["active"]:
            pw, ok = QInputDialog.getText(self, net["ssid"], "Enter the network security key",
                                          QLineEdit.EchoMode.Password)
            if not ok:
                return
        system.connect_wifi(net["ssid"], pw)

    def refresh(self):
        on, ssid = system.wifi_state()
        self.wifi.set_checked(on)
        self.wifi.label.setText(ssid or "Wi-Fi")
        self.bt.set_checked(system.bluetooth_state())
        vol, _ = system.get_volume()
        self.vol.blockSignals(True)
        self.vol.setValue(vol)
        self.vol.blockSignals(False)


class NotificationCenter(Flyout):
    """Notifications list on top, calendar below (Win+N)."""

    def __init__(self, p):
        super().__init__(p)
        self.setFixedSize(360, 700)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        top = QHBoxLayout()
        t = QLabel("Notifications")
        t.setStyleSheet("font-weight: 600;")
        top.addWidget(t)
        top.addStretch()
        clear = QPushButton("Clear all")
        clear.setObjectName("Flat")
        clear.clicked.connect(self.clear)
        top.addWidget(clear)
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.setStyleSheet("QListWidget { background: transparent; } QListWidget::item { padding: 8px; }")
        self.list.setWordWrap(True)
        lay.addWidget(self.list, 1)
        self.empty = QLabel("No new notifications")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setObjectName("Secondary")
        lay.addWidget(self.empty)
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {p.stroke};")
        lay.addWidget(sep)
        self.date_label = QLabel()
        self.date_label.setStyleSheet("font-weight: 600;")
        lay.addWidget(self.date_label)
        self.cal = QCalendarWidget()
        self.cal.setGridVisible(False)
        self.cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.cal.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.SingleLetterDayNames)
        self.cal.setStyleSheet(
            f"QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: transparent; }}"
            f"QCalendarWidget QToolButton {{ color: {p.text}; font-weight: 600; }}"
            f"QCalendarWidget QAbstractItemView {{ background: transparent; selection-background-color: {p.accent};"
            f" selection-color: {p.accent_text}; }}")
        self.cal.setFixedHeight(300)
        lay.addWidget(self.cal)
        focus = QHBoxLayout()
        focus.addStretch()
        fb = QPushButton("  Focus")
        fb.setIcon(icons.icon("history", p.text))
        fb.clicked.connect(self.focus_session)
        focus.addWidget(fb)
        lay.addLayout(focus)
        self.dnd_until = 0

    def add(self, app, summary, body):
        it = QListWidgetItem(f"{app}\n{summary}\n{body}".strip())
        self.list.insertItem(0, it)
        self.empty.setVisible(False)

    def clear(self):
        self.list.clear()
        self.empty.setVisible(True)

    def focus_session(self):
        self.dnd_until = time.time() + 25 * 60
        self.add("Clock", "Focus session started", "Notifications are silenced for 25 minutes.")

    @property
    def do_not_disturb(self):
        return time.time() < self.dnd_until

    def popup_at(self, x, y):
        self.date_label.setText(QDate.currentDate().toString("dddd, MMMM d"))
        self.cal.setSelectedDate(QDate.currentDate())
        self.empty.setVisible(self.list.count() == 0)
        super().popup_at(x, y)


class Toast(Flyout):
    """Bottom-right notification banner."""

    def __init__(self, p, app, summary, body, timeout=6000):
        super().__init__(p)
        self.setFixedSize(364, 110)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        a = QLabel(app)
        a.setObjectName("Secondary")
        a.setStyleSheet("font-size: 8.5pt;")
        s = QLabel(summary)
        f = s.font()
        f.setWeight(QFont.Weight.DemiBold)
        s.setFont(f)
        b = QLabel(body)
        b.setWordWrap(True)
        for w in (a, s, b):
            lay.addWidget(w)
        QTimer.singleShot(timeout, self.close)

    def changeEvent(self, e):
        # toasts don't close on focus loss
        QWidget.changeEvent(self, e)

    def mousePressEvent(self, e):
        self.close()


class TaskView(Flyout):
    """Win+Tab: grid of open windows."""

    def __init__(self, p):
        super().__init__(p, radius=0)
        self.lay = QGridLayout(self)
        self.lay.setContentsMargins(60, 60, 60, 60)
        self.lay.setSpacing(24)

    def show_windows(self, geometry):
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        wins = x11.wm().windows()
        if not wins:
            lbl = QLabel("No open windows")
            lbl.setStyleSheet("font-size: 16pt;")
            self.lay.addWidget(lbl, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        cols = max(1, min(4, len(wins)))
        for i, w in enumerate(wins):
            b = QToolButton()
            b.setText(w.title[:60] or w.wm_class)
            b.setIcon(icons.icon("file-exe"))
            b.setIconSize(QSize(64, 64))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setFixedSize(280, 180)
            b.setStyleSheet(f"QToolButton {{ background: {self.p.surface}; border: 1px solid {self.p.stroke}; border-radius: 8px; }}"
                            f"QToolButton:hover {{ border: 2px solid {self.p.accent}; }}")
            b.clicked.connect(lambda _=False, wid=w.wid: (self.hide(), x11.wm().activate(wid)))
            self.lay.addWidget(b, i // cols, i % cols)
        self.setGeometry(geometry)
        self.show()
        self.raise_()
        self.activateWindow()
