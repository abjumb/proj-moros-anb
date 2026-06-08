"""AS-11: CSV/XLSX ingestion — encodings, headers, type inference, error handling."""

from pathlib import Path

import pytest

from mdiscovery.importer.ingestion import IngestionService, StagedDataset


def test_load_csv_columns_and_rows(people_csv: Path):
    ds = IngestionService().load(people_csv)
    assert ds.columns == ["name", "role", "city", "age"]
    assert len(ds.rows) == 5
    assert ds.rows[0]["name"] == "Alice Carter"


def test_type_inference(people_csv: Path):
    ds = IngestionService().load(people_csv)
    assert ds.column_types["age"] == "numeric"
    assert ds.column_types["name"] == "string"


def test_column_samples_capped(people_csv: Path):
    ds = IngestionService().load(people_csv)
    assert len(ds.column_samples["city"]) <= IngestionService.SAMPLE_ROWS
    assert "London" in ds.column_samples["city"]


def test_head_limit(people_csv: Path):
    ds = IngestionService().load(people_csv)
    assert len(ds.head(2)) == 2


def test_date_type_inference(tmp_path: Path):
    p = tmp_path / "events.csv"
    p.write_text("event,when\nA,2021-01-02\nB,2022-03-04\nC,2023-05-06\n")
    ds = IngestionService().load(p)
    # Regression: pandas 2.0+ removed infer_datetime_format; dates must still infer.
    assert ds.column_types["when"] == "date"


def test_numeric_not_misread_as_date(tmp_path: Path):
    p = tmp_path / "nums.csv"
    p.write_text("id,n\nA,100\nB,200\nC,300\n")
    ds = IngestionService().load(p)
    assert ds.column_types["n"] == "numeric"


def test_missing_values_become_none(tmp_path: Path):
    p = tmp_path / "gappy.csv"
    p.write_text("a,b\n1,\n,2\n")
    ds = IngestionService().load(p)
    assert ds.rows[0]["b"] is None
    assert ds.rows[1]["a"] is None


def test_bad_path_raises(tmp_path: Path):
    with pytest.raises(Exception):
        IngestionService().load(tmp_path / "does_not_exist.csv")


def test_xlsx_roundtrip(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["name", "score"])
    ws.append(["Alice", 10])
    ws.append(["Bob", 20])
    path = tmp_path / "scores.xlsx"
    wb.save(path)

    ds = IngestionService().load(path)
    assert ds.columns == ["name", "score"]
    assert len(ds.rows) == 2
    assert ds.rows[0]["name"] == "Alice"
