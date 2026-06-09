"""M3: case persistence — copy_case and RecentCases."""

import pytest

from mdiscovery.persistence import copy_case, RecentCases


# --- copy_case -------------------------------------------------------------

def test_copy_case_copies_file_and_wal_sidecar(tmp_path):
    src = tmp_path / "case"
    src.write_text("db-bytes")
    src.with_name("case.wal").write_text("wal-bytes")

    dst = tmp_path / "out" / "copy"
    result = copy_case(src, dst)

    assert result == dst
    assert dst.read_text() == "db-bytes"
    assert dst.with_name("copy.wal").read_text() == "wal-bytes"


def test_copy_case_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        copy_case(tmp_path / "nope", tmp_path / "dst")


def test_copy_case_existing_dest_raises_unless_overwrite(tmp_path):
    src = tmp_path / "case"
    src.write_text("new")
    dst = tmp_path / "dst"
    dst.write_text("old")

    with pytest.raises(FileExistsError):
        copy_case(src, dst)

    copy_case(src, dst, overwrite=True)
    assert dst.read_text() == "new"


def test_copy_case_same_path_is_noop_and_preserves_source(tmp_path):
    # Save Case As onto the currently-open case must not delete it.
    src = tmp_path / "case"
    src.write_text("important")
    result = copy_case(src, tmp_path / "case", overwrite=True)
    assert result == tmp_path / "case"
    assert src.read_text() == "important"


def test_copy_case_copies_directory(tmp_path):
    src = tmp_path / "casedir"
    src.mkdir()
    (src / "data").write_text("x")
    dst = tmp_path / "copydir"
    copy_case(src, dst)
    assert (dst / "data").read_text() == "x"


# --- RecentCases -----------------------------------------------------------

def test_recent_add_orders_most_recent_first(tmp_path):
    store = tmp_path / "recent.json"
    rc = RecentCases(store)
    rc.add(tmp_path / "a")
    rc.add(tmp_path / "b")
    names = [p.name for p in rc.list()]
    assert names == ["b", "a"]


def test_recent_add_dedupes_and_promotes(tmp_path):
    rc = RecentCases(tmp_path / "recent.json")
    rc.add(tmp_path / "a")
    rc.add(tmp_path / "b")
    rc.add(tmp_path / "a")  # re-add promotes to front, no duplicate
    names = [p.name for p in rc.list()]
    assert names == ["a", "b"]


def test_recent_respects_max_entries(tmp_path):
    rc = RecentCases(tmp_path / "recent.json", max_entries=2)
    rc.add(tmp_path / "a")
    rc.add(tmp_path / "b")
    rc.add(tmp_path / "c")
    names = [p.name for p in rc.list()]
    assert names == ["c", "b"]


def test_recent_persists_across_instances(tmp_path):
    store = tmp_path / "recent.json"
    RecentCases(store).add(tmp_path / "a")
    reloaded = RecentCases(store)
    assert [p.name for p in reloaded.list()] == ["a"]


def test_recent_existing_filters_missing_without_mutating(tmp_path):
    rc = RecentCases(tmp_path / "recent.json")
    present = tmp_path / "here"
    present.write_text("x")
    rc.add(present)
    rc.add(tmp_path / "gone")
    assert [p.name for p in rc.existing()] == ["here"]
    assert len(rc.list()) == 2  # list itself is untouched


def test_recent_remove_and_clear(tmp_path):
    rc = RecentCases(tmp_path / "recent.json")
    rc.add(tmp_path / "a")
    rc.add(tmp_path / "b")
    rc.remove(tmp_path / "a")
    assert [p.name for p in rc.list()] == ["b"]
    rc.clear()
    assert rc.list() == []


def test_recent_tolerates_corrupt_store(tmp_path):
    store = tmp_path / "recent.json"
    store.write_text("{not valid json")
    rc = RecentCases(store)
    assert rc.list() == []
    rc.add(tmp_path / "a")  # still usable
    assert [p.name for p in rc.list()] == ["a"]
