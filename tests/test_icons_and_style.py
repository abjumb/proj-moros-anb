"""Icon library registry + entity icon/style persistence + theming tokens."""

import xml.etree.ElementTree as ET

import pytest

from mdiscovery.icons import (
    DEFAULT_TYPE_ICONS, ICONS, ICONS_DIR, colored_svg, icon_for, load_icon_svgs,
)
from mdiscovery.graph.database import GraphDatabase
from mdiscovery.graph.models import Entity, Link, SemanticType
from mdiscovery.graph.repository import GraphRepository
from mdiscovery.ui import theme


# ── Icon registry ─────────────────────────────────────────────────────

def test_all_registry_icons_exist_and_parse():
    svgs = load_icon_svgs()
    for stem in ICONS.values():
        assert stem in svgs, f"missing icon file for {stem}"
        ET.fromstring(svgs[stem])  # valid XML
        assert "currentColor" in svgs[stem], f"{stem} must use currentColor"


def test_requested_starting_icons_present():
    # The nine starting icons from the design brief.
    expected = {"person-male", "person-female", "organization", "money",
                "cell-phone", "imsi", "imei", "cell-tower", "group"}
    assert expected == {p.stem for p in ICONS_DIR.glob("*.svg")}


def test_default_type_icons_resolve():
    for stype, stem in DEFAULT_TYPE_ICONS.items():
        assert icon_for(stype) == stem
    assert icon_for(SemanticType.PERSON, override="person-female") == "person-female"
    assert icon_for(SemanticType.EVENT) == ""


def test_colored_svg_substitutes():
    svg = colored_svg("money", "#123456")
    assert "#123456" in svg and "currentColor" not in svg
    assert colored_svg("nonexistent", "#123456") == ""


# ── Entity icon/style round-trip ──────────────────────────────────────

@pytest.fixture
def repo(tmp_path):
    db = GraphDatabase(tmp_path / "case")
    yield GraphRepository(db)
    db.close()


def test_entity_icon_and_style_roundtrip(repo):
    e = Entity(label="Jane", id="j", semantic_type=SemanticType.PERSON,
               icon="person-female",
               style={"size": 90, "font_size": 14, "photo": "/tmp/x.png"})
    repo.entities.upsert(e)
    fetched = repo.entities.get("j")
    assert fetched.icon == "person-female"
    assert fetched.style == {"size": 90, "font_size": 14, "photo": "/tmp/x.png"}


def test_entity_defaults_when_unset(repo):
    repo.entities.upsert(Entity(label="X", id="x"))
    fetched = repo.entities.get("x")
    assert fetched.icon == ""
    assert fetched.style == {}


def test_to_cytoscape_carries_display_fields():
    e = Entity(label="Jane", id="j", icon="person-female",
               style={"size": 90, "font_size": 14, "photo": "/tmp/pic.png"})
    data = e.to_cytoscape()["data"]
    assert data["icon"] == "person-female"
    assert data["_size"] == 90
    assert data["_fontSize"] == 14
    assert data["photo"].startswith("file://")
    # No display keys at all when unset:
    bare = Entity(label="B", id="b").to_cytoscape()["data"]
    assert "icon" not in bare and "_size" not in bare and "photo" not in bare


def test_migration_adds_columns_to_old_schema(tmp_path):
    """A pre-icon case file opens cleanly and gains the new columns."""
    import kuzu
    path = tmp_path / "old_case"
    db = kuzu.Database(str(path))
    conn = kuzu.Connection(db)
    conn.execute(
        "CREATE NODE TABLE Entity (id STRING PRIMARY KEY, label STRING,"
        " semantic_type STRING, properties_json STRING)")
    conn.execute(
        "CREATE REL TABLE Link (FROM Entity TO Entity, id STRING,"
        " link_type STRING, direction STRING, strength DOUBLE,"
        " confidence DOUBLE, properties_json STRING)")
    conn.execute(
        "CREATE (:Entity {id: 'a', label: 'Old', semantic_type: 'Person',"
        " properties_json: '{}'})")
    conn.close(); db.close()

    gdb = GraphDatabase(path)   # runs the migration
    repo = GraphRepository(gdb)
    old = repo.entities.get("a")
    assert old.label == "Old" and old.icon == "" and old.style == {}
    old.icon = "person-male"
    repo.entities.upsert(old)
    assert repo.entities.get("a").icon == "person-male"
    gdb.close()


# ── Link rename / partial update ──────────────────────────────────────

def test_link_update_fields_rename(repo):
    repo.entities.upsert_batch([Entity(label="A", id="a"), Entity(label="B", id="b")])
    repo.links.upsert(Link(source_id="a", target_id="b", id="l1", link_type="knows"))
    repo.links.update_fields("l1", link_type="works_with")
    fetched = repo.links.get("l1")
    assert fetched.link_type == "works_with"
    assert fetched.strength == 1.0  # untouched


def test_link_update_fields_partial(repo):
    from mdiscovery.graph.models import LinkDirection
    repo.entities.upsert_batch([Entity(label="A", id="a"), Entity(label="B", id="b")])
    repo.links.upsert(Link(source_id="a", target_id="b", id="l1"))
    repo.links.update_fields("l1", strength=2.5,
                             direction=LinkDirection.BIDIRECTIONAL,
                             properties={"since": "2021"})
    fetched = repo.links.get("l1")
    assert fetched.strength == 2.5
    assert fetched.direction == LinkDirection.BIDIRECTIONAL
    assert fetched.properties == {"since": "2021"}
    assert fetched.link_type == "relates_to"  # untouched
    repo.links.update_fields("l1")  # no kwargs — must be a no-op, not an error


def test_link_get_missing_returns_none(repo):
    assert repo.links.get("nope") is None


# ── Theme palettes ────────────────────────────────────────────────────

def test_palettes_have_identical_token_sets():
    assert set(theme.PALETTES["dark"]) == set(theme.PALETTES["light"])


def test_mode_switching():
    assert theme.current_mode() == "dark"
    try:
        theme.set_mode("light")
        assert theme.active_tokens() == theme.PALETTES["light"]
        assert theme.canvas_theme()["mode"] == "light"
        assert "QToolBar" in theme.build_stylesheet("light")
        with pytest.raises(ValueError):
            theme.set_mode("solarized")
    finally:
        theme.set_mode("dark")


def test_clipboard_payload_roundtrip():
    """Copy/paste between workspaces reuses the node-link JSON format."""
    from mdiscovery.export.exporters import to_json
    from mdiscovery.importer.json_import import parse_node_link_text
    entities = [Entity(label="A", id="a", icon="person-male", style={"size": 80}),
                Entity(label="B", id="b")]
    links = [Link(source_id="a", target_id="b", id="ab", link_type="calls")]
    payload = to_json(entities, links)
    restored_e, restored_l = parse_node_link_text(payload)
    assert {e.id for e in restored_e} == {"a", "b"}
    by_id = {e.id: e for e in restored_e}
    assert by_id["a"].icon == "person-male"
    assert by_id["a"].style == {"size": 80}
    assert restored_l[0].link_type == "calls"


# ── Code-review fixes ─────────────────────────────────────────────────

def test_reserved_property_names_not_spread_into_canvas_data():
    """A user property literally named 'photo'/'icon'/'_size' must not be
    misread by the canvas as an image URL or size override."""
    e = Entity(label="X", id="x",
               properties={"photo": "IMG_0231.jpg", "_size": "huge", "ok": "v"})
    data = e.to_cytoscape()["data"]
    assert "photo" not in data and "_size" not in data
    assert data["ok"] == "v"
    # The properties themselves survive in the model and exports:
    assert e.to_dict()["properties"]["photo"] == "IMG_0231.jpg"


def test_merge_edited_properties_preserves_untouched_types():
    from mdiscovery.graph.models import merge_edited_properties
    original = {"age": 41, "score": 0.5, "tags": [1, 2], "name": "Bob"}
    # Table round-trips everything as text; user only edited "name".
    edited = {"age": "41", "score": "0.5", "tags": "[1, 2]", "name": "Robert"}
    merged = merge_edited_properties(original, edited)
    assert merged["age"] == 41 and isinstance(merged["age"], int)
    assert merged["score"] == 0.5 and isinstance(merged["score"], float)
    assert merged["tags"] == [1, 2]
    assert merged["name"] == "Robert"
    # Deletions and additions pass through:
    assert merge_edited_properties({"gone": 1}, {"new": "x"}) == {"new": "x"}
