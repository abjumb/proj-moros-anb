"""AS-30 + AS-31: Graph visualization via Cytoscape.js embedded in a PyQt6 WebEngine view.

Decision: Cytoscape.js via QWebEngineView.
Pros: rich layout ecosystem, battle-tested graph UX, maintains the all-Python app shell.
QWebChannel bridges JS ↔ Python for node selection and command dispatch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QMessageBox, QWidget, QVBoxLayout

from ..graph.repository import GraphRepository
from ..icons import DEFAULT_TYPE_ICONS, colored_svg, load_icon_svgs
from ..resources import CYTOSCAPE_DIR
from ..ui import theme

# Resolved per deployment shape (dev checkout / PyInstaller) in resources.py.
ASSETS_DIR = CYTOSCAPE_DIR

# Above this many entities, drawing the whole graph at once can freeze the
# WebEngine renderer (and on low-memory boxes get it OOM-killed). We warn and
# let the user decide to wait, rather than silently hanging or crashing.
LARGE_GRAPH_WARN = 5000


class PythonBridge(QObject):
    """Exposed to JS as `pybridge`. Handles JS → Python signals."""

    nodeSelectedSignal = pyqtSignal(str)
    nodeDoubleClickedSignal = pyqtSignal(str)
    backgroundTappedSignal = pyqtSignal()
    linkRenamedSignal = pyqtSignal(str, str)
    nodesMovedSignal = pyqtSignal(str)
    viewReadySignal = pyqtSignal()

    @pyqtSlot(str)
    def nodeSelected(self, node_id: str) -> None:
        self.nodeSelectedSignal.emit(node_id)

    @pyqtSlot(str)
    def nodeDoubleClicked(self, node_id: str) -> None:
        self.nodeDoubleClickedSignal.emit(node_id)

    @pyqtSlot()
    def backgroundTapped(self) -> None:
        self.backgroundTappedSignal.emit()

    @pyqtSlot(str, str)
    def linkRenamed(self, link_id: str, new_label: str) -> None:
        self.linkRenamedSignal.emit(link_id, new_label)

    @pyqtSlot(str)
    def nodesMoved(self, payload_json: str) -> None:
        self.nodesMovedSignal.emit(payload_json)

    @pyqtSlot()
    def viewReady(self) -> None:
        self.viewReadySignal.emit()


class GraphView(QWidget):
    """Cytoscape.js graph embedded in a PyQt6 WebEngine widget."""

    nodeSelected = pyqtSignal(str)
    nodeDoubleClicked = pyqtSignal(str)
    backgroundTapped = pyqtSignal()

    def __init__(self, repo: Optional[GraphRepository] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._repo = repo
        self._ready = False
        self._pending_graph: Optional[dict] = None
        self._pending_message: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._web = QWebEngineView()
        layout.addWidget(self._web)

        self._channel = QWebChannel()
        self._bridge = PythonBridge()
        self._channel.registerObject("pybridge", self._bridge)
        self._web.page().setWebChannel(self._channel)

        self._bridge.nodeSelectedSignal.connect(self.nodeSelected)
        self._bridge.nodeDoubleClickedSignal.connect(self.nodeDoubleClicked)
        self._bridge.backgroundTappedSignal.connect(self.backgroundTapped)
        self._bridge.linkRenamedSignal.connect(self._on_link_renamed)
        self._bridge.nodesMovedSignal.connect(self._on_nodes_moved)
        self._bridge.viewReadySignal.connect(self._on_view_ready)
        self._web.loadFinished.connect(self._on_load_finished)
        # Turn a renderer crash (OOM on a huge graph, GPU/GBM failure) into a
        # readable message instead of a silent blank canvas.
        self._web.page().renderProcessTerminated.connect(self._on_render_terminated)

        self._load_html()

    def _load_html(self) -> None:
        html_path = ASSETS_DIR / "graph.html"
        if html_path.exists():
            self._web.setUrl(QUrl.fromLocalFile(str(html_path)))
        else:
            t = theme.active_tokens()
            self._web.setHtml(
                f"<body style='background:{t['bg_window']};color:{t['text']}'>"
                "graph.html not found</body>"
            )

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        # Inject qwebchannel.js via page API (it's built into QtWebEngine)
        self._web.page().runJavaScript(
            "if(typeof QWebChannel === 'undefined') {"
            "  let s = document.createElement('script');"
            "  s.src = 'qrc:///qtwebchannel/qwebchannel.js';"
            "  s.onload = () => initChannel();"
            "  document.head.appendChild(s);"
            "} else { initChannel(); }"
        )

    def _on_view_ready(self) -> None:
        self._ready = True
        self.apply_theme()
        if self._pending_graph is not None:
            self._push_graph(self._pending_graph)
            self._pending_graph = None
        if self._pending_message is not None:
            self._run_js("window.showMessage", self._pending_message)
            self._pending_message = None

    def _on_link_renamed(self, link_id: str, new_label: str) -> None:
        """Persist a canvas-side link rename (the edge label is the link type)."""
        if self._repo is not None:
            self._repo.links.update_fields(link_id, link_type=new_label)

    def _on_nodes_moved(self, payload_json: str) -> None:
        """Persist dragged node positions into each entity's style (x/y)."""
        if self._repo is None:
            return
        try:
            moves = json.loads(payload_json)
        except ValueError:
            return
        entities = []
        for move in moves:
            entity = self._repo.entities.get(move.get("id", ""))
            if entity is None:
                continue
            entity.style = dict(entity.style)
            entity.style["x"] = round(float(move["x"]), 2)
            entity.style["y"] = round(float(move["y"]), 2)
            entities.append(entity)
        if entities:
            self._repo.entities.upsert_batch(entities)

    def capture_positions(self, callback: Callable[[], None]) -> None:
        """Pull every node's current position into the store, then call back.

        Drag capture covers user-arranged nodes; this sweep also captures
        coordinates produced by automatic layout runs (used before package
        export so a never-touched chart still ships with its layout).
        """
        def on_positions(positions) -> None:
            if positions and self._repo is not None:
                payload = [{"id": nid, "x": p["x"], "y": p["y"]}
                           for nid, p in positions.items()]
                self._on_nodes_moved(json.dumps(payload))
            callback()

        self._web.page().runJavaScript("window.getNodePositions()", on_positions)

    def load_from_repo(self) -> None:
        if self._repo is None:
            return
        # Cheap COUNT first — don't materialize a huge graph just to find out
        # it's huge. Warn before the heavy get_graph_json()/render.
        count = self._repo.entities.count()
        if count > LARGE_GRAPH_WARN and not self._confirm_large_render(count):
            self._show_skipped(count)
            return
        graph_json = self._repo.get_graph_json()
        if self._ready:
            self._push_graph(graph_json)
        else:
            self._pending_graph = graph_json

    def _confirm_large_render(self, count: int) -> bool:
        """Warn that rendering a large case may freeze; return True to proceed."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Large case")
        box.setText(f"This case has {count:,} entities.")
        box.setInformativeText(
            "Drawing the whole chart at once can make the app appear frozen "
            "while it lays out and renders — this is normal; let the analysis "
            "finish.\n\nRender the full chart now, or skip it and use Search / "
            "Expand neighbors to pull in just the parts you need?")
        render_btn = box.addButton("Render anyway", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Skip for now", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(render_btn)
        box.exec()
        return box.clickedButton() is render_btn

    def _show_skipped(self, count: int) -> None:
        """Placeholder shown when the user declines the big render."""
        message = (
            f"{count:,} entities — render skipped to keep the app responsive. "
            "Click Refresh on the toolbar to draw the full chart.")
        self._pending_graph = None
        if self._ready:
            self._run_js("window.showMessage", message)
        else:
            self._pending_message = message

    def _on_render_terminated(self, status, exit_code) -> None:
        """Renderer process died (OOM / GPU). Show guidance, not a blank page."""
        t = theme.active_tokens()
        msg = (
            "The graph view stopped unexpectedly — usually too many items to "
            "draw at once, or a graphics-driver issue. Open a smaller case or "
            "use Search/Expand to load less at a time. On Linux you can also "
            "launch with MDISCOVERY_SOFTWARE_RENDER=1 for software rendering."
        )
        self._web.setHtml(
            f"<body style='margin:0;background:{t['bg_window']};color:{t['text']};"
            "font:14px Inter,system-ui,sans-serif;display:flex;align-items:center;"
            "justify-content:center;height:100vh'>"
            f"<div style='max-width:520px;padding:24px;text-align:center;"
            f"border:1px solid {t['border']};border-radius:8px'>"
            f"<div style='font-size:15px;font-weight:600;margin-bottom:8px'>"
            "Graph view crashed</div>"
            f"<div style='color:{t['text_muted']};line-height:1.5'>{msg}</div></div></body>"
        )
        self._ready = False

    def _push_graph(self, graph_json: dict) -> None:
        self._run_js("window.loadGraph", graph_json)

    def _run_js(self, fn: str, *args) -> None:
        """Invoke a JS API function with arguments serialized via json.dumps.

        json.dumps (not repr) is the only safe way to embed Python values in a
        script string — labels and queries are user data.
        """
        payload = ", ".join(json.dumps(a) for a in args)
        self._web.page().runJavaScript(f"{fn}({payload})")

    def apply_theme(self) -> None:
        """Push the active palette and a re-colored icon library to the canvas."""
        self._run_js("window.setTheme", theme.canvas_theme())
        icon_color = theme.active_tokens()["text"]
        svgs = {stem: colored_svg(stem, icon_color) for stem in load_icon_svgs()}
        defaults = {st.value: stem for st, stem in DEFAULT_TYPE_ICONS.items()}
        self._run_js("window.setIconLibrary", svgs, defaults)

    def apply_layout(self, name: str) -> None:
        """name: 'cose' | 'hierarchical' | 'circular' | 'grid'"""
        self._run_js("window.applyLayout", name)

    def highlight_path(self, node_ids: list[str]) -> None:
        self._run_js("window.highlightPath", node_ids)

    def clear_highlight(self) -> None:
        self._web.page().runJavaScript("window.clearHighlight()")

    def locate_nodes(self, node_ids: list[str]) -> None:
        """Select and zoom to the given nodes (repo-backed search results)."""
        self._run_js("window.selectAndFit", node_ids)

    def expand_neighbors(self, node_id: str) -> None:
        """Pull the entity's neighborhood from the store and add it to the canvas.

        Previously this only un-faded already-loaded elements; now it fetches
        neighbors + incident links from the repository so expansion works when
        the canvas holds a partial graph.
        """
        if self._repo is not None:
            elements = self._repo.neighborhood(node_id)
            self._run_js("window.addElements", elements, node_id)
        self._run_js("window.expandNeighbors", node_id)

    def add_elements(self, elements: dict, anchor_id: Optional[str] = None) -> None:
        """Incrementally add a node-link payload without relayouting the canvas."""
        self._run_js("window.addElements", elements, anchor_id)

    def update_node(self, node_id: str, data: dict, replace: bool = False) -> None:
        """Update an on-canvas node's data without reloading the graph.

        ``replace=True`` also drops keys missing from ``data`` (removed photo,
        deleted properties) instead of merging.
        """
        self._run_js("window.updateNodeData", node_id, data, bool(replace))

    def remove_element(self, element_id: str) -> None:
        self._run_js("window.removeElement", element_id)

    def set_degree_sizing(self, enabled: bool) -> None:
        """Toggle conditional formatting: node size scaled by degree."""
        self._run_js("window.setDegreeSizing", bool(enabled))

    def set_grid_snap(self, enabled: bool, step: int = 40) -> None:
        """Grid-block movement (snap on drop) vs free-flow canvas."""
        self._run_js("window.setGridSnap", bool(enabled), int(step))

    def get_selected_nodes(self, callback: Callable[[list], None]) -> None:
        """Async: fetch selected node ids from the canvas, then call ``callback``."""
        self._web.page().runJavaScript(
            "window.getSelectedNodes()", lambda ids: callback(ids or [])
        )

    def set_repo(self, repo: Optional[GraphRepository]) -> None:
        """Bind a repository (or None to detach, e.g. while closing a case)."""
        self._repo = repo
