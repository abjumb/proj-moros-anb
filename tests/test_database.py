"""AS-20 + AS-21: embedded graph DB stands up, schema present, no server."""

from pathlib import Path

from mdiscovery.graph.database import GraphDatabase


def test_database_creates_schema(tmp_path: Path):
    db = GraphDatabase(tmp_path / "case")
    # Schema tables should accept queries without error
    r = db.connection.execute("MATCH (e:Entity) RETURN count(e)")
    assert r.get_next()[0] == 0
    db.close()


def test_database_persists_across_reopen(tmp_path: Path):
    case = tmp_path / "case"
    db = GraphDatabase(case)
    db.connection.execute(
        "MERGE (e:Entity {id: 'a'}) SET e.label = 'Alice', "
        "e.semantic_type = 'Person', e.properties_json = '{}'"
    )
    db.close()

    db2 = GraphDatabase(case)
    r = db2.connection.execute("MATCH (e:Entity {id: 'a'}) RETURN e.label")
    assert r.get_next()[0] == "Alice"
    db2.close()


def test_schema_idempotent(tmp_path: Path):
    case = tmp_path / "case"
    GraphDatabase(case).close()
    # Re-opening must not fail on CREATE TABLE IF NOT EXISTS
    GraphDatabase(case).close()
