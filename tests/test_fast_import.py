"""Bulk import + vectorized build: equivalence with the row-wise path."""

from pathlib import Path

import pytest

from mdiscovery.analysis.metrics import analysis_inputs_from_repo, graph_summary, graph_summary_from_repo
from mdiscovery.graph.database import GraphDatabase
from mdiscovery.graph.models import Entity, Link, SemanticType
from mdiscovery.graph.repository import GraphRepository
from mdiscovery.importer.automap import detect_mapping
from mdiscovery.importer.ingestion import IngestionService, StagedDataset
from mdiscovery.importer.pipeline import ImportPipeline

DATA = Path(__file__).parent / "data"


@pytest.fixture
def repo(tmp_path):
    db = GraphDatabase(tmp_path / "case")
    yield GraphRepository(db)
    db.close()


def _slow_dataset(ds: StagedDataset) -> StagedDataset:
    """Same data, no frame -> forces the row-wise builder."""
    return StagedDataset(columns=ds.columns, rows=list(ds.rows),
                         column_samples=ds.column_samples,
                         column_types=ds.column_types,
                         parse_warnings=ds.parse_warnings)


def _key_e(e): return (e.id, e.label, e.semantic_type, dict(e.properties))
def _key_l(l): return (l.id, l.source_id, l.target_id, l.link_type,
                       l.direction, dict(l.properties))


@pytest.mark.parametrize("csv_name", ["contacts.csv", "people.csv"])
def test_vectorized_equals_rowwise(repo, csv_name):
    ds = IngestionService().load(DATA / csv_name)
    mapping = detect_mapping(ds).mapping
    pipe = ImportPipeline(repo)
    fast = pipe._build_vectorized(ds, mapping)
    slow = pipe._build_rowwise(_slow_dataset(ds), mapping)
    assert sorted(map(_key_e, fast[0])) == sorted(map(_key_e, slow[0]))
    assert sorted(map(_key_l, fast[1])) == sorted(map(_key_l, slow[1]))


def test_vectorized_equals_rowwise_messy(repo, tmp_path):
    p = tmp_path / "messy.csv"
    p.write_text(
        'source,target,relationship,note,score\n'
        'Ann,Bob,calls,"has, comma",1\n'
        'Bob,,ignored-row,x,2\n'           # empty target dropped
        'Ann,Cy,,empty type -> default,\n'  # empty type + NaN attr
        '"Q ""Quote""",Ann,meets,,9\n')
    ds = IngestionService().load(p)
    mapping = detect_mapping(ds).mapping
    pipe = ImportPipeline(repo)
    fast = pipe._build_vectorized(ds, mapping)
    slow = pipe._build_rowwise(_slow_dataset(ds), mapping)
    assert sorted(map(_key_e, fast[0])) == sorted(map(_key_e, slow[0]))
    assert sorted(map(_key_l, fast[1])) == sorted(map(_key_l, slow[1]))
    assert len(fast[1]) == 3  # the empty-target row is dropped


def test_lazy_rows_not_materialized_by_pipeline(repo):
    ds = IngestionService().load(DATA / "contacts.csv")
    assert ds._rows is None
    pipe = ImportPipeline(repo)
    pipe.commit(ds, detect_mapping(ds).mapping)
    assert ds._rows is None          # vectorized path never touched .rows
    assert repo.stats() == {"entity_count": 5, "link_count": 4}


def test_preview_then_commit_builds_once(repo):
    ds = IngestionService().load(DATA / "contacts.csv")
    mapping = detect_mapping(ds).mapping
    pipe = ImportPipeline(repo)
    pipe.preview(ds, mapping)
    pipe.commit(ds, mapping)
    assert pipe.build_calls == 1
    # changing the mapping invalidates the cache
    mapping.default_link_type = "other"
    pipe.preview(ds, mapping)
    assert pipe.build_calls == 2


def test_bulk_upsert_semantics(repo):
    nasty = [Entity('He said "hi", twice', SemanticType.PERSON, id="q1",
                    properties={"note": 'va"l,ue', "path": "C:\\tmp\\x"}),
             Entity("Comma, Inc.", SemanticType.ORGANIZATION, id="q2",
                    style={"x": 1.5})]
    links = [Link(source_id="q1", target_id="q2", id="L1",
                  link_type='says "hello, world"', properties={"k": 'quo"te'}),
             Link(source_id="q1", target_id="q1", id="L1", link_type="dup"),
             Link(source_id="q2", target_id="ghost", id="L2")]
    stats = repo.bulk_upsert(nasty, links)
    assert stats == {"entities_new": 2, "entities_updated": 0,
                     "links_new": 1, "links_skipped": 2}
    assert repo.entities.get("q1").properties == {"note": 'va"l,ue',
                                                  "path": "C:\\tmp\\x"}
    fetched = repo.links.get("L1")
    assert fetched.link_type == 'says "hello, world"'
    assert fetched.properties == {"k": 'quo"te'}
    # idempotent rerun: entities update, links skip
    stats2 = repo.bulk_upsert(nasty, links)
    assert stats2["entities_new"] == 0 and stats2["links_new"] == 0
    assert repo.stats() == {"entity_count": 2, "link_count": 1}
    nasty[0].label = "UPDATED"
    repo.bulk_upsert([nasty[0]], [])
    assert repo.entities.get("q1").label == "UPDATED"


def test_bulk_equals_perrow_results(repo, tmp_path):
    ds = IngestionService().load(DATA / "contacts.csv")
    mapping = detect_mapping(ds).mapping
    ImportPipeline(repo).commit(ds, mapping)         # bulk path
    db2 = GraphDatabase(tmp_path / "case2")
    repo2 = GraphRepository(db2)
    ents, links, _ = ImportPipeline(repo2)._build_rowwise(_slow_dataset(ds), mapping)
    repo2.entities.upsert_batch(ents)                # per-row path
    repo2.links.upsert_batch(links)
    a = sorted(map(_key_e, repo.entities.all()))
    b = sorted(map(_key_e, repo2.entities.all()))
    assert a == b
    assert sorted(map(_key_l, repo.links.all())) == sorted(map(_key_l, repo2.links.all()))
    db2.close()


def test_fast_analysis_inputs_match_full_objects(repo):
    ds = IngestionService().load(DATA / "contacts.csv")
    ImportPipeline(repo).commit(ds, detect_mapping(ds).mapping)
    full = graph_summary(repo.entities.all(), repo.links.all())
    fast = graph_summary_from_repo(repo)
    assert fast.to_dict() == full.to_dict()
    ents, links = analysis_inputs_from_repo(repo)
    full_types = {e.id: e.semantic_type for e in repo.entities.all()}
    assert {e.id: e.semantic_type for e in ents} == full_types


def test_bulk_import_performance_guard(repo, tmp_path):
    """Catastrophic-regression guard: 30k records through the full pipeline
    (load -> detect -> preview -> commit) must stay well under the old
    per-row pace (~33s for this size). Budget is generous for slow CI."""
    import random, time
    rng = random.Random(3)
    p = tmp_path / "mid.csv"
    with p.open("w") as f:
        f.write("source,target,relationship\n")
        for i in range(30000):
            f.write(f"E{rng.randrange(4000)},E{rng.randrange(4000)},r{rng.randrange(6)}\n")
    t0 = time.perf_counter()
    ds = IngestionService().load(p)
    mapping = detect_mapping(ds).mapping
    pipe = ImportPipeline(repo)
    pipe.preview(ds, mapping)
    pipe.commit(ds, mapping)
    elapsed = time.perf_counter() - t0
    assert repo.entities.count() == 4000
    assert repo.links.count() > 25000  # stable-id dedup collapses repeats
    assert elapsed < 20.0, f"bulk import regressed: {elapsed:.1f}s for 30k rows"


# ── Code-review regressions (PR #13 review) ───────────────────────────

def test_bulk_import_handles_embedded_newlines(repo):
    """COPY's parallel reader rejects quoted newlines; we retry serial."""
    e = [Entity("line1\nline2", SemanticType.PERSON, id="nl1"),
         Entity("plain", SemanticType.PERSON, id="nl2")]
    l = [Link(source_id="nl1", target_id="nl2", id="LN",
              link_type="multi\nline type")]
    repo.bulk_upsert(e, l)
    assert repo.entities.get("nl1").label == "line1\nline2"
    assert repo.links.get("LN").link_type == "multi\nline type"


def test_zero_cells_kept_by_both_builders(repo, tmp_path):
    """'0' endpoints/types are data, not emptiness — both builders agree."""
    p = tmp_path / "zero.csv"
    p.write_text("source,target,relationship\n0,Bob,calls\nAnn,0,0\n")
    ds = IngestionService().load(p)
    mapping = detect_mapping(ds).mapping
    pipe = ImportPipeline(repo)
    fast = pipe._build_vectorized(ds, mapping)
    slow = pipe._build_rowwise(_slow_dataset(ds), mapping)
    assert sorted(map(_key_e, fast[0])) == sorted(map(_key_e, slow[0]))
    assert sorted(map(_key_l, fast[1])) == sorted(map(_key_l, slow[1]))
    labels = {e.label for e in fast[0]}
    assert "0" in labels and len(fast[1]) == 2


def test_cache_not_fooled_by_lookalike_dataset(repo):
    """Cache keys hold the dataset object — same-shape file ≠ cache hit."""
    ds1 = IngestionService().load(DATA / "contacts.csv")
    mapping = detect_mapping(ds1).mapping
    pipe = ImportPipeline(repo)
    pipe.preview(ds1, mapping)
    ds2 = IngestionService().load(DATA / "contacts.csv")  # identical shape
    pipe.preview(ds2, mapping)
    assert pipe.build_calls == 2


def test_imported_objects_do_not_share_properties_dict(repo, tmp_path):
    p = tmp_path / "noattr.csv"
    p.write_text("source,target,relationship\nA,B,r\nB,C,r\n")
    ds = IngestionService().load(p)
    pipe = ImportPipeline(repo)
    ents, links, _ = pipe._build_vectorized(ds, detect_mapping(ds).mapping)
    links[0].properties["poison"] = True
    assert "poison" not in links[1].properties
    ents[0].properties["poison"] = True
    assert "poison" not in ents[1].properties


def test_stale_columnar_links_never_leak_to_rowwise_commit(repo, tmp_path):
    """Vectorized preview of A, then commit of frameless B: B's links win."""
    ds_a = IngestionService().load(DATA / "contacts.csv")
    pipe = ImportPipeline(repo)
    pipe.preview(ds_a, detect_mapping(ds_a).mapping)   # arms columnar cols
    ds_b = _slow_dataset(IngestionService().load(tmp_path_csv(tmp_path)))
    mapping_b = detect_mapping(ds_b).mapping
    pipe.commit(ds_b, mapping_b)
    types = {l.link_type for l in repo.links.all()}
    assert types == {"zz"}                              # only B's links


def tmp_path_csv(tmp_path):
    p = tmp_path / "b.csv"
    p.write_text("source,target,relationship\nX,Y,zz\n")
    return p


def test_summary_buckets_unknown_semantic_types_consistently(repo):
    repo.entities.upsert(Entity("X", id="x"))
    # Corrupt the stored type directly (legacy/foreign case file).
    repo._db.connection.execute(
        "MATCH (e:Entity {id:'x'}) SET e.semantic_type = 'NotAType'")
    summary = graph_summary_from_repo(repo)
    assert summary.entities_by_type == {"Unknown": 1}
