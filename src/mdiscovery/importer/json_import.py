"""Node-link JSON import — the inverse of ``export.exporters.to_json``.

Pure loader: parses and validates a node-link document into ``Entity`` and
``Link`` lists without touching the database, so it is unit-testable and the
caller decides when to commit (mirroring the CSV/XLSX pipeline's
preview-before-write philosophy).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..graph.models import Entity, Link


def load_node_link_json(path: str | Path) -> tuple[list[Entity], list[Link]]:
    """Parse a node-link JSON file into entities and links.

    Raises ``ValueError`` with positional context for malformed documents so
    the UI can surface a useful message instead of a raw traceback.
    """
    return parse_node_link_text(Path(path).read_text(encoding="utf-8"))


def parse_node_link_text(raw: str) -> tuple[list[Entity], list[Link]]:
    """Parse node-link JSON text (file contents or clipboard payload)."""
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not valid JSON: {exc}") from exc

    if not isinstance(doc, dict):
        raise ValueError("Expected a JSON object with 'nodes' and 'links' arrays.")

    nodes_raw = doc.get("nodes", [])
    links_raw = doc.get("links", [])
    if not isinstance(nodes_raw, list) or not isinstance(links_raw, list):
        raise ValueError("'nodes' and 'links' must be arrays.")

    entities: list[Entity] = []
    for i, item in enumerate(nodes_raw):
        try:
            entities.append(Entity.from_dict(item))
        except Exception as exc:
            raise ValueError(f"Invalid node at index {i}: {exc}") from exc

    known_ids = {e.id for e in entities}
    links: list[Link] = []
    for i, item in enumerate(links_raw):
        try:
            link = Link.from_dict(item)
        except Exception as exc:
            raise ValueError(f"Invalid link at index {i}: {exc}") from exc
        if link.source_id not in known_ids or link.target_id not in known_ids:
            raise ValueError(
                f"Link at index {i} references unknown entity "
                f"({link.source_id} -> {link.target_id})."
            )
        links.append(link)

    return entities, links
