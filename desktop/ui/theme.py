"""Dark color theme and shared QSS stylesheet for the SW Team Optimizer."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from src.core.resources import ASSETS_DIR


# ── Palette colors ────────────────────────────────────────────────────────────
BG_DEEP    = "#0d1117"
BG_PANEL   = "#161b22"
BG_CARD    = "#1c2128"
BG_INPUT   = "#21262d"
BORDER     = "#30363d"
ACCENT     = "#e94560"
ACCENT_DIM = "#a8324a"
TEXT_MAIN  = "#c9d1d9"
TEXT_DIM   = "#6e7681"
TEXT_LINK  = "#58a6ff"

GRADE_S = "#ffd700"
GRADE_A = "#7fff00"
GRADE_B = "#00bfff"
GRADE_C = "#aaaaaa"
GRADE_D = "#ff5555"

ELEMENT_COLORS = {
    "Fire":    "#ff6b6b",
    "Water":   "#74b9ff",
    "Wind":    "#55efc4",
    "Light":   "#ffeaa7",
    "Dark":    "#a29bfe",
    "Unknown": "#aaaaaa",
}


def load_bundled_fonts(app: QApplication) -> str | None:
    """Load the shipped Vera family for deterministic source and packaged UI."""
    families = []
    for filename in ("Vera.ttf", "VeraBd.ttf", "VeraIt.ttf", "VeraBI.ttf"):
        font_id = QFontDatabase.addApplicationFont(
            str(ASSETS_DIR / "fonts" / filename)
        )
        if font_id >= 0:
            families.extend(QFontDatabase.applicationFontFamilies(font_id))
    if not families:
        return None
    family = families[0]
    QFont.insertSubstitution("Segoe UI", family)
    QFont.insertSubstitution("Inter", family)
    app.setFont(QFont(family, 10))
    return family


def apply_dark_palette(app: QApplication) -> None:
    """Apply the dark palette to a QApplication instance."""
    app.setStyle("Fusion")

    p = QPalette()
    p.setColor(QPalette.Window,          QColor(BG_DEEP))
    p.setColor(QPalette.WindowText,      QColor(TEXT_MAIN))
    p.setColor(QPalette.Base,            QColor(BG_INPUT))
    p.setColor(QPalette.AlternateBase,   QColor(BG_PANEL))
    p.setColor(QPalette.ToolTipBase,     QColor(BG_CARD))
    p.setColor(QPalette.ToolTipText,     QColor(TEXT_MAIN))
    p.setColor(QPalette.Text,            QColor(TEXT_MAIN))
    p.setColor(QPalette.Button,          QColor(BG_CARD))
    p.setColor(QPalette.ButtonText,      QColor(TEXT_MAIN))
    p.setColor(QPalette.BrightText,      QColor("#ffffff"))
    p.setColor(QPalette.Link,            QColor(TEXT_LINK))
    p.setColor(QPalette.Highlight,       QColor(ACCENT))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Disabled, QPalette.Text,       QColor(TEXT_DIM))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(TEXT_DIM))
    app.setPalette(p)


STYLESHEET = f"""
/* ── Global ──────────────────────────────────────────────── */
QWidget {{
    background-color: {BG_DEEP};
    color: {TEXT_MAIN};
    font-family: "Bitstream Vera Sans", "Segoe UI", sans-serif;
    font-size: 13px;
}}

QMainWindow {{
    background-color: {BG_DEEP};
}}

/* ── Menus ────────────────────────────────────────────────── */
QMenuBar {{
    background-color: {BG_PANEL};
    color: {TEXT_MAIN};
    border-bottom: 1px solid {BORDER};
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 10px;
}}
QMenuBar::item:selected {{
    background-color: {BG_CARD};
}}
QMenu {{
    background-color: {BG_CARD};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 28px 6px 10px;
}}
QMenu::item:selected {{
    background-color: {ACCENT};
    color: #ffffff;
}}
QMenu::separator {{
    background-color: {BORDER};
    height: 1px;
    margin: 4px 8px;
}}

/* ── Panels / frames ─────────────────────────────────────── */
QFrame#sidebar {{
    background-color: {BG_PANEL};
    border-right: 1px solid {BORDER};
}}

QFrame#topbar {{
    background-color: {BG_PANEL};
    border-bottom: 1px solid {BORDER};
}}

/* ── Sidebar nav buttons ─────────────────────────────────── */
QPushButton#navbtn {{
    background-color: transparent;
    color: {TEXT_DIM};
    border: none;
    border-radius: 6px;
    padding: 10px 16px;
    text-align: left;
    font-size: 13px;
}}
QPushButton#navbtn:hover {{
    background-color: {BG_CARD};
    color: {TEXT_MAIN};
}}
QPushButton#navbtn:checked {{
    background-color: {BG_CARD};
    color: {ACCENT};
    border-left: 3px solid {ACCENT};
}}

/* ── Import button ───────────────────────────────────────── */
QPushButton#import_btn {{
    background-color: {ACCENT};
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: bold;
}}
QPushButton#import_btn:hover {{
    background-color: {ACCENT_DIM};
}}

/* ── Generic buttons ─────────────────────────────────────── */
QPushButton {{
    background-color: {BG_CARD};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 6px 14px;
}}
QPushButton:hover {{
    background-color: {BG_INPUT};
    border-color: #484f58;
}}

/* ── Inputs / combos ─────────────────────────────────────── */
QLineEdit, QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 5px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
}}

/* ── Table ────────────────────────────────────────────────── */
QTableView {{
    background-color: {BG_DEEP};
    alternate-background-color: {BG_PANEL};
    gridline-color: {BORDER};
    border: none;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
    outline: none;
}}
QTableView::item {{
    padding: 4px 8px;
    border: none;
}}
QHeaderView::section {{
    background-color: {BG_CARD};
    color: {TEXT_DIM};
    padding: 6px 8px;
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    font-weight: bold;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QHeaderView::section:hover {{
    background-color: {BG_INPUT};
    color: {TEXT_MAIN};
}}

/* ── Scrollbars ───────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {BG_PANEL};
    width: 8px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: #484f58;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {BG_PANEL};
    height: 8px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #484f58;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ── Labels ───────────────────────────────────────────────── */
QLabel#title {{
    color: {TEXT_MAIN};
    font-size: 18px;
    font-weight: bold;
}}
QLabel#subtitle {{
    color: {TEXT_DIM};
    font-size: 12px;
}}
QLabel#stat_badge {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 12px;
    color: {TEXT_DIM};
}}

/* ── Tabs ─────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background-color: {BG_DEEP};
}}
QTabBar::tab {{
    background-color: {BG_PANEL};
    color: {TEXT_DIM};
    border: none;
    padding: 8px 18px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {TEXT_MAIN};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover {{
    color: {TEXT_MAIN};
}}

/* ── Status bar ───────────────────────────────────────────── */
QStatusBar {{
    background-color: {BG_PANEL};
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER};
    font-size: 12px;
}}

/* ── Tooltips ─────────────────────────────────────────────── */
QToolTip {{
    background-color: {BG_CARD};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    padding: 4px 8px;
}}

/* ── Progress bar ─────────────────────────────────────────── */
QProgressDialog, QProgressBar {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    text-align: center;
    color: {TEXT_MAIN};
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 4px;
}}
"""
