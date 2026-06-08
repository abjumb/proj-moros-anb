"""AS-11: CSV/XLSX ingestion service.

Parses raw files into staged, typed rows. Handles encodings, headers,
mixed types, and surfaces parse errors without crashing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
import io

import chardet
import pandas as pd


@dataclass
class StagedDataset:
    columns: list[str]
    rows: list[dict[str, Any]]
    column_samples: dict[str, list[Any]]
    column_types: dict[str, str]  # "string" | "numeric" | "date" | "mixed"
    parse_warnings: list[str] = field(default_factory=list)

    def head(self, n: int = 50) -> list[dict[str, Any]]:
        return self.rows[:n]


class IngestionService:
    """Detect encoding, parse CSV/XLSX into a StagedDataset."""

    SAMPLE_ROWS = 5

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
            non_null = df[col].dropna().tolist()
            column_samples[col] = non_null[: self.SAMPLE_ROWS]
            column_types[col] = self._infer_type(non_null)

        # Normalise missing values to None. `df.where(pd.notna(df), None)` is
        # unreliable under pandas 3.x (NaN leaks back into object columns), so
        # sanitise the materialised rows directly.
        raw_rows = df.to_dict(orient="records")
        rows = [
            {k: (None if (v is None or (isinstance(v, float) and pd.isna(v))) else v)
             for k, v in row.items()}
            for row in raw_rows
        ]
        return StagedDataset(
            columns=list(df.columns),
            rows=rows,
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
