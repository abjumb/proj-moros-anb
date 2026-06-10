"""Find-shortest-path dialog — pick two entities, resolve a path via the repository."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QWidget

from ..graph.repository import GraphRepository
from .widgets import EntityPicker


class FindPathDialog(QDialog):
    """Two entity pickers + a result. ``path`` holds the resolved id list on accept."""

    def __init__(self, repo: GraphRepository, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Find Path")
        self._repo = repo
        self.path: list[str] = []

        entities = repo.entities.all()  # fetched once, shared by both pickers
        self._source = EntityPicker(entities)
        self._target = EntityPicker(entities)
        self._message = QLabel("")
        self._message.setWordWrap(True)

        form = QFormLayout(self)
        form.addRow("From:", self._source)
        form.addRow("To:", self._target)
        form.addRow(self._message)

        buttons = QDialogButtonBox()
        self._find_btn = buttons.addButton("Find", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_find)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_find(self) -> None:
        src = self._source.selected_id()
        tgt = self._target.selected_id()
        if not src or not tgt:
            self._message.setText("Pick both a source and a target entity.")
            return
        if src == tgt:
            self._message.setText("Source and target are the same entity.")
            return
        path = self._repo.find_path(src, tgt)
        if not path:
            self._message.setText("No path connects those entities.")
            return
        self.path = path
        self.accept()
