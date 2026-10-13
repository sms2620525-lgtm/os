"""Procedurally generated default wallpaper ("Fenestra Glow").

Original artwork: layered translucent petals over a deep gradient, in the
spirit of Fluent wallpapers. Rendered once per resolution and cached.
"""

import os
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QRadialGradient


def render(width: int, height: int, dark: bool = False) -> QImage:
    img = QImage(width, height, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    bg = QLinearGradient(0, 0, width, height)
    if dark:
        bg.setColorAt(0, QColor("#020b1f"))
        bg.setColorAt(0.6, QColor("#06204a"))
        bg.setColorAt(1, QColor("#0a1430"))
    else:
        bg.setColorAt(0, QColor("#a9d4ff"))
        bg.setColorAt(0.55, QColor("#5aa6f2"))
        bg.setColorAt(1, QColor("#2f6fd0"))
    p.fillRect(img.rect(), bg)

    cx, cy = width * 0.52, height * 0.58
    scale = min(width, height) / 1080.0
    petals = 7
    for layer in range(3):
        for i in range(petals):
            angle = -100 + i * (200 / (petals - 1)) + layer * 9
            length = (520 - layer * 90) * scale
            breadth = (210 - layer * 40) * scale
            path = QPainterPath()
            path.moveTo(0, 0)
            path.cubicTo(QPointF(-breadth, -length * 0.35), QPointF(-breadth * 0.6, -length * 0.95), QPointF(0, -length))
            path.cubicTo(QPointF(breadth * 0.6, -length * 0.95), QPointF(breadth, -length * 0.35), QPointF(0, 0))
            p.save()
            p.translate(cx, cy)
            p.rotate(angle)
            g = QRadialGradient(QPointF(0, -length * 0.55), length * 0.75)
            if dark:
                c1, c2 = QColor(70, 150, 255, 150 - layer * 30), QColor(20, 60, 160, 20)
            else:
                c1, c2 = QColor(255, 255, 255, 150 - layer * 35), QColor(20, 90, 210, 40)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawPath(path)
            p.restore()
    glow = QRadialGradient(QPointF(cx, cy), 260 * scale)
    glow.setColorAt(0, QColor(255, 255, 255, 120 if not dark else 70))
    glow.setColorAt(1, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawEllipse(QPointF(cx, cy), 260 * scale, 260 * scale)
    p.end()
    return img


def cached(width: int, height: int, dark: bool = False) -> str:
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "fenestra"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"wallpaper-{'dark' if dark else 'light'}-{width}x{height}.png"
    if not path.exists():
        render(width, height, dark).save(str(path), "PNG")
    return str(path)


if __name__ == "__main__":
    import sys
    from PyQt6.QtGui import QGuiApplication
    app = QGuiApplication(sys.argv)
    w, h = (int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "1920x1080").split("x"))
    out = sys.argv[2] if len(sys.argv) > 2 else "wallpaper.png"
    render(w, h, "--dark" in sys.argv).save(out)
    print(out)
