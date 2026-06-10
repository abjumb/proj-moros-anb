"""AS-14 + AS-15: import preview (dry-run), commit, and idempotent re-import."""

from pathlib import Path

import pytest

from mdiscovery.graph.models import SemanticType
from mdiscovery.graph.repository import GraphRepository
from mdiscovery.importer.ingestion import IngestionService
from mdiscovery.importer.pipeline import (
    ColumnMapping, ImportMapping, ImportPipeline,
)


def _simple_mapping() -> ImportMapping:
    """name -> Person label; role/city/age -> entity attributes."""
    m = ImportMapping()
    m.column_mappings = [
        ColumnMapping(column="name", role="entity_label", semantic_type=SemanticType.PERSON),
        ColumnMapping(column="role", role="entity_attr"),
        ColumnMapping(column="city", role="entity_attr"),
        ColumnMapping(column="age", role="entity_attr"),
    ]
    return m


def _link_mapping() -> ImportMapping:
    m = ImportMapping()
    m.column_mappings = [
        ColumnMapping(column="source", role="link_source", semantic_type=SemanticType.PERSON),
        ColumnMapping(column="target", role="link_target", semantic_type=SemanticType.PERSON),
        ColumnMapping(column="relationship", role="link_type"),
    ]
    return m


def test_preview_is_dry_run(repo: GraphRepository, people_csv: Path):
    ds = IngestionService().load(people_csv)
    pipeline = ImportPipeline(repo)
    preview = pipeline.preview(ds, _simple_mapping())
    assert preview.entity_count == 5
    # AS-14: nothing is written until commit
    assert repo.entities.count() == 0


def test_commit_writes_entities_with_attrs(repo: GraphRepository, people_csv: Path):
    ds = IngestionService().load(people_csv)
    pipeline = ImportPipeline(repo)
    pipeline.commit(ds, _simple_mapping())

    assert repo.entities.count() == 5
    persons = repo.entities.by_type(SemanticType.PERSON)
    alice = next(e for e in persons if e.label == "Alice Carter")
    assert alice.properties["city"] == "London"
    assert alice.properties["role"] == "Analyst"


def test_reimport_is_idempotent(repo: GraphRepository, people_csv: Path):
    """AS-15: re-running an import must not cause a duplicate explosion."""
    ds = IngestionService().load(people_csv)
    pipeline = ImportPipeline(repo)
    pipeline.commit(ds, _simple_mapping())
    pipeline.commit(ds, _simple_mapping())
    assert repo.entities.count() == 5  # not 10


def test_reimport_flags_duplicates_in_preview(repo: GraphRepository, people_csv: Path):
    ds = IngestionService().load(people_csv)
    pipeline = ImportPipeline(repo)
    pipeline.commit(ds, _simple_mapping())
    preview = pipeline.preview(ds, _simple_mapping())
    assert preview.duplicate_entity_count == 5
    assert any("exist" in w for w in preview.warnings)


def test_link_mode_builds_entities_and_links(repo: GraphRepository, contacts_csv: Path):
    ds = IngestionService().load(contacts_csv)
    pipeline = ImportPipeline(repo)
    result = pipeline.commit(ds, _link_mapping())

    assert result.link_count == 4
    assert repo.links.count() == 4
    # endpoints created as entities
    assert repo.entities.count() >= 5
    types = {l.link_type for l in repo.links.all()}
    assert "handles" in types


def test_link_mode_connects_correct_endpoints(repo: GraphRepository, contacts_csv: Path):
    ds = IngestionService().load(contacts_csv)
    pipeline = ImportPipeline(repo)
    pipeline.commit(ds, _link_mapping())

    alice = repo.entities.search("Alice Carter")[0]
    bob = repo.entities.search("Bob Mensah")[0]
    # Alice -> Bob (handles) means Bob is a neighbour of Alice
    neighbour_ids = {e.id for e in repo.neighbors(alice.id)}
    assert bob.id in neighbour_ids


def test_empty_labels_skipped(repo: GraphRepository, tmp_path: Path):
    p = tmp_path / "gappy.csv"
    p.write_text("name\nAlice\n\nBob\n")
    ds = IngestionService().load(p)
    m = ImportMapping()
    m.column_mappings = [ColumnMapping(column="name", role="entity_label",
                                       semantic_type=SemanticType.PERSON)]
    ImportPipeline(repo).commit(ds, m)
    assert repo.entities.count() == 2  # blank row skipped


def test_reimport_does_not_duplicate_links(repo: GraphRepository, contacts_csv: Path):
    """Stable link ids make re-imports MERGE — the docstring's promise."""
    ds = IngestionService().load(contacts_csv)
    pipeline = ImportPipeline(repo)
    pipeline.commit(ds, _link_mapping())
    first = repo.links.count()
    pipeline.commit(ds, _link_mapping())
    assert repo.links.count() == first


def test_link_ids_are_stable_across_runs(repo: GraphRepository, contacts_csv: Path):
    ds = IngestionService().load(contacts_csv)
    pipeline = ImportPipeline(repo)
    links_a = pipeline._build_graph_objects(ds, _link_mapping())[1]
    links_b = pipeline._build_graph_objects(ds, _link_mapping())[1]
    assert sorted(l.id for l in links_a) == sorted(l.id for l in links_b)


def test_distinct_same_pair_links_preserved_within_one_import(repo: GraphRepository, tmp_path: Path):
    """Two A->B 'call' rows with different attributes are distinct relationships
    (i2 allows parallel same-type links) and must not collapse to one."""
    p = tmp_path / "calls.csv"
    p.write_text(
        "caller,callee,rel,weight\n"
        "Alice,Bob,call,0.2\n"
        "Alice,Bob,call,0.9\n"
        "Alice,Bob,call,0.2\n"   # exact duplicate of row 1 — SHOULD merge
    )
    ds = IngestionService().load(p)
    m = ImportMapping()
    m.column_mappings = [
        ColumnMapping(column="caller", role="link_source", semantic_type=SemanticType.PERSON),
        ColumnMapping(column="callee", role="link_target", semantic_type=SemanticType.PERSON),
        ColumnMapping(column="rel", role="link_type"),
        ColumnMapping(column="weight", role="entity_attr", attr_name="weight"),
    ]
    pipeline = ImportPipeline(repo)
    _, links, _ = pipeline._build_graph_objects(ds, m)
    # rows 1 and 3 are identical → same id (merged at the DB); row 2 differs.
    assert len({l.id for l in links}) == 2

    pipeline.commit(ds, m)
    assert repo.links.count() == 2
    assert sorted(l.properties["weight"] for l in repo.links.all()) == ["0.2", "0.9"]
    # Re-import is still idempotent.
    pipeline.commit(ds, m)
    assert repo.links.count() == 2
