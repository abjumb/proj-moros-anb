# mDiscovery

**Local-first intelligence analysis suite** — an IBM i2 Analyst's Notebook alternative
at a fraction of the cost. Import structured data, build an entity-relationship graph,
explore it visually, analyze its structure, and export to standard formats. Everything
runs on your machine: no servers, no JVM, no cloud.

## Highlights

- **Embedded graph store** — [Kuzu](https://kuzudb.com/), a Python-native graph
  database. Zero external services.
- **Smart import** — CSV/XLSX ingestion with encoding detection, type inference, and a
  preview-before-commit pipeline. Re-importing merges (stable IDs) instead of duplicating.
- **Interactive visualization** — Cytoscape.js in a PyQt6 WebEngine view, with
  semantic-type styling, multiple layouts, search, and path highlighting.
- **Analysis** — degree centrality, connected components, and graph summaries.
- **Export** — GraphML (Gephi/yEd/i2), CSV node/edge pairs, node-link JSON, and
  Markdown case reports.

## Install

Requires Python 3.11+.

```bash
pip install -e .            # runtime app (pulls in PyQt6 + WebEngine)
pip install -e ".[dev]"     # + test tooling
```

## Run

```bash
mdiscovery                  # launches the desktop app
```

The app opens an empty default case at `~/.mdiscovery/default_case.kuzu`. Use
**Import…** to load data, **Export…** to write it out, and the layout buttons to
re-arrange the graph.

## Architecture

```
src/mdiscovery/
├── app.py            # entry point (QApplication bootstrap, dark palette)
├── graph/            # data layer
│   ├── models.py     #   Entity, Link, SemanticType, LinkDirection
│   ├── database.py   #   embedded Kuzu database + schema
│   └── repository.py #   query/repository API (no raw Cypher leaks out)
├── importer/         # CSV/XLSX ingestion + preview→commit pipeline
├── analysis/         # degree centrality, components, graph summary
├── export/           # GraphML / CSV / JSON / Markdown report serializers
├── viz/              # GraphView (PyQt6 ↔ Cytoscape.js bridge)
└── ui/               # MainWindow, EntityInspector, ImportDialog
```

The analysis and export layers operate on plain `Entity`/`Link` lists, so they are
fully unit-testable without a live database or a display.

## Development

```bash
pytest                      # run the test suite
```

Tests cover the data model, database, repository, traversal, ingestion, import
pipeline, analysis metrics, and export serializers. The UI and visualization layers
require a Qt binding and a display, so they are exercised manually rather than in CI.
