"""AS-22: Repository abstraction tests — 21 tests covering CRUD, traversal, stats."""

import tempfile
import pytest

from mdiscovery.graph.database import GraphDatabase
from mdiscovery.graph.models import Entity, Link, SemanticType, LinkDirection
from mdiscovery.graph.repository import EntityRepository, LinkRepository, GraphRepository


@pytest.fixture
def db(tmp_path):
    d = GraphDatabase(tmp_path / "testdb")
    yield d
    d.close()


@pytest.fixture
def repo(db):
    return GraphRepository(db)


@pytest.fixture
def alice(repo):
    e = Entity(label="Alice", semantic_type=SemanticType.PERSON)
    repo.entities.upsert(e)
    return e


@pytest.fixture
def bob(repo):
    e = Entity(label="Bob", semantic_type=SemanticType.PERSON)
    repo.entities.upsert(e)
    return e


@pytest.fixture
def acme(repo):
    e = Entity(label="Acme Corp", semantic_type=SemanticType.ORGANIZATION)
    repo.entities.upsert(e)
    return e


# ── Entity CRUD ───────────────────────────────────────────────────────

def test_entity_upsert_and_get(repo, alice):
    fetched = repo.entities.get(alice.id)
    assert fetched is not None
    assert fetched.label == "Alice"
    assert fetched.semantic_type == SemanticType.PERSON


def test_entity_get_missing_returns_none(repo):
    assert repo.entities.get("nonexistent-id") is None


def test_entity_upsert_updates_existing(repo, alice):
    alice.label = "Alice Smith"
    repo.entities.upsert(alice)
    fetched = repo.entities.get(alice.id)
    assert fetched.label == "Alice Smith"


def test_entity_delete(repo, alice):
    repo.entities.delete(alice.id)
    assert repo.entities.get(alice.id) is None


def test_entity_count_empty(repo):
    assert repo.entities.count() == 0


def test_entity_count_after_inserts(repo, alice, bob, acme):
    assert repo.entities.count() == 3


def test_entity_all(repo, alice, bob):
    entities = repo.entities.all()
    ids = {e.id for e in entities}
    assert alice.id in ids
    assert bob.id in ids


def test_entity_search(repo, alice, bob):
    results = repo.entities.search("Ali")
    assert len(results) == 1
    assert results[0].label == "Alice"


def test_entity_search_no_match(repo, alice):
    assert repo.entities.search("Zzz") == []


def test_entity_by_type(repo, alice, bob, acme):
    persons = repo.entities.by_type(SemanticType.PERSON)
    assert len(persons) == 2
    orgs = repo.entities.by_type(SemanticType.ORGANIZATION)
    assert len(orgs) == 1


# ── Link CRUD ─────────────────────────────────────────────────────────

def test_link_upsert_and_all(repo, alice, bob):
    link = Link(source_id=alice.id, target_id=bob.id, link_type="knows")
    repo.links.upsert(link)
    all_links = repo.links.all()
    assert len(all_links) == 1
    assert all_links[0].link_type == "knows"


def test_link_count(repo, alice, bob):
    repo.links.upsert(Link(source_id=alice.id, target_id=bob.id))
    assert repo.links.count() == 1


def test_link_for_entity(repo, alice, bob, acme):
    repo.links.upsert(Link(source_id=alice.id, target_id=bob.id, link_type="knows"))
    repo.links.upsert(Link(source_id=alice.id, target_id=acme.id, link_type="works_at"))
    links = repo.links.for_entity(alice.id)
    assert len(links) == 2


def test_link_delete(repo, alice, bob):
    link = Link(source_id=alice.id, target_id=bob.id)
    repo.links.upsert(link)
    repo.links.delete(link.id)
    assert repo.links.count() == 0


def test_link_idempotent_upsert(repo, alice, bob):
    link = Link(source_id=alice.id, target_id=bob.id)
    repo.links.upsert(link)
    repo.links.upsert(link)  # second call should be a no-op
    assert repo.links.count() == 1


# ── GraphRepository facade ────────────────────────────────────────────

def test_stats(repo, alice, bob):
    repo.links.upsert(Link(source_id=alice.id, target_id=bob.id))
    stats = repo.stats()
    assert stats["entity_count"] == 2
    assert stats["link_count"] == 1


def test_get_graph_json_structure(repo, alice, bob):
    repo.links.upsert(Link(source_id=alice.id, target_id=bob.id))
    gj = repo.get_graph_json()
    assert "nodes" in gj and "edges" in gj
    assert len(gj["nodes"]) == 2
    assert len(gj["edges"]) == 1


def test_neighbors(repo, alice, bob, acme):
    repo.links.upsert(Link(source_id=alice.id, target_id=bob.id))
    repo.links.upsert(Link(source_id=alice.id, target_id=acme.id))
    nbrs = repo.neighbors(alice.id)
    nbr_ids = {n.id for n in nbrs}
    assert bob.id in nbr_ids
    assert acme.id in nbr_ids


def test_clear(repo, alice, bob):
    repo.links.upsert(Link(source_id=alice.id, target_id=bob.id))
    repo.clear()
    assert repo.entities.count() == 0
    assert repo.links.count() == 0


def test_entity_properties_roundtrip(repo):
    e = Entity(label="Doc42", semantic_type=SemanticType.DOCUMENT, properties={"page_count": "12", "author": "Smith"})
    repo.entities.upsert(e)
    fetched = repo.entities.get(e.id)
    assert fetched.properties["author"] == "Smith"
    assert fetched.properties["page_count"] == "12"


def test_link_undirected(repo, alice, bob):
    link = Link(source_id=alice.id, target_id=bob.id, direction=LinkDirection.UNDIRECTED)
    repo.links.upsert(link)
    links = repo.links.all()
    assert links[0].direction == LinkDirection.UNDIRECTED


# ── Batch upserts, search, and incremental-expand support ─────────────

def test_entity_search_case_insensitive(repo, alice):
    assert [e.label for e in repo.entities.search("aLiC")] == ["Alice"]


def test_entity_all_ids(repo, alice, bob):
    assert repo.entities.all_ids() == {alice.id, bob.id}


def test_entity_upsert_batch_bulk(repo):
    batch = [Entity(label=f"E{i}", id=f"e{i}") for i in range(50)]
    repo.entities.upsert_batch(batch)
    assert repo.entities.count() == 50
    # Re-running the same batch updates rather than duplicates.
    repo.entities.upsert_batch(batch)
    assert repo.entities.count() == 50


def test_entity_upsert_batch_empty_noop(repo):
    repo.entities.upsert_batch([])
    assert repo.entities.count() == 0


def test_link_upsert_batch_bulk_and_idempotent(repo):
    repo.entities.upsert_batch([Entity(label=f"E{i}", id=f"e{i}") for i in range(10)])
    links = [
        Link(source_id=f"e{i}", target_id=f"e{i+1}", id=f"l{i}")
        for i in range(9)
    ]
    repo.links.upsert_batch(links)
    assert repo.links.count() == 9
    repo.links.upsert_batch(links)  # same ids — skipped, not duplicated
    assert repo.links.count() == 9


def test_link_upsert_batch_missing_endpoint_dropped(repo, alice):
    repo.links.upsert_batch([
        Link(source_id=alice.id, target_id="ghost-id", id="lg"),
    ])
    assert repo.links.count() == 0


def test_link_for_entity_preserves_direction(repo, alice, bob):
    repo.links.upsert(Link(source_id=bob.id, target_id=alice.id, link_type="manages"))
    links = repo.links.for_entity(alice.id)
    assert len(links) == 1
    # Alice is the *target* of the incoming link — direction must survive.
    assert links[0].source_id == bob.id
    assert links[0].target_id == alice.id


def test_neighborhood_payload(repo, alice, bob, acme):
    repo.links.upsert(Link(source_id=alice.id, target_id=bob.id, id="l1"))
    repo.links.upsert(Link(source_id=acme.id, target_id=alice.id, id="l2"))
    payload = repo.neighborhood(alice.id)
    node_ids = {n["data"]["id"] for n in payload["nodes"]}
    edge_ids = {e["data"]["id"] for e in payload["edges"]}
    assert node_ids == {bob.id, acme.id}
    assert edge_ids == {"l1", "l2"}
