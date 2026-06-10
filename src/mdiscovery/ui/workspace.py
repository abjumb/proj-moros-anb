"""Workspace — one open case (database + repository + canvas) in a pane.

Multiple workspaces tile side-by-side in the main window (e.g. a raw-input
case on the left, the cleaned-up chart on the right). Entities move between
workspaces via copy/paste of node-link JSON — deliberately not via drag —
and each workspace keeps its own grid-snap state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..graph.database import GraphDatabase
from ..graph.repository import GraphRepository
from ..viz.graph_view import GraphView
from . import theme


class Workspace(QWidget):
    """A titled pane hosting one case file and its graph canvas."""

    activated = pyqtSignal(object)        # self — emitted on any interaction
    nodeSelected = pyqtSignal(object, str)        # self, node_id
    nodeDoubleClicked = pyqtSignal(object, str)   # self, node_id
    backgroundTapped = pyqtSignal(object)         # self
    closeRequested = pyqtSignal(object)           # self

    def __init__(self, db_path: Path, parent: Optional[QWidget] = None,
                 closable: bool = True):
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.db = GraphDatabase(self.db_path)
        self.repo = GraphRepository(self.db)
        self.grid_snap = False
        self._active = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = QWidget()
        self._header.setObjectName("workspaceHeader")
        self._header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(10, 4, 6, 4)
        self._title = QLabel(self.db_path.name)
        header_layout.addWidget(self._title)
        header_layout.addStretch()
        self._close_btn = QPushButton("✕")
        self._close_btn.setObjectName("workspaceClose")
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setVisible(closable)
        self._close_btn.clicked.connect(lambda: self.closeRequested.emit(self))
        header_layout.addWidget(self._close_btn)
        layout.addWidget(self._header)

        self.graph_view = GraphView(self.repo)
        layout.addWidget(self.graph_view, stretch=1)

        self.graph_view.nodeSelected.connect(
            lambda nid: (self._mark_active(), self.nodeSelected.emit(self, nid)))
        self.graph_view.nodeDoubleClicked.connect(
            lambda nid: (self._mark_active(), self.nodeDoubleClicked.emit(self, nid)))
        self.graph_view.backgroundTapped.connect(
            lambda: (self._mark_active(), self.backgroundTapped.emit(self)))

        # WebEngine swallows mouse events; its focusProxy sees focus changes.
        proxy = self.graph_view._web.focusProxy()
        if proxy is not None:
            proxy.installEventFilter(self)
        self._header.installEventFilter(self)

        self.graph_view.load_from_repo()
        self._refresh_header_style()

    # ── Activation tracking ─────────────────────────────────────────
    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress):
            self._mark_active()
        return super().eventFilter(obj, event)

    def _mark_active(self) -> None:
        self.activated.emit(self)

    def set_active(self, active: bool) -> None:
        self._active = active
        self._refresh_header_style()

    def _refresh_header_style(self) -> None:
        t = theme.active_tokens()
        accent = t["accent"] if self._active else t["border"]
        self._header.setStyleSheet(
            f"#workspaceHeader {{ background: {t['bg_panel']};"
            f" border-bottom: 2px solid {accent}; }}"
            f"#workspaceClose {{ min-width: 22px; padding: 0; }}"
        )
        self._title.setStyleSheet(
            f"color: {t['text'] if self._active else t['text_muted']};"
            "font-weight: 600;"
        )

    def refresh_theme(self) -> None:
        self._refresh_header_style()
        self.graph_view.apply_theme()

    # ── Case / canvas operations ────────────────────────────────────
    @property
    def media_dir(self) -> Path:
        return self.db_path.parent / f"{self.db_path.name}.media"

    def refresh(self) -> None:
        self.graph_view.load_from_repo()

    def set_grid_snap(self, enabled: bool) -> None:
        self.grid_snap = enabled
        self.graph_view.set_grid_snap(enabled)

    def switch_case(self, path: Path) -> None:
        """Close the current case and open ``path`` in this pane."""
        new_db = GraphDatabase(path)  # raises before we tear anything down
        self.db.close()
        self.db = new_db
        self.db_path = Path(path)
        self.repo = GraphRepository(self.db)
        self.graph_view.set_repo(self.repo)
        self.graph_view.load_from_repo()
        self._title.setText(self.db_path.name)

    def close_db(self) -> None:
        self.db.close()
