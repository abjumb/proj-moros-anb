"""AS-22: Query/repository abstraction — clean API, no raw Cypher in the rest of the app."""

from __future__ import annotations

import json
from typing import Optional
import kuzu

from .database import GraphDatabase
from .models import Entity, Link, SemanticType, LinkDirection


class EntityRepository:
    def __init__(self, conn: kuzu.Connection):
        self._c = conn

    def upsert(self, entity: Entity) -> None:
        """Insert or update entity (MERGE on primary key)."""
        self._c.execute(
            """
            MERGE (e:Entity {id: $id})
            ON CREATE SET e.label = $label, e.semantic_type = $stype, e.properties_json = $props
            ON MATCH  SET e.label = $label, e.semantic_type = $stype, e.properties_json = $props
            """,
            {"id": entity.id, "label": entity.label,
             "stype": entity.semantic_type.value,
             "props": entity.properties_json()},
        )

    def upsert_batch(self, entities: list[Entity]) -> None:
        for e in entities:
            self.upsert(e)

    def get(self, entity_id: str) -> Optional[Entity]:
        r = self._c.execute(
            "MATCH (e:Entity {id: $id}) RETURN e.id, e.label, e.semantic_type, e.properties_json",
            {"id": entity_id},
        )
        if r.has_next():
            row = r.get_next()
            return Entity.from_dict({
                "id": row[0], "label": row[1],
                "semantic_type": row[2], "properties": row[3],
            })
        return None

    def search(self, query: str) -> list[Entity]:
        r = self._c.execute(
            "MATCH (e:Entity) WHERE e.label CONTAINS $q "
            "RETURN e.id, e.label, e.semantic_type, e.properties_json",
            {"q": query},
        )
        results = []
        while r.has_next():
            row = r.get_next()
            results.append(Entity.from_dict({
                "id": row[0], "label": row[1],
                "semantic_type": row[2], "properties": row[3],
            }))
        return results

    def all(self) -> list[Entity]:
        r = self._c.execute(
            "MATCH (e:Entity) RETURN e.id, e.label, e.semantic_type, e.properties_json"
        )
        results = []
        while r.has_next():
            row = r.get_next()
            results.append(Entity.from_dict({
                "id": row[0], "label": row[1],
                "semantic_type": row[2], "properties": row[3],
            }))
        return results

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
            "RETURN e.id, e.label, e.semantic_type, e.properties_json",
            {"stype": semantic_type.value},
        )
        results = []
        while r.has_next():
            row = r.get_next()
            results.append(Entity.from_dict({
                "id": row[0], "label": row[1],
                "semantic_type": row[2], "properties": row[3],
            }))
        return results


class LinkRepository:
    def __init__(self, conn: kuzu.Connection):
        self._c = conn

    def upsert(self, link: Link) -> None:
        """Insert link; skip silently if it already exists (match on id)."""
        existing = self._c.execute(
            "MATCH ()-[l:Link {id: $id}]->() RETURN l.id", {"id": link.id}
        )
        if existing.has_next():
            return
        self._c.execute(
            """
            MATCH (src:Entity {id: $src}), (tgt:Entity {id: $tgt})
            CREATE (src)-[:Link {
                id: $id, link_type: $lt, direction: $dir,
                strength: $str, confidence: $conf, properties_json: $props
            }]->(tgt)
            """,
            {
                "src": link.source_id, "tgt": link.target_id,
                "id": link.id, "lt": link.link_type,
                "dir": link.direction.value,
                "str": link.strength, "conf": link.confidence,
                "props": link.properties_json(),
            },
        )

    def upsert_batch(self, links: list[Link]) -> None:
        for l in links:
            self.upsert(l)

    def all(self) -> list[Link]:
        r = self._c.execute(
            """
            MATCH (src:Entity)-[l:Link]->(tgt:Entity)
            RETURN l.id, src.id, tgt.id, l.link_type, l.direction,
                   l.strength, l.confidence, l.properties_json
            """
        )
        results = []
        while r.has_next():
            row = r.get_next()
            results.append(Link.from_dict({
                "id": row[0], "source_id": row[1], "target_id": row[2],
                "link_type": row[3], "direction": row[4],
                "strength": row[5], "confidence": row[6], "properties": row[7],
            }))
        return results

    def for_entity(self, entity_id: str) -> list[Link]:
        r = self._c.execute(
            """
            MATCH (e:Entity {id: $id})-[l:Link]-(other:Entity)
            RETURN l.id, e.id, other.id, l.link_type, l.direction,
                   l.strength, l.confidence, l.properties_json
            """,
            {"id": entity_id},
        )
        results = []
        while r.has_next():
            row = r.get_next()
            results.append(Link.from_dict({
                "id": row[0], "source_id": row[1], "target_id": row[2],
                "link_type": row[3], "direction": row[4],
                "strength": row[5], "confidence": row[6], "properties": row[7],
            }))
        return results

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
        results = []
        while r.has_next():
            row = r.get_next()
            results.append(Entity.from_dict({
                "id": row[0], "label": row[1],
                "semantic_type": row[2], "properties": row[3],
            }))
        return results

    def find_path(self, source_id: str, target_id: str) -> list[str]:
        """Return entity IDs along the shortest path, or empty list if none."""
        r = self._db.connection.execute(
            """
            MATCH p = (src:Entity {id: $src})-[:Link* SHORTEST 1..15]->(tgt:Entity {id: $tgt})
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
