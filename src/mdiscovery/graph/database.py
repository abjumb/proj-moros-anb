"""AS-20 + AS-21: Embedded Kuzu graph database with schema and indexing.

Kuzu is used instead of Neo4j embedded because Neo4j requires a JVM process.
Kuzu is Python-native and satisfies the no-server constraint.
"""

from pathlib import Path
import kuzu


class GraphDatabase:
    """Embedded Kuzu graph database — zero external services, zero JVM."""

    ENTITY_TABLE = "Entity"
    LINK_TABLE = "Link"

    def __init__(self, db_path: str | Path):
        self._path = Path(db_path)
        # Kuzu manages its own files at this path — do NOT pre-create it as a directory
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(str(self._path))
        self._conn = kuzu.Connection(self._db)
        self._init_schema()

    def _init_schema(self) -> None:
        """Define node/rel tables. Kuzu auto-indexes PRIMARY KEY columns (AS-21)."""
        self._conn.execute(f"""
            CREATE NODE TABLE IF NOT EXISTS {self.ENTITY_TABLE} (
                id STRING PRIMARY KEY,
                label STRING,
                semantic_type STRING,
                properties_json STRING,
                icon STRING DEFAULT '',
                style_json STRING DEFAULT '{{}}'
            )
        """)
        # Migrate pre-icon case files in place; DEFAULT backfills existing rows.
        for column, default in (("icon", "''"), ("style_json", "'{}'")):
            self._conn.execute(
                f"ALTER TABLE {self.ENTITY_TABLE} "
                f"ADD IF NOT EXISTS {column} STRING DEFAULT {default}"
            )
        self._conn.execute(f"""
            CREATE REL TABLE IF NOT EXISTS {self.LINK_TABLE} (
                FROM {self.ENTITY_TABLE} TO {self.ENTITY_TABLE},
                id STRING,
                link_type STRING,
                direction STRING,
                strength DOUBLE,
                confidence DOUBLE,
                properties_json STRING
            )
        """)

    @property
    def connection(self) -> kuzu.Connection:
        if self._conn is None:
            raise RuntimeError("GraphDatabase is closed")
        return self._conn

    def close(self) -> None:
        """Release the database file and WAL sidecar immediately.

        Explicit close (rather than relying on GC) so switching cases can
        reopen a path without racing the old handles. Safe to call twice.
        """
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._db is not None:
            self._db.close()
            self._db = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
