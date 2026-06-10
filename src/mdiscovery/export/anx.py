"""ANX (i2 Analyst's Notebook chart XML) export.

Targets the publicly known i2 chart-XML structure: a ``Chart`` of
``ChartItem`` elements where entity items carry an ``End``/``Entity`` with an
``Icon`` style and link items reference their endpoints via ``End1Id``/
``End2Id``, with free attributes in an ``AttributeCollection``.

FIDELITY CAVEAT: written against the publicly documented shape and validated
by round-trip with ``importer.anx_import`` — final verification against a
real Analyst's Notebook installation still requires reference .anx files.
Adjust ``ANX_TYPE_BY_SEMANTIC`` / structural details there, not at call sites.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ..graph.models import Entity, Link, LinkDirection, SemanticType

# Our semantic types -> i2 icon style types. Identity-ish mapping kept in one
# table so it can be corrected against reference charts without code churn.
ANX_TYPE_BY_SEMANTIC: dict[SemanticType, str] = {
    SemanticType.PERSON:       "Person",
    SemanticType.ORGANIZATION: "Organization",
    SemanticType.LOCATION:     "Location",
    SemanticType.EVENT:        "Event",
    SemanticType.DOCUMENT:     "Document",
    SemanticType.VEHICLE:      "Vehicle",
    SemanticType.PHONE:        "Telephone",
    SemanticType.EMAIL:        "Email",
    SemanticType.ACCOUNT:      "Account",
    SemanticType.UNKNOWN:      "General",
}

ARROW_BY_DIRECTION: dict[LinkDirection, str] = {
    LinkDirection.DIRECTED:      "ArrowOnHead",
    LinkDirection.UNDIRECTED:    "ArrowNone",
    LinkDirection.BIDIRECTIONAL: "ArrowOnBoth",
}


def _add_attributes(item: ET.Element, properties: dict) -> None:
    if not properties:
        return
    collection = ET.SubElement(item, "AttributeCollection")
    for key, value in properties.items():
        ET.SubElement(collection, "Attribute", {
            "AttributeClass": str(key),
            "Value": str(value),
        })


def to_anx(entities: list[Entity], links: list[Link]) -> str:
    """Render the graph as an i2 chart XML document string."""
    chart = ET.Element("Chart", {"Generator": "mDiscovery"})
    items = ET.SubElement(chart, "ChartItemCollection")

    for entity in entities:
        item_attrs = {"Label": entity.label}
        if "x" in entity.style:
            item_attrs["XPosition"] = str(entity.style["x"])
        item = ET.SubElement(items, "ChartItem", item_attrs)
        end_attrs = {}
        if "y" in entity.style:
            end_attrs["Y"] = str(entity.style["y"])
        end = ET.SubElement(item, "End", end_attrs)
        node = ET.SubElement(end, "Entity", {
            "EntityId": entity.id,
            "Identity": entity.label,
        })
        icon = ET.SubElement(node, "Icon")
        ET.SubElement(icon, "IconStyle", {
            "Type": ANX_TYPE_BY_SEMANTIC.get(entity.semantic_type, "General"),
        })
        _add_attributes(item, entity.properties)

    for link in links:
        item = ET.SubElement(items, "ChartItem", {"Label": link.link_type})
        link_el = ET.SubElement(item, "Link", {
            "End1Id": link.source_id,
            "End2Id": link.target_id,
        })
        ET.SubElement(link_el, "LinkStyle", {
            "ArrowStyle": ARROW_BY_DIRECTION.get(link.direction, "ArrowOnHead"),
            "Strength": str(link.strength),
        })
        _add_attributes(item, link.properties)

    ET.indent(chart, space="  ")
    body = ET.tostring(chart, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"
