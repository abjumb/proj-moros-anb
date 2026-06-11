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
    here = Path(__file__).resolve()
    # Dev / editable install first: a stale wheel-built _assets copy in a
    # dev tree must never shadow the live repo assets/.
    for parent in here.parents[:5]:
        candidates.append(parent / "assets")
    # Non-editable wheel installs: assets are force-included into the
    # package as mdiscovery/_assets (see pyproject).
    candidates.append(here.parent / "_assets")
    for candidate in candidates:
        if (candidate / "cytoscape" / "graph.html").exists():
            return candidate
    # Fail loudly: a silent guessed path surfaces three layers away as a
    # blank canvas with zero diagnostics.
    searched = "\n  ".join(str(c) for c in candidates)
    raise RuntimeError(
        "mDiscovery assets not found. Searched:\n  " + searched
        + "\nSupported layouts: dev checkout, pip wheel, PyInstaller bundle.")


ASSETS_ROOT: Path = _find_assets_root()
CYTOSCAPE_DIR: Path = ASSETS_ROOT / "cytoscape"
ICONS_DIR: Path = ASSETS_ROOT / "icons"
