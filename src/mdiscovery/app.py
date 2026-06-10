"""Application entry point."""

import sys
from PyQt6.QtWidgets import QApplication
from .ui.main_window import MainWindow
from .ui.theme import TOKENS, UI_FONT_FAMILIES, UI_FONT_PIXEL_SIZE, build_stylesheet


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("mDiscovery")
    app.setOrganizationName("moroslab")

    # Darcula-style dark theme (JetBrains New UI palette)
    app.setStyle("Fusion")
    _apply_dark_palette(app)
    _apply_ui_font(app)
    app.setStyleSheet(build_stylesheet())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def _apply_dark_palette(app: QApplication) -> None:
    from PyQt6.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(TOKENS["bg_window"]))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(TOKENS["text"]))
    palette.setColor(QPalette.ColorRole.Base,            QColor(TOKENS["bg_window"]))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(TOKENS["row_alt"]))
    palette.setColor(QPalette.ColorRole.Text,            QColor(TOKENS["text"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TOKENS["text_muted"]))
    palette.setColor(QPalette.ColorRole.Button,          QColor(TOKENS["bg_panel"]))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(TOKENS["text"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(TOKENS["bg_panel"]))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(TOKENS["text"]))
    palette.setColor(QPalette.ColorRole.Link,            QColor(TOKENS["accent"]))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(TOKENS["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role,
                         QColor(TOKENS["text_muted"]))
    app.setPalette(palette)


def _apply_ui_font(app: QApplication) -> None:
    from PyQt6.QtGui import QFont
    font = QFont()
    font.setFamilies(UI_FONT_FAMILIES)
    font.setPixelSize(UI_FONT_PIXEL_SIZE)
    app.setFont(font)


if __name__ == "__main__":
    main()
