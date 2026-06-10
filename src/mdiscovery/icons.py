"""Entity icon library — i2-style minimalist SVG icons from ``assets/icons``.

Icons are stroke-based SVGs drawn with ``currentColor`` so they can be
recolored per theme. Python reads them once and injects them into the
Cytoscape canvas (via ``GraphView.push_icon_library``); the dossier and
authoring dialogs use the same registry for pickers and previews.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .graph.models import SemanticType

# icons.py lives at <root>/src/mdiscovery/ — parents[2] is <root>.
ICONS_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"

# Display name -> file stem. Order is the picker order.
ICONS: dict[str, str] = {
    "Man":           "person-male",
    "Woman":         "person-female",
    "Organization":  "organization",
    "Group":         "group",
    "Money":         "money",
    "Cell Phone":    "cell-phone",
    "IMSI":          "imsi",
    "IMEI":          "imei",
    "Cell Tower":    "cell-tower",
}

# Default icon per semantic type (entities can override per-instance).
DEFAULT_TYPE_ICONS: dict[SemanticType, str] = {
    SemanticType.PERSON:       "person-male",
    SemanticType.ORGANIZATION: "organization",
    SemanticType.PHONE:        "cell-phone",
    SemanticType.ACCOUNT:      "money",
}


@lru_cache(maxsize=1)
def load_icon_svgs() -> dict[str, str]:
    """Read every library SVG once; returns {stem: svg_text}."""
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(ICONS_DIR.glob("*.svg"))
    }


def icon_for(semantic_type: SemanticType, override: str = "") -> str:
    """Resolve the icon stem an entity should display ("" = no icon)."""
    if override:
        return override
    return DEFAULT_TYPE_ICONS.get(semantic_type, "")


def colored_svg(stem: str, color: str) -> str:
    """Icon SVG with ``currentColor`` replaced by a concrete theme color."""
    svg = load_icon_svgs().get(stem)
    return svg.replace("currentColor", color) if svg else ""
