"""fenestra-shell: desktop, taskbar, Start menu, flyouts and notification daemon.

Run without arguments to start the shell.  With a command it talks to the
running shell over a local socket (used by Openbox key bindings):

    fenestra-shell start          toggle the Start menu   (Win)
    fenestra-shell search         Start menu with search  (Win+S)
    fenestra-shell quick          Quick Settings          (Win+A)
    fenestra-shell notifications  Notification centre     (Win+N)
    fenestra-shell taskview       Task View               (Win+Tab)
    fenestra-shell widgets        Widgets board           (Win+W)
    fenestra-shell run            Run dialog              (Win+R)
    fenestra-shell desktop        Show desktop            (Win+D)
    fenestra-shell reload         Re-read settings / theme

Options:
    --windowed    run the whole desktop inside one window (default on macOS
                  and when no X11 display is available)
"""

import os
import shlex
import subprocess
import sys
import time

import psutil
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                             QPushButton, QVBoxLayout, QWidget)

from ..common import platform as hostos
from ..common import config, icons, theme
from . import flyouts, system
from .desktop import Desktop
from .startmenu import Flyout, StartMenu
from .taskbar import HEIGHT, Taskbar

SOCKET = f"fenestra-shell-{os.getuid()}"
OPEN = "open" if hostos.IS_MAC else "xdg-open"
GAP = 12


class RunDialog(QDialog):
    def __init__(self, p):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Run")
        self.setWindowIcon(icons.icon("logo"))
        self.setFixedWidth(420)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("logo", 32))
        top.addWidget(ic, alignment=Qt.AlignmentFlag.AlignTop)
        top.addWidget(QLabel("Type the name of a program, folder, document, or Internet\nresource, and Fenestra will open it for you."), 1)
        lay.addLayout(top)
        row = QHBoxLayout()
        row.addWidget(QLabel("Open:"))
        self.edit = QLineEdit()
        row.addWidget(self.edit, 1)
        lay.addLayout(row)
        self.admin = QCheckBox("Run with administrative privileges")
        lay.addWidget(self.admin)
        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("OK")
        ok.setObjectName("Accent")
        ok.clicked.connect(self.go)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)
        self.edit.returnPressed.connect(self.go)

    ALIASES = {"cmd": hostos.terminal_command(), "powershell": hostos.terminal_command(command="pwsh"),
               "notepad": ["mousepad"], "explorer": [sys.executable, "-m", "fenestra.explorer"],
               "taskmgr": [sys.executable, "-m", "fenestra.taskmgr"], "control": [sys.executable, "-m", "fenestra.settings"],
               "ms-settings:": [sys.executable, "-m", "fenestra.settings"], "calc": ["gnome-calculator"],
               "regedit": ["wine", "regedit"], "winver": [sys.executable, "-m", "fenestra.settings", "--page", "about"],
               "msconfig": [sys.executable, "-m", "fenestra.taskmgr"], "%temp%": [OPEN, "/tmp"]}

    def go(self):
        text = self.edit.text().strip()
        if not text:
            return
        argv = self.ALIASES.get(text.lower())
        if argv is None:
            path = os.path.expanduser(os.path.expandvars(text))
            if text.startswith(("http://", "https://", "www.")):
                argv = [OPEN, text if "://" in text else "https://" + text]
            elif os.path.isdir(path):
                argv = [sys.executable, "-m", "fenestra.explorer", path]
            elif os.path.isfile(path) and path.lower().endswith((".exe", ".msi", ".bat", ".cmd", ".reg", ".lnk")):
                argv = [sys.executable, "-m", "fenestra.compat", "run", path]
            elif os.path.isfile(path) and not os.access(path, os.X_OK):
                argv = [OPEN, path]
            else:
                try:
                    argv = shlex.split(text)
                except ValueError:
                    argv = [text]
        if self.admin.isChecked():
            argv = ["pkexec"] + argv
        try:
            subprocess.Popen(argv, start_new_session=True)
            self.accept()
        except OSError:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, text, f"Fenestra cannot find '{text}'. Make sure you typed the name correctly, and then try again.")


class WidgetsBoard(Flyout):
    def __init__(self, p):
        super().__init__(p)
        self.setFixedSize(760, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        self.time = QLabel()
        self.time.setStyleSheet("font-size: 28pt; font-weight: 300;")
        lay.addWidget(self.time)
        self.date = QLabel()
        self.date.setObjectName("Secondary")
        lay.addWidget(self.date)
        lay.addSpacing(16)
        card = QLabel("System")
        card.setStyleSheet("font-weight: 600;")
        lay.addWidget(card)
        self.bars = {}
        for name in ("CPU", "Memory", "Disk (/)"):
            row = QHBoxLayout()
            row.addWidget(QLabel(name), 1)
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setFixedWidth(400)
            row.addWidget(bar)
            val = QLabel()
            val.setFixedWidth(60)
            row.addWidget(val)
            lay.addLayout(row)
            self.bars[name] = (bar, val)
        lay.addSpacing(16)
        up = QLabel()
        up.setObjectName("Secondary")
        self.uptime = up
        lay.addWidget(up)
        lay.addStretch()
        tip = QLabel("Tip: press Win+E for File Explorer, Ctrl+Shift+Esc for Task Manager, "
                     "and drop any .exe onto the Windows App Converter to run it on Fenestra.")
        tip.setWordWrap(True)
        tip.setObjectName("Secondary")
        lay.addWidget(tip)
        t = QTimer(self)
        t.timeout.connect(self.tick)
        t.start(1000)
        self.tick()

    def tick(self):
        if not self.isVisible() and self.time.text():
            return
        self.time.setText(time.strftime("%H:%M"))
        self.date.setText(time.strftime("%A, %B %d"))
        vals = {"CPU": psutil.cpu_percent(), "Memory": psutil.virtual_memory().percent,
                "Disk (/)": psutil.disk_usage("/").percent}
        for k, v in vals.items():
            self.bars[k][0].setValue(int(v))
            self.bars[k][1].setText(f"{v:.0f}%")
        s = int(time.time() - psutil.boot_time())
        self.uptime.setText(f"Up time: {s // 86400}d {s % 86400 // 3600}h {s % 3600 // 60}m")


class NotificationServer:
    """org.freedesktop.Notifications implemented with QtDBus (optional)."""

    def __init__(self, shell):
        self.shell = shell
        self.ok = False
        try:
            from PyQt6.QtCore import QObject, pyqtClassInfo, pyqtSlot
            from PyQt6.QtDBus import QDBusAbstractAdaptor, QDBusConnection
        except ImportError:
            return

        server = self

        @pyqtClassInfo("D-Bus Interface", "org.freedesktop.Notifications")
        class Adaptor(QDBusAbstractAdaptor):
            def __init__(self, parent):
                super().__init__(parent)
                self.counter = 0

            @pyqtSlot(str, "uint", str, str, str, "QStringList", "QVariantMap", int, result="uint")
            def Notify(self, app, replaces, icon, summary, body, actions, hints, timeout):
                self.counter += 1
                server.shell.notify(app or "Notification", summary, body, timeout)
                return replaces or self.counter

            @pyqtSlot("uint")
            def CloseNotification(self, nid):
                pass

            @pyqtSlot(result="QStringList")
            def GetCapabilities(self):
                return ["body", "persistence"]

        self.obj = QObject()
        self.adaptor = Adaptor(self.obj)
        bus = QDBusConnection.sessionBus()
        if bus.isConnected() and bus.registerService("org.freedesktop.Notifications"):
            self.ok = bus.registerObject("/org/freedesktop/Notifications", self.obj)


class HostWindow(QWidget):
    """Windowed mode: the whole Fenestra desktop inside one resizable window (macOS, other desktops)."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fenestra")
        self.setWindowIcon(icons.icon("logo"))
        self.resize(1440, 900)
        self.desktop = self.taskbar = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.desktop:
            self.desktop.setGeometry(self.rect())
        if self.taskbar:
            self.taskbar.setGeometry(0, self.height() - HEIGHT, self.width(), HEIGHT)

    def closeEvent(self, e):
        QApplication.quit()
        super().closeEvent(e)


class Shell:
    def __init__(self, app, windowed=False):
        self.app = app
        self.p = theme.apply(app)
        app.setQuitOnLastWindowClosed(False)
        screen = app.primaryScreen()
        self.screen = screen
        self.host = HostWindow() if windowed else None
        self.desktop = Desktop(self.p, screen, self.host)
        self.taskbar = Taskbar(self.p, screen, self.host)
        if self.host:
            self.host.desktop, self.host.taskbar = self.desktop, self.taskbar
        self.start = StartMenu(self.p, self.taskbar)
        self.quick = flyouts.QuickSettings(self.p)
        self.notifications = flyouts.NotificationCenter(self.p)
        self.widgets = WidgetsBoard(self.p)
        self.taskview = flyouts.TaskView(self.p)
        self.toasts = []

        self.taskbar.start_clicked.connect(self.toggle_start)
        self.taskbar.search_clicked.connect(self.search)
        self.taskbar.quick_clicked.connect(self.toggle_quick)
        self.taskbar.clock_clicked.connect(self.toggle_notifications)
        self.taskbar.taskview_clicked.connect(self.show_taskview)
        self.taskbar.widgets_clicked.connect(self.toggle_widgets)

        self.desktop.show()
        self.taskbar.show()
        if self.host:
            self.taskbar.raise_()
            self.host.show()

        self.server = QLocalServer()
        QLocalServer.removeServer(SOCKET)
        self.server.listen(SOCKET)
        self.server.newConnection.connect(self._ipc)
        self.notifyd = NotificationServer(self)
        self.run_dialog = None
        QTimer.singleShot(1500, self.welcome)

    # --- geometry helpers ------------------------------------------------------
    def _avail(self):
        if self.host:
            from PyQt6.QtCore import QPoint
            tl = self.host.mapToGlobal(QPoint(0, 0))
            return tl.x(), tl.y(), self.host.width(), self.host.height() - HEIGHT
        g = self.screen.geometry()
        return g.x(), g.y(), g.width(), g.height() - HEIGHT

    def _center_above(self, w):
        x, y, width, height = self._avail()
        if config.get("taskbar_alignment") == "left":
            return x + GAP, y + height - w.height() - GAP
        return x + (width - w.width()) // 2, max(y, y + height - w.height() - GAP)

    def _right_above(self, w):
        x, y, width, height = self._avail()
        return x + width - w.width() - GAP, y + height - w.height() - GAP

    def _hide_all(self, except_=None):
        for f in (self.start, self.quick, self.notifications, self.widgets):
            if f is not except_ and f.isVisible():
                f.hide()

    # --- actions ------------------------------------------------------------------
    def toggle_start(self):
        self._hide_all(self.start)
        self.start.toggle(*self._center_above(self.start))

    def search(self):
        self._hide_all(self.start)
        if not self.start.isVisible():
            self.start.toggle(*self._center_above(self.start))
        self.start.search.setFocus()

    def toggle_quick(self):
        self._hide_all(self.quick)
        if self.quick.isVisible():
            self.quick.hide()
        else:
            self.quick.refresh()
            self.quick.popup_at(*self._right_above(self.quick))

    def toggle_notifications(self):
        self._hide_all(self.notifications)
        if self.notifications.isVisible():
            self.notifications.hide()
        else:
            self.notifications.popup_at(*self._right_above(self.notifications))

    def toggle_widgets(self):
        self._hide_all(self.widgets)
        if self.widgets.isVisible():
            self.widgets.hide()
        else:
            x, y, width, height = self._avail()
            self.widgets.tick()
            self.widgets.popup_at(x + GAP, y + height - self.widgets.height() - GAP)

    def show_taskview(self):
        self._hide_all()
        x, y, w, h = self._avail()
        from PyQt6.QtCore import QRect
        self.taskview.show_windows(QRect(x, y, w, h))

    def run(self):
        if self.run_dialog is None:
            self.run_dialog = RunDialog(self.p)
        x, y, w, h = self._avail()
        self.run_dialog.move(x + 12, y + h - 220)
        self.run_dialog.edit.clear()
        self.run_dialog.show()
        self.run_dialog.raise_()
        self.run_dialog.activateWindow()

    def notify(self, app, summary, body, timeout=-1):
        self.notifications.add(app, summary, body)
        if self.notifications.do_not_disturb:
            return
        t = flyouts.Toast(self.p, app, summary, body, timeout if timeout and timeout > 0 else 6000)
        self.toasts = [x for x in self.toasts if x.isVisible()]
        x, y = self._right_above(t)
        t.move(x, y - sum(o.height() + 8 for o in self.toasts))
        t.show()
        self.toasts.append(t)

    def welcome(self):
        flag = config.config_dir() / ".welcomed"
        if not flag.exists():
            flag.write_text("1")
            self.notify("Fenestra", "Welcome to Fenestra OS",
                        "Press the Win key for Start. Drop .exe files on the Windows App Converter to run them.")

    def reload(self):
        self.p = theme.apply(self.app)
        self.desktop.p = self.p
        self.desktop.load_wallpaper()
        self.taskbar.apply_alignment()
        self.taskbar.update()

    def _ipc(self):
        conn = self.server.nextPendingConnection()
        if conn is None:
            return
        conn.waitForReadyRead(500)
        cmd = bytes(conn.readAll()).decode().strip()
        conn.disconnectFromServer()
        actions = {
            "start": self.toggle_start, "search": self.search, "quick": self.toggle_quick,
            "notifications": self.toggle_notifications, "taskview": self.show_taskview,
            "widgets": self.toggle_widgets, "run": self.run, "desktop": self.taskbar.toggle_desktop,
            "reload": self.reload, "lock": lambda: system.power("lock"),
        }
        fn = actions.get(cmd)
        if fn:
            fn()


def send(cmd: str) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SOCKET)
    if not sock.waitForConnected(500):
        return False
    sock.write(cmd.encode())
    sock.flush()
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    windowed = "--windowed" in argv or hostos.IS_MAC or not (os.environ.get("DISPLAY") or "--fullscreen" in argv)
    argv = [a for a in argv if a not in ("--windowed", "--fullscreen")]
    if argv:
        from PyQt6.QtCore import QCoreApplication
        app = QCoreApplication(sys.argv[:1])  # noqa: F841 - needed for QLocalSocket
        if not send(argv[0]):
            print("fenestra-shell is not running", file=sys.stderr)
            return 1
        return 0
    app = QApplication(sys.argv[:1])
    app.setApplicationName("fenestra-shell")
    shell = Shell(app, windowed=windowed)
    app.shell = shell
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
