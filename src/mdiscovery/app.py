"""Application entry point."""

import sys
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from .ui.main_window import MainWindow
from .ui import theme
from .ui.theme import UI_FONT_FAMILIES, UI_FONT_PIXEL_SIZE
from .ui.theming import apply_theme  # noqa: F401  (re-exported for tooling)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("mDiscovery")
    app.setOrganizationName("moroslab")

    # JetBrains New UI theme; mode (dark/light) persists across sessions.
    # Font must be set BEFORE the app stylesheet — QStyleSheetStyle caches
    # font resolution at polish time.
    app.setStyle("Fusion")
    _apply_ui_font(app)
    saved_mode = QSettings().value("ui/theme", "dark")
    apply_theme(app, saved_mode if saved_mode in theme.PALETTES else "dark")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def _apply_ui_font(app: QApplication) -> None:
    from PyQt6.QtGui import QFont
    font = QFont()
    font.setFamilies(UI_FONT_FAMILIES)
    font.setPixelSize(UI_FONT_PIXEL_SIZE)
    app.setFont(font)


if __name__ == "__main__":
    main()
