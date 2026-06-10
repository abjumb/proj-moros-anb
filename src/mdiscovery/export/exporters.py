"""M3: Serialize the graph to interchange formats and human-readable reports.

Like the metrics module, the core functions take plain ``Entity``/``Link`` lists
so they can be tested without a live database. ``write_export`` is the
repository-facing convenience that picks a serializer and writes file(s) to disk.

Formats:
- **GraphML** — XML understood by Gephi, yEd, Cytoscape desktop, and i2.
- **CSV** — a ``*_nodes.csv`` + ``*_edges.csv`` pair (one row per entity / link).
- **JSON** — node-link document round-trippable via ``Entity``/``Link.from_dict``.
- **Report** — a Markdown case summary built on the analysis metrics.
"""

from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from ..graph.models import Entity, Link, LinkDirection
from ..analysis.metrics import (
    betweenness_centrality, graph_summary, recommended_sample_size,
)


class ExportFormat(str, Enum):
    GRAPHML = "graphml"
    CSV = "csv"
    JSON = "json"
    REPORT = "report"
    ANX = "anx"

    @property
    def suffix(self) -> str:
        return {
            ExportFormat.GRAPHML: ".graphml",
            ExportFormat.CSV: ".csv",
            ExportFormat.JSON: ".json",
            ExportFormat.REPORT: ".md",
            ExportFormat.ANX: ".anx",
        }[self]


# --- GraphML ---------------------------------------------------------------

_GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"


def to_graphml(entities: list[Entity], links: list[Link]) -> str:
    """Render the graph as a GraphML XML document.

    Entity/link properties are emitted as dynamically-declared ``<key>`` data
    fields (string-typed). Built-in numeric link attributes (strength,
    confidence) are declared as doubles.
    """
    node_prop_keys = _collect_keys(e.properties for e in entities)
    edge_prop_keys = _collect_keys(l.properties for l in links)

    graphml = ET.Element("graphml", {"xmlns": _GRAPHML_NS})

    def add_key(key_id: str, domain: str, name: str, attr_type: str) -> None:
        ET.SubElement(
            graphml, "key",
            {"id": key_id, "for": domain, "attr.name": name, "attr.type": attr_type},
        )

    add_key("label", "node", "label", "string")
    add_key("type", "node", "type", "string")
    for name in node_prop_keys:
        add_key(f"np__{name}", "node", name, "string")

    add_key("link_type", "edge", "link_type", "string")
    add_key("direction", "edge", "direction", "string")
    add_key("strength", "edge", "strength", "double")
    add_key("confidence", "edge", "confidence", "double")
    for name in edge_prop_keys:
        add_key(f"ep__{name}", "edge", name, "string")

    graph = ET.SubElement(graphml, "graph", {"edgedefault": "directed"})

    for e in entities:
        node = ET.SubElement(graph, "node", {"id": e.id})
        _add_data(node, "label", e.label)
        _add_data(node, "type", e.semantic_type.value)
        for name in node_prop_keys:
            if name in e.properties:
                _add_data(node, f"np__{name}", e.properties[name])

    for l in links:
        edge_attrs = {"id": l.id, "source": l.source_id, "target": l.target_id}
        # GraphML consumers (Gephi/yEd/i2) read the structural `directed`
        # attribute, not our custom `direction` data field. Override the graph's
        # directed default for undirected links so their semantics survive export.
        if l.direction is LinkDirection.UNDIRECTED:
            edge_attrs["directed"] = "false"
        edge = ET.SubElement(graph, "edge", edge_attrs)
        _add_data(edge, "link_type", l.link_type)
        _add_data(edge, "direction", l.direction.value)
        _add_data(edge, "strength", l.strength)
        _add_data(edge, "confidence", l.confidence)
        for name in edge_prop_keys:
            if name in l.properties:
                _add_data(edge, f"ep__{name}", l.properties[name])

    ET.indent(graphml, space="  ")
    body = ET.tostring(graphml, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


def _add_data(parent: ET.Element, key: str, value) -> None:
    data = ET.SubElement(parent, "data", {"key": key})
    data.text = str(value)


def _collect_keys(prop_dicts) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for d in prop_dicts:
        for k in d:
            if k not in seen:
                seen.add(k)
                keys.append(str(k))
    return sorted(keys)


# --- CSV -------------------------------------------------------------------

def to_csv(entities: list[Entity], links: list[Link]) -> tuple[str, str]:
    """Return ``(nodes_csv, edges_csv)`` as strings.

    Property columns are the sorted union of all property keys, so every row
    shares the same header.
    """
    node_prop_keys = _collect_keys(e.properties for e in entities)
    edge_prop_keys = _collect_keys(l.properties for l in links)

    nodes_buf = io.StringIO()
    nwriter = csv.writer(nodes_buf)
    nwriter.writerow(["id", "label", "type", *node_prop_keys])
    for e in entities:
        nwriter.writerow(
            [e.id, e.label, e.semantic_type.value,
             *[_csv_cell(e.properties.get(k)) for k in node_prop_keys]]
        )

    edges_buf = io.StringIO()
    ewriter = csv.writer(edges_buf)
    ewriter.writerow(
        ["id", "source", "target", "link_type", "direction",
         "strength", "confidence", *edge_prop_keys]
    )
    for l in links:
        ewriter.writerow(
            [l.id, l.source_id, l.target_id, l.link_type, l.direction.value,
             l.strength, l.confidence,
             *[_csv_cell(l.properties.get(k)) for k in edge_prop_keys]]
        )

    return nodes_buf.getvalue(), edges_buf.getvalue()


def _csv_cell(value) -> str:
    return "" if value is None else str(value)


# --- JSON ------------------------------------------------------------------

def to_json(entities: list[Entity], links: list[Link], *, indent: int = 2) -> str:
    """Node-link JSON document. Round-trips via Entity/Link.from_dict."""
    payload = {
        "nodes": [e.to_dict() for e in entities],
        "links": [l.to_dict() for l in links],
    }
    return json.dumps(payload, indent=indent, ensure_ascii=False)


# --- Markdown report -------------------------------------------------------

def to_report(
    entities: list[Entity],
    links: list[Link],
    *,
    title: str = "mDiscovery Case Report",
    generated_at: Optional[datetime] = None,
    top_n: int = 10,
) -> str:
    """Human-readable Markdown summary of the graph.

    ``generated_at`` is injectable so callers (and tests) can pin the timestamp;
    pass ``None`` to omit the line entirely.
    """
    summary = graph_summary(entities, links, top_n=top_n)
    lines: list[str] = [f"# {title}", ""]
    if generated_at is not None:
        lines.append(f"_Generated: {generated_at:%Y-%m-%d %H:%M}_")
        lines.append("")

    lines += [
        "## Overview",
        "",
        f"- **Entities:** {summary.entity_count}",
        f"- **Links:** {summary.link_count}",
        f"- **Connected components:** {summary.component_count}",
        f"- **Largest component:** {summary.largest_component_size}",
        f"- **Density:** {summary.density:.4f}",
        "",
    ]

    lines.append("## Entities by type")
    lines.append("")
    if summary.entities_by_type:
        for stype, count in summary.entities_by_type.items():
            lines.append(f"- {stype}: {count}")
    else:
        lines.append("- _none_")
    lines.append("")

    lines.append("## Links by type")
    lines.append("")
    if summary.links_by_type:
        for ltype, count in summary.links_by_type.items():
            lines.append(f"- {ltype}: {count}")
    else:
        lines.append("- _none_")
    lines.append("")

    lines.append(f"## Most connected entities (top {top_n})")
    lines.append("")
    if summary.top_entities:
        lines.append("| Rank | Entity | Total | In | Out |")
        lines.append("| ---: | --- | ---: | ---: | ---: |")
        for rank, d in enumerate(summary.top_entities, start=1):
            lines.append(
                f"| {rank} | {d.label} | {d.total_degree} | {d.in_degree} | {d.out_degree} |"
            )
    else:
        lines.append("_No entities._")
    lines.append("")

    lines.append("## Key brokers (betweenness centrality)")
    lines.append("")
    bc = betweenness_centrality(
        entities, links, sample_size=recommended_sample_size(len(entities))
    )
    labels = {e.id: e.label for e in entities}
    brokers = sorted(
        ((eid, score) for eid, score in bc.items() if score > 0),
        key=lambda kv: (-kv[1], labels.get(kv[0], "")),
    )[:top_n]
    if brokers:
        lines.append("| Rank | Entity | Betweenness |")
        lines.append("| ---: | --- | ---: |")
        for rank, (eid, score) in enumerate(brokers, start=1):
            lines.append(f"| {rank} | {labels.get(eid, eid)} | {score:.3f} |")
    else:
        lines.append("_No broker nodes (no entity sits between others)._")
    lines.append("")

    return "\n".join(lines)


# --- repository-facing writer ----------------------------------------------

def write_export(repo, path: str | Path, fmt: ExportFormat | str) -> list[Path]:
    """Export the repo's full graph to ``path`` in ``fmt``; return written paths.

    For CSV the ``path`` stem is used to derive ``<stem>_nodes.csv`` and
    ``<stem>_edges.csv`` (two files); all other formats write a single file.
    """
    fmt = ExportFormat(fmt)
    path = Path(path)
    entities = repo.entities.all()
    links = repo.links.all()

    if fmt is ExportFormat.GRAPHML:
        path.write_text(to_graphml(entities, links), encoding="utf-8")
        return [path]

    if fmt is ExportFormat.JSON:
        path.write_text(to_json(entities, links), encoding="utf-8")
        return [path]

    if fmt is ExportFormat.REPORT:
        path.write_text(
            to_report(entities, links, generated_at=datetime.now()),
            encoding="utf-8",
        )
        return [path]

    if fmt is ExportFormat.ANX:
        from .anx import to_anx  # local import keeps the module table here
        path.write_text(to_anx(entities, links), encoding="utf-8")
        return [path]

    if fmt is ExportFormat.CSV:
        nodes_csv, edges_csv = to_csv(entities, links)
        nodes_path = path.with_name(f"{path.stem}_nodes.csv")
        edges_path = path.with_name(f"{path.stem}_edges.csv")
        nodes_path.write_text(nodes_csv, encoding="utf-8")
        edges_path.write_text(edges_csv, encoding="utf-8")
        return [nodes_path, edges_path]

    raise ValueError(f"Unsupported export format: {fmt}")  # pragma: no cover
