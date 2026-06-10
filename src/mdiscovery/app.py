"""Application entry point."""

import os
import platform
import sys
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from .ui.main_window import MainWindow
from .ui import theme
from .ui.theme import UI_FONT_FAMILIES, UI_FONT_PIXEL_SIZE
from .ui.theming import apply_theme  # noqa: F401  (re-exported for tooling)


def _configure_webengine() -> None:
    """Set Chromium flags before QApplication (the only time they're read).

    QtWebEngine's GPU process is a frequent source of instability on Linux —
    GBM/driver crashes that blank the canvas — and a 2D graph canvas gains
    little from GPU compositing, so Linux defaults to software rendering for
    reliability. macOS/Windows keep hardware acceleration. Overrides:
      MDISCOVERY_SOFTWARE_RENDER=1  force software rendering anywhere
      MDISCOVERY_GPU=1              force hardware acceleration anywhere
    """
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    force_sw = os.environ.get("MDISCOVERY_SOFTWARE_RENDER") == "1"
    force_gpu = os.environ.get("MDISCOVERY_GPU") == "1"
    disable_gpu = force_sw or (platform.system() == "Linux" and not force_gpu)
    if disable_gpu and "--disable-gpu" not in flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --disable-gpu").strip()


def main() -> None:
    _configure_webengine()
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
