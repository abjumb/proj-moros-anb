"""Node-link JSON import — round-trips the to_json export."""

from pathlib import Path

import pytest

from mdiscovery.export.exporters import to_json
from mdiscovery.graph.models import Entity, Link, LinkDirection, SemanticType
from mdiscovery.importer.json_import import load_node_link_json


def _sample():
    entities = [
        Entity(label="Alice", id="a", semantic_type=SemanticType.PERSON,
               properties={"role": "analyst"}),
        Entity(label="Acme", id="o", semantic_type=SemanticType.ORGANIZATION),
    ]
    links = [Link(source_id="a", target_id="o", id="ao", link_type="works_at",
                  direction=LinkDirection.UNDIRECTED, strength=0.5)]
    return entities, links


def test_round_trip(tmp_path: Path):
    entities, links = _sample()
    p = tmp_path / "case.json"
    p.write_text(to_json(entities, links), encoding="utf-8")

    loaded_entities, loaded_links = load_node_link_json(p)
    assert {e.id for e in loaded_entities} == {"a", "o"}
    by_id = {e.id: e for e in loaded_entities}
    assert by_id["a"].label == "Alice"
    assert by_id["a"].properties == {"role": "analyst"}
    assert by_id["a"].semantic_type == SemanticType.PERSON

    assert len(loaded_links) == 1
    l = loaded_links[0]
    assert (l.source_id, l.target_id, l.link_type) == ("a", "o", "works_at")
    assert l.direction == LinkDirection.UNDIRECTED
    assert l.strength == 0.5


def test_invalid_json_raises(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Not valid JSON"):
        load_node_link_json(p)


def test_non_object_root_raises(tmp_path: Path):
    p = tmp_path / "arr.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="Expected a JSON object"):
        load_node_link_json(p)


def test_unknown_link_endpoint_raises(tmp_path: Path):
    p = tmp_path / "dangling.json"
    p.write_text(
        '{"nodes": [{"id": "a", "label": "A"}],'
        ' "links": [{"id": "l", "source_id": "a", "target_id": "ghost"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown entity"):
        load_node_link_json(p)


def test_malformed_node_raises_with_index(tmp_path: Path):
    p = tmp_path / "noid.json"
    p.write_text('{"nodes": [{"label": "missing id"}], "links": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid node at index 0"):
        load_node_link_json(p)
