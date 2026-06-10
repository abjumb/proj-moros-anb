"""ANX (i2 Analyst's Notebook chart XML) import.

Tolerant parser for the chart-XML shape produced by ``export.anx`` and by
i2-ecosystem integrations: entity ``ChartItem``s (an ``End`` containing an
``Entity``) and link ``ChartItem``s (a ``Link`` with ``End1Id``/``End2Id``).
Unknown elements are ignored rather than rejected, since real ANB charts
carry far more styling detail than we model.

Same fidelity caveat as the exporter: validated by round-trip; verification
against real Analyst's Notebook output needs reference .anx files.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

from ..graph.models import Entity, Link, LinkDirection, SemanticType
from ..export.anx import ANX_TYPE_BY_SEMANTIC, ARROW_BY_DIRECTION

_SEMANTIC_BY_ANX = {v: k for k, v in ANX_TYPE_BY_SEMANTIC.items()}
_DIRECTION_BY_ARROW = {v: k for k, v in ARROW_BY_DIRECTION.items()}


def _attributes(item: ET.Element) -> dict[str, str]:
    return {
        attr.get("AttributeClass", ""): attr.get("Value", "")
        for attr in item.findall("./AttributeCollection/Attribute")
        if attr.get("AttributeClass")
    }


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def load_anx(path: str | Path) -> tuple[list[Entity], list[Link]]:
    """Parse an .anx chart file into entities and links.

    Raises ``ValueError`` with positional context for malformed documents.
    """
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"Not valid chart XML: {exc}") from exc

    entities: list[Entity] = []
    links: list[Link] = []

    # First pass: entities (so the link pass can validate endpoint ids).
    items = root.findall(".//ChartItem")
    for index, item in enumerate(items):
        entity_el = item.find("./End/Entity")
        if entity_el is not None:
            label = (entity_el.get("Identity") or item.get("Label") or "").strip()
            if not label:
                raise ValueError(f"ChartItem {index}: entity has no label/identity.")
            icon_type = None
            icon_style = item.find("./End/Entity/Icon/IconStyle")
            if icon_style is not None:
                icon_type = icon_style.get("Type")
            semantic = _SEMANTIC_BY_ANX.get(icon_type or "", SemanticType.UNKNOWN)

            entity_id = entity_el.get("EntityId") or hashlib.sha256(
                f"{semantic.value}::{label.lower()}".encode()).hexdigest()[:16]
            style: dict = {}
            x = _float(item.get("XPosition"))
            end = item.find("./End")
            y = _float(end.get("Y")) if end is not None else None
            if x is not None and y is not None:
                style["x"], style["y"] = x, y
            entities.append(Entity(
                id=entity_id, label=label, semantic_type=semantic,
                properties=_attributes(item), style=style,
            ))
        # Link items handled in the second pass; other ChartItem kinds
        # (theme lines, ole frames, …) are ignored.

    known_ids = {e.id for e in entities}
    for index, item in enumerate(items):
        link_el = item.find("./Link")
        if link_el is None:
            continue
        src, tgt = link_el.get("End1Id"), link_el.get("End2Id")
        if not src or not tgt:
            raise ValueError(f"ChartItem {index}: link missing End1Id/End2Id.")
        if src not in known_ids or tgt not in known_ids:
            raise ValueError(
                f"ChartItem {index}: link references unknown entity "
                f"({src} -> {tgt}).")
        link_style = link_el.find("./LinkStyle")
        arrow = link_style.get("ArrowStyle") if link_style is not None else None
        strength = _float(link_style.get("Strength")) if link_style is not None else None
        link_type = (item.get("Label") or "relates_to").strip() or "relates_to"
        links.append(Link(
            id=hashlib.sha256(
                f"{src}->{tgt}::{link_type}::{index}".encode()).hexdigest()[:16],
            source_id=src, target_id=tgt, link_type=link_type,
            direction=_DIRECTION_BY_ARROW.get(arrow or "", LinkDirection.DIRECTED),
            strength=strength if strength is not None else 1.0,
            properties=_attributes(item),
        ))

    return entities, links
