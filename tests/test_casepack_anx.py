""".onb case packages and ANX chart XML import/export."""

import json
import zipfile
import xml.etree.ElementTree as ET

import pytest

from mdiscovery import casepack
from mdiscovery.export.anx import to_anx
from mdiscovery.export.exporters import ExportFormat, write_export
from mdiscovery.graph.models import Entity, Link, LinkDirection, SemanticType
from mdiscovery.importer.anx_import import load_anx


def _sample(tmp_path=None, with_photo=False):
    style_a = {"x": 120.0, "y": 80.0, "size": 90}
    if with_photo:
        photo = tmp_path / "alice.jpg"
        photo.write_bytes(b"jpegdata")
        style_a["photo"] = str(photo)
    entities = [
        Entity(label="Alice", id="a", semantic_type=SemanticType.PERSON,
               icon="person-female", properties={"age": "41"}, style=style_a),
        Entity(label="Acme", id="o", semantic_type=SemanticType.ORGANIZATION,
               style={"x": 300.0, "y": 200.0}),
    ]
    links = [Link(source_id="a", target_id="o", id="ao", link_type="works_at",
                  direction=LinkDirection.BIDIRECTIONAL, strength=2.0,
                  properties={"since": "2021"})]
    return entities, links


# ── .onb package ──────────────────────────────────────────────────────

def test_package_roundtrip_with_layout_and_photo(tmp_path):
    entities, links = _sample(tmp_path, with_photo=True)
    pkg = casepack.write_package(tmp_path / "case", entities, links)
    assert pkg.suffix == casepack.EXTENSION

    with zipfile.ZipFile(pkg) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format"] == casepack.FORMAT_NAME
        assert manifest["version"] == casepack.FORMAT_VERSION
        assert "media/a.jpg" in zf.namelist()

    media_out = tmp_path / "restored_media"
    loaded_manifest, loaded_e, loaded_l = casepack.read_package(pkg, media_dir=media_out)
    assert loaded_manifest["entity_count"] == 2
    by_id = {e.id: e for e in loaded_e}
    # Layout travelled:
    assert by_id["a"].style["x"] == 120.0 and by_id["a"].style["y"] == 80.0
    assert by_id["a"].style["size"] == 90
    # Photo extracted and re-pointed to an absolute local path:
    restored_photo = by_id["a"].style["photo"]
    assert (media_out / "a.jpg").read_bytes() == b"jpegdata"
    assert restored_photo == str(media_out / "a.jpg")
    # Source entity untouched (write didn't mutate caller data):
    assert entities[0].style["photo"].endswith("alice.jpg")
    assert loaded_l[0].link_type == "works_at"


def test_package_without_media_dir_drops_photo_refs(tmp_path):
    entities, links = _sample(tmp_path, with_photo=True)
    pkg = casepack.write_package(tmp_path / "case", entities, links)
    _, loaded_e, _ = casepack.read_package(pkg)  # no media_dir
    by_id = {e.id: e for e in loaded_e}
    assert "photo" not in by_id["a"].style
    assert by_id["a"].style["x"] == 120.0  # rest of style intact


def test_package_rejects_newer_version(tmp_path):
    entities, links = _sample()
    pkg = casepack.write_package(tmp_path / "case", entities, links)
    # Rewrite manifest with a future version.
    bumped = tmp_path / "future.onb"
    with zipfile.ZipFile(pkg) as zin, zipfile.ZipFile(bumped, "w") as zout:
        for name in zin.namelist():
            data = zin.read(name)
            if name == "manifest.json":
                m = json.loads(data)
                m["version"] = casepack.FORMAT_VERSION + 1
                data = json.dumps(m).encode()
            zout.writestr(name, data)
    with pytest.raises(ValueError, match="newer than this app"):
        casepack.read_package(bumped)


def test_package_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.onb"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="Not a case package"):
        casepack.read_package(bad)
    empty = tmp_path / "empty.onb"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("readme.txt", "hi")
    with pytest.raises(ValueError, match="missing manifest"):
        casepack.read_package(empty)


def test_package_missing_photo_file_dropped(tmp_path):
    entities, links = _sample()
    entities[0].style["photo"] = str(tmp_path / "ghost.jpg")  # doesn't exist
    pkg = casepack.write_package(tmp_path / "case", entities, links)
    _, loaded_e, _ = casepack.read_package(pkg, media_dir=tmp_path / "m")
    assert "photo" not in {e.id: e for e in loaded_e}["a"].style


# ── ANX export / import round-trip ────────────────────────────────────

def test_anx_structure():
    entities, links = _sample()
    xml = to_anx(entities, links)
    root = ET.fromstring(xml)
    items = root.findall(".//ChartItem")
    assert len(items) == 3  # 2 entities + 1 link
    ent = root.find(".//ChartItem/End/Entity[@EntityId='a']")
    assert ent is not None and ent.get("Identity") == "Alice"
    icon = root.find(".//Entity[@EntityId='a']/Icon/IconStyle")
    assert icon.get("Type") == "Person"
    link = root.find(".//Link")
    assert (link.get("End1Id"), link.get("End2Id")) == ("a", "o")
    assert link.find("LinkStyle").get("ArrowStyle") == "ArrowOnBoth"


def test_anx_roundtrip(tmp_path):
    entities, links = _sample()
    anx = tmp_path / "chart.anx"
    anx.write_text(to_anx(entities, links), encoding="utf-8")

    loaded_e, loaded_l = load_anx(anx)
    by_id = {e.id: e for e in loaded_e}
    assert set(by_id) == {"a", "o"}
    assert by_id["a"].label == "Alice"
    assert by_id["a"].semantic_type == SemanticType.PERSON
    assert by_id["a"].properties["age"] == "41"
    assert by_id["a"].style == {"x": 120.0, "y": 80.0}  # layout survives
    assert by_id["o"].semantic_type == SemanticType.ORGANIZATION

    assert len(loaded_l) == 1
    l = loaded_l[0]
    assert (l.source_id, l.target_id, l.link_type) == ("a", "o", "works_at")
    assert l.direction == LinkDirection.BIDIRECTIONAL
    assert l.strength == 2.0
    assert l.properties == {"since": "2021"}


def test_anx_rejects_malformed(tmp_path):
    bad = tmp_path / "bad.anx"
    bad.write_text("<Chart><unclosed>", encoding="utf-8")
    with pytest.raises(ValueError, match="Not valid chart XML"):
        load_anx(bad)


def test_anx_rejects_dangling_link(tmp_path):
    xml = """<?xml version="1.0"?>
    <Chart><ChartItemCollection>
      <ChartItem Label="A"><End><Entity EntityId="a" Identity="A"/></End></ChartItem>
      <ChartItem Label="ghost"><Link End1Id="a" End2Id="zzz"/></ChartItem>
    </ChartItemCollection></Chart>"""
    p = tmp_path / "dangling.anx"
    p.write_text(xml, encoding="utf-8")
    with pytest.raises(ValueError, match="unknown entity"):
        load_anx(p)


def test_anx_ignores_unmodeled_items(tmp_path):
    xml = """<?xml version="1.0"?>
    <Chart><ChartItemCollection>
      <ChartItem Label="A"><End><Entity EntityId="a" Identity="A"/></End></ChartItem>
      <ChartItem Label="theme line"><ThemeLine/></ChartItem>
    </ChartItemCollection></Chart>"""
    p = tmp_path / "extra.anx"
    p.write_text(xml, encoding="utf-8")
    entities, links = load_anx(p)
    assert len(entities) == 1 and links == []


def test_write_export_anx(tmp_path):
    import kuzu  # noqa: F401  (repo fixture machinery not needed — use models)
    from mdiscovery.graph.database import GraphDatabase
    from mdiscovery.graph.repository import GraphRepository
    db = GraphDatabase(tmp_path / "c")
    repo = GraphRepository(db)
    entities, links = _sample()
    repo.entities.upsert_batch(entities)
    repo.links.upsert_batch(links)
    out = write_export(repo, tmp_path / "chart.anx", ExportFormat.ANX)
    assert out[0].suffix == ".anx" and out[0].stat().st_size > 0
    ET.parse(out[0])  # well-formed
    db.close()


# ── Layout in cytoscape elements ──────────────────────────────────────

def test_to_cytoscape_position_preset():
    e = Entity(label="A", id="a", style={"x": 10.5, "y": -3.0})
    el = e.to_cytoscape()
    assert el["position"] == {"x": 10.5, "y": -3.0}
    assert "position" not in Entity(label="B", id="b").to_cytoscape()
