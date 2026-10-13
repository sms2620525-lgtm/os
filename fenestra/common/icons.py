"""Vector icons drawn with QPainter.

All artwork is original (no Microsoft assets) but follows the Fluent style:
simple geometry, soft gradients, rounded corners.  Icons are generated at any
size and cached.
"""

from functools import lru_cache

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QIcon, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap, QPolygonF)


def _grad(r: QRectF, top: str, bottom: str) -> QBrush:
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0, QColor(top))
    g.setColorAt(1, QColor(bottom))
    return QBrush(g)


def _rounded(p: QPainter, r: QRectF, radius: float, brush, pen=Qt.PenStyle.NoPen):
    p.setPen(pen)
    p.setBrush(brush)
    p.drawRoundedRect(r, radius, radius)


# --- individual icons ----------------------------------------------------
# Each painter works in a 0..100 coordinate space.

def _logo(p):
    # Fenestra logo: four rounded panes in a slight perspective with gradient.
    colors = [("#4cc2ff", "#0078d4"), ("#6ad3ff", "#1690e8"), ("#2aa7f5", "#0063b1"), ("#4cc2ff", "#0a74cc")]
    k = 0
    for y in (8, 52):
        for x in (8, 52):
            r = QRectF(x, y, 40, 40)
            _rounded(p, r, 9, _grad(r, *colors[k]))
            k += 1


def _start_logo_mono(p, color="#ffffff"):
    for y in (10, 53):
        for x in (10, 53):
            _rounded(p, QRectF(x, y, 37, 37), 7, QColor(color))


def _folder(p):
    back = QRectF(6, 18, 88, 66)
    path = QPainterPath()
    path.addRoundedRect(QRectF(6, 14, 38, 20), 6, 6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#e8a317"))
    p.drawPath(path)
    _rounded(p, back, 7, QColor("#e8a317"))
    front = QRectF(6, 30, 88, 56)
    _rounded(p, front, 7, _grad(front, "#ffd75e", "#f4b400"))


def _explorer(p):
    _folder(p)
    p.setBrush(QColor("#1e88e5"))
    p.drawRoundedRect(QRectF(22, 62, 56, 8), 3, 3)


def _settings(p):
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(50, 50)
    path = QPainterPath()
    import math
    teeth = 8
    for i in range(teeth * 2):
        a = math.pi * i / teeth
        rad = 42 if i % 2 == 0 else 33
        pt = QPointF(rad * math.cos(a), rad * math.sin(a))
        path.lineTo(pt) if i else path.moveTo(pt)
    path.closeSubpath()
    hole = QPainterPath()
    hole.addEllipse(QPointF(0, 0), 14, 14)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_grad(QRectF(-42, -42, 84, 84), "#9aa4b1", "#5c6670"))
    p.drawPath(path.subtracted(hole))
    p.translate(-50, -50)


def _taskmgr(p):
    r = QRectF(8, 12, 84, 76)
    _rounded(p, r, 10, _grad(r, "#3a8f4a", "#1f6b30"))
    pen = QPen(QColor("#ffffff"), 6, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(18, 56), QPointF(34, 56), QPointF(42, 34),
                              QPointF(54, 72), QPointF(64, 46), QPointF(82, 46)]))


def _terminal(p):
    r = QRectF(6, 14, 88, 72)
    _rounded(p, r, 9, QColor("#2b2b2b"), QPen(QColor("#8a8a8a"), 3))
    _rounded(p, QRectF(8, 16, 84, 12), 8, QColor("#4a4a4a"))
    pen = QPen(QColor("#ffffff"), 6, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPolyline(QPolygonF([QPointF(22, 42), QPointF(34, 54), QPointF(22, 66)]))
    p.drawLine(QPointF(42, 66), QPointF(62, 66))


def _browser(p):
    r = QRectF(8, 8, 84, 84)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0, QColor("#35c1f1"))
    g.setColorAt(0.5, QColor("#1b8fd8"))
    g.setColorAt(1, QColor("#36b37e"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawEllipse(r)
    p.setBrush(QColor(255, 255, 255, 220))
    p.drawEllipse(QRectF(30, 30, 40, 40))
    p.setBrush(QColor("#1b8fd8"))
    p.drawEllipse(QRectF(40, 40, 20, 20))


def _store(p):
    bag = QRectF(12, 30, 76, 60)
    _rounded(p, bag, 8, _grad(bag, "#3f9cf0", "#1866c4"))
    pen = QPen(QColor("#1866c4"), 6)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(32, 12, 36, 36), 0, 180 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    for i, c in enumerate(("#f25022", "#7fba00", "#00a4ef", "#ffb900")):
        x, y = 36 + (i % 2) * 15, 46 + (i // 2) * 15
        p.setBrush(QColor(c))
        p.drawRoundedRect(QRectF(x, y, 13, 13), 2, 2)


def _compat(p):
    # A window + penguin-ish badge: "run Windows apps"
    r = QRectF(6, 10, 70, 60)
    _rounded(p, r, 8, _grad(r, "#7b5cff", "#4b2fd1"))
    _rounded(p, QRectF(6, 10, 70, 14), 8, QColor("#5b3fe6"))
    p.setBrush(QColor("#ffffff"))
    for x in (14, 24, 34):
        p.drawEllipse(QRectF(x, 14, 6, 6))
    badge = QRectF(48, 46, 46, 46)
    _rounded(p, badge, 23, _grad(badge, "#ffb900", "#f7630c"))
    pen = QPen(QColor("#ffffff"), 6, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(QPointF(60, 69), QPointF(82, 69))
    p.drawPolyline(QPolygonF([QPointF(74, 61), QPointF(82, 69), QPointF(74, 77)]))


def _file(p, color="#ffffff", band=None, label=None):
    path = QPainterPath()
    path.moveTo(20, 6)
    path.lineTo(62, 6)
    path.lineTo(82, 26)
    path.lineTo(82, 94)
    path.lineTo(20, 94)
    path.closeSubpath()
    p.setPen(QPen(QColor("#b8b8b8"), 1.5))
    p.setBrush(QColor(color))
    p.drawPath(path)
    p.setBrush(QColor("#e2e2e2"))
    p.drawPolygon(QPolygonF([QPointF(62, 6), QPointF(62, 26), QPointF(82, 26)]))
    if band:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(band))
        p.drawRoundedRect(QRectF(10, 54, 54, 26), 4, 4)
        if label:
            f = p.font()
            f.setPixelSize(15)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(10, 54, 54, 26), Qt.AlignmentFlag.AlignCenter, label)


def _exe(p):
    r = QRectF(10, 14, 80, 72)
    _rounded(p, r, 6, QColor("#f3f3f3"), QPen(QColor("#9a9a9a"), 2))
    _rounded(p, QRectF(10, 14, 80, 16), 6, QColor("#0078d4"))
    p.setPen(QPen(QColor("#9a9a9a"), 3))
    for y in (44, 56, 68):
        p.drawLine(QPointF(22, y), QPointF(78, y))


def _monitor(p):
    r = QRectF(8, 14, 84, 56)
    _rounded(p, r, 5, QColor("#2d2d2d"))
    inner = QRectF(13, 19, 74, 46)
    _rounded(p, inner, 2, _grad(inner, "#4cc2ff", "#0050a0"))
    p.setBrush(QColor("#7a7a7a"))
    p.drawRect(QRectF(44, 70, 12, 10))
    p.drawRoundedRect(QRectF(30, 80, 40, 6), 3, 3)


def _drive(p):
    r = QRectF(8, 30, 84, 40)
    _rounded(p, r, 6, _grad(r, "#d9d9d9", "#a6a6a6"))
    p.setBrush(QColor("#0078d4"))
    p.drawRoundedRect(QRectF(16, 54, 50, 6), 3, 3)
    p.setBrush(QColor("#33d17a"))
    p.drawEllipse(QRectF(76, 52, 9, 9))


def _home(p):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#e8a317"))
    p.drawPolygon(QPolygonF([QPointF(50, 8), QPointF(94, 46), QPointF(6, 46)]))
    r = QRectF(18, 42, 64, 50)
    _rounded(p, r, 4, _grad(r, "#ffd75e", "#f4b400"))
    p.setBrush(QColor("#a0522d"))
    p.drawRoundedRect(QRectF(42, 62, 16, 30), 2, 2)


def _special_folder(glyph_color):
    def draw(p):
        _folder(p)
        p.setBrush(QColor(glyph_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(38, 48, 24, 24))
    return draw


def _download_folder(p):
    _folder(p)
    pen = QPen(QColor("#0b6a0b"), 6, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(QPointF(50, 44), QPointF(50, 72))
    p.drawPolyline(QPolygonF([QPointF(40, 62), QPointF(50, 72), QPointF(60, 62)]))


def _trash(p):
    body = QRectF(22, 26, 56, 66)
    _rounded(p, body, 6, _grad(body, "#e3eef8", "#a9c4dd"), QPen(QColor("#7a9cbc"), 2))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#7a9cbc"))
    p.drawRoundedRect(QRectF(14, 16, 72, 10), 4, 4)
    p.drawRoundedRect(QRectF(40, 8, 20, 10), 3, 3)
    p.setPen(QPen(QColor("#7a9cbc"), 3))
    for x in (38, 50, 62):
        p.drawLine(QPointF(x, 38), QPointF(x, 80))


def _calculator(p):
    r = QRectF(16, 6, 68, 88)
    _rounded(p, r, 8, QColor("#3b3b3b"))
    _rounded(p, QRectF(24, 14, 52, 18), 3, QColor("#bfe3ff"))
    p.setBrush(QColor("#d0d0d0"))
    for row in range(3):
        for col in range(3):
            p.drawRoundedRect(QRectF(24 + col * 18, 40 + row * 17, 14, 13), 2, 2)
    p.setBrush(QColor("#f7630c"))
    p.drawRoundedRect(QRectF(24, 89, 50, 3), 1, 1)


def _text_editor(p):
    r = QRectF(16, 6, 68, 88)
    _rounded(p, r, 6, QColor("#ffffff"), QPen(QColor("#9a9a9a"), 2))
    _rounded(p, QRectF(16, 6, 68, 14), 6, QColor("#4cc2ff"))
    p.setPen(QPen(QColor("#7a7a7a"), 3))
    for y in (34, 46, 58, 70):
        p.drawLine(QPointF(26, y), QPointF(74 if y != 70 else 56, y))


def _photos(p):
    r = QRectF(8, 14, 84, 72)
    _rounded(p, r, 8, _grad(r, "#4cc2ff", "#0063b1"))
    p.setBrush(QColor("#ffd75e"))
    p.drawEllipse(QRectF(62, 24, 16, 16))
    p.setBrush(QColor("#ffffff"))
    p.drawPolygon(QPolygonF([QPointF(14, 80), QPointF(40, 44), QPointF(62, 80)]))
    p.setBrush(QColor(255, 255, 255, 190))
    p.drawPolygon(QPolygonF([QPointF(46, 80), QPointF(66, 54), QPointF(86, 80)]))


def _music(p):
    r = QRectF(8, 8, 84, 84)
    _rounded(p, r, 18, _grad(r, "#ff6b6b", "#c50f1f"))
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(QRectF(28, 58, 20, 16))
    p.drawEllipse(QRectF(56, 52, 20, 16))
    p.drawRect(QRectF(44, 26, 4, 40))
    p.drawRect(QRectF(72, 20, 4, 40))
    p.drawPolygon(QPolygonF([QPointF(44, 26), QPointF(76, 20), QPointF(76, 30), QPointF(44, 36)]))


def _control(p):
    r = QRectF(8, 12, 84, 76)
    _rounded(p, r, 8, _grad(r, "#3f9cf0", "#1866c4"))
    p.setBrush(QColor("#ffffff"))
    for i, (x, w) in enumerate(((18, 40), (18, 60), (18, 30))):
        y = 28 + i * 18
        p.drawRoundedRect(QRectF(x, y, 64, 4), 2, 2)
        p.drawEllipse(QRectF(x + w - 6, y - 5, 14, 14))


def _search(p, color="#1b1b1b"):
    pen = QPen(QColor(color), 9, cap=Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(14, 14, 50, 50))
    p.drawLine(QPointF(58, 58), QPointF(86, 86))


def _glyph_painter(kind):
    """Monochrome UI glyphs; color is supplied at render time."""
    def draw(p, color):
        pen = QPen(QColor(color), 7, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "wifi":
            for i, s in enumerate((80, 54, 28)):
                p.drawArc(QRectF(50 - s / 2, 72 - s / 2, s, s), 45 * 16, 90 * 16)
            p.setBrush(QColor(color))
            p.drawEllipse(QRectF(46, 70, 8, 8))
        elif kind == "volume":
            p.setBrush(QColor(color))
            p.drawPolygon(QPolygonF([QPointF(12, 38), QPointF(28, 38), QPointF(48, 20),
                                     QPointF(48, 80), QPointF(28, 62), QPointF(12, 62)]))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(44, 32, 24, 36), -60 * 16, 120 * 16)
            p.drawArc(QRectF(44, 18, 42, 64), -60 * 16, 120 * 16)
        elif kind == "battery":
            p.drawRoundedRect(QRectF(8, 30, 74, 40), 7, 7)
            p.setBrush(QColor(color))
            p.drawRect(QRectF(84, 42, 6, 16))
            p.drawRoundedRect(QRectF(16, 38, 44, 24), 3, 3)
        elif kind == "bluetooth":
            p.drawPolyline(QPolygonF([QPointF(28, 30), QPointF(70, 66), QPointF(50, 86), QPointF(50, 14),
                                      QPointF(70, 34), QPointF(28, 70)]))
        elif kind == "airplane":
            p.drawLine(QPointF(50, 10), QPointF(50, 88))
            p.drawLine(QPointF(14, 54), QPointF(86, 54))
            p.drawLine(QPointF(34, 84), QPointF(66, 84))
        elif kind == "moon":
            path = QPainterPath()
            path.addEllipse(QRectF(16, 16, 68, 68))
            cut = QPainterPath()
            cut.addEllipse(QRectF(36, 6, 60, 60))
            p.setBrush(QColor(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(path.subtracted(cut))
        elif kind == "sun":
            p.drawEllipse(QRectF(32, 32, 36, 36))
            import math
            for i in range(8):
                a = math.pi * i / 4
                p.drawLine(QPointF(50 + 28 * math.cos(a), 50 + 28 * math.sin(a)),
                           QPointF(50 + 40 * math.cos(a), 50 + 40 * math.sin(a)))
        elif kind == "power":
            p.drawArc(QRectF(16, 18, 68, 68), 60 * 16, -300 * 16)
            p.drawLine(QPointF(50, 10), QPointF(50, 46))
        elif kind == "back":
            p.drawLine(QPointF(84, 50), QPointF(18, 50))
            p.drawPolyline(QPolygonF([QPointF(44, 24), QPointF(18, 50), QPointF(44, 76)]))
        elif kind == "forward":
            p.drawLine(QPointF(16, 50), QPointF(82, 50))
            p.drawPolyline(QPolygonF([QPointF(56, 24), QPointF(82, 50), QPointF(56, 76)]))
        elif kind == "up":
            p.drawLine(QPointF(50, 84), QPointF(50, 18))
            p.drawPolyline(QPolygonF([QPointF(24, 44), QPointF(50, 18), QPointF(76, 44)]))
        elif kind == "refresh":
            p.drawArc(QRectF(16, 16, 68, 68), 60 * 16, 290 * 16)
            p.drawPolyline(QPolygonF([QPointF(66, 8), QPointF(70, 24), QPointF(54, 28)]))
        elif kind == "plus":
            p.drawLine(QPointF(50, 16), QPointF(50, 84))
            p.drawLine(QPointF(16, 50), QPointF(84, 50))
        elif kind == "cut":
            p.drawEllipse(QRectF(14, 60, 24, 24))
            p.drawEllipse(QRectF(62, 60, 24, 24))
            p.drawLine(QPointF(34, 64), QPointF(72, 12))
            p.drawLine(QPointF(66, 64), QPointF(28, 12))
        elif kind == "copy":
            p.drawRoundedRect(QRectF(34, 30, 50, 60), 7, 7)
            p.drawPolyline(QPolygonF([QPointF(66, 16), QPointF(18, 16), QPointF(18, 72)]))
        elif kind == "paste":
            p.drawRoundedRect(QRectF(18, 18, 64, 74), 7, 7)
            p.drawRoundedRect(QRectF(34, 10, 32, 16), 4, 4)
        elif kind == "rename":
            p.drawRoundedRect(QRectF(10, 30, 80, 40), 6, 6)
            p.drawLine(QPointF(60, 18), QPointF(60, 82))
        elif kind == "share":
            p.drawPolyline(QPolygonF([QPointF(30, 40), QPointF(14, 40), QPointF(14, 88), QPointF(86, 88), QPointF(86, 40), QPointF(70, 40)]))
            p.drawLine(QPointF(50, 12), QPointF(50, 62))
            p.drawPolyline(QPolygonF([QPointF(34, 28), QPointF(50, 12), QPointF(66, 28)]))
        elif kind == "delete":
            p.drawPolyline(QPolygonF([QPointF(24, 28), QPointF(30, 88), QPointF(70, 88), QPointF(76, 28)]))
            p.drawLine(QPointF(14, 26), QPointF(86, 26))
            p.drawLine(QPointF(38, 12), QPointF(62, 12))
        elif kind == "sort":
            p.drawLine(QPointF(30, 14), QPointF(30, 86))
            p.drawPolyline(QPolygonF([QPointF(14, 70), QPointF(30, 86), QPointF(46, 70)]))
            p.drawLine(QPointF(70, 86), QPointF(70, 14))
            p.drawPolyline(QPolygonF([QPointF(54, 30), QPointF(70, 14), QPointF(86, 30)]))
        elif kind == "view":
            for y in (22, 50, 78):
                p.drawLine(QPointF(34, y), QPointF(86, y))
                p.drawPoint(QPointF(16, y))
        elif kind == "more":
            p.setBrush(QColor(color))
            for x in (20, 50, 80):
                p.drawEllipse(QPointF(x, 50), 4, 4)
        elif kind == "menu":
            for y in (26, 50, 74):
                p.drawLine(QPointF(16, y), QPointF(84, y))
        elif kind == "close":
            p.drawLine(QPointF(22, 22), QPointF(78, 78))
            p.drawLine(QPointF(78, 22), QPointF(22, 78))
        elif kind == "bell":
            path = QPainterPath()
            path.moveTo(20, 72)
            path.cubicTo(28, 60, 24, 20, 50, 18)
            path.cubicTo(76, 20, 72, 60, 80, 72)
            path.closeSubpath()
            p.drawPath(path)
            p.drawLine(QPointF(42, 84), QPointF(58, 84))
        elif kind == "user":
            p.drawEllipse(QRectF(32, 12, 36, 36))
            p.drawArc(QRectF(14, 56, 72, 64), 0, 180 * 16)
        elif kind == "lock":
            p.drawRoundedRect(QRectF(20, 44, 60, 46), 7, 7)
            p.drawArc(QRectF(32, 12, 36, 52), 0, 180 * 16)
        elif kind == "chevron-right":
            p.drawPolyline(QPolygonF([QPointF(38, 18), QPointF(70, 50), QPointF(38, 82)]))
        elif kind == "chevron-down":
            p.drawPolyline(QPolygonF([QPointF(18, 36), QPointF(50, 68), QPointF(82, 36)]))
        elif kind == "chevron-up":
            p.drawPolyline(QPolygonF([QPointF(18, 64), QPointF(50, 32), QPointF(82, 64)]))
        elif kind == "widgets":
            p.drawRoundedRect(QRectF(10, 10, 36, 50), 7, 7)
            p.drawRoundedRect(QRectF(54, 10, 36, 30), 7, 7)
            p.drawRoundedRect(QRectF(54, 48, 36, 42), 7, 7)
            p.drawRoundedRect(QRectF(10, 68, 36, 22), 7, 7)
        elif kind == "taskview":
            p.drawRoundedRect(QRectF(8, 22, 54, 46), 6, 6)
            p.drawPolyline(QPolygonF([QPointF(26, 82), QPointF(80, 82), QPointF(80, 40)]))
        elif kind == "pin":
            p.drawLine(QPointF(50, 60), QPointF(50, 92))
            p.drawPolygon(QPolygonF([QPointF(30, 12), QPointF(70, 12), QPointF(64, 40), QPointF(78, 60), QPointF(22, 60), QPointF(36, 40)]))
        elif kind == "grid":
            for y in (14, 56):
                for x in (14, 56):
                    p.drawRoundedRect(QRectF(x, y, 30, 30), 5, 5)
        elif kind == "list":
            for y in (20, 50, 80):
                p.drawLine(QPointF(14, y), QPointF(86, y))
        elif kind == "cpu":
            p.drawRoundedRect(QRectF(24, 24, 52, 52), 6, 6)
            for k in (36, 50, 64):
                p.drawLine(QPointF(k, 8), QPointF(k, 22))
                p.drawLine(QPointF(k, 78), QPointF(k, 92))
                p.drawLine(QPointF(8, k), QPointF(22, k))
                p.drawLine(QPointF(78, k), QPointF(92, k))
        elif kind == "apps":
            for y in (14, 56):
                for x in (14, 56):
                    p.drawRoundedRect(QRectF(x, y, 30, 30), 5, 5)
        elif kind == "history":
            p.drawEllipse(QRectF(14, 14, 72, 72))
            p.drawPolyline(QPolygonF([QPointF(50, 30), QPointF(50, 52), QPointF(66, 60)]))
        elif kind == "startup":
            p.drawEllipse(QRectF(14, 14, 72, 72))
            p.drawPolyline(QPolygonF([QPointF(40, 32), QPointF(64, 50), QPointF(40, 68)]))
        elif kind == "users":
            p.drawEllipse(QRectF(16, 18, 30, 30))
            p.drawArc(QRectF(4, 56, 54, 50), 0, 180 * 16)
            p.drawEllipse(QRectF(58, 24, 24, 24))
            p.drawArc(QRectF(52, 58, 40, 40), 0, 180 * 16)
        elif kind == "details":
            for y in (22, 50, 78):
                p.drawLine(QPointF(14, y), QPointF(86, y))
        elif kind == "services":
            p.drawEllipse(QRectF(30, 30, 40, 40))
            p.drawEllipse(QRectF(12, 12, 76, 76))
        elif kind == "performance":
            p.drawPolyline(QPolygonF([QPointF(8, 60), QPointF(30, 60), QPointF(40, 30), QPointF(56, 80),
                                      QPointF(66, 50), QPointF(92, 50)]))
        elif kind == "efficiency":
            path = QPainterPath()
            path.moveTo(20, 84)
            path.cubicTo(10, 30, 50, 10, 86, 14)
            path.cubicTo(88, 60, 60, 90, 20, 84)
            p.drawPath(path)
            p.drawLine(QPointF(20, 84), QPointF(60, 44))
        elif kind == "folder-outline":
            p.drawPolyline(QPolygonF([QPointF(10, 82), QPointF(10, 18), QPointF(40, 18), QPointF(50, 30),
                                      QPointF(90, 30), QPointF(90, 82), QPointF(10, 82)]))
        elif kind == "star":
            import math
            pts = []
            for i in range(10):
                a = -math.pi / 2 + math.pi * i / 5
                rr = 40 if i % 2 == 0 else 17
                pts.append(QPointF(50 + rr * math.cos(a), 52 + rr * math.sin(a)))
            p.drawPolygon(QPolygonF(pts))
        elif kind == "terminal":
            p.drawPolyline(QPolygonF([QPointF(16, 26), QPointF(40, 50), QPointF(16, 74)]))
            p.drawLine(QPointF(50, 74), QPointF(84, 74))
        elif kind == "maximize":
            p.drawRoundedRect(QRectF(18, 18, 64, 64), 6, 6)
        elif kind == "minimize":
            p.drawLine(QPointF(18, 50), QPointF(82, 50))
    return draw


COLOR_ICONS = {
    "logo": _logo,
    "folder": _folder,
    "explorer": _explorer,
    "settings": _settings,
    "taskmgr": _taskmgr,
    "terminal": _terminal,
    "browser": _browser,
    "store": _store,
    "compat": _compat,
    "file": lambda p: _file(p),
    "file-text": lambda p: _file(p, band="#4c8bf5", label="TXT"),
    "file-image": lambda p: _file(p, band="#2ea043", label="IMG"),
    "file-audio": lambda p: _file(p, band="#d63384", label="MP3"),
    "file-video": lambda p: _file(p, band="#8957e5", label="VID"),
    "file-archive": lambda p: _file(p, band="#a0522d", label="ZIP"),
    "file-pdf": lambda p: _file(p, band="#d1242f", label="PDF"),
    "file-code": lambda p: _file(p, band="#0969da", label="</>"),
    "file-doc": lambda p: _file(p, band="#185abd", label="DOC"),
    "file-sheet": lambda p: _file(p, band="#107c41", label="XLS"),
    "file-exe": _exe,
    "monitor": _monitor,
    "drive": _drive,
    "home": _home,
    "desktop-folder": _special_folder("#0078d4"),
    "documents-folder": _special_folder("#5c6bc0"),
    "downloads-folder": _download_folder,
    "pictures-folder": _special_folder("#2ea043"),
    "music-folder": _special_folder("#d63384"),
    "videos-folder": _special_folder("#8957e5"),
    "trash": _trash,
    "calculator": _calculator,
    "text-editor": _text_editor,
    "photos": _photos,
    "music": _music,
    "control": _control,
}

GLYPHS = {name: _glyph_painter(name) for name in (
    "wifi", "volume", "battery", "bluetooth", "airplane", "moon", "sun", "power",
    "back", "forward", "up", "refresh", "plus", "cut", "copy", "paste", "rename",
    "share", "delete", "sort", "view", "more", "menu", "close", "bell", "user",
    "lock", "chevron-right", "chevron-down", "chevron-up", "widgets", "taskview",
    "pin", "grid", "list", "cpu", "apps", "history", "startup", "users", "details",
    "services", "performance", "efficiency", "folder-outline", "star", "terminal",
    "maximize", "minimize",
)}


@lru_cache(maxsize=512)
def pixmap(name: str, size: int = 32, color: str = "#1b1b1b") -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(size / 100.0, size / 100.0)
    if name == "start":
        _start_logo_mono(p, color)
    elif name == "search":
        _search(p, color)
    elif name in GLYPHS:
        GLYPHS[name](p, color)
    else:
        COLOR_ICONS.get(name, COLOR_ICONS["file"])(p)
    p.end()
    return pm


def icon(name: str, color: str = "#1b1b1b") -> QIcon:
    ic = QIcon()
    for s in (16, 20, 24, 32, 48, 64, 96, 128, 256):
        ic.addPixmap(pixmap(name, s, color))
    return ic


EXT_MAP = {
    "file-text": {"txt", "md", "log", "ini", "cfg", "conf", "csv", "rst"},
    "file-image": {"png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "ico", "tiff"},
    "file-audio": {"mp3", "wav", "flac", "ogg", "m4a", "aac", "opus"},
    "file-video": {"mp4", "mkv", "avi", "mov", "webm", "wmv"},
    "file-archive": {"zip", "tar", "gz", "xz", "bz2", "7z", "rar", "zst", "deb", "rpm"},
    "file-pdf": {"pdf"},
    "file-code": {"py", "c", "h", "cpp", "js", "ts", "rs", "go", "java", "sh", "html", "css", "json", "xml", "yml", "yaml", "toml"},
    "file-doc": {"doc", "docx", "odt", "rtf"},
    "file-sheet": {"xls", "xlsx", "ods"},
    "file-exe": {"exe", "msi", "bat", "cmd", "com", "lnk", "ps1", "dll"},
}


def for_filename(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    for key, exts in EXT_MAP.items():
        if ext in exts:
            return key
    return "file"


def glyph_file(name: str, color: str, size: int = 32) -> str:
    """Render an icon to a cached PNG (for use in Qt style sheets)."""
    import os
    from pathlib import Path
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "fenestra" / "icons"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{name}-{color.strip('#')}-{size}.png"
    if not path.exists():
        pixmap(name, size, color).save(str(path), "PNG")
    return str(path)


def export(dest: str) -> list:
    """Write PNG app icons into an XDG hicolor tree (used by `make install`)."""
    import os
    written = []
    for name in ("explorer", "taskmgr", "settings", "compat", "logo"):
        for size in (16, 24, 32, 48, 64, 128, 256):
            d = os.path.join(dest, f"{size}x{size}", "apps")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, f"fenestra-{name}.png")
            pixmap(name, size).save(path, "PNG")
            written.append(path)
    return written


def export_icns(name: str, dest: str) -> str:
    """Write a macOS .icns for one of the Fenestra icons (used by scripts/macos/install.sh)."""
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from ..compat.runner import make_icns
    pngs = {}
    for size in (32, 128, 256, 512, 1024):
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap(name, size).save(buf, "PNG")
        pngs[size] = bytes(ba)
    with open(dest, "wb") as fh:
        fh.write(make_icns(pngs))
    return dest


if __name__ == "__main__":
    import sys
    from PyQt6.QtGui import QGuiApplication
    app = QGuiApplication(sys.argv[:1])
    if len(sys.argv) > 3 and sys.argv[1] == "--icns":
        print(export_icns(sys.argv[2], sys.argv[3]))
    else:
        print("\n".join(export(sys.argv[1] if len(sys.argv) > 1 else "icons")))
