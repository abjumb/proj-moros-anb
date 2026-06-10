"""AS-22 / AS-41: shortest-path traversal via the repository."""

from mdiscovery.graph.models import Entity, Link, SemanticType
from mdiscovery.graph.repository import GraphRepository


def _chain(repo: GraphRepository) -> None:
    repo.entities.upsert_batch([
        Entity(label=n, id=i, semantic_type=SemanticType.PERSON)
        for i, n in [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")]
    ])
    repo.links.upsert_batch([
        Link(source_id="a", target_id="b", id="ab"),
        Link(source_id="b", target_id="c", id="bc"),
        Link(source_id="c", target_id="d", id="cd"),
    ])


def test_find_path_returns_full_chain(repo: GraphRepository):
    _chain(repo)
    path = repo.find_path("a", "d")
    assert path[0] == "a"
    assert path[-1] == "d"
    assert path == ["a", "b", "c", "d"]


def test_find_path_direct(repo: GraphRepository):
    _chain(repo)
    assert repo.find_path("a", "b") == ["a", "b"]


def test_find_path_no_connection(repo: GraphRepository):
    repo.entities.upsert(Entity(label="X", id="x"))
    repo.entities.upsert(Entity(label="Y", id="y"))
    assert repo.find_path("x", "y") == []


def test_find_path_ignores_link_direction(repo: GraphRepository):
    """Connectivity is undirected — a reverse-direction chain still connects."""
    _chain(repo)
    assert repo.find_path("d", "a") == ["d", "c", "b", "a"]


def test_find_path_mixed_directions(repo: GraphRepository):
    repo.entities.upsert_batch([
        Entity(label=n, id=i) for i, n in [("x", "X"), ("y", "Y"), ("z", "Z")]
    ])
    # x -> y <- z : no directed path x..z, but an undirected one exists.
    repo.links.upsert_batch([
        Link(source_id="x", target_id="y", id="xy"),
        Link(source_id="z", target_id="y", id="zy"),
    ])
    assert repo.find_path("x", "z") == ["x", "y", "z"]
