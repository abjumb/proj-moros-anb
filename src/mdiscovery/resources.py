"""Locate bundled resources (assets/) in every deployment shape.

Three layouts must resolve identically:

1. **Editable/dev checkout** — ``assets/`` sits at the repository root,
   three levels above this file.
2. **PyInstaller onefile** — resources are unpacked to ``sys._MEIPASS``.
3. **PyInstaller onedir** — resources sit next to the executable.

Resolved once at import; PyInstaller builds must add ``assets`` via
``--add-data`` (see packaging/mdiscovery.spec).
"""

from __future__ import annotations

import sys
from pathlib import Path


def _find_assets_root() -> Path:
    candidates = []
    if getattr(sys, "frozen", False):  # PyInstaller
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "assets")
        candidates.append(Path(sys.executable).resolve().parent / "assets")
    # Dev / editable install: walk up from this file looking for assets/.
    here = Path(__file__).resolve()
    for parent in here.parents[:5]:
        candidates.append(parent / "assets")
    for candidate in candidates:
        if (candidate / "cytoscape" / "graph.html").exists():
            return candidate
    # Fall back to the historical location so the error message points
    # somewhere sensible instead of raising during import.
    return here.parents[2] / "assets"


ASSETS_ROOT: Path = _find_assets_root()
CYTOSCAPE_DIR: Path = ASSETS_ROOT / "cytoscape"
ICONS_DIR: Path = ASSETS_ROOT / "icons"
