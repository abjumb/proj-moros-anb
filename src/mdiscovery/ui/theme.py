"""Darcula-style theme — design tokens and the application stylesheet.

Single source of truth for the JetBrains "New UI" dark palette. The QPalette in
``app.py`` and the QSS built here both read from ``TOKENS``; the Cytoscape canvas
(``assets/cytoscape/graph.html``) mirrors the same hex values.
"""

from __future__ import annotations

TOKENS: dict[str, str] = {
    "bg_window":      "#1E1F22",  # main window / editor / canvas
    "bg_panel":       "#2B2D30",  # tool windows, dialogs, inputs
    "bg_hover":       "#3C3F44",
    "bg_pressed":     "#43454A",
    "border":         "#393B40",  # dividers, panel borders
    "border_control": "#43454A",  # button / input outlines
    "text":           "#DFE1E5",
    "text_muted":     "#6F737A",
    "accent":         "#3574F0",  # selection, focus ring
    "accent_hover":   "#366ACE",
    "row_alt":        "#26282E",  # alternating table rows
    "scroll_handle":  "#43454A",
    "scroll_hover":   "#54585E",
}

# Sans-serif stack approximating the JetBrains New UI font; QFont.setFamilies
# walks this list for the first installed family.
UI_FONT_FAMILIES = [
    "Inter", "SF Pro Text", "Segoe UI", "Ubuntu", "Cantarell", "Noto Sans",
]
UI_FONT_PIXEL_SIZE = 13
MONO_FONT_FAMILY = "JetBrains Mono"


def _center_line(color: str, horizontal: bool) -> str:
    """A 5px-wide grab area painting only a centered 1px line.

    Keeps splitter/dock separators visually thin (JetBrains style) without
    shrinking the draggable hit target to 1px.
    """
    x2, y2 = ("1", "0") if horizontal else ("0", "1")
    return (
        f"qlineargradient(x1: 0, y1: 0, x2: {x2}, y2: {y2},"
        f" stop: 0 transparent, stop: 0.4 transparent,"
        f" stop: 0.4 {color}, stop: 0.6 {color},"
        f" stop: 0.6 transparent, stop: 1 transparent)"
    )


def build_stylesheet() -> str:
    """Return the application-wide QSS for the parts QPalette can't reach."""
    t = TOKENS
    return f"""
/* ── Base ─────────────────────────────────────────────────────────── */
QWidget {{
    color: {t["text"]};
}}
QWidget:disabled {{
    color: {t["text_muted"]};
}}
QLabel {{
    background: transparent;
}}
QToolTip {{
    background-color: {t["bg_panel"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
    padding: 4px 8px;
}}
QDialog {{
    background-color: {t["bg_panel"]};
}}

/* ── Menu bar & menus ─────────────────────────────────────────────── */
QMenuBar {{
    background-color: {t["bg_window"]};
    border: none;
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
    margin: 2px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background: {t["bg_hover"]};
}}
QMenu {{
    background-color: {t["bg_panel"]};
    border: 1px solid {t["border"]};
    padding: 4px;
}}
QMenu::item {{
    padding: 4px 24px 4px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {t["accent"]};
    color: #FFFFFF;
}}
QMenu::item:disabled {{
    color: {t["text_muted"]};
    background: transparent;
}}
QMenu::separator {{
    height: 1px;
    background: {t["border"]};
    margin: 4px 8px;
}}

/* ── Toolbar ──────────────────────────────────────────────────────── */
QToolBar {{
    background-color: {t["bg_window"]};
    border: none;
    border-bottom: 1px solid {t["border"]};
    padding: 3px 6px;
    spacing: 2px;
}}
QToolBar::separator {{
    background: {t["border"]};
    width: 1px;
    margin: 4px 6px;
}}
QToolBar::handle {{
    image: none;
    width: 6px;
}}
QToolButton {{
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 4px 10px;
}}
QToolButton:hover {{
    background-color: {t["bg_hover"]};
}}
QToolButton:pressed, QToolButton:checked {{
    background-color: {t["bg_pressed"]};
}}
QToolButton:disabled {{
    color: {t["text_muted"]};
}}

/* ── Buttons ──────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {t["bg_panel"]};
    border: 1px solid {t["border_control"]};
    border-radius: 4px;
    padding: 5px 14px;
    min-width: 60px;
}}
QPushButton:hover {{
    background-color: {t["bg_hover"]};
}}
QPushButton:pressed {{
    background-color: {t["bg_pressed"]};
}}
QPushButton:focus {{
    border: 1px solid {t["accent"]};
    outline: none;
}}
QPushButton:default {{
    border: 1px solid {t["accent"]};
}}
QPushButton:disabled {{
    color: {t["text_muted"]};
    border-color: {t["border"]};
}}

/* ── Inputs ───────────────────────────────────────────────────────── */
QLineEdit, QComboBox, QAbstractSpinBox {{
    background-color: {t["bg_panel"]};
    border: 1px solid {t["border_control"]};
    border-radius: 4px;
    padding: 4px 8px;
    selection-background-color: {t["accent"]};
    selection-color: #FFFFFF;
}}
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{
    border: 1px solid {t["accent"]};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {t["text_muted"]};
    border-color: {t["border"]};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    width: 20px;
    border: none;
}}
QComboBox QAbstractItemView {{
    background-color: {t["bg_panel"]};
    border: 1px solid {t["border"]};
    outline: none;
}}

/* ── Item views ───────────────────────────────────────────────────── */
QAbstractItemView {{
    background-color: {t["bg_panel"]};
    border: 1px solid {t["border"]};
    selection-background-color: {t["accent"]};
    selection-color: #FFFFFF;
    outline: none;
}}
QTableView, QTableWidget {{
    background-color: {t["bg_window"]};
    alternate-background-color: {t["row_alt"]};
    gridline-color: {t["border"]};
    border: 1px solid {t["border"]};
    border-radius: 4px;
}}
QHeaderView::section {{
    background-color: {t["bg_panel"]};
    color: {t["text_muted"]};
    border: none;
    border-right: 1px solid {t["border"]};
    border-bottom: 1px solid {t["border"]};
    padding: 4px 8px;
}}
QTableCornerButton::section {{
    background-color: {t["bg_panel"]};
    border: none;
    border-bottom: 1px solid {t["border"]};
}}

/* ── Tabs ─────────────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {t["border"]};
    border-radius: 4px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {t["text_muted"]};
    padding: 6px 14px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{
    color: {t["text"]};
    background: {t["bg_hover"]};
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}
QTabBar::tab:selected {{
    color: {t["text"]};
    border-bottom: 2px solid {t["accent"]};
}}

/* ── Group boxes & scroll areas ───────────────────────────────────── */
QGroupBox {{
    border: 1px solid {t["border"]};
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {t["text_muted"]};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

/* ── Dock widgets (tool windows) ──────────────────────────────────── */
QDockWidget {{
    color: {t["text"]};
}}
QDockWidget::title {{
    background-color: {t["bg_panel"]};
    border-bottom: 1px solid {t["border"]};
    padding: 5px 10px;
    text-align: left;
}}
EntityInspector {{
    background-color: {t["bg_panel"]};
}}

/* ── Splitters & separators ───────────────────────────────────────── */
QSplitter::handle:horizontal {{
    width: 5px;
    background: {_center_line(TOKENS["border"], horizontal=True)};
}}
QSplitter::handle:vertical {{
    height: 5px;
    background: {_center_line(TOKENS["border"], horizontal=False)};
}}
QSplitter::handle:horizontal:hover {{
    background: {_center_line(TOKENS["accent"], horizontal=True)};
}}
QSplitter::handle:vertical:hover {{
    background: {_center_line(TOKENS["accent"], horizontal=False)};
}}
QMainWindow::separator {{
    width: 5px;
    height: 5px;
    background: {_center_line(TOKENS["border"], horizontal=True)};
}}
QMainWindow::separator:hover {{
    background: {_center_line(TOKENS["accent"], horizontal=True)};
}}

/* ── Status bar ───────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {t["bg_window"]};
    color: {t["text_muted"]};
    border-top: 1px solid {t["border"]};
    font-size: 12px;
}}
QStatusBar::item {{
    border: none;
}}
QStatusBar QLabel {{
    color: {t["text_muted"]};
}}

/* ── Scrollbars ───────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {t["scroll_handle"]};
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t["scroll_hover"]};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {t["scroll_handle"]};
    border-radius: 3px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {t["scroll_hover"]};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
"""
