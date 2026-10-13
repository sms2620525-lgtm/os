"""FluentWindow: frameless top-level window with a Windows 11 style title bar.

The title bar hosts arbitrary widgets (tabs, search box, back button) next
to the caption buttons, exactly like modern Windows apps.  Moving and
resizing are delegated to the window manager (startSystemMove/Resize) so
snapping and Aero-like edge tiling keep working.
"""

from PyQt6.QtCore import QEvent, QPoint, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import icons

EDGE = 5


class CaptionButton(QPushButton):
    def __init__(self, kind, palette):
        super().__init__()
        self.kind = kind
        self.p = palette
        self.setFixedSize(46, 32)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("QPushButton { border: none; background: transparent; border-radius: 0; padding: 0; min-height: 0; }")
        self._hover = False
        self.maximized = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fg = QColor(self.p.text)
        if self._hover:
            if self.kind == "close":
                p.fillRect(self.rect(), QColor("#c42b1c"))
                fg = QColor("#ffffff")
            else:
                c = QColor(self.p.text)
                c.setAlpha(18 if not self.isDown() else 30)
                p.fillRect(self.rect(), c)
        p.setPen(QPen(fg, 1))
        cx, cy = self.width() / 2, self.height() / 2
        if self.kind == "min":
            p.drawLine(int(cx - 5), int(cy), int(cx + 5), int(cy))
        elif self.kind == "max":
            if self.maximized:
                p.drawRoundedRect(QRectF(cx - 5, cy - 3, 8, 8), 1.5, 1.5)
                p.drawLine(int(cx - 3), int(cy - 5), int(cx + 4), int(cy - 5))
                p.drawLine(int(cx + 5), int(cy - 4), int(cx + 5), int(cy + 3))
            else:
                p.drawRoundedRect(QRectF(cx - 5, cy - 5, 10, 10), 1.5, 1.5)
        else:
            p.drawLine(int(cx - 5), int(cy - 5), int(cx + 5), int(cy + 5))
            p.drawLine(int(cx + 5), int(cy - 5), int(cx - 5), int(cy + 5))
        p.end()


class TitleBar(QWidget):
    def __init__(self, window, palette, title="", icon_name=None):
        super().__init__()
        self.win = window
        self.setFixedHeight(40)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(10, 0, 0, 0)
        self.lay.setSpacing(6)
        self.left = QHBoxLayout()
        self.left.setSpacing(6)
        if icon_name:
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icon_name, 16))
            self.left.addWidget(ic)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-size: 9pt;")
        self.title.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        if title:
            self.left.addWidget(self.title)
        self.lay.addLayout(self.left)
        self.center = QHBoxLayout()
        self.lay.addLayout(self.center, 1)
        self.btn_min = CaptionButton("min", palette)
        self.btn_max = CaptionButton("max", palette)
        self.btn_close = CaptionButton("close", palette)
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max.clicked.connect(self.toggle_max)
        self.btn_close.clicked.connect(window.close)
        caps = QHBoxLayout()
        caps.setSpacing(0)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            caps.addWidget(b, alignment=Qt.AlignmentFlag.AlignTop)
        self.lay.addLayout(caps)

    def toggle_max(self):
        if self.win.isMaximized():
            self.win.showNormal()
        else:
            self.win.showMaximized()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.win.windowHandle():
            self.win.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        self.toggle_max()


class FluentWindow(QMainWindow):
    def __init__(self, palette, title="", icon_name=None, frameless=True):
        super().__init__()
        self.p = palette
        self.frameless = frameless
        self.setWindowTitle(title)
        if icon_name:
            self.setWindowIcon(icons.icon(icon_name))
        if frameless:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        root = QWidget()
        root.setObjectName("Window")
        root.setMouseTracking(True)
        self.setCentralWidget(root)
        self._root_layout = QVBoxLayout(root)
        m = 1 if frameless else 0
        self._root_layout.setContentsMargins(m, m, m, m)
        self._root_layout.setSpacing(0)
        self.titlebar = TitleBar(self, palette, title, icon_name)
        self._root_layout.addWidget(self.titlebar)
        if not frameless:
            self.titlebar.hide()
        self.content = QWidget()
        self._root_layout.addWidget(self.content, 1)
        root.installEventFilter(self)
        self.setMouseTracking(True)

    def set_content(self, widget):
        self._root_layout.replaceWidget(self.content, widget)
        self.content.deleteLater()
        self.content = widget

    def changeEvent(self, e):
        if e.type() == QEvent.Type.WindowStateChange:
            self.titlebar.btn_max.maximized = self.isMaximized()
            self.titlebar.btn_max.update()
        super().changeEvent(e)

    # --- edge resizing --------------------------------------------------
    def _edges(self, pos: QPoint):
        r = self.rect()
        edges = Qt.Edge(0)
        if pos.x() <= EDGE:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= r.width() - EDGE:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= EDGE:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= r.height() - EDGE:
            edges |= Qt.Edge.BottomEdge
        return edges

    def eventFilter(self, obj, e):
        if self.frameless and not self.isMaximized():
            if e.type() == QEvent.Type.MouseMove:
                ed = self._edges(e.position().toPoint())
                cursors = {
                    Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor, Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
                    Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor, Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
                    Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
                    Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
                    Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
                    Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
                }
                if ed in cursors:
                    self.setCursor(cursors[ed])
                else:
                    self.unsetCursor()
            elif e.type() == QEvent.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
                ed = self._edges(e.position().toPoint())
                if ed and self.windowHandle():
                    self.windowHandle().startSystemResize(ed)
                    return True
        return super().eventFilter(obj, e)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.frameless and not self.isMaximized():
            p = QPainter(self)
            p.setPen(QPen(QColor(self.p.stroke), 1))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
            p.end()

    def sizeHint(self):
        return QSize(1100, 720)
