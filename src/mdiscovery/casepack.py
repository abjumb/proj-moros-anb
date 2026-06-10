"""The .onb case package — mDiscovery's portable chart document.

The Kuzu database is the *working store*; this is the *document*: a single
zip the analyst can share or archive. Layout travels automatically because
node positions live in each entity's ``style`` (x/y), and dossier photos are
bundled with their references rewritten to package-relative paths.

Package layout::

    manifest.json    {"format": "onb", "version": 1, "generator": ..., "created_at": ...}
    graph.json       node-link document (same schema as the JSON export)
    media/<files>    dossier photos referenced by entity styles

The extension is a single constant so the format can be renamed later
without touching call sites. Versioned from day one: readers reject packages
written by a NEWER format version with a clear message instead of
misparsing them.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path

from .graph.models import Entity, Link
from .export.exporters import to_json
from .importer.json_import import parse_node_link_text

EXTENSION = ".onb"
FORMAT_NAME = "onb"
FORMAT_VERSION = 1
_GENERATOR = "mDiscovery"


def write_package(path: str | Path, entities: list[Entity],
                  links: list[Link]) -> Path:
    """Write a case package; returns the path written.

    Entity photo references (absolute paths in ``style['photo']``) are copied
    into ``media/`` and rewritten package-relative, so the package is
    self-contained. Entities whose photo file is missing keep their other
    style fields and simply drop the dangling reference.
    """
    path = Path(path)
    if path.suffix != EXTENSION:
        path = path.with_suffix(EXTENSION)

    packaged: list[Entity] = []
    media: dict[str, Path] = {}  # arcname -> source file
    for entity in entities:
        photo = entity.style.get("photo")
        if photo and Path(photo).is_file():
            arcname = f"media/{entity.id}{Path(photo).suffix.lower()}"
            media[arcname] = Path(photo)
            style = dict(entity.style)
            style["photo"] = arcname
        elif photo:
            style = dict(entity.style)
            style.pop("photo")
        else:
            style = entity.style
        packaged.append(Entity(
            id=entity.id, label=entity.label,
            semantic_type=entity.semantic_type,
            properties=entity.properties, icon=entity.icon, style=style,
        ))

    manifest = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "generator": _GENERATOR,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "entity_count": len(packaged),
        "link_count": len(links),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("graph.json", to_json(packaged, links))
        for arcname, source in media.items():
            zf.write(source, arcname)
    return path


def read_package(path: str | Path,
                 media_dir: str | Path | None = None
                 ) -> tuple[dict, list[Entity], list[Link]]:
    """Read a case package; returns (manifest, entities, links).

    When ``media_dir`` is given, bundled photos are extracted there and
    entity photo references are rewritten back to absolute paths; without
    it, photo references are dropped (graph data still loads fully).

    Raises ``ValueError`` for non-packages, foreign formats, and packages
    written by a newer format version than this reader understands.
    """
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "manifest.json" not in names or "graph.json" not in names:
                raise ValueError("Not a case package (missing manifest/graph).")
            try:
                manifest = json.loads(zf.read("manifest.json"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Unreadable manifest: {exc}") from exc
            if manifest.get("format") != FORMAT_NAME:
                raise ValueError(
                    f"Unknown package format {manifest.get('format')!r}.")
            version = manifest.get("version", 0)
            if not isinstance(version, int) or version > FORMAT_VERSION:
                raise ValueError(
                    f"Package version {version} is newer than this app "
                    f"supports (≤ {FORMAT_VERSION}) — please update mDiscovery.")

            entities, links = parse_node_link_text(
                zf.read("graph.json").decode("utf-8"))

            for entity in entities:
                photo = entity.style.get("photo")
                if not photo or not str(photo).startswith("media/"):
                    continue
                if media_dir is not None and photo in names:
                    target_dir = Path(media_dir)
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / Path(photo).name
                    target.write_bytes(zf.read(photo))
                    entity.style["photo"] = str(target)
                else:
                    entity.style.pop("photo", None)
            return manifest, entities, links
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a case package: {exc}") from exc
