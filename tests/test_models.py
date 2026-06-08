"""AS-10: data model serialization round-trips."""

from mdiscovery.graph.models import Entity, Link, SemanticType, LinkDirection


def test_entity_defaults():
    e = Entity(label="Alice")
    assert e.semantic_type is SemanticType.UNKNOWN
    assert e.id  # auto uuid
    assert e.properties == {}


def test_entity_roundtrip():
    e = Entity(label="Alice", semantic_type=SemanticType.PERSON,
               id="x1", properties={"age": 34, "city": "London"})
    d = e.to_dict()
    e2 = Entity.from_dict(d)
    assert e2 == e


def test_entity_from_dict_with_json_string_props():
    e = Entity.from_dict({
        "id": "x1", "label": "Org", "semantic_type": "Organization",
        "properties": '{"sector": "finance"}',
    })
    assert e.semantic_type is SemanticType.ORGANIZATION
    assert e.properties == {"sector": "finance"}


def test_entity_cytoscape_shape():
    e = Entity(label="Alice", semantic_type=SemanticType.PERSON, id="x1",
               properties={"age": 34})
    cyto = e.to_cytoscape()
    assert cyto["data"]["id"] == "x1"
    assert cyto["data"]["label"] == "Alice"
    assert cyto["data"]["type"] == "Person"
    assert cyto["data"]["age"] == "34"  # stringified


def test_link_roundtrip():
    l = Link(source_id="a", target_id="b", link_type="knows",
             direction=LinkDirection.UNDIRECTED, strength=0.5, confidence=0.9, id="r1")
    d = l.to_dict()
    l2 = Link.from_dict(d)
    assert l2 == l


def test_link_cytoscape_shape():
    l = Link(source_id="a", target_id="b", link_type="knows", id="r1")
    cyto = l.to_cytoscape()
    assert cyto["data"]["source"] == "a"
    assert cyto["data"]["target"] == "b"
    assert cyto["data"]["type"] == "knows"
