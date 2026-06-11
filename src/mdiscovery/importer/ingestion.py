"""AS-11: CSV/XLSX ingestion service.

Parses raw files into staged, typed rows. Handles encodings, headers,
mixed types, and surfaces parse errors without crashing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import io

import chardet
import pandas as pd


def _sanitize_records(records: list[dict]) -> list[dict]:
    # Normalise missing values to None. `df.where(pd.notna(df), None)` is
    # unreliable under pandas 3.x (NaN leaks back into object columns), so
    # sanitise materialised rows directly.
    return [
        {k: (None if (v is None or (isinstance(v, float) and pd.isna(v))) else v)
         for k, v in row.items()}
        for row in records
    ]


class StagedDataset:
    """Parsed file staged for import.

    Holds the pandas frame; ``rows`` (a list of sanitised dicts) is
    materialised lazily because a 50 MB file is ~1M dict allocations the
    vectorised import path never needs.
    """

    def __init__(self, columns: list[str],
                 rows: Optional[list[dict[str, Any]]] = None,
                 column_samples: Optional[dict[str, list[Any]]] = None,
                 column_types: Optional[dict[str, str]] = None,
                 parse_warnings: Optional[list[str]] = None,
                 frame: Optional[pd.DataFrame] = None):
        self.columns = columns
        self._rows = rows
        self.frame = frame
        self.column_samples = column_samples or {}
        self.column_types = column_types or {}  # "string"|"numeric"|"date"|"mixed"
        self.parse_warnings = parse_warnings or []

    @property
    def rows(self) -> list[dict[str, Any]]:
        if self._rows is None:
            self._rows = (_sanitize_records(self.frame.to_dict(orient="records"))
                          if self.frame is not None else [])
        return self._rows

    def row_count(self) -> int:
        if self._rows is not None:
            return len(self._rows)
        return 0 if self.frame is None else len(self.frame)

    def head(self, n: int = 50) -> list[dict[str, Any]]:
        if self._rows is not None:
            return self._rows[:n]
        if self.frame is None:
            return []
        return _sanitize_records(self.frame.head(n).to_dict(orient="records"))


class IngestionService:
    """Detect encoding, parse CSV/XLSX into a StagedDataset."""

    SAMPLE_ROWS = 5
    # Type inference reads at most this many non-null values per column —
    # pd.to_datetime per value over a whole 100k-row column is pure overhead.
    TYPE_INFERENCE_SAMPLE = 200

    def load(self, path: str | Path) -> StagedDataset:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix in (".xlsx", ".xls", ".xlsm"):
            return self._load_excel(path)
        return self._load_csv(path)

    def _load_csv(self, path: Path) -> StagedDataset:
        raw = path.read_bytes()
        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"
        warnings: list[str] = []
        if (detected.get("confidence") or 0) < 0.7:
            warnings.append(
                f"Low encoding confidence ({detected.get('confidence', 0):.0%}); "
                f"assuming {encoding}."
            )
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding=encoding, dtype=str, low_memory=False)
        except Exception as exc:
            raise ValueError(f"Failed to parse CSV: {exc}") from exc
        return self._frame_to_staged(df, warnings)

    def _load_excel(self, path: Path) -> StagedDataset:
        try:
            df = pd.read_excel(path, dtype=str)
        except Exception as exc:
            raise ValueError(f"Failed to parse Excel: {exc}") from exc
        return self._frame_to_staged(df, [])

    def _frame_to_staged(self, df: pd.DataFrame, warnings: list[str]) -> StagedDataset:
        df.columns = [str(c).strip() for c in df.columns]

        column_samples: dict[str, list[Any]] = {}
        column_types: dict[str, str] = {}

        for col in df.columns:
            non_null = df[col].dropna()
            column_samples[col] = non_null.head(self.SAMPLE_ROWS).tolist()
            # Spread the inference sample across the whole column, not just the
            # head — otherwise a column that turns mixed only in later rows is
            # misclassified on large files (and never on small ones).
            n = len(non_null)
            if n > self.TYPE_INFERENCE_SAMPLE:
                step = n // self.TYPE_INFERENCE_SAMPLE
                inference_sample = non_null.iloc[::step].tolist()
            else:
                inference_sample = non_null.tolist()
            column_types[col] = self._infer_type(inference_sample)

        return StagedDataset(
            columns=list(df.columns),
            frame=df,
            column_samples=column_samples,
            column_types=column_types,
            parse_warnings=warnings,
        )

    def _infer_type(self, values: list[Any]) -> str:
        if not values:
            return "string"
        numeric_ok = sum(1 for v in values if self._is_numeric(str(v)))
        if numeric_ok == len(values):
            return "numeric"
        date_ok = sum(1 for v in values if self._is_date(str(v)))
        if date_ok > len(values) * 0.8:
            return "date"
        if numeric_ok > 0:
            return "mixed"
        return "string"

    @staticmethod
    def _is_numeric(s: str) -> bool:
        try:
            float(s.replace(",", ""))
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_date(s: str) -> bool:
        s = s.strip()
        if not s:
            return False
        # A bare integer/float is numeric, not a date — guard against
        # pandas interpreting "123" as a nanosecond timestamp.
        try:
            float(s.replace(",", ""))
            return False
        except ValueError:
            pass
        try:
            # `infer_datetime_format` was removed in pandas 2.0; format is
            # inferred automatically. errors="raise" so non-dates fall through.
            pd.to_datetime(s, errors="raise")
            return True
        except (ValueError, TypeError, OverflowError):
            return False
