"""M3: graph metrics — degree centrality, components, summary."""

from mdiscovery.graph.models import Entity, Link, SemanticType, LinkDirection
from mdiscovery.analysis.metrics import (
    degree_centrality,
    connected_components,
    graph_summary,
)


def _star():
    """Hub 'h' linked out to three leaves a, b, c (directed)."""
    entities = [
        Entity(label="Hub", id="h", semantic_type=SemanticType.PERSON),
        Entity(label="A", id="a", semantic_type=SemanticType.PERSON),
        Entity(label="B", id="b", semantic_type=SemanticType.ORGANIZATION),
        Entity(label="C", id="c", semantic_type=SemanticType.ORGANIZATION),
    ]
    links = [
        Link(source_id="h", target_id="a", id="ha"),
        Link(source_id="h", target_id="b", id="hb"),
        Link(source_id="h", target_id="c", id="hc"),
    ]
    return entities, links


def test_degree_directed_counts():
    entities, links = _star()
    stats = {d.entity_id: d for d in degree_centrality(entities, links)}
    assert stats["h"].out_degree == 3
    assert stats["h"].in_degree == 0
    assert stats["h"].total_degree == 3
    assert stats["a"].in_degree == 1
    assert stats["a"].out_degree == 0
    assert stats["a"].total_degree == 1


def test_degree_sorted_by_total_desc():
    entities, links = _star()
    stats = degree_centrality(entities, links)
    assert stats[0].entity_id == "h"
    assert [d.total_degree for d in stats] == sorted(
        [d.total_degree for d in stats], reverse=True
    )


def test_undirected_link_counts_both_directions():
    entities = [Entity(label="A", id="a"), Entity(label="B", id="b")]
    links = [Link(source_id="a", target_id="b", id="ab",
                  direction=LinkDirection.UNDIRECTED)]
    stats = {d.entity_id: d for d in degree_centrality(entities, links)}
    assert stats["a"].in_degree == 1 and stats["a"].out_degree == 1
    assert stats["b"].in_degree == 1 and stats["b"].out_degree == 1


def test_link_to_unknown_entity_is_ignored():
    entities = [Entity(label="A", id="a")]
    links = [Link(source_id="a", target_id="ghost", id="ag")]
    stats = {d.entity_id: d for d in degree_centrality(entities, links)}
    assert set(stats) == {"a"}
    assert stats["a"].out_degree == 1
    assert stats["a"].total_degree == 1


def test_connected_components_splits_disjoint_graphs():
    entities = [Entity(label=n, id=n) for n in ["a", "b", "c", "d", "e"]]
    links = [
        Link(source_id="a", target_id="b", id="ab"),
        Link(source_id="b", target_id="c", id="bc"),
        Link(source_id="d", target_id="e", id="de"),
    ]
    comps = connected_components(entities, links)
    assert len(comps) == 2
    assert comps[0] == {"a", "b", "c"}  # largest first
    assert comps[1] == {"d", "e"}


def test_isolated_entity_is_singleton_component():
    entities = [Entity(label="lonely", id="x")]
    comps = connected_components(entities, [])
    assert comps == [{"x"}]


def test_graph_summary_aggregates():
    entities, links = _star()
    summary = graph_summary(entities, links)
    assert summary.entity_count == 4
    assert summary.link_count == 3
    assert summary.component_count == 1
    assert summary.largest_component_size == 4
    assert summary.entities_by_type == {"Organization": 2, "Person": 2}
    assert summary.links_by_type == {"relates_to": 3}
    assert summary.top_entities[0].entity_id == "h"


def test_density_empty_graph_is_zero():
    summary = graph_summary([], [])
    assert summary.density == 0.0
    assert summary.component_count == 0
    assert summary.largest_component_size == 0
