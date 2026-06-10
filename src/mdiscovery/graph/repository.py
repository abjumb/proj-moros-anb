"""AS-22: Query/repository abstraction — clean API, no raw Cypher in the rest of the app."""

from __future__ import annotations

from typing import Optional
import kuzu

from .database import GraphDatabase
from .models import Entity, Link, SemanticType, LinkDirection

_ENTITY_RETURN = "e.id, e.label, e.semantic_type, e.properties_json"


def _entity_from_row(row) -> Entity:
    return Entity.from_dict({
        "id": row[0], "label": row[1],
        "semantic_type": row[2], "properties": row[3],
    })


def _link_from_row(row) -> Link:
    return Link.from_dict({
        "id": row[0], "source_id": row[1], "target_id": row[2],
        "link_type": row[3], "direction": row[4],
        "strength": row[5], "confidence": row[6], "properties": row[7],
    })


def _collect_entities(result) -> list[Entity]:
    out = []
    while result.has_next():
        out.append(_entity_from_row(result.get_next()))
    return out


def _collect_links(result) -> list[Link]:
    out = []
    while result.has_next():
        out.append(_link_from_row(result.get_next()))
    return out


class EntityRepository:
    def __init__(self, conn: kuzu.Connection):
        self._c = conn

    def upsert(self, entity: Entity) -> None:
        """Insert or update entity (MERGE on primary key)."""
        self.upsert_batch([entity])

    def upsert_batch(self, entities: list[Entity]) -> None:
        """Insert-or-update all entities in a single UNWIND statement.

        One round-trip regardless of batch size — per-row execute() calls
        dominated import time before (each Kuzu statement auto-commits).
        """
        if not entities:
            return
        rows = [
            {"id": e.id, "label": e.label,
             "stype": e.semantic_type.value, "props": e.properties_json()}
            for e in entities
        ]
        self._c.execute(
            """
            UNWIND $rows AS r
            MERGE (e:Entity {id: r.id})
            ON CREATE SET e.label = r.label, e.semantic_type = r.stype, e.properties_json = r.props
            ON MATCH  SET e.label = r.label, e.semantic_type = r.stype, e.properties_json = r.props
            """,
            {"rows": rows},
        )

    def get(self, entity_id: str) -> Optional[Entity]:
        r = self._c.execute(
            f"MATCH (e:Entity {{id: $id}}) RETURN {_ENTITY_RETURN}",
            {"id": entity_id},
        )
        return _entity_from_row(r.get_next()) if r.has_next() else None

    def search(self, query: str) -> list[Entity]:
        """Case-insensitive substring match on label."""
        r = self._c.execute(
            "MATCH (e:Entity) WHERE lower(e.label) CONTAINS lower($q) "
            f"RETURN {_ENTITY_RETURN}",
            {"q": query},
        )
        return _collect_entities(r)

    def all(self) -> list[Entity]:
        r = self._c.execute(f"MATCH (e:Entity) RETURN {_ENTITY_RETURN}")
        return _collect_entities(r)

    def all_ids(self) -> set[str]:
        """All entity ids without materializing full entities (dupe checks)."""
        r = self._c.execute("MATCH (e:Entity) RETURN e.id")
        ids: set[str] = set()
        while r.has_next():
            ids.add(r.get_next()[0])
        return ids

    def delete(self, entity_id: str) -> None:
        self._c.execute(
            "MATCH (e:Entity {id: $id}) DETACH DELETE e",
            {"id": entity_id},
        )

    def count(self) -> int:
        r = self._c.execute("MATCH (e:Entity) RETURN count(e)")
        return r.get_next()[0] if r.has_next() else 0

    def by_type(self, semantic_type: SemanticType) -> list[Entity]:
        r = self._c.execute(
            "MATCH (e:Entity {semantic_type: $stype}) "
            f"RETURN {_ENTITY_RETURN}",
            {"stype": semantic_type.value},
        )
        return _collect_entities(r)


class LinkRepository:
    def __init__(self, conn: kuzu.Connection):
        self._c = conn

    def upsert(self, link: Link) -> None:
        """Insert link; skip silently if it already exists (match on id)."""
        self.upsert_batch([link])

    def upsert_batch(self, links: list[Link]) -> None:
        """Insert all links in one UNWIND statement; existing ids are skipped.

        MERGE on the (source, target, id) pattern replaces the old
        check-then-CREATE pair of statements per link. Rows whose endpoints
        don't exist match nothing and are silently dropped, preserving the
        previous behavior.
        """
        if not links:
            return
        rows = [
            {"id": l.id, "src": l.source_id, "tgt": l.target_id,
             "lt": l.link_type, "dir": l.direction.value,
             "str": l.strength, "conf": l.confidence,
             "props": l.properties_json()}
            for l in links
        ]
        self._c.execute(
            """
            UNWIND $rows AS r
            MATCH (src:Entity {id: r.src}), (tgt:Entity {id: r.tgt})
            MERGE (src)-[l:Link {id: r.id}]->(tgt)
            ON CREATE SET l.link_type = r.lt, l.direction = r.dir,
                          l.strength = r.str, l.confidence = r.conf,
                          l.properties_json = r.props
            """,
            {"rows": rows},
        )

    def all(self) -> list[Link]:
        r = self._c.execute(
            """
            MATCH (src:Entity)-[l:Link]->(tgt:Entity)
            RETURN l.id, src.id, tgt.id, l.link_type, l.direction,
                   l.strength, l.confidence, l.properties_json
            """
        )
        return _collect_links(r)

    def for_entity(self, entity_id: str) -> list[Link]:
        r = self._c.execute(
            """
            MATCH (src:Entity)-[l:Link]->(tgt:Entity)
            WHERE src.id = $id OR tgt.id = $id
            RETURN l.id, src.id, tgt.id, l.link_type, l.direction,
                   l.strength, l.confidence, l.properties_json
            """,
            {"id": entity_id},
        )
        return _collect_links(r)

    def count(self) -> int:
        r = self._c.execute("MATCH ()-[l:Link]->() RETURN count(l)")
        return r.get_next()[0] if r.has_next() else 0

    def delete(self, link_id: str) -> None:
        self._c.execute(
            "MATCH ()-[l:Link {id: $id}]->() DELETE l",
            {"id": link_id},
        )


class GraphRepository:
    """Facade combining entity + link repos with traversal and export methods."""

    def __init__(self, db: GraphDatabase):
        self._db = db
        self.entities = EntityRepository(db.connection)
        self.links = LinkRepository(db.connection)

    def stats(self) -> dict:
        return {
            "entity_count": self.entities.count(),
            "link_count": self.links.count(),
        }

    def get_graph_json(self) -> dict:
        """Return Cytoscape.js-compatible graph JSON."""
        nodes = [e.to_cytoscape() for e in self.entities.all()]
        edges = [l.to_cytoscape() for l in self.links.all()]
        return {"nodes": nodes, "edges": edges}

    def neighbors(self, entity_id: str) -> list[Entity]:
        r = self._db.connection.execute(
            """
            MATCH (e:Entity {id: $id})-[:Link]-(n:Entity)
            RETURN DISTINCT n.id, n.label, n.semantic_type, n.properties_json
            """,
            {"id": entity_id},
        )
        return _collect_entities(r)

    def neighborhood(self, entity_id: str) -> dict:
        """Cytoscape JSON for an entity's neighbors and incident links.

        Feeds incremental expansion in the view: the canvas adds only the
        elements it doesn't already show instead of reloading the full graph.
        """
        nodes = [e.to_cytoscape() for e in self.neighbors(entity_id)]
        edges = [l.to_cytoscape() for l in self.links.for_entity(entity_id)]
        return {"nodes": nodes, "edges": edges}

    def find_path(self, source_id: str, target_id: str) -> list[str]:
        """Return entity IDs along the shortest path, or empty list if none.

        Traversal ignores link direction — consistent with the analysis
        layer, which treats the graph as undirected for connectivity.
        """
        r = self._db.connection.execute(
            """
            MATCH p = (src:Entity {id: $src})-[:Link* SHORTEST 1..15]-(tgt:Entity {id: $tgt})
            RETURN nodes(p)
            LIMIT 1
            """,
            {"src": source_id, "tgt": target_id},
        )
        if r.has_next():
            row = r.get_next()
            return [node["id"] for node in row[0]]
        return []

    def clear(self) -> None:
        self._db.connection.execute("MATCH (e:Entity) DETACH DELETE e")
