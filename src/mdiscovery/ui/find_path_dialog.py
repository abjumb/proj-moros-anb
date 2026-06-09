"""Find-shortest-path dialog — pick two entities, resolve a path via the repository."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QWidget,
)

from ..graph.repository import GraphRepository


class FindPathDialog(QDialog):
    """Two entity pickers + a result. ``path`` holds the resolved id list on accept."""

    def __init__(self, repo: GraphRepository, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Find Path")
        self._repo = repo
        self.path: list[str] = []

        self._source = self._entity_combo()
        self._target = self._entity_combo()
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

    def _entity_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        for entity in sorted(self._repo.entities.all(), key=lambda e: e.label.lower()):
            combo.addItem(f"{entity.label}  ·  {entity.semantic_type.value}", entity.id)
        combo.setCurrentIndex(-1)
        return combo

    def _selected_id(self, combo: QComboBox) -> Optional[str]:
        # Prefer the data of the chosen row; fall back to matching typed text.
        idx = combo.currentIndex()
        if idx >= 0:
            return combo.itemData(idx)
        text = combo.currentText().strip()
        match = combo.findText(text, Qt.MatchFlag.MatchFixedString)
        return combo.itemData(match) if match >= 0 else None

    def _on_find(self) -> None:
        src = self._selected_id(self._source)
        tgt = self._selected_id(self._target)
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
