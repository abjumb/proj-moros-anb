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
    known = {e.id for e in entities}
    adj: dict[str, set[str]] = {e.id: set() for e in entities}
    for link in links:
        s, t = link.source_id, link.target_id
        if s in known and t in known:
            adj[s].add(t)
            adj[t].add(s)

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


# --- repository convenience wrappers ---------------------------------------

def degree_centrality_from_repo(repo) -> list[DegreeStats]:
    return degree_centrality(repo.entities.all(), repo.links.all())


def connected_components_from_repo(repo) -> list[set[str]]:
    return connected_components(repo.entities.all(), repo.links.all())


def graph_summary_from_repo(repo, top_n: int = 10) -> GraphSummary:
    return graph_summary(repo.entities.all(), repo.links.all(), top_n=top_n)
