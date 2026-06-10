"""Entity Dossier — the double-click metadata window for an entity.

Modeled on i2 Analyst's Notebook entity cards: identity, description,
source/origin with the i2 grading trio (source reliability A–E, information
credibility 1–5, handling code), free properties, an uploaded photo, and
per-entity display controls (node size, label font size).

Dossier metadata lives in conventional property keys so it survives export
and round-trips through the node-link JSON format.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSlider, QVBoxLayout, QWidget,
)

from ..graph.models import Entity, SemanticType
from ..graph.repository import GraphRepository
from .entity_dialog import _icon_combo, _type_combo
from .widgets import PropertiesTable

# Property keys the dossier surfaces as dedicated fields (everything else
# appears in the free properties table).
METADATA_KEYS = (
    "description", "source", "source_reliability", "info_credibility",
    "handling_code", "notes", "created_at", "modified_at",
)

_RELIABILITY = ["", "A — Completely reliable", "B — Usually reliable",
                "C — Fairly reliable", "D — Not usually reliable",
                "E — Unreliable"]
_CREDIBILITY = ["", "1 — Confirmed", "2 — Probably true", "3 — Possibly true",
                "4 — Doubtful", "5 — Improbable"]

DELETED = 2  # custom dialog result code


class DossierDialog(QDialog):
    """Pop-up dossier for one entity; saves through the repository."""

    def __init__(self, entity: Entity, repo: GraphRepository, media_dir: Path,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._entity = entity
        self._repo = repo
        self._media_dir = media_dir
        self._photo_path: str = entity.style.get("photo", "")
        self.setWindowTitle(f"Dossier — {entity.label}")
        self.resize(560, 720)

        layout = QVBoxLayout(self)

        # ── Header: photo + identity ─────────────────────────────────
        header = QHBoxLayout()
        self._photo_label = QLabel()
        self._photo_label.setFixedSize(96, 96)
        self._photo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._photo_label.setStyleSheet("border: 1px solid palette(mid); border-radius: 4px;")
        header.addWidget(self._photo_label)

        identity = QFormLayout()
        self._label_edit = QLineEdit(entity.label)
        self._type_combo = _type_combo(entity.semantic_type)
        self._icon_combo = _icon_combo(entity.icon)
        identity.addRow("Label:", self._label_edit)
        identity.addRow("Type:", self._type_combo)
        identity.addRow("Icon:", self._icon_combo)
        header.addLayout(identity, stretch=1)
        layout.addLayout(header)

        photo_buttons = QHBoxLayout()
        upload_btn = QPushButton("Upload Photo…")
        upload_btn.clicked.connect(self._upload_photo)
        remove_btn = QPushButton("Remove Photo")
        remove_btn.clicked.connect(self._remove_photo)
        photo_buttons.addWidget(upload_btn)
        photo_buttons.addWidget(remove_btn)
        photo_buttons.addStretch()
        layout.addLayout(photo_buttons)

        # ── Provenance / i2 grading ──────────────────────────────────
        props = entity.properties
        meta_box = QGroupBox("Background && provenance")
        meta = QFormLayout(meta_box)
        self._description = QPlainTextEdit(str(props.get("description", "")))
        self._description.setMaximumHeight(64)
        self._source = QLineEdit(str(props.get("source", "")))
        self._reliability = QComboBox()
        self._reliability.addItems(_RELIABILITY)
        self._reliability.setCurrentText(str(props.get("source_reliability", "")))
        self._credibility = QComboBox()
        self._credibility.addItems(_CREDIBILITY)
        self._credibility.setCurrentText(str(props.get("info_credibility", "")))
        self._handling = QLineEdit(str(props.get("handling_code", "")))
        self._notes = QPlainTextEdit(str(props.get("notes", "")))
        self._notes.setMaximumHeight(64)
        meta.addRow("Description:", self._description)
        meta.addRow("Source / origin:", self._source)
        meta.addRow("Source reliability:", self._reliability)
        meta.addRow("Info credibility:", self._credibility)
        meta.addRow("Handling code:", self._handling)
        meta.addRow("Notes:", self._notes)

        created = str(props.get("created_at", "—"))
        modified = str(props.get("modified_at", "—"))
        audit = QLabel(f"ID {entity.id}   ·   created {created}   ·   modified {modified}")
        audit.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        meta.addRow(audit)
        layout.addWidget(meta_box)

        # ── Free properties ──────────────────────────────────────────
        props_box = QGroupBox("Properties")
        props_layout = QVBoxLayout(props_box)
        self._props = PropertiesTable()
        self._props.set_properties(
            {k: v for k, v in props.items() if k not in METADATA_KEYS}
        )
        props_layout.addWidget(self._props)
        layout.addWidget(props_box)

        # ── Display ──────────────────────────────────────────────────
        display_box = QGroupBox("Display")
        display = QFormLayout(display_box)
        self._size_slider, size_row = self._slider(
            30, 150, int(entity.style.get("size", 60)))
        self._font_slider, font_row = self._slider(
            8, 24, int(entity.style.get("font_size", 11)))
        display.addRow("Entity size:", size_row)
        display.addRow("Label font size:", font_row)
        layout.addWidget(display_box)

        # ── Buttons ──────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        delete_btn = QPushButton("Delete Entity")
        buttons.addButton(delete_btn, QDialogButtonBox.ButtonRole.DestructiveRole)
        delete_btn.clicked.connect(self._delete_entity)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_photo()

    @staticmethod
    def _slider(low: int, high: int, value: int) -> tuple[QSlider, QWidget]:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setValue(max(low, min(high, value)))
        readout = QLabel(str(slider.value()))
        readout.setMinimumWidth(28)
        slider.valueChanged.connect(lambda v: readout.setText(str(v)))
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(slider, stretch=1)
        row_layout.addWidget(readout)
        return slider, row

    def _refresh_photo(self) -> None:
        if self._photo_path and Path(self._photo_path).exists():
            pix = QPixmap(self._photo_path).scaled(
                96, 96, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            self._photo_label.setPixmap(pix)
        else:
            self._photo_label.setPixmap(QPixmap())
            self._photo_label.setText("no\nphoto")

    def _upload_photo(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Choose photo", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path_str:
            return
        source = Path(path_str)
        self._media_dir.mkdir(parents=True, exist_ok=True)
        dest = self._media_dir / f"{self._entity.id}{source.suffix.lower()}"
        try:
            shutil.copy2(source, dest)
        except OSError as exc:
            QMessageBox.critical(self, "Photo upload failed", str(exc))
            return
        self._photo_path = str(dest)
        self._refresh_photo()

    def _remove_photo(self) -> None:
        self._photo_path = ""
        self._refresh_photo()

    def _delete_entity(self) -> None:
        answer = QMessageBox.question(
            self, "Delete entity",
            f"Delete “{self._entity.label}” and all its links?")
        if answer == QMessageBox.StandardButton.Yes:
            self._repo.entities.delete(self._entity.id)
            self.done(DELETED)

    def _save(self) -> None:
        label = self._label_edit.text().strip()
        if not label:
            self._label_edit.setFocus()
            return
        entity = self._entity
        entity.label = label
        entity.semantic_type = SemanticType(self._type_combo.currentData())
        entity.icon = self._icon_combo.currentData() or ""

        properties = self._props.properties()
        now = datetime.now().isoformat(timespec="seconds")
        meta = {
            "description": self._description.toPlainText().strip(),
            "source": self._source.text().strip(),
            "source_reliability": self._reliability.currentText(),
            "info_credibility": self._credibility.currentText(),
            "handling_code": self._handling.text().strip(),
            "notes": self._notes.toPlainText().strip(),
        }
        for key, value in meta.items():
            if value:
                properties[key] = value
        properties["created_at"] = entity.properties.get("created_at", now)
        properties["modified_at"] = now
        entity.properties = properties

        entity.style = dict(entity.style)
        entity.style["size"] = self._size_slider.value()
        entity.style["font_size"] = self._font_slider.value()
        if self._photo_path:
            entity.style["photo"] = self._photo_path
        else:
            entity.style.pop("photo", None)

        self._repo.entities.upsert(entity)
        self.accept()

    @property
    def entity(self) -> Entity:
        return self._entity
