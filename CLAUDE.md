# CLAUDE.md

Guidance for AI agents working in this repository.

## What this is

**mDiscovery** — a local-first, desktop intelligence-analysis app (an IBM i2 Analyst's
Notebook alternative). Import structured data → entity/relationship graph → visualize,
analyze, and export. All on-device: embedded Kuzu graph DB, PyQt6 UI, no servers.

## Layout

```
src/mdiscovery/
  app.py            entry point (mdiscovery console script → main())
  graph/            data layer — models, Kuzu database, repository facade
  importer/         ingestion (CSV/XLSX) + preview→commit pipeline
  analysis/         metrics: degree centrality, connected components, summary
  export/           serializers: GraphML, CSV, JSON, Markdown report
  viz/              GraphView — PyQt6 WebEngine ↔ Cytoscape.js bridge
  ui/               MainWindow, EntityInspector, ImportDialog
assets/cytoscape/   graph.html — the Cytoscape front-end (JS API called from Python)
tests/              pytest suite (data layer + analysis + export)
benchmarks/         graph performance harness
```

## Conventions

- **Layering:** keep raw Cypher inside `graph/repository.py`; the rest of the app talks
  to the repository API. UI never touches the database directly.
- **Pure cores:** `analysis/` and `export/` functions take plain `list[Entity]` /
  `list[Link]` and return values — no DB, no Qt. Add thin `*_from_repo` / `write_export`
  wrappers for app wiring. This keeps them unit-testable (and testable in CI, which has
  no Qt/display).
- **Stable IDs:** entity IDs are derived deterministically from label + semantic type
  (`ImportPipeline._stable_id`) so re-imports MERGE rather than duplicate.
- **Style:** dataclasses with type hints, module docstrings describing purpose. Match the
  surrounding code's density and naming.

## Testing

```bash
pytest            # full suite
pytest tests/test_export.py -q   # a single file
```

The data layer, analysis, and export are fully covered. The **UI/viz layers are not
unit-tested** — they need a Qt binding and a display. When you touch `ui/` or `viz/`,
verify with `python -m py_compile` and exercise the behavior manually; don't claim test
coverage that doesn't exist.

## Gotchas

- Kuzu's database path is a single file (with a transient `.wal` sidecar while open),
  not a directory — do not pre-create it as a directory.
- `pandas` 3.x: `df.where(pd.notna(df), None)` leaks NaN into object columns; sanitize
  materialized rows directly (see `importer/ingestion.py`).
- The Cytoscape JS API (`loadGraph`, `applyLayout`, `highlightPath`, `searchAndLocate`,
  `expandNeighbors`) lives in `assets/cytoscape/graph.html` and is invoked from
  `viz/graph_view.py` via `runJavaScript`. Keep the two in sync.
