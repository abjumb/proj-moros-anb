"""AS-14 + AS-15: Import validation, preview-before-commit, and commit pipeline.

Nothing writes to the graph until the user confirms. Conflicts/dupes are flagged.
Uses MERGE semantics so re-running an import never causes a silent duplicate explosion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

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
        # (id(dataset), mapping fingerprint) -> built objects, so the commit
        # that follows an auto-preview never rebuilds 1M rows.
        self._cache_key = None
        self._cache_value = None
        self.build_calls = 0  # observability for tests

    def preview(
        self,
        dataset: StagedDataset,
        mapping: ImportMapping,
    ) -> CommitPreview:
        """Build a CommitPreview (dry-run) — nothing is written to the graph."""
        entities, links, warnings = self._build_cached(dataset, mapping)

        existing_ids = self._repo.entities.all_ids()
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
        entities, links, warnings = self._build_cached(dataset, mapping)

        existing_ids = self._repo.entities.all_ids()
        dupes = sum(1 for e in entities if e.id in existing_ids)

        # COPY-based bulk path: identical semantics to the per-row MERGE
        # (entities updated, existing link ids skipped) at ~250x the speed.
        # The vectorized build leaves a columnar copy of the links so the
        # repo can stream them to CSV without touching 1M objects again.
        link_cols = getattr(self, "_bulk_link_cols", None)
        if link_cols is not None:
            self._repo.bulk_upsert(
                entities, [], link_cols=link_cols,
                link_direction=self._bulk_direction.value)
            self._bulk_link_cols = None  # free ~hundreds of MB on big files
        else:
            self._repo.bulk_upsert(entities, links)

        return CommitPreview(
            entity_count=len(entities),
            link_count=len(links),
            duplicate_entity_count=dupes,
            warnings=warnings,
        )

    @staticmethod
    def _mapping_fingerprint(mapping: ImportMapping) -> tuple:
        return (
            tuple((m.column, m.role, m.attr_name, m.entity_index,
                   m.semantic_type.value) for m in mapping.column_mappings),
            mapping.default_link_type,
            mapping.default_link_direction.value,
        )

    def _build_cached(self, dataset, mapping):
        key = (id(dataset), self._mapping_fingerprint(mapping))
        if key == self._cache_key:
            return self._cache_value
        value = self._build_graph_objects(dataset, mapping)
        self._cache_key, self._cache_value = key, value
        return value

    def _build_graph_objects(
        self,
        dataset: StagedDataset,
        mapping: ImportMapping,
    ) -> tuple[list[Entity], list[Link], list[str]]:
        """Translate the staged dataset into Entity and Link objects.

        Datasets that retain their pandas frame take the vectorised path
        (unique-label hashing, column-level ops); the row-wise fallback
        remains for hand-built datasets. Both produce identical objects —
        pinned by equivalence tests.
        """
        self.build_calls += 1
        if getattr(dataset, "frame", None) is not None:
            return self._build_vectorized(dataset, mapping)
        return self._build_rowwise(dataset, mapping)

    def _build_vectorized(self, dataset, mapping):
        import pandas as pd

        df = dataset.frame
        warnings: list[str] = list()
        entities: dict[str, Entity] = {}
        links: list[Link] = []
        bulk_links_cols: dict[str, list] = {k: [] for k in
                                            ("src", "tgt", "id", "lt", "props")}
        self._bulk_link_cols = None
        self._bulk_direction = mapping.default_link_direction

        label_cols = mapping.label_columns()
        src_cols = mapping.source_columns()
        tgt_cols = mapping.target_columns()
        link_type_cols = [m for m in mapping.column_mappings if m.role == "link_type"]
        attr_maps = [m for m in mapping.column_mappings if m.role == "entity_attr"]

        def clean(col):
            return df[col].fillna("").astype(str).str.strip()

        def id_map(labels, stype):
            return {lab: self._stable_id(lab, stype) for lab in pd.unique(labels)}

        def attr_records(mask, exclude):
            cols = [(m.column, m.attr_name or m.column) for m in attr_maps
                    if m.column not in exclude and m.column in df.columns]
            if not cols:
                return [{}] * int(mask.sum())
            arrays = [(name, df.loc[mask, col].tolist()) for col, name in cols]
            count = int(mask.sum())
            out = []
            for i in range(count):
                rec = {}
                for name, arr in arrays:
                    v = arr[i]
                    if v is not None and not (isinstance(v, float) and pd.isna(v)):
                        rec[name] = v
                out.append(rec)
            return out

        if src_cols and tgt_cols:
            for src_col, tgt_col in zip(src_cols, tgt_cols):
                s = clean(src_col.column)
                t = clean(tgt_col.column)
                mask = (s != "") & (t != "")
                s_v, t_v = s[mask], t[mask]

                smap = id_map(s_v, src_col.semantic_type)
                tmap = id_map(t_v, tgt_col.semantic_type)
                for lab, eid in smap.items():
                    if eid not in entities:
                        entities[eid] = Entity(id=eid, label=lab,
                                               semantic_type=src_col.semantic_type)
                for lab, eid in tmap.items():
                    if eid not in entities:
                        entities[eid] = Entity(id=eid, label=lab,
                                               semantic_type=tgt_col.semantic_type)

                # Per-row link type: default, overridden by each non-empty
                # link_type column in order (matches the row-wise loop).
                lt = pd.Series(mapping.default_link_type, index=s_v.index)
                for m in link_type_cols:
                    vals = clean(m.column)[mask]
                    lt = lt.where(vals == "", vals)

                props = attr_records(mask, {src_col.column, tgt_col.column})
                src_ids = s_v.map(smap).tolist()
                tgt_ids = t_v.map(tmap).tolist()
                lt_list = lt.tolist()
                direction = mapping.default_link_direction
                make = self._stable_link_id_and_props
                ids_json = [make(src_ids[i], tgt_ids[i], lt_list[i], props[i])
                            for i in range(len(src_ids))]
                for i in range(len(src_ids)):
                    links.append(Link(
                        id=ids_json[i][0],
                        source_id=src_ids[i], target_id=tgt_ids[i],
                        link_type=lt_list[i], direction=direction,
                        properties=props[i],
                    ))
                bulk_links_cols["src"].extend(src_ids)
                bulk_links_cols["tgt"].extend(tgt_ids)
                bulk_links_cols["id"].extend(j[0] for j in ids_json)
                bulk_links_cols["lt"].extend(lt_list)
                bulk_links_cols["props"].extend(j[1] for j in ids_json)
        else:
            for lc in label_cols:
                lab = clean(lc.column)
                mask = lab != ""
                lab_v = lab[mask]
                lmap = id_map(lab_v, lc.semantic_type)
                props = attr_records(mask, {lc.column})
                lab_list = lab_v.tolist()
                for i in range(len(lab_list)):
                    eid = lmap[lab_list[i]]
                    if eid in entities:
                        entities[eid].properties.update(props[i])
                    else:
                        entities[eid] = Entity(
                            id=eid, label=lab_list[i],
                            semantic_type=lc.semantic_type,
                            properties=props[i])

        if bulk_links_cols["id"]:
            self._bulk_link_cols = bulk_links_cols
        return list(entities.values()), links, warnings

    def _build_rowwise(
        self,
        dataset: StagedDataset,
        mapping: ImportMapping,
    ) -> tuple[list[Entity], list[Link], list[str]]:
        """Row-dict fallback for datasets without a pandas frame."""
        warnings: list[str] = []
        entities: dict[str, Entity] = {}
        links: list[Link] = []

        label_cols = mapping.label_columns()
        src_cols = mapping.source_columns()
        tgt_cols = mapping.target_columns()
        link_type_cols = [m for m in mapping.column_mappings if m.role == "link_type"]

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
                    for m in link_type_cols:
                        lt = str(row.get(m.column) or "").strip()
                        if lt:
                            link_type = lt

                    links.append(Link(
                        id=self._stable_link_id(src_id, tgt_id, link_type, extra_props),
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
        key = f"{semantic_type.value}::{label.lower().strip()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    @staticmethod
    def _stable_link_id_and_props(
        source_id: str, target_id: str, link_type: str, properties: dict[str, Any]
    ) -> tuple[str, str]:
        """(stable id, canonical props JSON) — the JSON is computed for the
        id anyway; the bulk commit lane reuses it instead of re-serializing."""
        props = json.dumps(properties, sort_keys=True, default=str)
        key = f"{source_id}->{target_id}::{link_type}::{props}"
        return hashlib.sha256(key.encode()).hexdigest()[:16], props

    @staticmethod
    def _stable_link_id(
        source_id: str, target_id: str, link_type: str, properties: dict[str, Any]
    ) -> str:
        """Deterministic link ID so re-imports merge instead of duplicating.

        Random UUIDs previously defeated the MERGE semantics promised in the
        module docstring: every re-import minted fresh ids and silently
        doubled the link set. Properties are folded into the key so that
        genuinely distinct relationships between the same pair — e.g. two calls
        of different weight, which the i2 model represents as parallel links —
        keep separate ids, while re-importing identical rows still collapses.
        """
        props = json.dumps(properties, sort_keys=True, default=str)
        key = f"{source_id}->{target_id}::{link_type}::{props}"
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
