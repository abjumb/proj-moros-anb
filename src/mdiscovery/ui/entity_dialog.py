"""Manual chart authoring — create/edit entities and links from nothing.

Charts can start from zero inputs, so every field is user-definable here:
label, type, icon, direction, strength/confidence, and arbitrary properties.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QLineEdit, QVBoxLayout, QWidget,
)

from ..graph.models import Entity, Link, LinkDirection, SemanticType
from ..graph.repository import GraphRepository
from ..icons import ICONS
from .widgets import PropertiesTable

_AUTO_ICON = "(default for type)"


def _icon_combo(selected: str = "") -> QComboBox:
    combo = QComboBox()
    combo.addItem(_AUTO_ICON, "")
    for display, stem in ICONS.items():
        combo.addItem(display, stem)
    if selected:
        index = combo.findData(selected)
        if index >= 0:
            combo.setCurrentIndex(index)
    return combo


def _type_combo(selected: SemanticType = SemanticType.UNKNOWN) -> QComboBox:
    combo = QComboBox()
    for stype in SemanticType:
        combo.addItem(stype.value, stype.value)
    combo.setCurrentIndex(combo.findData(selected.value))
    return combo


class EntityDialog(QDialog):
    """Create or edit a single entity, every field user-defined."""

    def __init__(self, entity: Optional[Entity] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._entity = entity
        self.setWindowTitle("Edit Entity" if entity else "New Entity")
        self.resize(440, 460)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._label_edit = QLineEdit(entity.label if entity else "")
        self._type_combo = _type_combo(entity.semantic_type if entity else SemanticType.UNKNOWN)
        self._icon_combo = _icon_combo(entity.icon if entity else "")
        form.addRow("Label:", self._label_edit)
        form.addRow("Type:", self._type_combo)
        form.addRow("Icon:", self._icon_combo)
        layout.addLayout(form)

        props_box = QGroupBox("Properties")
        props_layout = QVBoxLayout(props_box)
        self._props = PropertiesTable()
        if entity:
            self._props.set_properties(entity.properties)
        props_layout.addWidget(self._props)
        layout.addWidget(props_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self._label_edit.text().strip():
            self._label_edit.setFocus()
            return
        self.accept()

    def result_entity(self) -> Entity:
        """The entity as defined in the dialog (existing id/style preserved)."""
        base = self._entity
        entity = Entity(
            label=self._label_edit.text().strip(),
            semantic_type=SemanticType(self._type_combo.currentData()),
            icon=self._icon_combo.currentData() or "",
            properties=self._props.properties(),
        )
        if base is not None:
            entity.id = base.id
            entity.style = base.style
        return entity


class LinkDialog(QDialog):
    """Create a link between two entities, every field user-defined."""

    def __init__(self, repo: GraphRepository, parent: Optional[QWidget] = None,
                 source_id: Optional[str] = None):
        super().__init__(parent)
        self._repo = repo
        self.setWindowTitle("New Link")
        self.resize(440, 420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._source = self._entity_combo(source_id)
        self._target = self._entity_combo(None)
        self._type_edit = QLineEdit("relates_to")
        self._direction = QComboBox()
        for direction in LinkDirection:
            self._direction.addItem(direction.value, direction.value)
        self._strength = QDoubleSpinBox()
        self._strength.setRange(0.1, 5.0)
        self._strength.setSingleStep(0.1)
        self._strength.setValue(1.0)
        self._confidence = QDoubleSpinBox()
        self._confidence.setRange(0.0, 1.0)
        self._confidence.setSingleStep(0.05)
        self._confidence.setValue(1.0)

        form.addRow("From:", self._source)
        form.addRow("To:", self._target)
        form.addRow("Label / type:", self._type_edit)
        form.addRow("Direction:", self._direction)
        form.addRow("Strength:", self._strength)
        form.addRow("Confidence:", self._confidence)
        layout.addLayout(form)

        props_box = QGroupBox("Properties")
        props_layout = QVBoxLayout(props_box)
        self._props = PropertiesTable()
        props_layout.addWidget(self._props)
        layout.addWidget(props_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _entity_combo(self, preselect_id: Optional[str]) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        for entity in sorted(self._repo.entities.all(), key=lambda e: e.label.lower()):
            combo.addItem(f"{entity.label}  ·  {entity.semantic_type.value}", entity.id)
        if preselect_id is not None:
            index = combo.findData(preselect_id)
            combo.setCurrentIndex(index)
        else:
            combo.setCurrentIndex(-1)
        return combo

    def _selected_id(self, combo: QComboBox) -> Optional[str]:
        idx = combo.currentIndex()
        if idx >= 0:
            return combo.itemData(idx)
        match = combo.findText(combo.currentText().strip(),
                               Qt.MatchFlag.MatchFixedString)
        return combo.itemData(match) if match >= 0 else None

    def _on_accept(self) -> None:
        src, tgt = self._selected_id(self._source), self._selected_id(self._target)
        if not src or not tgt or src == tgt:
            return
        self.accept()

    def result_link(self) -> Link:
        return Link(
            source_id=self._selected_id(self._source),
            target_id=self._selected_id(self._target),
            link_type=self._type_edit.text().strip() or "relates_to",
            direction=LinkDirection(self._direction.currentData()),
            strength=self._strength.value(),
            confidence=self._confidence.value(),
            properties=self._props.properties(),
        )
