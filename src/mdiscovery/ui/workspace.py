"""Workspace — one open case (database + repository + canvas) in a pane.

Multiple workspaces tile side-by-side in the main window (e.g. a raw-input
case on the left, the cleaned-up chart on the right). Entities move between
workspaces via copy/paste of node-link JSON — deliberately not via drag —
and each workspace keeps its own grid-snap / degree-sizing state.

Header styling lives in the global QSS (#workspaceHeader rules in theme.py)
keyed off the ``wsActive`` dynamic property, so theme switches restyle panes
through the normal stylesheet reset with no per-widget refresh code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..graph.database import GraphDatabase
from ..graph.repository import GraphRepository
from ..viz.graph_view import GraphView


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class Workspace(QWidget):
    """A titled pane hosting one case file and its graph canvas."""

    activated = pyqtSignal(object)        # self — emitted on any interaction
    nodeSelected = pyqtSignal(object, str)        # self, node_id
    nodeDoubleClicked = pyqtSignal(object, str)   # self, node_id
    backgroundTapped = pyqtSignal(object)         # self
    closeRequested = pyqtSignal(object)           # self

    def __init__(self, db_path: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.db = GraphDatabase(self.db_path)
        self.repo = GraphRepository(self.db)
        self.grid_snap = False
        self.degree_sizing = False

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
        self._close_btn.clicked.connect(self._on_close_clicked)
        header_layout.addWidget(self._close_btn)
        layout.addWidget(self._header)

        self.graph_view = GraphView(self.repo)
        layout.addWidget(self.graph_view, stretch=1)

        self.graph_view.nodeSelected.connect(self._on_node_selected)
        self.graph_view.nodeDoubleClicked.connect(self._on_node_double_clicked)
        self.graph_view.backgroundTapped.connect(self._on_background_tapped)

        self.graph_view.load_from_repo()
        self.set_active(False)

    # ── Canvas signal relays (also mark this pane active) ───────────
    def _on_node_selected(self, node_id: str) -> None:
        self.mark_active()
        self.nodeSelected.emit(self, node_id)

    def _on_node_double_clicked(self, node_id: str) -> None:
        self.mark_active()
        self.nodeDoubleClicked.emit(self, node_id)

    def _on_background_tapped(self) -> None:
        self.mark_active()
        self.backgroundTapped.emit(self)

    def _on_close_clicked(self) -> None:
        self.closeRequested.emit(self)

    def mousePressEvent(self, event) -> None:  # header / chrome clicks
        self.mark_active()
        super().mousePressEvent(event)

    # ── Activation state ─────────────────────────────────────────────
    def mark_active(self) -> None:
        self.activated.emit(self)

    def set_active(self, active: bool) -> None:
        self._header.setProperty("wsActive", "true" if active else "false")
        _repolish(self._header)
        _repolish(self._title)

    def set_closable(self, closable: bool) -> None:
        self._close_btn.setVisible(closable)

    def refresh_theme(self) -> None:
        # Chrome restyles via the global QSS reset; only the canvas needs a push.
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

    def set_degree_sizing(self, enabled: bool) -> None:
        self.degree_sizing = enabled
        self.graph_view.set_degree_sizing(enabled)

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
        # Detach the canvas first: late bridge events (an in-flight edge
        # rename, queued JS callbacks) must not hit a closed connection.
        self.graph_view.set_repo(None)
        self.db.close()
