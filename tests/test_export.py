"""M3: graph export — GraphML, CSV, JSON, Markdown report, and write_export."""

import json
import xml.etree.ElementTree as ET
from datetime import datetime

import pytest

from mdiscovery.graph.models import Entity, Link, SemanticType
from mdiscovery.graph.repository import GraphRepository
from mdiscovery.export.exporters import (
    ExportFormat,
    to_graphml,
    to_csv,
    to_json,
    to_report,
    write_export,
)


def _sample():
    entities = [
        Entity(label="Alice", id="a", semantic_type=SemanticType.PERSON,
               properties={"role": "analyst"}),
        Entity(label="Acme", id="b", semantic_type=SemanticType.ORGANIZATION),
    ]
    links = [
        Link(source_id="a", target_id="b", id="ab", link_type="works_at",
             strength=0.8, properties={"since": "2021"}),
    ]
    return entities, links


def test_graphml_is_wellformed_and_has_nodes_edges():
    entities, links = _sample()
    xml = to_graphml(entities, links)
    root = ET.fromstring(xml)  # raises if malformed
    ns = "{http://graphml.graphdrawing.org/xmlns}"
    graph = root.find(f"{ns}graph")
    assert len(graph.findall(f"{ns}node")) == 2
    assert len(graph.findall(f"{ns}edge")) == 1
    # property key for the entity attribute was declared
    key_names = {k.get("attr.name") for k in root.findall(f"{ns}key")}
    assert {"label", "type", "role", "since", "strength"} <= key_names


def test_graphml_escapes_special_characters():
    entities = [Entity(label="A & <B>", id="x")]
    xml = to_graphml(entities, [])
    root = ET.fromstring(xml)
    ns = "{http://graphml.graphdrawing.org/xmlns}"
    label = root.find(f".//{ns}node/{ns}data[@key='label']")
    assert label.text == "A & <B>"


def test_csv_pair_headers_and_rows():
    entities, links = _sample()
    nodes_csv, edges_csv = to_csv(entities, links)
    node_header = nodes_csv.splitlines()[0]
    assert node_header == "id,label,type,role"
    assert "Alice" in nodes_csv
    edge_header = edges_csv.splitlines()[0]
    assert edge_header == "id,source,target,link_type,direction,strength,confidence,since"
    assert "works_at" in edges_csv


def test_json_roundtrips():
    entities, links = _sample()
    payload = json.loads(to_json(entities, links))
    assert len(payload["nodes"]) == 2
    assert len(payload["links"]) == 1
    restored = Entity.from_dict(payload["nodes"][0])
    assert restored.label == "Alice"
    assert restored.properties == {"role": "analyst"}
    restored_link = Link.from_dict(payload["links"][0])
    assert restored_link.link_type == "works_at"


def test_report_contains_summary_sections():
    entities, links = _sample()
    md = to_report(entities, links, generated_at=datetime(2026, 6, 9, 12, 0))
    assert "# mDiscovery Case Report" in md
    assert "_Generated: 2026-06-09 12:00_" in md
    assert "**Entities:** 2" in md
    assert "Most connected entities" in md
    assert "Alice" in md


def test_report_timestamp_omitted_when_none():
    md = to_report([], [], generated_at=None)
    assert "Generated:" not in md
    assert "**Entities:** 0" in md


@pytest.mark.parametrize("fmt,expected_files", [
    (ExportFormat.GRAPHML, 1),
    (ExportFormat.JSON, 1),
    (ExportFormat.REPORT, 1),
    (ExportFormat.CSV, 2),
])
def test_write_export_from_repo(repo: GraphRepository, tmp_path, fmt, expected_files):
    repo.entities.upsert_batch([
        Entity(label="Alice", id="a", semantic_type=SemanticType.PERSON),
        Entity(label="Acme", id="b", semantic_type=SemanticType.ORGANIZATION),
    ])
    repo.links.upsert(Link(source_id="a", target_id="b", id="ab"))

    written = write_export(repo, tmp_path / "case", fmt)
    assert len(written) == expected_files
    for p in written:
        assert p.exists() and p.stat().st_size > 0


def test_write_export_csv_splits_node_edge_files(repo: GraphRepository, tmp_path):
    repo.entities.upsert(Entity(label="Solo", id="s"))
    written = write_export(repo, tmp_path / "case.csv", ExportFormat.CSV)
    names = sorted(p.name for p in written)
    assert names == ["case_edges.csv", "case_nodes.csv"]


def test_write_export_accepts_string_format(repo: GraphRepository, tmp_path):
    repo.entities.upsert(Entity(label="Solo", id="s"))
    written = write_export(repo, tmp_path / "g.json", "json")
    assert written[0].exists()
