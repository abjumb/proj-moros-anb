"""AS-12 + AS-13: Simple Mode and Advanced Mode import dialog.

Simple Mode: non-technical user maps a CSV column to entity labels and sees
a 50-row live preview before committing.

Advanced Mode: power user maps every column to a precise entity/link attribute
with full control; preview reflects choices.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QComboBox, QLineEdit, QPushButton, QSizePolicy, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QMessageBox, QGroupBox, QScrollArea,
)

from ..graph.models import SemanticType, LinkDirection
from ..graph.repository import GraphRepository
from ..importer.ingestion import IngestionService, StagedDataset
from ..importer.pipeline import (
    ColumnMapping, ImportMapping, ImportPipeline, CommitPreview,
)

ROLE_OPTIONS = [
    ("entity_label", "Entity label"),
    ("entity_attr",  "Entity attribute"),
    ("link_source",  "Link — source"),
    ("link_target",  "Link — target"),
    ("link_type",    "Link — type"),
    ("skip",         "Skip"),
]

STYPE_OPTIONS = [(s.value, s.value) for s in SemanticType]


# ──────────────────────────────────────────────────────────────────────
# Simple Mode tab (AS-12)
# ──────────────────────────────────────────────────────────────────────

class SimpleModeTab(QWidget):
    """Everyday-user import view.

    Left side: file picker + column selector + semantic type.
    Right side: 50-row live preview table with label column highlighted.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._dataset: Optional[StagedDataset] = None
        self._label_col: Optional[str] = None
        self._stype = SemanticType.UNKNOWN
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # File row
        file_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Select a CSV or XLSX file…")
        self._path_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        file_row.addWidget(self._path_edit)
        file_row.addWidget(browse_btn)
        root.addLayout(file_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left panel ─────────────────────────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)

        grp = QGroupBox("Column mapping")
        grp_layout = QVBoxLayout(grp)

        grp_layout.addWidget(QLabel("Label column:"))
        self._col_combo = QComboBox()
        self._col_combo.currentTextChanged.connect(self._on_col_changed)
        grp_layout.addWidget(self._col_combo)

        grp_layout.addWidget(QLabel("Semantic type:"))
        self._stype_combo = QComboBox()
        for val, label in STYPE_OPTIONS:
            self._stype_combo.addItem(label, val)
        self._stype_combo.currentIndexChanged.connect(self._on_stype_changed)
        grp_layout.addWidget(self._stype_combo)

        left_layout.addWidget(grp)
        left_layout.addStretch()
        splitter.addWidget(left)

        # ── Right panel: live preview ───────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Preview (first 50 rows):"))
        self._preview_table = QTableWidget()
        self._preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._preview_table.setAlternatingRowColors(True)
        right_layout.addWidget(self._preview_table)
        splitter.addWidget(right)

        splitter.setSizes([250, 600])
        root.addWidget(splitter)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open data file", "",
            "Data files (*.csv *.xlsx *.xls);;All files (*)"
        )
        if not path:
            return
        self._path_edit.setText(path)
        try:
            svc = IngestionService()
            self._dataset = svc.load(path)
            self._populate_columns()
        except Exception as exc:
            QMessageBox.critical(self, "Import error", str(exc))

    def _populate_columns(self) -> None:
        if self._dataset is None:
            return
        self._col_combo.blockSignals(True)
        self._col_combo.clear()
        for col in self._dataset.columns:
            self._col_combo.addItem(col)
        self._col_combo.blockSignals(False)
        self._label_col = self._dataset.columns[0] if self._dataset.columns else None
        self._refresh_preview()

    def _on_col_changed(self, col: str) -> None:
        self._label_col = col
        self._refresh_preview()

    def _on_stype_changed(self, idx: int) -> None:
        val = self._stype_combo.currentData()
        self._stype = SemanticType(val) if val else SemanticType.UNKNOWN
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if self._dataset is None:
            return
        rows = self._dataset.head(50)
        cols = self._dataset.columns
        self._preview_table.setColumnCount(len(cols))
        self._preview_table.setHorizontalHeaderLabels(cols)
        self._preview_table.setRowCount(len(rows))

        label_idx = cols.index(self._label_col) if self._label_col in cols else -1
        for r_idx, row in enumerate(rows):
            for c_idx, col in enumerate(cols):
                val = row.get(col)
                item = QTableWidgetItem(str(val) if val is not None else "")
                if c_idx == label_idx:
                    item.setBackground(Qt.GlobalColor.darkGreen)
                self._preview_table.setItem(r_idx, c_idx, item)

        self._preview_table.resizeColumnsToContents()

    def build_mapping(self) -> Optional[ImportMapping]:
        if not self._dataset or not self._label_col:
            return None
        mapping = ImportMapping()
        mapping.column_mappings.append(
            ColumnMapping(column=self._label_col, role="entity_label", semantic_type=self._stype)
        )
        return mapping

    @property
    def dataset(self) -> Optional[StagedDataset]:
        return self._dataset


# ──────────────────────────────────────────────────────────────────────
# Advanced Mode tab (AS-13)
# ──────────────────────────────────────────────────────────────────────

class ColumnMappingRow(QWidget):
    """One row in the Advanced Mode mapping table."""

    def __init__(self, col_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.col_name = col_name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        layout.addWidget(QLabel(col_name))

        self._role_combo = QComboBox()
        for val, label in ROLE_OPTIONS:
            self._role_combo.addItem(label, val)
        layout.addWidget(self._role_combo)

        self._attr_name = QLineEdit()
        self._attr_name.setPlaceholderText("attr name (optional)")
        self._attr_name.setMaximumWidth(130)
        layout.addWidget(self._attr_name)

        self._stype_combo = QComboBox()
        for val, label in STYPE_OPTIONS:
            self._stype_combo.addItem(label, val)
        layout.addWidget(self._stype_combo)

    def get_mapping(self) -> ColumnMapping:
        return ColumnMapping(
            column=self.col_name,
            role=self._role_combo.currentData(),
            attr_name=self._attr_name.text().strip() or self.col_name,
            semantic_type=SemanticType(self._stype_combo.currentData()),
        )


class AdvancedModeTab(QWidget):
    """Power-user import view.

    Per-column role combo: entity label/attr, link source/target/type, skip.
    Semantic type assignment per column. Preview reflects choices.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._dataset: Optional[StagedDataset] = None
        self._col_rows: list[ColumnMappingRow] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        file_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Select a CSV or XLSX file…")
        self._path_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        file_row.addWidget(self._path_edit)
        file_row.addWidget(browse_btn)
        root.addLayout(file_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Column mapping panel
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Column  →  Role  →  Attr name  →  Type"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._mapping_container = QWidget()
        self._mapping_layout = QVBoxLayout(self._mapping_container)
        self._mapping_layout.addStretch()
        scroll.setWidget(self._mapping_container)
        left_layout.addWidget(scroll)
        splitter.addWidget(left)

        # Preview
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Preview (first 50 rows):"))
        self._preview_table = QTableWidget()
        self._preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._preview_table.setAlternatingRowColors(True)
        right_layout.addWidget(self._preview_table)

        refresh_btn = QPushButton("Refresh preview")
        refresh_btn.clicked.connect(self._refresh_preview)
        right_layout.addWidget(refresh_btn)
        splitter.addWidget(right)

        splitter.setSizes([350, 500])
        root.addWidget(splitter)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open data file", "",
            "Data files (*.csv *.xlsx *.xls);;All files (*)"
        )
        if not path:
            return
        self._path_edit.setText(path)
        try:
            svc = IngestionService()
            self._dataset = svc.load(path)
            self._build_column_rows()
            self._refresh_preview()
        except Exception as exc:
            QMessageBox.critical(self, "Import error", str(exc))

    def _build_column_rows(self) -> None:
        # Clear
        for row in self._col_rows:
            self._mapping_layout.removeWidget(row)
            row.deleteLater()
        self._col_rows = []

        if self._dataset is None:
            return

        stretch = self._mapping_layout.takeAt(self._mapping_layout.count() - 1)
        for col in self._dataset.columns:
            row = ColumnMappingRow(col)
            self._mapping_layout.addWidget(row)
            self._col_rows.append(row)
        self._mapping_layout.addStretch()

    def _refresh_preview(self) -> None:
        if self._dataset is None:
            return
        rows = self._dataset.head(50)
        cols = self._dataset.columns
        self._preview_table.setColumnCount(len(cols))
        self._preview_table.setHorizontalHeaderLabels(cols)
        self._preview_table.setRowCount(len(rows))

        role_map = {r.col_name: r.get_mapping().role for r in self._col_rows}

        ROLE_COLORS = {
            "entity_label": Qt.GlobalColor.darkGreen,
            "link_source":  Qt.GlobalColor.darkBlue,
            "link_target":  Qt.GlobalColor.darkMagenta,
        }

        for r_idx, row in enumerate(rows):
            for c_idx, col in enumerate(cols):
                val = row.get(col)
                item = QTableWidgetItem(str(val) if val is not None else "")
                role = role_map.get(col, "skip")
                if role in ROLE_COLORS:
                    item.setBackground(ROLE_COLORS[role])
                self._preview_table.setItem(r_idx, c_idx, item)

        self._preview_table.resizeColumnsToContents()

    def build_mapping(self) -> Optional[ImportMapping]:
        if not self._dataset:
            return None
        mapping = ImportMapping()
        for row in self._col_rows:
            cm = row.get_mapping()
            if cm.role != "skip":
                mapping.column_mappings.append(cm)
        return mapping

    @property
    def dataset(self) -> Optional[StagedDataset]:
        return self._dataset


# ──────────────────────────────────────────────────────────────────────
# Outer dialog (ties Simple + Advanced tabs together)
# ──────────────────────────────────────────────────────────────────────

class ImportDialog(QDialog):
    """Modal import dialog with Simple and Advanced mode tabs."""

    def __init__(self, repo: GraphRepository, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._repo = repo
        self._pipeline = ImportPipeline(repo)
        self.setWindowTitle("Import data")
        self.resize(900, 600)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._tabs = QTabWidget()
        self._simple = SimpleModeTab()
        self._advanced = AdvancedModeTab()
        self._tabs.addTab(self._simple, "Simple")
        self._tabs.addTab(self._advanced, "Advanced")
        layout.addWidget(self._tabs)

        self._status = QLabel("")
        layout.addWidget(self._status)

        buttons = QDialogButtonBox()
        self._preview_btn = QPushButton("Preview")
        self._commit_btn = QPushButton("Import")
        self._commit_btn.setEnabled(False)
        cancel_btn = QPushButton("Cancel")

        buttons.addButton(self._preview_btn, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self._commit_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)

        self._preview_btn.clicked.connect(self._do_preview)
        self._commit_btn.clicked.connect(self._do_commit)
        cancel_btn.clicked.connect(self.reject)

        self._last_preview: Optional[CommitPreview] = None

    def _active_tab(self) -> SimpleModeTab | AdvancedModeTab:
        return self._simple if self._tabs.currentIndex() == 0 else self._advanced

    def _do_preview(self) -> None:
        tab = self._active_tab()
        dataset = tab.dataset
        mapping = tab.build_mapping()
        if dataset is None or mapping is None:
            QMessageBox.warning(self, "No file", "Load a file first.")
            return
        try:
            preview = self._pipeline.preview(dataset, mapping)
            self._last_preview = preview
            self._show_preview(preview)
            self._commit_btn.setEnabled(True)
        except Exception as exc:
            QMessageBox.critical(self, "Preview error", str(exc))

    def _show_preview(self, p: CommitPreview) -> None:
        msg = (
            f"Ready to import: {p.entity_count} entities, {p.link_count} links."
        )
        if p.duplicate_entity_count:
            msg += f" ({p.duplicate_entity_count} will be updated.)"
        if p.warnings:
            msg += "  Warnings: " + "; ".join(p.warnings)
        self._status.setText(msg)

    def _do_commit(self) -> None:
        tab = self._active_tab()
        dataset = tab.dataset
        mapping = tab.build_mapping()
        if dataset is None or mapping is None:
            return
        try:
            result = self._pipeline.commit(dataset, mapping)
            QMessageBox.information(
                self, "Import complete",
                f"Imported {result.entity_count} entities and {result.link_count} links."
            )
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Import error", str(exc))
