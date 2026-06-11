"""Automatic column→role detection for imports."""

from pathlib import Path

from mdiscovery.graph.models import SemanticType
from mdiscovery.importer.automap import detect_mapping
from mdiscovery.importer.ingestion import IngestionService

DATA = Path(__file__).parent / "data"


def _roles(result):
    return {m.column: m.role for m in result.mapping.column_mappings}


def _load_csv(tmp_path, text):
    p = tmp_path / "data.csv"
    p.write_text(text)
    return IngestionService().load(p)


def test_contacts_csv_detected_as_link_data():
    ds = IngestionService().load(DATA / "contacts.csv")
    result = detect_mapping(ds)
    assert result.link_mode
    assert _roles(result) == {
        "source": "link_source", "target": "link_target",
        "relationship": "link_type", "since": "entity_attr",
    }


def test_people_csv_detected_as_entity_list():
    ds = IngestionService().load(DATA / "people.csv")
    result = detect_mapping(ds)
    assert not result.link_mode
    assert result.label_column == "name"
    roles = _roles(result)
    assert roles["name"] == "entity_label"
    assert roles["role"] == roles["city"] == roles["age"] == "entity_attr"


def test_header_synonyms(tmp_path):
    ds = _load_csv(tmp_path, "from,to,type\nA,B,calls\nB,C,meets\n")
    result = detect_mapping(ds)
    assert result.link_mode
    assert _roles(result) == {
        "from": "link_source", "to": "link_target", "type": "link_type",
    }


def test_content_overlap_fallback(tmp_path):
    # Generic headers, but the two columns share the same population —
    # the structural signature of an edge list.
    ds = _load_csv(tmp_path,
        "alpha,beta,how\nAnn,Bob,knows\nBob,Cy,knows\nCy,Ann,pays\nAnn,Cy,pays\n")
    result = detect_mapping(ds)
    assert result.link_mode
    roles = _roles(result)
    assert roles["alpha"] == "link_source"
    assert roles["beta"] == "link_target"
    assert roles["how"] == "link_type"  # low-cardinality short strings


def test_no_signals_falls_back_to_entity_mode(tmp_path):
    ds = _load_csv(tmp_path,
        "case_ref,amount\nC-1001,50\nC-1002,75\nC-1003,20\n")
    result = detect_mapping(ds)
    assert not result.link_mode
    assert result.label_column == "case_ref"  # most-unique string column


def test_semantic_hints_from_headers(tmp_path):
    ds = _load_csv(tmp_path,
        "caller_phone,receiver_email,relation\n555,a@x.io,texts\n556,b@x.io,texts\n")
    result = detect_mapping(ds)
    assert result.link_mode
    by_col = {m.column: m for m in result.mapping.column_mappings}
    assert by_col["caller_phone"].role == "link_source"
    assert by_col["caller_phone"].semantic_type == SemanticType.PHONE
    assert by_col["receiver_email"].role == "link_target"
    assert by_col["receiver_email"].semantic_type == SemanticType.EMAIL


def test_notes_are_human_readable():
    ds = IngestionService().load(DATA / "contacts.csv")
    result = detect_mapping(ds)
    joined = "; ".join(result.notes)
    assert "source" in joined and "link source" in joined


# ── Review regressions (charliecreates on PR #12) ─────────────────────

def test_total_does_not_match_to_hint(tmp_path):
    """'total' must not prefix-match the 'to' hint and flip into link mode."""
    ds = _load_csv(tmp_path,
        "from_name,total,amount\nAlice,3,50\nBob,2,75\nCara,5,20\n")
    result = detect_mapping(ds)
    assert not result.link_mode
    roles = _roles(result)
    assert roles["total"] == "entity_attr"


def test_separator_prefixed_endpoint_headers_still_match(tmp_path):
    ds = _load_csv(tmp_path,
        "from_account,to_account,amount\nAC1,AC2,50\nAC2,AC3,75\n")
    result = detect_mapping(ds)
    assert result.link_mode
    roles = _roles(result)
    assert roles["from_account"] == "link_source"
    assert roles["to_account"] == "link_target"


def test_low_cardinality_categories_not_endpoints(tmp_path):
    """status_before/status_after overlap fully but are categories, not entities."""
    rows = "\n".join(
        f"C-{i},{'open' if i % 2 else 'closed'},{'closed' if i % 2 else 'open'}"
        for i in range(12))
    ds = _load_csv(tmp_path, "case_id,status_before,status_after\n" + rows + "\n")
    result = detect_mapping(ds)
    assert not result.link_mode
    assert result.label_column == "case_id"
