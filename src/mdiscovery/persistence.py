"""M3: Case persistence — recent-cases tracking and case-file copying.

A "case" is a single Kuzu database file (with a transient ``.wal`` sidecar while
open). These helpers let the app open, copy, and remember case files. They are
plain filesystem/JSON operations — no Qt — so they are unit-testable.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

# Sidecar files Kuzu may write next to the main database file.
_KUZU_SIDECARS = (".wal", ".shadow", ".tmp")


def copy_case(src: str | Path, dst: str | Path, *, overwrite: bool = False) -> Path:
    """Copy a case at ``src`` to ``dst`` (including Kuzu sidecar files).

    Returns the destination path. Raises ``FileNotFoundError`` if ``src`` does
    not exist and ``FileExistsError`` if ``dst`` exists and ``overwrite`` is False.
    """
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        raise FileNotFoundError(f"No case at {src}")
    if dst.exists():
        if not overwrite:
            raise FileExistsError(f"{dst} already exists")
        _remove(dst)

    dst.parent.mkdir(parents=True, exist_ok=True)

    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
        for suffix in _KUZU_SIDECARS:
            sidecar = src.with_name(src.name + suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, dst.with_name(dst.name + suffix))
    return dst


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


class RecentCases:
    """Most-recently-used list of case paths, persisted as JSON.

    Entries are de-duplicated by resolved absolute path, ordered most-recent
    first, and capped at ``max_entries``. All mutations write through to disk
    immediately so the list survives restarts.
    """

    def __init__(self, store_path: str | Path, max_entries: int = 10):
        self._store = Path(store_path)
        self._max = max_entries
        self._paths: list[str] = self._load()

    def _load(self) -> list[str]:
        if not self._store.exists():
            return []
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(data, list):
            return [str(p) for p in data][: self._max]
        return []

    def _save(self) -> None:
        self._store.parent.mkdir(parents=True, exist_ok=True)
        self._store.write_text(json.dumps(self._paths, indent=2), encoding="utf-8")

    @staticmethod
    def _key(case_path: str | Path) -> str:
        return str(Path(case_path).expanduser().resolve())

    def add(self, case_path: str | Path) -> None:
        key = self._key(case_path)
        if key in self._paths:
            self._paths.remove(key)
        self._paths.insert(0, key)
        del self._paths[self._max:]
        self._save()

    def remove(self, case_path: str | Path) -> None:
        key = self._key(case_path)
        if key in self._paths:
            self._paths.remove(key)
            self._save()

    def list(self) -> list[Path]:
        return [Path(p) for p in self._paths]

    def existing(self) -> list[Path]:
        """Recent paths that still exist on disk (the list is left unchanged)."""
        return [Path(p) for p in self._paths if Path(p).exists()]

    def clear(self) -> None:
        self._paths = []
        self._save()
