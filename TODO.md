# mDiscovery — Improvement TODOs

Findings from a full repo scan (2026-06-09). Items marked **[verified]** were
reproduced against the current code, not just read from it. File references
point at the relevant code.

---

## P0 — Correctness bugs

- [ ] **`LinkRepository.upsert` never updates** — it is insert-or-skip, despite
  the name and docstring ("Insert or update"). Re-upserting a link with a new
  `strength`/`confidence` silently keeps the old values. **[verified]**
  Add `ON MATCH SET` semantics or rename to `insert_if_absent` and fix callers.
  → `src/mdiscovery/graph/repository.py:105`

- [ ] **Entity search is case-sensitive** — `search("alice")` finds nothing for
  an entity labelled "Alice". **[verified]** Use `LOWER(e.label) CONTAINS LOWER($q)`
  (or a full-text index when graph size warrants it).
  → `src/mdiscovery/graph/repository.py:47`

- [ ] **`find_path` only follows link direction** — `find_path("b", "a")` returns
  no path even when a directed link a→b exists. **[verified]** Meanwhile
  `neighbors()` matches undirected. The data model has `LinkDirection`
  (directed/undirected/bidirectional) but storage is always a single directed
  edge and traversal ignores the `direction` property entirely. Decide the
  semantics once and make `find_path`, `neighbors`, and the Cytoscape rendering
  agree: undirected/bidirectional links should be traversable both ways.
  → `src/mdiscovery/graph/repository.py:218`, `src/mdiscovery/graph/models.py:23`

- [ ] **`Entity.from_dict` crashes on unknown `semantic_type`** — raises
  `ValueError` instead of degrading to `UNKNOWN`. **[verified]** Any DB written
  by a future version with a new type makes today's build unable to read the
  case file. Same applies to `LinkDirection` in `Link.from_dict`.
  → `src/mdiscovery/graph/models.py:55`, `src/mdiscovery/graph/models.py:106`

## P0 — Security (this app ingests untrusted CSVs)

- [ ] **HTML injection from imported data** — entity labels/properties are
  interpolated unescaped into `tooltip.innerHTML` in the graph view and into
  the rich-text `QLabel` in `EntityInspector.show_entity`. A CSV cell like
  `<img src=x onerror=...>` executes inside the WebEngine page. Escape all
  data-derived strings in both places.
  → `assets/cytoscape/graph.html:138`, `src/mdiscovery/ui/main_window.py:36`

- [ ] **Cytoscape.js loaded from unpkg CDN** — a "local-first" intelligence
  tool must not require internet or leak usage to a third party, and the graph
  view silently breaks offline. Vendor `cytoscape.min.js` into `assets/`.
  → `assets/cytoscape/graph.html:25`

- [ ] **Fragile Python→JS interpolation** — `runJavaScript(f"...({name!r})")`
  builds JS by Python `repr`, and `highlightPath` builds selectors via
  `cy.$('#' + id)`, which breaks (or worse) on IDs with special characters.
  Pass data via `json.dumps` only, and use `cy.getElementById(id)`.
  → `src/mdiscovery/viz/graph_view.py:109-127`, `assets/cytoscape/graph.html:194-216`

## P1 — Performance (stated budgets are currently missed)

- [ ] **Row-at-a-time writes: ~330 entities/s** — `upsert_batch` loops single
  `execute` calls; 10k entities ≈ 30s vs. the 5s budget in
  `benchmarks/graph_perf.py`. **[verified]** Batch with a single parameterized
  statement, a transaction, or Kuzu's `COPY FROM` a DataFrame.
  → `src/mdiscovery/graph/repository.py:30`, `:129`

- [ ] **Import runs on the GUI thread** — `ImportDialog._do_commit` blocks the
  event loop, so a large import freezes the window for its full duration (see
  above: ~30s for 10k rows). Move commit (and preview) to a `QThread`/worker
  with a progress bar and cancel.
  → `src/mdiscovery/ui/import_dialog.py:428`

- [ ] **Duplicate detection loads the whole graph** — `preview()` and
  `commit()` call `entities.all()` and materialize every entity just to count
  ID collisions. Use per-ID existence checks or a single `WHERE e.id IN $ids`
  count query.
  → `src/mdiscovery/importer/pipeline.py:70`, `:95`

- [ ] **Ingestion reads + chardet-scans the entire file** — `read_bytes()` and
  whole-file `chardet.detect` make large CSVs slow and memory-heavy; detect on
  the first ~64KB. Also `_infer_type` runs try/except `pd.to_datetime` per
  value over every non-null row; cap inference to a bounded sample.
  → `src/mdiscovery/importer/ingestion.py:43`, `:93`

- [ ] **Full-graph reload on every change** — `load_from_repo` re-serializes
  and re-pushes the entire graph JSON and reruns layout after each import or
  refresh. Fine at hundreds of nodes, unusable at the 10k+ target; plan
  incremental adds (`cy.add` deltas) or progressive/viewport loading.
  → `src/mdiscovery/viz/graph_view.py:100`, `src/mdiscovery/graph/repository.py:195`

## P1 — Packaging / distribution

- [ ] **Installed wheel cannot find the graph HTML** — the wheel only packages
  `src/mdiscovery`, but the Cytoscape assets live in repo-root `assets/` and
  `ASSETS_DIR` climbs `parents[3]` from the module path, which only works from
  a source checkout. An installed app shows "graph.html not found". Move
  `assets/cytoscape/` inside the package and resolve via `importlib.resources`.
  → `pyproject.toml:31`, `src/mdiscovery/viz/graph_view.py:22`

- [ ] **No `python -m mdiscovery`** — add `src/mdiscovery/__main__.py` calling
  `app.main()`.

- [ ] **pyproject metadata incomplete** — no `readme`, `license`, `authors`,
  or classifiers; no pinned/lock file for reproducible installs (consider uv).
  → `pyproject.toml`

## P2 — Product gaps (backend exists, no UI wiring)

- [ ] **Search box** — `EntityRepository.search` and JS `searchAndLocate` both
  exist, but the main window has no search field. Add a toolbar search box
  (fix case-sensitivity first, see P0).
  → `src/mdiscovery/ui/main_window.py:79`

- [ ] **Path-finding tool** — `find_path` + `highlight_path`/`clearHighlight`
  are implemented and tested but unreachable from the UI. Add "find path
  between two selected nodes".
  → `src/mdiscovery/graph/repository.py:218`, `src/mdiscovery/viz/graph_view.py:117`

- [ ] **`expand_neighbors` is wired to nothing** — and its JS counterpart only
  un-fades the neighborhood; there is no on-demand subgraph loading. Hook it to
  node double-click/context menu.
  → `src/mdiscovery/viz/graph_view.py:126`, `assets/cytoscape/graph.html:213`

- [ ] **Case management** — DB path is hard-coded to
  `~/.mdiscovery/default_case.kuzu`; there is no New/Open/Recent case flow,
  which the product brief (i2 ANB replacement) implies. Add a case
  open/create dialog and window-title case name.
  → `src/mdiscovery/ui/main_window.py:21`

- [ ] **Manual entity/link editing** — no way to create, edit, or delete
  entities/links from the UI; the inspector is read-only. Repos already
  support delete/upsert.

- [ ] **Export** — no PNG/SVG image export and no CSV/JSON data export, both
  table-stakes for analyst reports. `get_graph_json` and Cytoscape's `png()`
  make this cheap.

- [ ] **Empty-state UX** — a first-run user sees a blank dark canvas with no
  hint; show a "Import data to get started" overlay when the graph is empty.

- [ ] **Status bar never shows link direction/strength legends or selection
  info** — only counts. Minor, but analysts need selection feedback.

## P3 — Testing & CI

- [ ] **Zero UI tests** — `pytest-qt` is declared as a dev dependency but
  unused. Add smoke tests: `MainWindow` constructs against a temp DB,
  `ImportDialog` simple-mode mapping builds, preview enables the Import
  button. (Headless: `QT_QPA_PLATFORM=offscreen`.)
  → `tests/`

- [ ] **No CI** — add a GitHub Actions workflow: install, `pytest`, and run
  ruff/mypy (below). The suite is fast (49 tests in ~3s) so this is cheap.

- [ ] **Benchmark has no regression guard** — `benchmarks/graph_perf.py`
  prints ✓/✗ but always exits 0. Make it exit non-zero on budget breach so CI
  can catch regressions (run a small-N variant in CI).
  → `benchmarks/graph_perf.py:74`

- [ ] **Missing edge-case ingestion tests** — duplicate column names, empty
  file/header-only CSV, non-UTF8 encodings (chardet path), multi-sheet XLSX
  (currently only the first sheet is read, silently — also worth a UI sheet
  picker).
  → `src/mdiscovery/importer/ingestion.py:58`

## P3 — Code quality & hygiene

- [ ] **No linter/type-checker config** — add ruff + mypy (strict on
  `graph/` and `importer/` at least) and pre-commit. Known issues they would
  catch today: `tuple[float, any]` (builtin `any`, should be `typing.Any`) in
  `benchmarks/graph_perf.py:39`; unused imports (`Optional` in
  `importer/ingestion.py`, `uuid` in `importer/pipeline.py`, `json` in
  `graph/repository.py`).

- [ ] **No logging** — exceptions in the UI become message boxes and parse
  warnings are strings; there is no `logging` anywhere, making field debugging
  impossible. Add a module-level logger and a rotating file handler under
  `~/.mdiscovery/logs/`.

- [ ] **`GraphDatabase.close()` relies on `del`** — recent kuzu versions
  expose explicit `close()`; prefer it, and make `close()` idempotent (a
  second call currently raises `AttributeError`).
  → `src/mdiscovery/graph/database.py:51`

- [ ] **Dead `.gitignore` entry** — `~/.mdiscovery/` does not do what it looks
  like (gitignore does not expand `~`); remove it.
  → `.gitignore:8`

- [ ] **`benchmarks/graph_perf.py` link-count arithmetic** — `n = min(len-1,
  len)` is always `len-1`; simplify, and the printed link count
  (`len(all_entities)//2`) does not match the number actually created.
  → `benchmarks/graph_perf.py:54-61`

## P3 — Documentation

- [ ] **No README** — add setup (editable install needed to run tests),
  usage, a screenshot, the Kuzu-over-Neo4j decision (currently only in a
  docstring), and the AS-XX ticket convention used in commits/docstrings.
- [ ] **No LICENSE** — decide and add one; required before any distribution.
- [ ] **No CONTRIBUTING / dev guide** — document `pip install -e .[dev]`,
  how to run tests and benchmarks, and the import-pipeline architecture
  (ingestion → mapping → preview → commit).
