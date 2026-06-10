"""Qt-side theme application (palette + stylesheet + persistence).

Separate from ``theme.py`` so that module stays import-safe without Qt (the
data-layer test suite imports it in CI). Anything that needs to *switch*
themes — app startup, the View menu toggle, tools — calls ``apply_theme``
from here instead of reaching into the application entry point.
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from . import theme
from .theme import build_stylesheet


def apply_theme(app: QApplication, mode: str) -> None:
    """Apply palette + stylesheet for ``mode`` and persist the choice.

    Safe to call at runtime; widgets repolish via the stylesheet reset.
    Canvas re-theming is the caller's job (workspaces push
    ``theme.canvas_theme()`` to their views).
    """
    theme.set_mode(mode)
    t = theme.active_tokens()
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(t["bg_window"]))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Base,            QColor(t["bg_window"]))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(t["row_alt"]))
    palette.setColor(QPalette.ColorRole.Text,            QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(t["text_muted"]))
    palette.setColor(QPalette.ColorRole.Button,          QColor(t["bg_panel"]))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(t["bg_panel"]))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Link,            QColor(t["accent"]))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(t["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role,
                         QColor(t["text_muted"]))
    app.setPalette(palette)
    app.setStyleSheet(build_stylesheet(mode))
    QSettings().setValue("ui/theme", mode)
