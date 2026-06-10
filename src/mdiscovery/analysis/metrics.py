"""M3: Graph metrics computed over Entity/Link collections.

These functions operate on plain lists of ``Entity`` and ``Link`` so they are
trivially unit-testable and decoupled from the Kuzu backend. Thin ``*_from_repo``
helpers pull the collections from a ``GraphRepository`` for app use.

Direction handling: a ``DIRECTED`` link contributes out-degree to its source and
in-degree to its target. ``UNDIRECTED`` / ``BIDIRECTIONAL`` links contribute in
both directions. ``total_degree`` counts incident links regardless of direction,
which is the intuitive "how connected is this node" measure. Connected components
always treat the graph as undirected.
"""

from __future__ import annotations

import random
from collections import defaultdict, deque
from dataclasses import dataclass, field

from ..graph.models import Entity, Link, LinkDirection


@dataclass
class DegreeStats:
    entity_id: str
    label: str
    in_degree: int
    out_degree: int
    total_degree: int


@dataclass
class GraphSummary:
    entity_count: int
    link_count: int
    component_count: int
    largest_component_size: int
    density: float
    entities_by_type: dict[str, int] = field(default_factory=dict)
    links_by_type: dict[str, int] = field(default_factory=dict)
    top_entities: list[DegreeStats] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entity_count": self.entity_count,
            "link_count": self.link_count,
            "component_count": self.component_count,
            "largest_component_size": self.largest_component_size,
            "density": self.density,
            "entities_by_type": dict(self.entities_by_type),
            "links_by_type": dict(self.links_by_type),
            "top_entities": [
                {
                    "id": d.entity_id,
                    "label": d.label,
                    "in_degree": d.in_degree,
                    "out_degree": d.out_degree,
                    "total_degree": d.total_degree,
                }
                for d in self.top_entities
            ],
        }


def _is_symmetric(link: Link) -> bool:
    return link.direction in (LinkDirection.UNDIRECTED, LinkDirection.BIDIRECTIONAL)


def _undirected_adjacency(
    entities: list[Entity], links: list[Link]
) -> dict[str, set[str]]:
    """Shared adjacency for connectivity-style metrics: undirected, de-duplicated
    parallel links, self-loops dropped."""
    known = {e.id for e in entities}
    adj: dict[str, set[str]] = {e.id: set() for e in entities}
    for link in links:
        s, t = link.source_id, link.target_id
        if s in known and t in known and s != t:
            adj[s].add(t)
            adj[t].add(s)
    return adj


def degree_centrality(entities: list[Entity], links: list[Link]) -> list[DegreeStats]:
    """Per-entity in/out/total degree, sorted by total degree descending.

    Links that reference an unknown entity id are ignored for the directed
    counts but still cannot create phantom nodes — only ids present in
    ``entities`` appear in the result.
    """
    in_deg: dict[str, int] = defaultdict(int)
    out_deg: dict[str, int] = defaultdict(int)
    incident: dict[str, int] = defaultdict(int)

    known = {e.id for e in entities}
    for link in links:
        s, t = link.source_id, link.target_id
        if s in known:
            out_deg[s] += 1
            incident[s] += 1
        if t in known:
            in_deg[t] += 1
            incident[t] += 1
        if _is_symmetric(link):
            if t in known:
                out_deg[t] += 1
            if s in known:
                in_deg[s] += 1

    stats = [
        DegreeStats(
            entity_id=e.id,
            label=e.label,
            in_degree=in_deg[e.id],
            out_degree=out_deg[e.id],
            total_degree=incident[e.id],
        )
        for e in entities
    ]
    stats.sort(key=lambda d: (d.total_degree, d.label), reverse=True)
    return stats


def connected_components(entities: list[Entity], links: list[Link]) -> list[set[str]]:
    """Weakly-connected components (graph treated as undirected).

    Returns a list of id-sets sorted by size descending. Isolated entities
    each form their own singleton component.
    """
    adj = _undirected_adjacency(entities, links)

    seen: set[str] = set()
    components: list[set[str]] = []
    for node in adj:
        if node in seen:
            continue
        comp: set[str] = set()
        queue = deque([node])
        seen.add(node)
        while queue:
            cur = queue.popleft()
            comp.add(cur)
            for nbr in adj[cur]:
                if nbr not in seen:
                    seen.add(nbr)
                    queue.append(nbr)
        components.append(comp)

    components.sort(key=len, reverse=True)
    return components


def _density(node_count: int, edge_count: int) -> float:
    """Directed-graph density: edges / (n * (n - 1)). 0 for n < 2."""
    if node_count < 2:
        return 0.0
    return edge_count / (node_count * (node_count - 1))


def graph_summary(
    entities: list[Entity],
    links: list[Link],
    top_n: int = 10,
) -> GraphSummary:
    """Aggregate overview combining type breakdowns, components, and degree."""
    entities_by_type: dict[str, int] = defaultdict(int)
    for e in entities:
        entities_by_type[e.semantic_type.value] += 1

    links_by_type: dict[str, int] = defaultdict(int)
    for link in links:
        links_by_type[link.link_type] += 1

    components = connected_components(entities, links)
    degrees = degree_centrality(entities, links)

    return GraphSummary(
        entity_count=len(entities),
        link_count=len(links),
        component_count=len(components),
        largest_component_size=len(components[0]) if components else 0,
        density=_density(len(entities), len(links)),
        entities_by_type=dict(sorted(entities_by_type.items())),
        links_by_type=dict(sorted(links_by_type.items())),
        top_entities=degrees[:top_n],
    )


# --- social network analysis ------------------------------------------------
#
# Like components, these treat the graph as undirected and de-duplicate
# parallel links (adjacency is a set): brokerage/closeness/influence questions
# are about who can reach whom, not arrow direction.

def betweenness_centrality(
    entities: list[Entity],
    links: list[Link],
    *,
    normalized: bool = True,
    sample_size: int | None = None,
    seed: int = 42,
) -> dict[str, float]:
    """Brandes betweenness: how often a node sits on shortest paths.

    Normalized scores divide by (n-1)(n-2)/2 — the maximum possible for an
    undirected graph — so values are comparable across graph sizes.

    Exact Brandes is O(V·E); for large graphs pass ``sample_size`` to run the
    standard pivot approximation (accumulate from k sampled sources, scale by
    n/k). With ``sample_size >= n`` results are exact.
    """
    adj = _undirected_adjacency(entities, links)
    bc: dict[str, float] = {v: 0.0 for v in adj}

    sources = list(adj)
    scale_up = 1.0
    if sample_size is not None and 0 < sample_size < len(sources):
        sources = random.Random(seed).sample(sources, sample_size)
        scale_up = len(adj) / sample_size

    for s in sources:
        # Single-source shortest paths (BFS — unweighted).
        stack: list[str] = []
        preds: dict[str, list[str]] = {v: [] for v in adj}
        sigma: dict[str, float] = {v: 0.0 for v in adj}
        dist: dict[str, int] = {v: -1 for v in adj}
        sigma[s], dist[s] = 1.0, 0
        queue = deque([s])
        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in adj[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    preds[w].append(v)
        # Back-propagate dependencies.
        delta: dict[str, float] = {v: 0.0 for v in adj}
        while stack:
            w = stack.pop()
            for v in preds[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                bc[w] += delta[w]

    for v in bc:
        bc[v] *= scale_up / 2.0  # halve double-counted pairs; rescale samples
    if normalized:
        n = len(adj)
        scale = (n - 1) * (n - 2) / 2.0
        if scale > 0:
            for v in bc:
                bc[v] /= scale
    return bc


def closeness_centrality(
    entities: list[Entity], links: list[Link]
) -> dict[str, float]:
    """Closeness with Wasserman-Faust component scaling.

    ``((r-1)/(n-1)) * ((r-1)/sum_d)`` where r is the node's reachable-set
    size — keeps scores comparable across disconnected components. Isolated
    nodes score 0.
    """
    adj = _undirected_adjacency(entities, links)
    n = len(adj)
    out: dict[str, float] = {}
    for s in adj:
        dist = {s: 0}
        queue = deque([s])
        total = 0
        while queue:
            v = queue.popleft()
            for w in adj[v]:
                if w not in dist:
                    dist[w] = dist[v] + 1
                    total += dist[w]
                    queue.append(w)
        r = len(dist)
        if r > 1 and n > 1 and total > 0:
            out[s] = ((r - 1) / (n - 1)) * ((r - 1) / total)
        else:
            out[s] = 0.0
    return out


def eigenvector_centrality(
    entities: list[Entity],
    links: list[Link],
    *,
    max_iter: int = 100,
    tol: float = 1.0e-6,
) -> dict[str, float]:
    """Power-iteration eigenvector centrality, scaled so the max score is 1.

    On disconnected graphs the dominant component wins and other components
    tend toward 0 — acceptable for "who is most influential overall".
    """
    adj = _undirected_adjacency(entities, links)
    if not adj:
        return {}
    score = {v: 1.0 for v in adj}
    for _ in range(max_iter):
        prev = score
        score = {v: 0.0 for v in adj}
        for v in adj:
            for w in adj[v]:
                score[w] += prev[v]
        norm = sum(x * x for x in score.values()) ** 0.5
        if norm == 0:  # no edges at all
            return {v: 0.0 for v in adj}
        score = {v: x / norm for v, x in score.items()}
        if sum(abs(score[v] - prev[v]) for v in adj) < len(adj) * tol:
            break
    peak = max(score.values())
    if peak > 0:
        score = {v: x / peak for v, x in score.items()}
    return score


def label_propagation_communities(
    entities: list[Entity],
    links: list[Link],
    *,
    max_iter: int = 20,
    seed: int = 42,
) -> list[set[str]]:
    """Community detection via label propagation (seeded, so deterministic).

    Returns id-sets sorted by size descending; isolated entities form
    singleton communities.
    """
    adj = _undirected_adjacency(entities, links)
    labels = {v: v for v in adj}
    rng = random.Random(seed)
    order = list(adj)

    for _ in range(max_iter):
        rng.shuffle(order)
        changed = False
        for v in order:
            if not adj[v]:
                continue
            counts: dict[str, int] = defaultdict(int)
            for w in adj[v]:
                counts[labels[w]] += 1
            best = max(counts.values())
            # Deterministic tie-break: smallest label among the most frequent.
            new_label = min(l for l, c in counts.items() if c == best)
            if new_label != labels[v]:
                labels[v] = new_label
                changed = True
        if not changed:
            break

    groups: dict[str, set[str]] = defaultdict(set)
    for v, label in labels.items():
        groups[label].add(v)
    return sorted(groups.values(), key=len, reverse=True)


# --- repository convenience wrappers ---------------------------------------

def degree_centrality_from_repo(repo) -> list[DegreeStats]:
    return degree_centrality(repo.entities.all(), repo.links.all())


def connected_components_from_repo(repo) -> list[set[str]]:
    return connected_components(repo.entities.all(), repo.links.all())


def graph_summary_from_repo(repo, top_n: int = 10) -> GraphSummary:
    return graph_summary(repo.entities.all(), repo.links.all(), top_n=top_n)


def betweenness_centrality_from_repo(repo) -> dict[str, float]:
    return betweenness_centrality(repo.entities.all(), repo.links.all())


def closeness_centrality_from_repo(repo) -> dict[str, float]:
    return closeness_centrality(repo.entities.all(), repo.links.all())


def eigenvector_centrality_from_repo(repo) -> dict[str, float]:
    return eigenvector_centrality(repo.entities.all(), repo.links.all())


def label_propagation_communities_from_repo(repo) -> list[set[str]]:
    return label_propagation_communities(repo.entities.all(), repo.links.all())
