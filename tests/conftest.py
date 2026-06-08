"""Shared pytest fixtures for mDiscovery tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdiscovery.graph.database import GraphDatabase
from mdiscovery.graph.repository import GraphRepository

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def db(tmp_path: Path) -> GraphDatabase:
    database = GraphDatabase(tmp_path / "case")
    yield database
    database.close()


@pytest.fixture
def repo(db: GraphDatabase) -> GraphRepository:
    return GraphRepository(db)


@pytest.fixture
def people_csv() -> Path:
    return DATA_DIR / "people.csv"


@pytest.fixture
def contacts_csv() -> Path:
    return DATA_DIR / "contacts.csv"
