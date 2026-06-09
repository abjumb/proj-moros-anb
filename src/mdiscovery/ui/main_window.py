"""Main application window — assembles graph view, entity inspector, toolbar."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDockWidget, QFileDialog, QLabel, QMainWindow, QMessageBox, QSplitter,
    QToolBar, QVBoxLayout, QWidget, QStatusBar, QApplication,
)
from PyQt6.QtGui import QAction

from ..graph.database import GraphDatabase
from ..graph.models import Entity
from ..graph.repository import GraphRepository
from ..export.exporters import ExportFormat, write_export
from ..viz.graph_view import GraphView
from .import_dialog import ImportDialog

# QFileDialog name-filter label -> export format.
_EXPORT_FILTERS: dict[str, ExportFormat] = {
    "GraphML (*.graphml)": ExportFormat.GRAPHML,
    "CSV node/edge pair (*.csv)": ExportFormat.CSV,
    "Node-link JSON (*.json)": ExportFormat.JSON,
    "Markdown report (*.md)": ExportFormat.REPORT,
}

DEFAULT_DB_PATH = Path.home() / ".mdiscovery" / "default_case.kuzu"


class EntityInspector(QWidget):
    """Side panel showing selected entity details."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._title = QLabel("Select a node to inspect")
        self._title.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._title.setWordWrap(True)
        layout.addWidget(self._title)
        layout.addStretch()

    def show_entity(self, entity: Entity) -> None:
        lines = [
            f"<b>{entity.label}</b>",
            f"<small>Type: {entity.semantic_type.value}</small>",
        ]
        for k, v in entity.properties.items():
            lines.append(f"<b>{k}:</b> {v}")
        self._title.setText("<br>".join(lines))

    def clear(self) -> None:
        self._title.setText("Select a node to inspect")


class MainWindow(QMainWindow):
    def __init__(self, db_path: Optional[Path] = None):
        super().__init__()
        self.setWindowTitle("mDiscovery")
        self.resize(1280, 800)

        db_path = db_path or DEFAULT_DB_PATH
        self._db = GraphDatabase(db_path)
        self._repo = GraphRepository(self._db)

        self._build_ui()
        self._build_toolbar()
        self._build_statusbar()

        # Initial load
        self._graph_view.set_repo(self._repo)
        self._graph_view.load_from_repo()

    def _build_ui(self) -> None:
        self._graph_view = GraphView(self._repo)
        self._graph_view.nodeSelected.connect(self._on_node_selected)
        self.setCentralWidget(self._graph_view)

        self._inspector = EntityInspector()
        self._graph_view.backgroundTapped.connect(self._inspector.clear)
        dock = QDockWidget("Entity Inspector", self)
        dock.setWidget(self._inspector)
        dock.setMinimumWidth(220)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        self.addToolBar(tb)

        import_action = QAction("Import…", self)
        import_action.triggered.connect(self._open_import)
        tb.addAction(import_action)

        export_action = QAction("Export…", self)
        export_action.triggered.connect(self._open_export)
        tb.addAction(export_action)

        tb.addSeparator()

        for name, label in [
            ("cose", "Force"),
            ("hierarchical", "Hierarchical"),
            ("circular", "Circular"),
            ("grid", "Grid"),
        ]:
            act = QAction(label, self)
            act.triggered.connect(lambda _, n=name: self._graph_view.apply_layout(n))
            tb.addAction(act)

        tb.addSeparator()

        refresh_act = QAction("Refresh", self)
        refresh_act.triggered.connect(self._refresh_graph)
        tb.addAction(refresh_act)

    def _build_statusbar(self) -> None:
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._update_status()

    def _update_status(self) -> None:
        stats = self._repo.stats()
        self._status.showMessage(
            f"{stats['entity_count']} entities · {stats['link_count']} links"
        )

    def _on_node_selected(self, node_id: str) -> None:
        entity = self._repo.entities.get(node_id)
        if entity:
            self._inspector.show_entity(entity)

    def _open_import(self) -> None:
        dlg = ImportDialog(self._repo, self)
        if dlg.exec():
            self._refresh_graph()

    def _open_export(self) -> None:
        if self._repo.entities.count() == 0:
            QMessageBox.information(
                self, "Nothing to export", "The graph is empty — import data first."
            )
            return
        path_str, selected_filter = QFileDialog.getSaveFileName(
            self, "Export graph", "case", ";;".join(_EXPORT_FILTERS),
        )
        if not path_str:
            return
        fmt = _EXPORT_FILTERS.get(selected_filter, ExportFormat.GRAPHML)
        try:
            written = write_export(self._repo, path_str, fmt)
        except Exception as exc:  # surface failures instead of crashing the UI
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        names = "\n".join(p.name for p in written)
        self._status.showMessage(f"Exported {fmt.value} → {names}", 5000)

    def _refresh_graph(self) -> None:
        self._graph_view.load_from_repo()
        self._update_status()

    def closeEvent(self, event) -> None:
        self._db.close()
        super().closeEvent(event)
