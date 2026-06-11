"""Main application window — tiled workspaces, inspector, toolbar, theming.

The window hosts one or more :class:`Workspace` panes in a splitter (e.g. a
raw-input case beside the cleaned-up chart). All chart actions — import,
export, search, authoring, layout — target the *active* workspace, marked by
its accented header. Entities move between workspaces via copy/paste of
node-link JSON (never drag), so the same payload also round-trips through the
system clipboard.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSizePolicy, QSplitter, QStatusBar, QToolBar,
    QVBoxLayout, QWidget,
)

from .. import casepack
from ..graph.models import Entity
from ..export.exporters import ExportFormat, to_json, write_export
from ..importer.anx_import import load_anx
from ..importer.json_import import load_node_link_json, parse_node_link_text
from ..persistence import copy_case, RecentCases
from . import theme
from .dossier import DELETED, DossierDialog
from .entity_dialog import EntityDialog, LinkDialog
from .find_path_dialog import FindPathDialog
from .import_dialog import ImportDialog
from .theme import MONO_FONT_FAMILY
from .theming import apply_theme
from .workspace import Workspace

# QFileDialog name-filter label -> export format.
_EXPORT_FILTERS: dict[str, ExportFormat] = {
    "GraphML (*.graphml)": ExportFormat.GRAPHML,
    "CSV node/edge pair (*.csv)": ExportFormat.CSV,
    "Node-link JSON (*.json)": ExportFormat.JSON,
    "Markdown report (*.md)": ExportFormat.REPORT,
    "i2 Chart XML (*.anx)": ExportFormat.ANX,
}

_PACKAGE_FILTER = f"Case packages (*{casepack.EXTENSION});;All files (*)"

_CASE_FILTER = "Case files (*.kuzu);;All files (*)"

MDISCOVERY_DIR = Path.home() / ".mdiscovery"
DEFAULT_DB_PATH = MDISCOVERY_DIR / "default_case.kuzu"
RECENT_STORE = MDISCOVERY_DIR / "recent.json"


class EntityInspector(QWidget):
    """Side panel showing selected entity details, with an expand-neighbors action."""

    expandRequested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        # Let the `EntityInspector { background }` QSS rule paint the panel.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._entity_id: Optional[str] = None
        self._entity: Optional[Entity] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self._title = QLabel(self._placeholder())
        self._title.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._expand_btn = QPushButton("Expand neighbors")
        self._expand_btn.setVisible(False)
        self._expand_btn.clicked.connect(self._on_expand)
        layout.addWidget(self._expand_btn)
        layout.addStretch()

    @staticmethod
    def _placeholder() -> str:
        muted = theme.active_tokens()["text_muted"]
        return f'<span style="color: {muted}">Select a node to inspect</span>'

    def show_entity(self, entity: Entity) -> None:
        self._entity_id = entity.id
        self._entity = entity
        muted, mono = theme.active_tokens()["text_muted"], MONO_FONT_FAMILY
        lines = [
            f"<b>{html.escape(entity.label)}</b>",
            f'<small style="color: {muted}">{entity.semantic_type.value.upper()}</small>',
        ]
        for k, v in entity.properties.items():
            lines.append(
                f'<span style="color: {muted}">{html.escape(str(k))}</span>&nbsp; '
                f'<span style="font-family: \'{mono}\', monospace; font-size: 12px">'
                f'{html.escape(str(v))}</span>'
            )
        self._title.setText("<br>".join(lines))
        self._expand_btn.setVisible(True)

    def clear(self) -> None:
        self._entity_id = None
        self._entity = None
        self._title.setText(self._placeholder())
        self._expand_btn.setVisible(False)

    def refresh_theme(self) -> None:
        if self._entity is not None:
            self.show_entity(self._entity)
        else:
            self._title.setText(self._placeholder())

    def _on_expand(self) -> None:
        if self._entity_id:
            self.expandRequested.emit(self._entity_id)


class MainWindow(QMainWindow):
    def __init__(self, db_path: Optional[Path] = None):
        super().__init__()
        self.setWindowTitle("mDiscovery")
        self.resize(1280, 800)

        self._recent = RecentCases(RECENT_STORE)
        self._workspaces: list[Workspace] = []
        self._active_ws: Optional[Workspace] = None

        self._build_ui()
        self._build_menubar()
        self._build_toolbar()
        self._build_statusbar()

        first = self._add_workspace(Path(db_path or DEFAULT_DB_PATH))
        self._set_active(first)
        self._rebuild_recent_menu()

        # Any focus landing inside a workspace (canvas render widget, header)
        # marks it active — covers pan/zoom/edge-tap gestures that produce no
        # bridge signal, without poking WebEngine internals.
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

    def _on_focus_changed(self, _old, new) -> None:
        widget = new
        while widget is not None:
            if isinstance(widget, Workspace):
                if widget in self._workspaces:
                    self._set_active(widget)
                return
            widget = widget.parentWidget()

    # ── UI assembly ──────────────────────────────────────────────────
    def _build_ui(self) -> None:
        self._split = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self._split)

        self._inspector = EntityInspector()
        self._inspector.expandRequested.connect(self._expand_in_active)
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

        import_json_act = QAction("Import &JSON…", self)
        import_json_act.triggered.connect(self._import_json)
        file_menu.addAction(import_json_act)

        import_anx_act = QAction("Import i2 Chart (AN&X)…", self)
        import_anx_act.triggered.connect(self._import_anx)
        file_menu.addAction(import_anx_act)

        file_menu.addSeparator()
        export_pkg_act = QAction("Export Case &Package…", self)
        export_pkg_act.triggered.connect(self._export_package)
        file_menu.addAction(export_pkg_act)

        import_pkg_act = QAction("Import Case Pac&kage…", self)
        import_pkg_act.triggered.connect(self._import_package)
        file_menu.addAction(import_pkg_act)
        file_menu.addSeparator()

        save_act = QAction("&Save Case As…", self)
        save_act.triggered.connect(self._save_case_as)
        file_menu.addAction(save_act)

        self._recent_menu = file_menu.addMenu("Open &Recent")

        file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        view_menu = self.menuBar().addMenu("&View")
        self._light_act = QAction("&Light Mode", self)
        self._light_act.setCheckable(True)
        self._light_act.setChecked(theme.current_mode() == "light")
        self._light_act.toggled.connect(self._toggle_theme)
        view_menu.addAction(self._light_act)

        ws_menu = self.menuBar().addMenu("&Workspace")
        new_ws_act = QAction("&New Workspace (New Case)…", self)
        new_ws_act.triggered.connect(self._new_workspace_new_case)
        ws_menu.addAction(new_ws_act)
        open_ws_act = QAction("New Workspace (&Open Case)…", self)
        open_ws_act.triggered.connect(self._new_workspace_open_case)
        ws_menu.addAction(open_ws_act)
        close_ws_act = QAction("&Close Workspace", self)
        close_ws_act.triggered.connect(self._close_active_workspace)
        ws_menu.addAction(close_ws_act)
        ws_menu.addSeparator()
        copy_act = QAction("&Copy Selection", self)
        copy_act.setShortcut(QKeySequence("Ctrl+Shift+C"))
        copy_act.triggered.connect(self._copy_selection)
        ws_menu.addAction(copy_act)
        paste_act = QAction("&Paste", self)
        paste_act.setShortcut(QKeySequence("Ctrl+Shift+V"))
        paste_act.triggered.connect(self._paste)
        ws_menu.addAction(paste_act)

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

        add_entity_act = QAction("Add Entity", self)
        add_entity_act.triggered.connect(self._add_entity)
        tb.addAction(add_entity_act)

        add_link_act = QAction("Add Link", self)
        add_link_act.triggered.connect(self._add_link)
        tb.addAction(add_link_act)

        tb.addSeparator()

        for name, label in [
            ("cose", "Force"),
            ("hierarchical", "Hierarchical"),
            ("circular", "Circular"),
            ("grid", "Grid"),
        ]:
            act = QAction(label, self)
            act.triggered.connect(
                lambda _, n=name: self._with_active(lambda ws: ws.graph_view.apply_layout(n)))
            tb.addAction(act)

        tb.addSeparator()

        find_path_act = QAction("Find Path", self)
        find_path_act.triggered.connect(self._open_find_path)
        tb.addAction(find_path_act)

        clear_hl_act = QAction("Clear Highlight", self)
        clear_hl_act.triggered.connect(
            lambda: self._with_active(lambda ws: ws.graph_view.clear_highlight()))
        tb.addAction(clear_hl_act)

        self._size_act = QAction("Size by Degree", self)
        self._size_act.setCheckable(True)
        self._size_act.toggled.connect(self._toggle_degree_sizing)
        tb.addAction(self._size_act)

        self._grid_act = QAction("Grid Snap", self)
        self._grid_act.setCheckable(True)
        self._grid_act.toggled.connect(self._toggle_grid_snap)
        tb.addAction(self._grid_act)

        refresh_act = QAction("Refresh", self)
        refresh_act.triggered.connect(self._refresh_graph)
        tb.addAction(refresh_act)

        # Right-aligned search box.
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search nodes…")
        self._search_edit.setMaximumWidth(220)
        self._search_edit.returnPressed.connect(self._do_search)
        tb.addWidget(self._search_edit)

    def _build_statusbar(self) -> None:
        self._status = QStatusBar()
        self.setStatusBar(self._status)

    # ── Workspace management ─────────────────────────────────────────
    def _add_workspace(self, path: Path) -> Workspace:
        ws = Workspace(path)
        ws.activated.connect(self._set_active)
        ws.nodeSelected.connect(self._on_node_selected)
        ws.nodeDoubleClicked.connect(self._on_node_double_clicked)
        ws.backgroundTapped.connect(self._on_background_tapped)
        ws.closeRequested.connect(self._close_workspace)
        self._workspaces.append(ws)
        self._split.addWidget(ws)
        self._recent.add(ws.db_path)
        self._rebuild_recent_menu()
        self._update_close_buttons()
        return ws

    def _close_workspace(self, ws: Workspace) -> None:
        if len(self._workspaces) <= 1:
            return
        self._workspaces.remove(ws)
        ws.close_db()
        ws.setParent(None)
        ws.deleteLater()
        self._update_close_buttons()
        # The inspector may be showing an entity from the closed case even
        # when that pane wasn't active.
        self._inspector.clear()
        self._rebuild_recent_menu()  # the closed case becomes re-openable
        if self._active_ws is ws:
            self._active_ws = None
            self._set_active(self._workspaces[0])

    def _close_active_workspace(self) -> None:
        if self._active_ws is not None:
            self._close_workspace(self._active_ws)

    def _update_close_buttons(self) -> None:
        many = len(self._workspaces) > 1
        for ws in self._workspaces:
            ws.set_closable(many)

    def _set_active(self, ws: Workspace) -> None:
        if ws is self._active_ws:
            return
        self._active_ws = ws
        for other in self._workspaces:
            other.set_active(other is ws)
        # Reflect per-workspace toggle state without re-triggering the actions.
        self._grid_act.blockSignals(True)
        self._grid_act.setChecked(ws.grid_snap)
        self._grid_act.blockSignals(False)
        self._size_act.blockSignals(True)
        self._size_act.setChecked(ws.degree_sizing)
        self._size_act.blockSignals(False)
        self._inspector.clear()
        self._update_title()
        self._update_status()

    def _with_active(self, fn) -> None:
        if self._active_ws is not None:
            fn(self._active_ws)

    # ── Canvas event handlers ────────────────────────────────────────
    # Liveness guard: bridge/JS events are asynchronous and can arrive after
    # their workspace was closed; a closed pane's repo must not be touched.
    def _ws_alive(self, ws: Workspace) -> bool:
        return ws in self._workspaces

    def _on_node_selected(self, ws: Workspace, node_id: str) -> None:
        if not self._ws_alive(ws):
            return
        entity = ws.repo.entities.get(node_id)
        if entity:
            self._inspector.show_entity(entity)

    def _on_node_double_clicked(self, ws: Workspace, node_id: str) -> None:
        if not self._ws_alive(ws):
            return
        entity = ws.repo.entities.get(node_id)
        if entity is None:
            return
        dlg = DossierDialog(entity, ws.repo, ws.media_dir, self)
        result = dlg.exec()
        if result == DELETED:
            ws.graph_view.remove_element(node_id)
            self._inspector.clear()
            self._update_status()
        elif result:
            updated = dlg.entity
            ws.graph_view.update_node(
                node_id, updated.to_cytoscape()["data"], replace=True)
            self._inspector.show_entity(updated)

    def _on_background_tapped(self, ws: Workspace) -> None:
        if self._ws_alive(ws) and ws is self._active_ws:
            self._inspector.clear()

    def _expand_in_active(self, node_id: str) -> None:
        self._with_active(lambda ws: ws.graph_view.expand_neighbors(node_id))

    # ── Authoring ────────────────────────────────────────────────────
    def _add_entity(self) -> None:
        ws = self._active_ws
        if ws is None:
            return
        dlg = EntityDialog(parent=self)
        if not dlg.exec():
            return
        entity = dlg.result_entity()
        ws.repo.entities.upsert(entity)
        ws.graph_view.add_elements({"nodes": [entity.to_cytoscape()], "edges": []})
        self._update_status()
        self._status.showMessage(f"Added entity “{entity.label}”", 4000)

    def _add_link(self) -> None:
        ws = self._active_ws
        if ws is None:
            return
        if ws.repo.entities.count() < 2:
            QMessageBox.information(
                self, "Add link", "Need at least two entities to create a link.")
            return
        dlg = LinkDialog(ws.repo, self)
        if not dlg.exec():
            return
        link = dlg.result_link()
        ws.repo.links.upsert(link)
        ws.graph_view.add_elements({"nodes": [], "edges": [link.to_cytoscape()]})
        self._update_status()
        self._status.showMessage(f"Added link “{link.link_type}”", 4000)

    # ── Copy / paste between workspaces ──────────────────────────────
    def _copy_selection(self) -> None:
        ws = self._active_ws
        if ws is None:
            return

        def on_ids(ids: list) -> None:
            if not self._ws_alive(ws):
                return  # workspace closed while the JS callback was in flight
            if not ids:
                self._status.showMessage("Nothing selected to copy", 4000)
                return
            wanted = set(ids)
            entities = [e for e in (ws.repo.entities.get(i) for i in ids) if e]
            links = [l for l in ws.repo.links.all()
                     if l.source_id in wanted and l.target_id in wanted]
            QApplication.clipboard().setText(to_json(entities, links))
            self._status.showMessage(
                f"Copied {len(entities)} entit{'ies' if len(entities) != 1 else 'y'}"
                f" · {len(links)} links", 4000)

        ws.graph_view.get_selected_nodes(on_ids)

    def _paste(self) -> None:
        ws = self._active_ws
        if ws is None:
            return
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        try:
            entities, links = parse_node_link_text(text)
        except ValueError as exc:
            self._status.showMessage(f"Clipboard is not a chart payload: {exc}", 5000)
            return
        # Never clobber: entities already in the target keep their stored
        # state (pasting must not silently revert edits made since the copy).
        existing = ws.repo.entities.all_ids()
        new_entities = [e for e in entities if e.id not in existing]
        skipped = len(entities) - len(new_entities)
        ws.repo.bulk_upsert(new_entities, links)  # existing links skip, as before
        ws.graph_view.add_elements({
            "nodes": [e.to_cytoscape() for e in entities],
            "edges": [l.to_cytoscape() for l in links],
        })
        self._update_status()
        message = f"Pasted {len(new_entities)} entities · {len(links)} links"
        if skipped:
            message += f" ({skipped} already present, left unchanged)"
        self._status.showMessage(message, 4000)

    # ── Theme ────────────────────────────────────────────────────────
    def _toggle_theme(self, light: bool) -> None:
        apply_theme(QApplication.instance(), "light" if light else "dark")
        for ws in self._workspaces:
            ws.refresh_theme()
        self._inspector.refresh_theme()

    # ── Toggles routed to the active workspace ───────────────────────
    def _toggle_degree_sizing(self, enabled: bool) -> None:
        self._with_active(lambda ws: ws.set_degree_sizing(enabled))

    def _toggle_grid_snap(self, enabled: bool) -> None:
        self._with_active(lambda ws: ws.set_grid_snap(enabled))

    # ── Case file management (active workspace) ──────────────────────
    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        open_paths = {ws.db_path for ws in self._workspaces}
        cases = [p for p in self._recent.existing() if p not in open_paths]
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
        for ws in self._workspaces:
            self._recent.add(ws.db_path)
        self._rebuild_recent_menu()

    def _update_title(self) -> None:
        name = self._active_ws.db_path.name if self._active_ws else ""
        self.setWindowTitle(f"mDiscovery — {name}")

    def _switch_case(self, path: Path) -> None:
        """Open ``path`` in the active workspace, keeping the case on failure."""
        ws = self._active_ws
        if ws is None:
            return
        try:
            ws.switch_case(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "Could not open case", str(exc))
            return
        self._inspector.clear()
        self._recent.add(ws.db_path)
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
        start_dir = str(self._active_ws.db_path.parent) if self._active_ws else ""
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open case", start_dir, _CASE_FILTER,
        )
        if path_str:
            self._switch_case(Path(path_str))

    def _save_case_as(self) -> None:
        ws = self._active_ws
        if ws is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save case as", "case-copy.kuzu", _CASE_FILTER,
        )
        if not path_str:
            return
        try:
            copy_case(ws.db_path, path_str, overwrite=True)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self._switch_case(Path(path_str))  # continue working in the saved copy

    def _new_workspace_new_case(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self, "New case for workspace", "case.kuzu", _CASE_FILTER,
        )
        if not path_str:
            return
        if Path(path_str).exists():
            QMessageBox.warning(
                self, "Path exists",
                "Choose a path that doesn't exist yet for a new case.",
            )
            return
        self._open_workspace(Path(path_str))

    def _new_workspace_open_case(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open case in new workspace", "", _CASE_FILTER,
        )
        if path_str:
            self._open_workspace(Path(path_str))

    def _open_workspace(self, path: Path) -> None:
        try:
            ws = self._add_workspace(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not open workspace", str(exc))
            return
        self._set_active(ws)

    # ── Import / export / analysis (active workspace) ────────────────
    def _open_import(self) -> None:
        ws = self._active_ws
        if ws is None:
            return
        dlg = ImportDialog(ws.repo, self)
        if dlg.exec():
            self._refresh_graph()

    def _import_json(self) -> None:
        ws = self._active_ws
        if ws is None:
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Import node-link JSON", "", "JSON files (*.json);;All files (*)",
        )
        if not path_str:
            return
        try:
            entities, links = load_node_link_json(path_str)
        except Exception as exc:
            QMessageBox.critical(self, "Import error", str(exc))
            return
        ws.repo.bulk_upsert(entities, links)
        self._refresh_graph()
        self._status.showMessage(
            f"Imported {len(entities)} entities · {len(links)} links from JSON", 5000
        )

    def _import_anx(self) -> None:
        ws = self._active_ws
        if ws is None:
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Import i2 chart", "", "i2 Chart XML (*.anx *.xml);;All files (*)",
        )
        if not path_str:
            return
        try:
            entities, links = load_anx(path_str)
        except Exception as exc:
            QMessageBox.critical(self, "Import error", str(exc))
            return
        ws.repo.bulk_upsert(entities, links)
        self._refresh_graph()
        self._status.showMessage(
            f"Imported {len(entities)} entities · {len(links)} links from ANX", 5000
        )

    def _export_package(self) -> None:
        ws = self._active_ws
        if ws is None:
            return
        if ws.repo.entities.count() == 0:
            QMessageBox.information(
                self, "Nothing to package", "The graph is empty.")
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export case package",
            ws.db_path.stem + casepack.EXTENSION, _PACKAGE_FILTER,
        )
        if not path_str:
            return

        def do_write() -> None:
            if not self._ws_alive(ws):
                return
            try:
                written = casepack.write_package(
                    path_str, ws.repo.entities.all(), ws.repo.links.all())
            except Exception as exc:
                QMessageBox.critical(self, "Package export failed", str(exc))
                return
            self._status.showMessage(f"Exported package → {written.name}", 5000)

        # Sweep current canvas coordinates into the store first, so charts
        # arranged only by automatic layout still ship with their layout.
        ws.graph_view.capture_positions(do_write)

    def _import_package(self) -> None:
        ws = self._active_ws
        if ws is None:
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Import case package", "", _PACKAGE_FILTER,
        )
        if not path_str:
            return
        try:
            _manifest, entities, links = casepack.read_package(
                path_str, media_dir=ws.media_dir)
        except Exception as exc:
            QMessageBox.critical(self, "Package import failed", str(exc))
            return
        ws.repo.bulk_upsert(entities, links)
        self._refresh_graph()
        self._status.showMessage(
            f"Imported package: {len(entities)} entities · {len(links)} links", 5000
        )

    def _open_export(self) -> None:
        ws = self._active_ws
        if ws is None:
            return
        if ws.repo.entities.count() == 0:
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
            written = write_export(ws.repo, path_str, fmt)
        except Exception as exc:  # surface failures instead of crashing the UI
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        names = "\n".join(p.name for p in written)
        self._status.showMessage(f"Exported {fmt.value} → {names}", 5000)

    def _open_find_path(self) -> None:
        ws = self._active_ws
        if ws is None:
            return
        if ws.repo.entities.count() < 2:
            QMessageBox.information(
                self, "Find path", "Need at least two entities to find a path."
            )
            return
        dlg = FindPathDialog(ws.repo, self)
        if dlg.exec() and dlg.path:
            ws.graph_view.highlight_path(dlg.path)
            self._status.showMessage(f"Path found: {len(dlg.path)} nodes", 5000)

    def _do_search(self) -> None:
        """Search the active workspace's repository and locate matches."""
        ws = self._active_ws
        query = self._search_edit.text().strip()
        if ws is None or not query:
            return
        matches = ws.repo.entities.search(query)
        if matches:
            ws.graph_view.locate_nodes([e.id for e in matches])
            self._status.showMessage(
                f"{len(matches)} match{'es' if len(matches) != 1 else ''} for “{query}”", 5000
            )
        else:
            self._status.showMessage(f"No matches for “{query}”", 5000)

    def _refresh_graph(self) -> None:
        self._with_active(lambda ws: ws.refresh())
        self._update_status()

    def _update_status(self) -> None:
        if self._active_ws is None:
            return
        stats = self._active_ws.repo.stats()
        self._status.showMessage(
            f"{stats['entity_count']} entities · {stats['link_count']} links"
        )

    def closeEvent(self, event) -> None:
        for ws in self._workspaces:
            ws.close_db()
        super().closeEvent(event)
