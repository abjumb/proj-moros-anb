"""Application entry point."""

import sys
from PyQt6.QtWidgets import QApplication
from .ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("mDiscovery")
    app.setOrganizationName("moroslab")

    # Dark palette
    app.setStyle("Fusion")
    _apply_dark_palette(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def _apply_dark_palette(app: QApplication) -> None:
    from PyQt6.QtGui import QPalette, QColor
    from PyQt6.QtCore import Qt
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(13, 17, 23))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(201, 209, 217))
    palette.setColor(QPalette.ColorRole.Base,            QColor(22, 27, 34))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(30, 37, 46))
    palette.setColor(QPalette.ColorRole.Text,            QColor(201, 209, 217))
    palette.setColor(QPalette.ColorRole.Button,          QColor(33, 38, 45))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(201, 209, 217))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(31, 111, 235))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)


if __name__ == "__main__":
    main()
