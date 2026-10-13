"""Windows App Converter - graphical front-end for fenestra-compat."""

import os
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                             QPushButton, QTabWidget, QVBoxLayout, QWidget)

from ..common import icons, theme
from ..common.window import FluentWindow
from ..common import platform as hostos
from . import analyzer, batch, hosts, pe, runner

RATING_COLORS = {"platinum": "#b4c7dc", "gold": "#cfb53b", "silver": "#a6a6a6", "bronze": "#cd7f32", "borked": "#d13438"}


class Worker(QObject):
    line = pyqtSignal(str)
    done = pyqtSignal(object, str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            res = self.fn(*self.args, log=runner.Log(self.line.emit))
            self.done.emit(res, "")
        except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
            self.done.emit(None, str(exc))


class DropZone(QFrame):
    dropped = pyqtSignal(str)

    def __init__(self, p):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("Card")
        self.setMinimumHeight(150)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("compat", 64))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = QLabel("Drop a Windows program here")
        t.setObjectName("Subtitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s = QLabel(".exe  .msi  .bat  .cmd  .ps1  .reg  .lnk")
        s.setObjectName("Secondary")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn = QPushButton("Browse files…")
        btn.setObjectName("Accent")
        btn.clicked.connect(self.browse)
        for w in (ic, t, s):
            lay.addWidget(w)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a Windows program", str(Path.home()),
                                              "Windows files (*.exe *.msi *.bat *.cmd *.ps1 *.reg *.lnk *.com);;All files (*)")
        if path:
            self.dropped.emit(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.dropped.emit(urls[0].toLocalFile())


class ConverterWindow(FluentWindow):
    def __init__(self, p, initial=None):
        super().__init__(p, "Windows App Converter", "compat")
        self.plan = None
        self.thread = None
        self.resize(900, 720)

        tabs = QTabWidget()
        self.set_content(tabs)

        # --- convert tab
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 16, 24, 16)
        title = QLabel("Windows App Converter")
        title.setObjectName("Title")
        lay.addWidget(title)
        sub = QLabel("Run Windows programs on Fenestra, turn them into Linux apps, or package them as .deb.")
        sub.setObjectName("Secondary")
        lay.addWidget(sub)
        self.drop = DropZone(p)
        self.drop.dropped.connect(self.load)
        lay.addWidget(self.drop)

        self.card = QFrame()
        self.card.setObjectName("Card")
        cl = QHBoxLayout(self.card)
        self.app_icon = QLabel()
        self.app_icon.setFixedSize(64, 64)
        cl.addWidget(self.app_icon, alignment=Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Application name")
        row.addWidget(self.name_edit, 1)
        self.badge = QLabel()
        row.addWidget(self.badge)
        info.addLayout(row)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info.addWidget(self.details)
        btns = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.convert_btn = QPushButton("Convert to Linux app")
        self.convert_btn.setObjectName("Accent")
        self.deb_btn = QPushButton("Build macOS .app" if hostos.IS_MAC else "Build .deb package")
        self.sh_btn = QPushButton("Translate to Bash")
        for b in (self.convert_btn, self.run_btn, self.deb_btn, self.sh_btn):
            btns.addWidget(b)
        btns.addStretch()
        info.addLayout(btns)
        cl.addLayout(info, 1)
        self.card.hide()
        lay.addWidget(self.card)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Progress output appears here")
        lay.addWidget(self.log, 1)
        tabs.addTab(page, "Convert")

        self.run_btn.clicked.connect(lambda: self.start(self._run))
        self.convert_btn.clicked.connect(lambda: self.start(runner.convert, self.plan.path, self.name_edit.text() or None))
        self.deb_btn.clicked.connect(self.build_deb)
        self.sh_btn.clicked.connect(self.translate_bat)

        # --- installed tab
        inst = QWidget()
        il = QVBoxLayout(inst)
        il.setContentsMargins(24, 16, 24, 16)
        t2 = QLabel("Converted apps")
        t2.setObjectName("Title")
        il.addWidget(t2)
        self.apps_list = QListWidget()
        il.addWidget(self.apps_list, 1)
        r2 = QHBoxLayout()
        launch = QPushButton("Open")
        launch.clicked.connect(self.open_selected)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_selected)
        integ = QPushButton("Make .exe files double-clickable")
        integ.clicked.connect(lambda: self.start(lambda log: runner.register_desktop_integration(log)))
        for b in (launch, remove, integ):
            r2.addWidget(b)
        r2.addStretch()
        il.addLayout(r2)
        tabs.addTab(inst, "Installed")
        tabs.currentChanged.connect(lambda i: i == 1 and self.refresh_installed())

        if initial:
            self.load(initial)

    # ------------------------------------------------------------------
    def load(self, path):
        self.plan = analyzer.analyze(path)
        pl = self.plan
        self.card.show()
        self.name_edit.setText(pl.name)
        color = RATING_COLORS.get(pl.rating, "#888")
        self.badge.setText(pl.rating.upper())
        self.badge.setStyleSheet(f"background:{color}; color:#000; border-radius:4px; padding:2px 8px; font-weight:600;")
        pm = None
        if pl.pe and pl.pe.has_icon:
            try:
                ico = pe.PEFile(path).icon_ico()
                if ico:
                    pm = QPixmap()
                    pm.loadFromData(ico, "ICO")
            except Exception:  # noqa: BLE001
                pm = None
        self.app_icon.setPixmap((pm if pm and not pm.isNull() else icons.pixmap("file-exe", 64)).scaled(
            64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        lines = [f"<b>Runtime:</b> {pl.runtime} &nbsp; <b>Type:</b> {pl.kind}"]
        if pl.pe:
            lines.append(f"<b>Architecture:</b> {pl.pe.machine} ({pl.pe.bits}-bit {pl.pe.subsystem})")
            if pl.pe.version.get("CompanyName"):
                lines.append(f"<b>Publisher:</b> {pl.pe.version['CompanyName']}")
        if pl.verbs:
            lines.append("<b>Windows components to install:</b> " + ", ".join(pl.verbs))
        if pl.host:
            state = "ready" if pl.host_ok else "<span style='color:#c42b1c'>not ready</span>"
            lines.append(f"<b>On this PC:</b> {hosts.describe_host()} → {pl.host} ({state})")
            lines += [f"&nbsp;&nbsp;{n}" for n in pl.host_notes]
        lines += [f"• {n}" for n in pl.notes]
        self.details.setText("<br>".join(lines))
        is_bat = pl.kind == "batch"
        self.sh_btn.setVisible(is_bat)
        self.deb_btn.setVisible(pl.kind in ("exe", "dotnet") and not pl.is_installer)
        ok = pl.runtime != "none"
        self.run_btn.setEnabled(ok)
        self.convert_btn.setEnabled(ok and not is_bat and pl.kind not in ("registry", "powershell", "dos"))
        self.log.appendPlainText(pl.summary() + "\n")

    def _run(self, log):
        return runner.run(self.plan.path, log=log)

    def start(self, fn, *args):
        if self.thread and self.thread.isRunning():
            return
        self.thread = QThread(self)
        self.worker = Worker(fn, *args)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.line.connect(self.log.appendPlainText)
        self.worker.done.connect(self.finished)
        self.worker.done.connect(self.thread.quit)
        self.thread.start()

    def finished(self, result, error):
        if error:
            self.log.appendPlainText(f"\nError: {error}")
            QMessageBox.warning(self, "Windows App Converter", error)
        elif isinstance(result, dict) and result.get("desktop"):
            QMessageBox.information(self, "Windows App Converter",
                                    f"{self.name_edit.text()} is now available in the Start menu.")

    def build_deb(self):
        kind = ".app" if hostos.IS_MAC else ".deb"
        out = QFileDialog.getExistingDirectory(self, f"Save {kind} to", str(Path.home()))
        if not out:
            return
        if hostos.IS_MAC:
            self.start(runner.package_app, self.plan.path, out, self.name_edit.text() or None)
        else:
            self.start(runner.package_deb, self.plan.path, out, self.name_edit.text() or None, None)

    def translate_bat(self):
        src = Path(self.plan.path)
        out, _ = QFileDialog.getSaveFileName(self, "Save Bash script", str(src.with_suffix(".sh")))
        if out:
            Path(out).write_text(batch.translate(src.read_text(errors="replace"), src.name))
            os.chmod(out, 0o755)
            self.log.appendPlainText(f"Saved {out}")

    def refresh_installed(self):
        self.apps_list.clear()
        for f in sorted(runner.APPS_DIR.glob("fenestra-app-*.desktop")):
            name = next((l[5:] for l in f.read_text().splitlines() if l.startswith("Name=")), f.stem)
            it = QListWidgetItem(icons.icon("file-exe"), name)
            it.setData(Qt.ItemDataRole.UserRole, str(f))
            self.apps_list.addItem(it)

    def _selected(self):
        it = self.apps_list.currentItem()
        return Path(it.data(Qt.ItemDataRole.UserRole)) if it else None

    def open_selected(self):
        f = self._selected()
        if f:
            exe = next((l[5:].split(" %")[0] for l in f.read_text().splitlines() if l.startswith("Exec=")), None)
            if exe:
                runner._launch([exe])

    def remove_selected(self):
        f = self._selected()
        if not f:
            return
        if QMessageBox.question(self, "Remove", f"Remove {f.stem}? Its Wine prefix is kept.") \
                != QMessageBox.StandardButton.Yes:
            return
        launcher = next((l[5:].split(" %")[0] for l in f.read_text().splitlines() if l.startswith("Exec=")), None)
        if launcher and Path(launcher).is_file() and str(runner.BIN_DIR) in launcher:
            Path(launcher).unlink()
        f.unlink()
        self.refresh_installed()


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("fenestra-compat")
    p = theme.apply(app)
    w = ConverterWindow(p, argv[0] if argv else None)
    w.show()
    return app.exec()
