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
from ..persistence import copy_case, RecentCases
from ..viz.graph_view import GraphView
from .import_dialog import ImportDialog

# QFileDialog name-filter label -> export format.
_EXPORT_FILTERS: dict[str, ExportFormat] = {
    "GraphML (*.graphml)": ExportFormat.GRAPHML,
    "CSV node/edge pair (*.csv)": ExportFormat.CSV,
    "Node-link JSON (*.json)": ExportFormat.JSON,
    "Markdown report (*.md)": ExportFormat.REPORT,
}

_CASE_FILTER = "Case files (*.kuzu);;All files (*)"

MDISCOVERY_DIR = Path.home() / ".mdiscovery"
DEFAULT_DB_PATH = MDISCOVERY_DIR / "default_case.kuzu"
RECENT_STORE = MDISCOVERY_DIR / "recent.json"


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

        self._db_path = Path(db_path or DEFAULT_DB_PATH)
        self._db = GraphDatabase(self._db_path)
        self._repo = GraphRepository(self._db)
        self._recent = RecentCases(RECENT_STORE)

        self._build_ui()
        self._build_menubar()
        self._build_toolbar()
        self._build_statusbar()

        # Initial load
        self._graph_view.set_repo(self._repo)
        self._graph_view.load_from_repo()
        self._recent.add(self._db_path)
        self._rebuild_recent_menu()
        self._update_title()

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

    def _build_menubar(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        new_act = QAction("&New Case…", self)
        new_act.triggered.connect(self._new_case)
        file_menu.addAction(new_act)

        open_act = QAction("&Open Case…", self)
        open_act.triggered.connect(self._open_case)
        file_menu.addAction(open_act)

        save_act = QAction("&Save Case As…", self)
        save_act.triggered.connect(self._save_case_as)
        file_menu.addAction(save_act)

        self._recent_menu = file_menu.addMenu("Open &Recent")

        file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        cases = [p for p in self._recent.existing() if p != self._db_path]
        if not cases:
            empty = self._recent_menu.addAction("(no recent cases)")
            empty.setEnabled(False)
            return
        for path in cases:
            act = QAction(path.name, self)
            act.setToolTip(str(path))
            act.triggered.connect(lambda _, p=path: self._switch_case(p))
            self._recent_menu.addAction(act)
        self._recent_menu.addSeparator()
        clear_act = QAction("Clear recent", self)
        clear_act.triggered.connect(self._clear_recent)
        self._recent_menu.addAction(clear_act)

    def _clear_recent(self) -> None:
        self._recent.clear()
        self._recent.add(self._db_path)  # keep the open case
        self._rebuild_recent_menu()

    def _update_title(self) -> None:
        self.setWindowTitle(f"mDiscovery — {self._db_path.name}")

    def _switch_case(self, path: Path) -> None:
        """Close the current case and open ``path``, reloading the view."""
        path = Path(path)
        try:
            new_db = GraphDatabase(path)
        except Exception as exc:  # bad path / corrupt DB — keep the current case
            QMessageBox.critical(self, "Could not open case", str(exc))
            return
        self._db.close()
        self._db = new_db
        self._db_path = path
        self._repo = GraphRepository(self._db)
        self._graph_view.set_repo(self._repo)
        self._graph_view.load_from_repo()
        self._inspector.clear()
        self._recent.add(path)
        self._rebuild_recent_menu()
        self._update_title()
        self._update_status()

    def _new_case(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self, "New case", "case.kuzu", _CASE_FILTER,
        )
        if not path_str:
            return
        if Path(path_str).exists():
            QMessageBox.warning(
                self, "Path exists",
                "Choose a path that doesn't exist yet for a new case.",
            )
            return
        self._switch_case(Path(path_str))

    def _open_case(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open case", str(self._db_path.parent), _CASE_FILTER,
        )
        if path_str:
            self._switch_case(Path(path_str))

    def _save_case_as(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save case as", "case-copy.kuzu", _CASE_FILTER,
        )
        if not path_str:
            return
        try:
            copy_case(self._db_path, path_str, overwrite=True)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self._switch_case(Path(path_str))  # continue working in the saved copy

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
