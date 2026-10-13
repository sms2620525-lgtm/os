"""Fluent-style theme for every Fenestra Qt application.

The visual language follows Windows 11 Fluent design: rounded 4/8px corners,
Mica-like translucent surfaces, subtle 1px strokes and an accent colour.
"""

from dataclasses import dataclass

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

from . import config

FONT_FAMILIES = ["Segoe UI Variable", "Segoe UI", "Selawik", "Inter", "Noto Sans", "Cantarell", "sans-serif"]


@dataclass
class Palette:
    dark: bool
    accent: str
    window: str
    surface: str        # cards / panels
    surface_alt: str    # hover
    pressed: str
    stroke: str
    text: str
    text_secondary: str
    taskbar: str        # rgba() string, translucent
    flyout: str         # start menu / quick settings
    selection: str

    @property
    def accent_text(self) -> str:
        return "#000000" if self.dark else "#ffffff"


def _mix(hex_a: str, hex_b: str, t: float) -> str:
    a, b = QColor(hex_a), QColor(hex_b)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    ).name()


def palette(dark: bool | None = None, accent: str | None = None) -> Palette:
    cfg = config.load()
    if dark is None:
        dark = cfg.get("theme") == "dark"
    accent = accent or cfg.get("accent", "#0067c0")
    if dark:
        # Dark mode uses a lighter tint of the accent, like Windows does.
        accent_d = _mix(accent, "#ffffff", 0.45)
        return Palette(True, accent_d, "#202020", "#2b2b2b", "#323232", "#3a3a3a",
                       "#3d3d3d", "#ffffff", "#c5c5c5",
                       "rgba(28, 28, 28, 0.86)", "rgba(36, 36, 36, 0.94)",
                       _mix(accent_d, "#202020", 0.55))
    return Palette(False, accent, "#f3f3f3", "#fbfbfb", "#f0f0f0", "#e5e5e5",
                   "#e5e5e5", "#1b1b1b", "#5f5f5f",
                   "rgba(238, 241, 246, 0.86)", "rgba(242, 242, 242, 0.96)",
                   _mix(accent, "#ffffff", 0.8))


def rgba(text: str, opaque: bool = False) -> QColor:
    """Parse 'rgba(r, g, b, a)' (a in 0..1) or '#rrggbb' into a QColor."""
    if text.startswith("rgba"):
        r, g, b, a = (float(x) for x in text[text.index("(") + 1:-1].split(","))
        return QColor(int(r), int(g), int(b), 255 if opaque else int(a * 255))
    return QColor(text)


def ui_font(size: float = 9.5) -> QFont:
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(size)
    return font


def stylesheet(p: Palette) -> str:
    return f"""
    * {{ color: {p.text}; outline: none; }}
    QWidget#Window, QMainWindow, QDialog {{ background: {p.window}; }}
    QToolTip {{ background: {p.flyout}; color: {p.text}; border: 1px solid {p.stroke};
               border-radius: 4px; padding: 4px 8px; }}
    QLabel#Secondary {{ color: {p.text_secondary}; }}
    QLabel#Title {{ font-size: 20pt; font-weight: 600; }}
    QLabel#Subtitle {{ font-size: 13pt; font-weight: 600; }}
    QFrame#Card {{ background: {p.surface}; border: 1px solid {p.stroke}; border-radius: 8px; }}

    QPushButton {{ background: {p.surface}; border: 1px solid {p.stroke}; border-radius: 4px;
                  padding: 5px 14px; min-height: 20px; }}
    QPushButton:hover {{ background: {p.surface_alt}; }}
    QPushButton:pressed {{ background: {p.pressed}; color: {p.text_secondary}; }}
    QPushButton:disabled {{ color: {p.text_secondary}; }}
    QPushButton#Accent {{ background: {p.accent}; color: {p.accent_text}; border: 1px solid {p.accent}; }}
    QPushButton#Accent:hover {{ background: {_mix(p.accent, p.window, 0.12)}; }}
    QPushButton#Flat, QToolButton {{ background: transparent; border: 1px solid transparent;
                  border-radius: 4px; padding: 4px 8px; }}
    QPushButton#Flat:hover, QToolButton:hover {{ background: {p.surface_alt}; }}
    QPushButton#Flat:pressed, QToolButton:pressed {{ background: {p.pressed}; }}
    QToolButton:checked {{ background: {p.pressed}; }}
    QToolButton::menu-indicator {{ image: none; }}

    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{
        background: {p.surface}; border: 1px solid {p.stroke}; border-bottom: 1px solid {p.text_secondary};
        border-radius: 4px; padding: 4px 8px; selection-background-color: {p.accent};
        selection-color: {p.accent_text}; }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-bottom: 2px solid {p.accent}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{ background: {p.flyout}; border: 1px solid {p.stroke};
        border-radius: 6px; selection-background-color: {p.surface_alt}; selection-color: {p.text}; }}

    QTreeView, QListView, QTableView, QTreeWidget, QListWidget, QTableWidget {{
        background: {p.surface}; border: none; alternate-background-color: {p.surface};
        selection-background-color: {p.selection}; selection-color: {p.text}; }}
    QTreeView::item, QListView::item, QTableView::item {{ padding: 3px; border-radius: 4px; }}
    QTreeView::item:hover, QListView::item:hover, QTableView::item:hover {{ background: {p.surface_alt}; }}
    QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {{
        background: {p.selection}; color: {p.text}; }}
    QHeaderView::section {{ background: {p.surface}; color: {p.text_secondary}; border: none;
        border-right: 1px solid {p.stroke}; border-bottom: 1px solid {p.stroke}; padding: 4px 8px; }}
    QHeaderView::section:hover {{ background: {p.surface_alt}; }}

    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ background: transparent; padding: 6px 14px; border-radius: 4px; margin: 2px; }}
    QTabBar::tab:selected {{ background: {p.surface}; border: 1px solid {p.stroke}; }}
    QTabBar::tab:hover:!selected {{ background: {p.surface_alt}; }}

    QMenu {{ background: {p.flyout}; border: 1px solid {p.stroke}; border-radius: 8px; padding: 4px; }}
    QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {p.surface_alt}; }}
    QMenu::separator {{ height: 1px; background: {p.stroke}; margin: 4px 8px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.text_secondary}; border-radius: 3px; min-height: 30px; margin: 0 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {p.text_secondary}; border-radius: 3px; min-width: 30px; margin: 2px 0; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}

    QSlider::groove:horizontal {{ height: 4px; background: {p.text_secondary}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {p.accent}; border: 4px solid {p.surface}; width: 12px; height: 12px;
        margin: -8px 0; border-radius: 10px; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
    QProgressBar {{ background: {p.stroke}; border: none; border-radius: 2px; height: 4px; text-align: center; }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: 2px; }}
    QStatusBar {{ background: {p.window}; color: {p.text_secondary}; }}
    QSplitter::handle {{ background: {p.stroke}; }}
    """


def apply(app: QApplication, dark: bool | None = None) -> Palette:
    p = palette(dark)
    app.setFont(ui_font())
    app.setStyle("Fusion")
    qp = QPalette()
    qp.setColor(QPalette.ColorRole.Window, QColor(p.window))
    qp.setColor(QPalette.ColorRole.Base, QColor(p.surface))
    qp.setColor(QPalette.ColorRole.AlternateBase, QColor(p.surface_alt))
    qp.setColor(QPalette.ColorRole.Text, QColor(p.text))
    qp.setColor(QPalette.ColorRole.WindowText, QColor(p.text))
    qp.setColor(QPalette.ColorRole.ButtonText, QColor(p.text))
    qp.setColor(QPalette.ColorRole.Button, QColor(p.surface))
    qp.setColor(QPalette.ColorRole.Highlight, QColor(p.accent))
    qp.setColor(QPalette.ColorRole.HighlightedText, QColor(p.accent_text))
    qp.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.text_secondary))
    app.setPalette(qp)
    app.setStyleSheet(stylesheet(p))
    return p
