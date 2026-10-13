"""Reusable Fluent widgets: navigation rail, graphs, toggle switch, cards."""

from collections import deque

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtProperty, pyqtSignal, QPropertyAnimation
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush
from PyQt6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel, QPushButton,
                             QSizePolicy, QVBoxLayout, QWidget)

from . import icons


class NavButton(QPushButton):
    """Left navigation item with icon and accent indicator pill."""

    def __init__(self, text, icon_name, palette, collapsed=False):
        super().__init__(text.replace("&", "&&"))
        self.p = palette
        self.icon_name = icon_name
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36)
        self.setStyleSheet(
            f"QPushButton {{ text-align: left; padding: 6px 12px 6px 40px; border: none; background: transparent; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {palette.surface_alt}; }}"
            f"QPushButton:checked {{ background: {palette.surface_alt}; }}")

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        glyph = self.icon_name in icons.GLYPHS or self.icon_name in ("search", "start")
        pm = icons.pixmap(self.icon_name, 16, self.p.text) if glyph else icons.pixmap(self.icon_name, 18)
        p.drawPixmap(14, (self.height() - pm.height()) // 2, pm)
        if self.isChecked():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.p.accent))
            h = 16
            p.drawRoundedRect(QRectF(0, (self.height() - h) / 2, 3, h), 1.5, 1.5)
        p.end()


class Graph(QWidget):
    """Scrolling line/area graph like the Task Manager performance charts."""

    def __init__(self, color="#0078d4", samples=60, maximum=100.0, grid=True, series=1):
        super().__init__()
        self.color = QColor(color)
        self.maximum = maximum
        self.grid = grid
        self.data = [deque([0.0] * samples, maxlen=samples) for _ in range(series)]
        self.setMinimumSize(80, 40)
        self.dashed_second = True

    def push(self, *values):
        for d, v in zip(self.data, values):
            d.append(float(v))
        if self.maximum is None:
            pass
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = QColor(self.color)
        fill.setAlpha(28)
        p.setPen(QPen(self.color, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        if self.grid:
            gpen = QPen(QColor(self.color.red(), self.color.green(), self.color.blue(), 40), 1)
            p.setPen(gpen)
            for i in range(1, 10):
                x = r.left() + r.width() * i / 10
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            for i in range(1, 10):
                y = r.top() + r.height() * i / 10
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        mx = self.maximum or max(1.0, max(max(d) for d in self.data) * 1.15)
        for idx, d in enumerate(self.data):
            n = len(d)
            path = QPainterPath()
            pts = []
            for i, v in enumerate(d):
                x = r.left() + r.width() * i / max(1, n - 1)
                y = r.bottom() - r.height() * min(v, mx) / mx
                pts.append(QPointF(x, y))
            path.moveTo(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            if idx == 0:
                area = QPainterPath(path)
                area.lineTo(QPointF(r.right(), r.bottom()))
                area.lineTo(QPointF(r.left(), r.bottom()))
                area.closeSubpath()
                p.fillPath(area, QBrush(fill))
            pen = QPen(self.color, 1.4)
            if idx > 0 and self.dashed_second:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawPath(path)
        p.end()


class ToggleSwitch(QAbstractButton):
    """Fluent toggle switch."""

    def __init__(self, palette, checked=False):
        super().__init__()
        self.p = palette
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self.anim = QPropertyAnimation(self, b"knob", self)
        self.anim.setDuration(120)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(40, 20)

    def _animate(self, on):
        self.anim.stop()
        self.anim.setStartValue(self._pos)
        self.anim.setEndValue(1.0 if on else 0.0)
        self.anim.start()

    def get_knob(self):
        return self._pos

    def set_knob(self, v):
        self._pos = v
        self.update()

    knob = pyqtProperty(float, get_knob, set_knob)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, 38, 18)
        on = self.isChecked()
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.p.accent))
        else:
            p.setPen(QPen(QColor(self.p.text_secondary), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 9, 9)
        x = 5 + self._pos * 20
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.p.accent_text if on else self.p.text_secondary))
        p.drawEllipse(QRectF(x, 5, 10, 10))
        p.end()


class SettingCard(QFrame):
    """Row card: icon, title + description, trailing control."""

    clicked = pyqtSignal()

    def __init__(self, icon_name, title, description="", control=None, palette=None):
        super().__init__()
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(14)
        if icon_name:
            ic = QLabel()
            color = palette.text if palette else "#1b1b1b"
            glyph = icon_name in icons.GLYPHS
            ic.setPixmap(icons.pixmap(icon_name, 20, color) if glyph else icons.pixmap(icon_name, 24))
            lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel(title)
        col.addWidget(t)
        if description:
            d = QLabel(description)
            d.setObjectName("Secondary")
            d.setWordWrap(True)
            col.addWidget(d)
        lay.addLayout(col, 1)
        if control is not None:
            lay.addWidget(control)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def mouseReleaseEvent(self, e):
        self.clicked.emit()
        super().mouseReleaseEvent(e)


def human_bytes(n: float, suffix="B") -> str:
    for unit in ("", "K", "M", "G", "T"):
        if abs(n) < 1024 or unit == "T":
            return f"{n:.1f} {unit}{suffix}" if unit else f"{n:.0f} {suffix}"
        n /= 1024.0
    return f"{n:.1f} P{suffix}"


def human_rate(n: float) -> str:
    bits = n * 8
    for unit in ("bps", "Kbps", "Mbps", "Gbps"):
        if bits < 1000 or unit == "Gbps":
            return f"{bits:.0f} {unit}" if unit == "bps" else f"{bits:.1f} {unit}"
        bits /= 1000.0
    return f"{bits:.1f} Gbps"
