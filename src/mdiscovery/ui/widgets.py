"""Small shared UI widgets for the authoring dialogs and dossier."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..graph.models import Entity, SemanticType
from ..icons import ICONS

AUTO_ICON_LABEL = "(default for type)"


def type_combo(selected: SemanticType = SemanticType.UNKNOWN) -> QComboBox:
    combo = QComboBox()
    for stype in SemanticType:
        combo.addItem(stype.value, stype.value)
    combo.setCurrentIndex(combo.findData(selected.value))
    return combo


def icon_combo(selected: str = "") -> QComboBox:
    combo = QComboBox()
    combo.addItem(AUTO_ICON_LABEL, "")
    for display, stem in ICONS.items():
        combo.addItem(display, stem)
    if selected:
        index = combo.findData(selected)
        if index >= 0:
            combo.setCurrentIndex(index)
    return combo


class EntityPicker(QComboBox):
    """Editable entity combo with type-ahead and safe typed-text resolution.

    ``selected_id`` trusts ``currentIndex`` only while the visible text still
    matches that row — an editable combo keeps its old index when the user
    types over the selection, which previously resolved to the wrong entity.
    """

    def __init__(self, entities: Iterable[Entity],
                 preselect_id: Optional[str] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        for entity in sorted(entities, key=lambda e: e.label.lower()):
            self.addItem(f"{entity.label}  ·  {entity.semantic_type.value}", entity.id)
        if preselect_id is not None:
            self.setCurrentIndex(self.findData(preselect_id))
        else:
            self.setCurrentIndex(-1)

    def selected_id(self) -> Optional[str]:
        text = self.currentText().strip()
        idx = self.currentIndex()
        if idx >= 0 and self.itemText(idx).strip() == text:
            return self.itemData(idx)
        match = self.findText(text, Qt.MatchFlag.MatchFixedString)
        return self.itemData(match) if match >= 0 else None


class PropertiesTable(QWidget):
    """Editable key/value table — lets the user define arbitrary fields."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Property", "Value"])
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Add")
        remove_btn = QPushButton("Remove")
        add_btn.clicked.connect(self._add_row)
        remove_btn.clicked.connect(self._remove_selected)
        buttons.addWidget(add_btn)
        buttons.addWidget(remove_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

    def _add_row(self) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(""))
        self._table.setItem(row, 1, QTableWidgetItem(""))
        self._table.editItem(self._table.item(row, 0))

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._table.removeRow(row)

    def set_properties(self, properties: dict[str, Any]) -> None:
        self._table.setRowCount(0)
        for key, value in properties.items():
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(str(key)))
            self._table.setItem(row, 1, QTableWidgetItem(str(value)))

    def properties(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for row in range(self._table.rowCount()):
            key_item = self._table.item(row, 0)
            value_item = self._table.item(row, 1)
            key = (key_item.text() if key_item else "").strip()
            if key:
                out[key] = (value_item.text() if value_item else "").strip()
        return out
