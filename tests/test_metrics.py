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


# ── Social network analysis ───────────────────────────────────────────

from mdiscovery.analysis.metrics import (
    betweenness_centrality,
    closeness_centrality,
    eigenvector_centrality,
    label_propagation_communities,
)


def _path_graph():
    """a — b — c — d — e (directed chain; SNA treats it as undirected)."""
    entities = [Entity(label=i.upper(), id=i) for i in "abcde"]
    links = [
        Link(source_id=s, target_id=t, id=f"{s}{t}")
        for s, t in [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")]
    ]
    return entities, links


def test_betweenness_path_graph_center_highest():
    entities, links = _path_graph()
    bc = betweenness_centrality(entities, links)
    assert bc["c"] > bc["b"] > bc["a"]
    assert bc["a"] == 0.0 and bc["e"] == 0.0
    # Center of a 5-path lies on 4 of the 6 pairs: 4/6 normalized.
    assert abs(bc["c"] - 4 / 6) < 1e-9


def test_betweenness_star_center_is_one():
    entities, links = _star()
    bc = betweenness_centrality(entities, links)
    assert abs(bc["h"] - 1.0) < 1e-9
    assert all(bc[i] == 0.0 for i in ("a", "b", "c"))


def test_closeness_star():
    entities, links = _star()
    cc = closeness_centrality(entities, links)
    assert abs(cc["h"] - 1.0) < 1e-9          # center reaches all in 1 hop
    assert abs(cc["a"] - 0.6) < 1e-9          # (3/3) * (3/5)
    isolated = entities + [Entity(label="Z", id="z")]
    assert closeness_centrality(isolated, links)["z"] == 0.0


def test_eigenvector_star_center_max():
    entities, links = _star()
    ec = eigenvector_centrality(entities, links)
    assert abs(ec["h"] - 1.0) < 1e-6
    assert all(ec[i] < 1.0 for i in ("a", "b", "c"))


def test_eigenvector_no_edges_all_zero():
    entities = [Entity(label="A", id="a"), Entity(label="B", id="b")]
    ec = eigenvector_centrality(entities, [])
    assert ec == {"a": 0.0, "b": 0.0}


def test_communities_disconnected_triangles():
    entities = [Entity(label=i.upper(), id=i) for i in "abcdefg"]
    tri = lambda x, y, z: [
        Link(source_id=x, target_id=y, id=x + y),
        Link(source_id=y, target_id=z, id=y + z),
        Link(source_id=z, target_id=x, id=z + x),
    ]
    links = tri("a", "b", "c") + tri("d", "e", "f")  # 'g' stays isolated
    comms = label_propagation_communities(entities, links)
    assert {frozenset(c) for c in comms} == {
        frozenset({"a", "b", "c"}), frozenset({"d", "e", "f"}), frozenset({"g"}),
    }
    assert len(comms[0]) >= len(comms[-1])  # sorted by size desc


def test_communities_deterministic():
    entities, links = _path_graph()
    runs = [label_propagation_communities(entities, links) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


def test_betweenness_sampled_full_size_is_exact():
    # sample_size >= n short-circuits the sampling branch → exact result.
    entities, links = _path_graph()
    exact = betweenness_centrality(entities, links)
    sampled = betweenness_centrality(entities, links, sample_size=len(entities))
    assert sampled == exact


def test_betweenness_sampled_preserves_ranking():
    # Star graph: any source sample still ranks the hub far above leaves.
    entities, links = _star()
    sampled = betweenness_centrality(entities, links, sample_size=2, seed=7)
    assert sampled["h"] >= max(sampled[i] for i in ("a", "b", "c"))


def test_betweenness_sampled_is_unbiased():
    """The n/k pivot scaling must recover the exact magnitude, not half/double.

    Regression guard for the `scale_up / 2.0` factor: averaged over many seeds
    the sampled estimate tracks exact betweenness within tolerance.
    """
    import random as _random
    n = 40
    entities = [Entity(label=f"E{i}", id=f"e{i}") for i in range(n)]
    rng = _random.Random(0)
    links = [Link(source_id=f"e{i}", target_id=f"e{rng.randrange(i)}", id=f"t{i}")
             for i in range(1, n)]  # random tree → connected
    exact = betweenness_centrality(entities, links, normalized=False)
    runs = [betweenness_centrality(entities, links, normalized=False,
                                   sample_size=15, seed=s) for s in range(150)]
    avg = {v: sum(r[v] for r in runs) / len(runs) for v in exact}
    hubs = [v for v in exact if exact[v] > 5]
    assert hubs  # the tree has real brokers
    for v in hubs:
        assert abs(avg[v] - exact[v]) / exact[v] < 0.15, (v, avg[v], exact[v])


def test_recommended_sample_size_policy():
    from mdiscovery.analysis.metrics import (
        recommended_sample_size, BETWEENNESS_EXACT_LIMIT, BETWEENNESS_SAMPLE,
    )
    assert recommended_sample_size(BETWEENNESS_EXACT_LIMIT) is None
    assert recommended_sample_size(BETWEENNESS_EXACT_LIMIT + 1) == BETWEENNESS_SAMPLE
