"""AS-30 + AS-31: Graph visualization via Cytoscape.js embedded in a PyQt6 WebEngine view.

Decision: Cytoscape.js via QWebEngineView.
Pros: rich layout ecosystem, battle-tested graph UX, maintains the all-Python app shell.
QWebChannel bridges JS ↔ Python for node selection and command dispatch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from ..graph.repository import GraphRepository

# graph_view.py lives at <root>/src/mdiscovery/viz/ — parents[3] is <root>.
ASSETS_DIR = Path(__file__).resolve().parents[3] / "assets" / "cytoscape"


class PythonBridge(QObject):
    """Exposed to JS as `pybridge`. Handles JS → Python signals."""

    nodeSelectedSignal = pyqtSignal(str)
    backgroundTappedSignal = pyqtSignal()
    viewReadySignal = pyqtSignal()

    @pyqtSlot(str)
    def nodeSelected(self, node_id: str) -> None:
        self.nodeSelectedSignal.emit(node_id)

    @pyqtSlot()
    def backgroundTapped(self) -> None:
        self.backgroundTappedSignal.emit()

    @pyqtSlot()
    def viewReady(self) -> None:
        self.viewReadySignal.emit()


class GraphView(QWidget):
    """Cytoscape.js graph embedded in a PyQt6 WebEngine widget."""

    nodeSelected = pyqtSignal(str)
    backgroundTapped = pyqtSignal()

    def __init__(self, repo: Optional[GraphRepository] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._repo = repo
        self._ready = False
        self._pending_graph: Optional[dict] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._web = QWebEngineView()
        layout.addWidget(self._web)

        self._channel = QWebChannel()
        self._bridge = PythonBridge()
        self._channel.registerObject("pybridge", self._bridge)
        self._web.page().setWebChannel(self._channel)

        self._bridge.nodeSelectedSignal.connect(self.nodeSelected)
        self._bridge.backgroundTappedSignal.connect(self.backgroundTapped)
        self._bridge.viewReadySignal.connect(self._on_view_ready)
        self._web.loadFinished.connect(self._on_load_finished)

        self._load_html()

    def _load_html(self) -> None:
        html_path = ASSETS_DIR / "graph.html"
        if html_path.exists():
            self._web.setUrl(QUrl.fromLocalFile(str(html_path)))
        else:
            self._web.setHtml("<body style='background:#1E1F22;color:#DFE1E5'>graph.html not found</body>")

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
        if self._pending_graph is not None:
            self._push_graph(self._pending_graph)
            self._pending_graph = None

    def load_from_repo(self) -> None:
        if self._repo is None:
            return
        graph_json = self._repo.get_graph_json()
        if self._ready:
            self._push_graph(graph_json)
        else:
            self._pending_graph = graph_json

    def _push_graph(self, graph_json: dict) -> None:
        self._run_js("window.loadGraph", graph_json)

    def _run_js(self, fn: str, *args) -> None:
        """Invoke a JS API function with arguments serialized via json.dumps.

        json.dumps (not repr) is the only safe way to embed Python values in a
        script string — labels and queries are user data.
        """
        payload = ", ".join(json.dumps(a) for a in args)
        self._web.page().runJavaScript(f"{fn}({payload})")

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

    def set_degree_sizing(self, enabled: bool) -> None:
        """Toggle conditional formatting: node size scaled by degree."""
        self._run_js("window.setDegreeSizing", bool(enabled))

    def set_repo(self, repo: GraphRepository) -> None:
        self._repo = repo
