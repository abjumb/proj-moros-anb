"""Application entry point."""

import sys
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from .ui.main_window import MainWindow
from .ui import theme
from .ui.theme import UI_FONT_FAMILIES, UI_FONT_PIXEL_SIZE, build_stylesheet


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("mDiscovery")
    app.setOrganizationName("moroslab")

    # JetBrains New UI theme; mode (dark/light) persists across sessions.
    app.setStyle("Fusion")
    saved_mode = QSettings().value("ui/theme", "dark")
    apply_theme(app, saved_mode if saved_mode in theme.PALETTES else "dark")
    _apply_ui_font(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def apply_theme(app: QApplication, mode: str) -> None:
    """Apply palette + stylesheet for ``mode`` and persist the choice.

    Safe to call at runtime (View ▸ toggle); widgets repolish via the
    stylesheet reset. Canvas re-theming is the caller's job (workspaces push
    ``theme.canvas_theme()`` to their views).
    """
    from PyQt6.QtGui import QPalette, QColor

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


def _apply_ui_font(app: QApplication) -> None:
    from PyQt6.QtGui import QFont
    font = QFont()
    font.setFamilies(UI_FONT_FAMILIES)
    font.setPixelSize(UI_FONT_PIXEL_SIZE)
    app.setFont(font)


if __name__ == "__main__":
    main()
