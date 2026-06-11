"""Automatic column→role detection for imports.

When a user picks a CSV/XLSX, the tool — not the user — should figure out
which columns are the link source/target, which is the relationship type,
and which are attributes. Detection combines:

1. **Header synonyms** — `source`/`from`/`caller`… vs `target`/`to`/`callee`…
   vs `relationship`/`type`/`rel`…
2. **Content overlap** — two columns whose value sets overlap substantially
   contain the same population of entities (Alice appears as both a source
   and a target), the structural signature of an edge list.
3. **Cardinality** — a low-cardinality short-string column among the leftovers
   is the link type.

If no source/target pair emerges, the dataset is treated as an entity list:
the best label column is chosen (header synonyms, then the most unique
string column) and the rest become attributes. Semantic types are guessed
from headers only when unambiguous (e.g. *email*, *phone*); otherwise left
Unknown rather than guessed wrong.

Everything here is pure and returns an ``ImportMapping`` plus human-readable
notes, so the UI can apply it silently and still show its reasoning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ingestion import StagedDataset
from .pipeline import ColumnMapping, ImportMapping
from ..graph.models import SemanticType

# Header keyword sets (matched on normalized header names).
_SOURCE_HINTS = {
    "source", "src", "from", "origin", "caller", "sender", "reporter",
    "entity1", "person1", "party1", "node1", "subject", "start",
}
_TARGET_HINTS = {
    "target", "tgt", "to", "destination", "dest", "callee", "receiver",
    "recipient", "entity2", "person2", "party2", "node2", "object", "end",
}
_TYPE_HINTS = {
    "relationship", "relation", "rel", "link", "linktype", "type", "edge",
    "predicate", "connection", "action", "reltype",
}
_LABEL_HINTS = {
    "name", "label", "entity", "title", "fullname", "displayname", "id",
}

# Header → semantic type, only where the header is unambiguous.
_SEMANTIC_HINTS: dict[str, SemanticType] = {
    "person": SemanticType.PERSON,
    "people": SemanticType.PERSON,
    "organization": SemanticType.ORGANIZATION,
    "organisation": SemanticType.ORGANIZATION,
    "company": SemanticType.ORGANIZATION,
    "org": SemanticType.ORGANIZATION,
    "phone": SemanticType.PHONE,
    "telephone": SemanticType.PHONE,
    "msisdn": SemanticType.PHONE,
    "email": SemanticType.EMAIL,
    "mail": SemanticType.EMAIL,
    "account": SemanticType.ACCOUNT,
    "iban": SemanticType.ACCOUNT,
    "location": SemanticType.LOCATION,
    "address": SemanticType.LOCATION,
    "city": SemanticType.LOCATION,
    "place": SemanticType.LOCATION,
    "vehicle": SemanticType.VEHICLE,
    "plate": SemanticType.VEHICLE,
    "event": SemanticType.EVENT,
    "document": SemanticType.DOCUMENT,
}

# Content-overlap threshold for declaring a source/target pair (fraction of
# the smaller column's distinct values that also appear in the other column).
_OVERLAP_THRESHOLD = 0.25
_SAMPLE_ROWS = 500


@dataclass
class AutoMapResult:
    mapping: ImportMapping
    link_mode: bool
    label_column: str | None = None
    notes: list[str] = field(default_factory=list)


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def _matches(header: str, hints: set[str]) -> bool:
    """Whole-token hint matching.

    Raw prefix matching is too broad for short hints — ``total`` must not
    match ``to`` (that flipped ordinary tables into link mode). A header
    matches when its fully normalized name is a hint, or its first token
    (split on separators) is — so ``from_name``/``to account`` match while
    ``total``/``fromage`` don't.
    """
    if _norm(header) in hints:
        return True
    tokens = [t for t in re.split(r"[^a-z0-9]+", header.lower()) if t]
    return bool(tokens) and tokens[0] in hints


def _semantic_for(header: str) -> SemanticType:
    norm = _norm(header)
    for key, stype in _SEMANTIC_HINTS.items():
        if key in norm:
            return stype
    return SemanticType.UNKNOWN


def _string_values(dataset: StagedDataset, column: str) -> list[str]:
    out = []
    for row in dataset.rows[:_SAMPLE_ROWS]:
        value = row.get(column)
        if value is not None and str(value).strip():
            out.append(str(value).strip())
    return out


def _find_endpoint_pair(dataset: StagedDataset) -> tuple[str, str] | None:
    """Locate the (source, target) column pair, by headers then by content."""

    def match(hints: set[str]) -> list[str]:
        return [c for c in dataset.columns if _matches(c, hints)]

    sources, targets = match(_SOURCE_HINTS), match(_TARGET_HINTS)
    if sources and targets and sources[0] != targets[0]:
        return sources[0], targets[0]

    # Content fallback: the pair of string columns with the highest mutual
    # value overlap — same entities appearing on both ends of an edge list.
    # Endpoints must look entity-like: low-cardinality categorical columns
    # (status flags, yes/no fields) overlap trivially but aren't entities,
    # and accepting them fabricates category→category links.
    row_count = max(len(dataset.rows), 1)
    min_distinct = max(3, min(int(row_count * 0.1), 20))

    string_cols = [c for c in dataset.columns
                   if dataset.column_types.get(c) in ("string", "mixed", "date")]
    best, best_score = None, 0.0
    for i, a in enumerate(string_cols):
        set_a = set(_string_values(dataset, a))
        if len(set_a) < min_distinct:
            continue
        for b in string_cols[i + 1:]:
            set_b = set(_string_values(dataset, b))
            if len(set_b) < min_distinct:
                continue
            overlap = len(set_a & set_b) / min(len(set_a), len(set_b))
            if overlap > best_score:
                best, best_score = (a, b), overlap
    if best and best_score >= _OVERLAP_THRESHOLD:
        return best
    return None


def _find_type_column(dataset: StagedDataset, taken: set[str]) -> str | None:
    """The relationship-label column: header hint, else low-cardinality text."""
    remaining = [c for c in dataset.columns if c not in taken]
    for col in remaining:
        if _matches(col, _TYPE_HINTS):
            return col
    candidates = []
    row_count = max(len(dataset.rows), 1)
    for col in remaining:
        if dataset.column_types.get(col) != "string":
            continue
        values = _string_values(dataset, col)
        if not values:
            continue
        distinct = len(set(values))
        avg_len = sum(len(v) for v in values) / len(values)
        if distinct <= max(10, row_count * 0.3) and avg_len <= 30:
            candidates.append((distinct, col))
    return min(candidates)[1] if candidates else None


def _find_label_column(dataset: StagedDataset) -> str | None:
    for col in dataset.columns:
        if _matches(col, _LABEL_HINTS):
            return col
    # Most-unique string column wins; entity labels are near-unique.
    best, best_ratio = None, 0.0
    for col in dataset.columns:
        if dataset.column_types.get(col) not in ("string", "mixed"):
            continue
        values = _string_values(dataset, col)
        if not values:
            continue
        ratio = len(set(values)) / len(values)
        if ratio > best_ratio:
            best, best_ratio = col, ratio
    return best or (dataset.columns[0] if dataset.columns else None)


def detect_mapping(dataset: StagedDataset) -> AutoMapResult:
    """Infer the full column→role mapping for a staged dataset."""
    notes: list[str] = []
    mapping = ImportMapping()

    pair = _find_endpoint_pair(dataset)
    if pair:
        src_col, tgt_col = pair
        taken = {src_col, tgt_col}
        type_col = _find_type_column(dataset, taken)
        mapping.column_mappings.append(ColumnMapping(
            column=src_col, role="link_source",
            semantic_type=_semantic_for(src_col)))
        mapping.column_mappings.append(ColumnMapping(
            column=tgt_col, role="link_target",
            semantic_type=_semantic_for(tgt_col)))
        notes.append(f"{src_col} → link source, {tgt_col} → link target")
        if type_col:
            taken.add(type_col)
            mapping.column_mappings.append(ColumnMapping(
                column=type_col, role="link_type"))
            notes.append(f"{type_col} → link type")
        for col in dataset.columns:
            if col not in taken:
                mapping.column_mappings.append(ColumnMapping(
                    column=col, role="entity_attr", attr_name=col))
        extras = [c for c in dataset.columns if c not in taken]
        if extras:
            notes.append(f"{', '.join(extras)} → attributes")
        return AutoMapResult(mapping=mapping, link_mode=True, notes=notes)

    label_col = _find_label_column(dataset)
    if label_col is None:
        return AutoMapResult(mapping=mapping, link_mode=False,
                             notes=["no columns detected"])
    stype = _semantic_for(label_col)
    mapping.column_mappings.append(ColumnMapping(
        column=label_col, role="entity_label", semantic_type=stype))
    notes.append(f"{label_col} → entity label"
                 + (f" ({stype.value})" if stype is not SemanticType.UNKNOWN else ""))
    for col in dataset.columns:
        if col != label_col:
            mapping.column_mappings.append(ColumnMapping(
                column=col, role="entity_attr", attr_name=col))
    extras = [c for c in dataset.columns if c != label_col]
    if extras:
        notes.append(f"{', '.join(extras)} → attributes")
    return AutoMapResult(mapping=mapping, link_mode=False,
                         label_column=label_col, notes=notes)
