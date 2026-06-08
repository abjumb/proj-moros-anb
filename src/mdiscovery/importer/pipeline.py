"""AS-14 + AS-15: Import validation, preview-before-commit, and commit pipeline.

Nothing writes to the graph until the user confirms. Conflicts/dupes are flagged.
Uses MERGE semantics so re-running an import never causes a silent duplicate explosion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid

from .ingestion import StagedDataset
from ..graph.models import Entity, Link, SemanticType, LinkDirection
from ..graph.repository import GraphRepository


@dataclass
class ColumnMapping:
    """How a single column maps to the graph."""
    column: str
    role: str  # "entity_label" | "entity_attr" | "link_source" | "link_target" | "link_type" | "skip"
    attr_name: str = ""
    entity_index: int = 0  # which entity slot (0=primary, 1=secondary)
    semantic_type: SemanticType = SemanticType.UNKNOWN


@dataclass
class ImportMapping:
    """Full column→graph mapping for one import run."""
    column_mappings: list[ColumnMapping] = field(default_factory=list)
    default_link_type: str = "relates_to"
    default_link_direction: LinkDirection = LinkDirection.DIRECTED

    def label_columns(self) -> list[ColumnMapping]:
        return [m for m in self.column_mappings if m.role == "entity_label"]

    def source_columns(self) -> list[ColumnMapping]:
        return [m for m in self.column_mappings if m.role == "link_source"]

    def target_columns(self) -> list[ColumnMapping]:
        return [m for m in self.column_mappings if m.role == "link_target"]


@dataclass
class CommitPreview:
    """Dry-run result shown to the user before writing anything."""
    entity_count: int
    link_count: int
    duplicate_entity_count: int
    warnings: list[str] = field(default_factory=list)
    sample_entities: list[Entity] = field(default_factory=list)
    sample_links: list[Link] = field(default_factory=list)


class ImportPipeline:
    """Orchestrates the staged→preview→confirm→commit flow."""

    def __init__(self, repo: GraphRepository):
        self._repo = repo

    def preview(
        self,
        dataset: StagedDataset,
        mapping: ImportMapping,
    ) -> CommitPreview:
        """Build a CommitPreview (dry-run) — nothing is written to the graph."""
        entities, links, warnings = self._build_graph_objects(dataset, mapping)

        existing_ids = {e.id for e in self._repo.entities.all()}
        dupes = sum(1 for e in entities if e.id in existing_ids)
        if dupes:
            warnings.append(f"{dupes} entit{'ies' if dupes != 1 else 'y'} already exist and will be updated.")

        if dataset.parse_warnings:
            warnings.extend(dataset.parse_warnings)

        return CommitPreview(
            entity_count=len(entities),
            link_count=len(links),
            duplicate_entity_count=dupes,
            warnings=warnings,
            sample_entities=entities[:10],
            sample_links=links[:10],
        )

    def commit(
        self,
        dataset: StagedDataset,
        mapping: ImportMapping,
    ) -> CommitPreview:
        """Write confirmed, mapped data into the embedded graph using MERGE semantics."""
        entities, links, warnings = self._build_graph_objects(dataset, mapping)

        existing_ids = {e.id for e in self._repo.entities.all()}
        dupes = sum(1 for e in entities if e.id in existing_ids)

        self._repo.entities.upsert_batch(entities)
        self._repo.links.upsert_batch(links)

        return CommitPreview(
            entity_count=len(entities),
            link_count=len(links),
            duplicate_entity_count=dupes,
            warnings=warnings,
        )

    def _build_graph_objects(
        self,
        dataset: StagedDataset,
        mapping: ImportMapping,
    ) -> tuple[list[Entity], list[Link], list[str]]:
        """Translate staged rows into Entity and Link objects."""
        warnings: list[str] = []
        entities: dict[str, Entity] = {}
        links: list[Link] = []

        label_cols = mapping.label_columns()
        src_cols = mapping.source_columns()
        tgt_cols = mapping.target_columns()

        has_link_mapping = bool(src_cols and tgt_cols)

        for row_idx, row in enumerate(dataset.rows):
            if has_link_mapping:
                # Entity–entity link mode: one entity per source col, one per target col
                for src_col, tgt_col in zip(src_cols, tgt_cols):
                    src_label = str(row.get(src_col.column) or "").strip()
                    tgt_label = str(row.get(tgt_col.column) or "").strip()
                    if not src_label or not tgt_label:
                        continue

                    src_id = self._stable_id(src_label, src_col.semantic_type)
                    tgt_id = self._stable_id(tgt_label, tgt_col.semantic_type)

                    if src_id not in entities:
                        entities[src_id] = Entity(
                            id=src_id,
                            label=src_label,
                            semantic_type=src_col.semantic_type,
                        )
                    if tgt_id not in entities:
                        entities[tgt_id] = Entity(
                            id=tgt_id,
                            label=tgt_label,
                            semantic_type=tgt_col.semantic_type,
                        )

                    # Attach extra attribute columns
                    extra_props = self._collect_attrs(row, mapping, [src_col.column, tgt_col.column])
                    link_type = mapping.default_link_type
                    for m in mapping.column_mappings:
                        if m.role == "link_type":
                            lt = str(row.get(m.column) or "").strip()
                            if lt:
                                link_type = lt

                    links.append(Link(
                        source_id=src_id,
                        target_id=tgt_id,
                        link_type=link_type,
                        direction=mapping.default_link_direction,
                        properties=extra_props,
                    ))
            else:
                # Simple mode: one entity per label column
                for lc in label_cols:
                    label = str(row.get(lc.column) or "").strip()
                    if not label:
                        continue
                    eid = self._stable_id(label, lc.semantic_type)
                    props = self._collect_attrs(row, mapping, [lc.column])
                    if eid in entities:
                        entities[eid].properties.update(props)
                    else:
                        entities[eid] = Entity(
                            id=eid,
                            label=label,
                            semantic_type=lc.semantic_type,
                            properties=props,
                        )

        return list(entities.values()), links, warnings

    @staticmethod
    def _stable_id(label: str, semantic_type: SemanticType) -> str:
        """Deterministic ID from label + type so re-importing merges, not duplicates."""
        import hashlib
        key = f"{semantic_type.value}::{label.lower().strip()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    @staticmethod
    def _collect_attrs(
        row: dict[str, Any],
        mapping: ImportMapping,
        exclude_cols: list[str],
    ) -> dict[str, Any]:
        props: dict[str, Any] = {}
        for m in mapping.column_mappings:
            if m.role == "entity_attr" and m.column not in exclude_cols:
                val = row.get(m.column)
                if val is not None:
                    props[m.attr_name or m.column] = val
        return props
