# Agent Handoff — mDiscovery

Handoff document for an AI agent picking up this project. Written 2026-06-10 at the
end of a session that delivered PRs #5 and #6 (both merged). Read `CLAUDE.md` first —
it is the standing guide; this file is the session-state snapshot, the lessons that
aren't in `CLAUDE.md` yet, and the roadmap.

---

## 1. What this project is

**mDiscovery** — a local-first desktop intelligence-analysis app, positioned as an
IBM i2 Analyst's Notebook alternative. Import structured data → entity/relationship
graph → visualize, analyze, export. Single user, no servers, no auth boundary.

| Layer | Tech |
|---|---|
| UI shell | PyQt6 (`ui/`), JetBrains Darcula-style theme (`ui/theme.py`) |
| Graph canvas | Cytoscape.js in QtWebEngine (`viz/graph_view.py` ↔ `assets/cytoscape/graph.html`) |
| Data | Embedded Kuzu graph DB (`graph/`), single-file cases (`*.kuzu` + transient `.wal`) |
| Ingestion | pandas CSV/XLSX + node-link JSON (`importer/`) |
| Analysis / Export | Pure functions over `list[Entity]`/`list[Link]` (`analysis/`, `export/`) |

The product's north star is the i2 feature set scaled to local-first. A detailed
feature-gap analysis against i2's architecture was produced this session (see §6).

## 2. Current state (all merged to `master`)

- **PR #3/#4** (pre-session): analysis metrics v1, exporters, persistence, analyst UI.
- **PR #5** (merged): full visual restyle to JetBrains "New UI" Darcula. Single token
  source `ui/theme.py::TOKENS`; QPalette + QSS + Cytoscape canvas all derive from it.
- **PR #6** (merged): optimization + quick-win feature pass:
  - **Batched writes** — `upsert_batch` is one `UNWIND … MERGE` statement. Measured:
    2k entities 4.98s → 0.094s; 1k links 3.92s → 0.21s; 10k entities 0.79s (passes
    the `benchmarks/graph_perf.py` budget that previously failed).
  - **Correctness** — undirected `find_path`; stable importer link ids (folding in
    properties so distinct parallel links survive — see §5.3); true direction from
    `links.for_entity()`; explicit `GraphDatabase.close()` with use-after-close guard;
    JS bridge arguments via `json.dumps` (never `repr`); `html.escape` in the
    inspector; `esc()` in the canvas tooltip.
  - **Features** — SNA metrics (betweenness w/ pivot sampling, closeness, eigenvector,
    label-propagation communities); store-backed incremental expand; repo-backed
    case-insensitive ordered search; "Size by Degree" toggle; File ▸ Import JSON;
    report "Key brokers" table.
- **Tests**: 113 passing (`pytest -q`, ~5s). CI (`.github/workflows/ci.yml`) is
  headless — installs non-Qt deps only; ui/viz are *not* covered by tests, by design.
- **Branch state**: `claude/ecstatic-goodall-vur5vb` == `origin/master` (plus this
  handoff). No other open PRs or branches with pending work.

## 3. Architecture contracts you must preserve

These are load-bearing conventions; breaking them has bitten before.

1. **Layering** — raw Cypher only inside `graph/repository.py`. UI never touches the
   DB. `analysis/` and `export/` cores take plain lists, no DB/Qt imports; app wiring
   goes through `*_from_repo` / `write_export` thin wrappers.
2. **Python ↔ JS bridge** — `viz/graph_view.py::_run_js` serializes every argument
   with `json.dumps`. Never build JS with f-string `repr`. The JS API surface in
   `graph.html` (keep both sides in sync):
   `loadGraph(data)`, `applyLayout(name)`, `highlightPath(ids)`, `clearHighlight()`,
   `expandNeighbors(id)` (un-fade only), `addElements(data, anchorId)` (incremental
   add), `selectAndFit(ids)`, `setDegreeSizing(bool)`.
   JS → Python via QWebChannel `pybridge`: `nodeSelected(id)`, `backgroundTapped()`,
   `viewReady()`. Bridge signals follow the `*Signal` pattern in `PythonBridge` —
   note `@pyqtSlot` methods are NOT connectable; that bug once made the app
   unlaunchable (fixed in `6476cc2`).
3. **Stable IDs** — entity ids: sha256 of `type::label` (`ImportPipeline._stable_id`);
   link ids: sha256 of `src->tgt::type::sorted-props-json` (`_stable_link_id`).
   This is what makes re-imports idempotent (tested). If you change either, you
   change dedup semantics — update the docstring contract and tests together.
4. **Theme tokens** — all chrome colors come from `ui/theme.py::TOKENS`;
   `assets/cytoscape/graph.html` mirrors the same hex values (annotated comment at
   the top of its `<style>`). Change colors in both places or not at all.
5. **Betweenness cost policy** — `analysis/metrics.py::recommended_sample_size()` is
   the single source of truth (exact ≤ 2000 nodes, else 500 pivots). Don't re-hardcode
   thresholds at call sites; `to_report` and `betweenness_centrality_from_repo`
   already route through it.

## 4. Working in this remote environment (practical recipes)

The container is ephemeral, network-restricted, headless. What works:

- **Setup**: `pip install -e .` then `pip install pytest`. PyQt6/WebEngine install
  fine from PyPI. For Qt offscreen you need system libs:
  `apt-get install -y libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1 libnss3
  libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxkbfile1 libasound2t64`.
- **unpkg.com is blocked** (graph.html loads cytoscape from CDN), but
  **raw.githubusercontent.com works**: fetch
  `https://raw.githubusercontent.com/cytoscape/cytoscape.js/v3.30.2/dist/cytoscape.min.js`,
  copy `graph.html` to `/tmp/cytoassets/` with the script src rewritten to the local
  file, and monkeypatch `mdiscovery.viz.graph_view.ASSETS_DIR = Path("/tmp/cytoassets")`
  in test harnesses. Never commit that rewrite.
- **Offscreen app launch** (smoke tests + screenshots via `QWidget.grab()`):
  ```
  QT_QPA_PLATFORM=offscreen QTWEBENGINE_DISABLE_SANDBOX=1 \
  QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" python harness.py
  ```
  Two hard requirements: `QApplication(["somename"])` — an **empty argv crashes
  Chromium init** — and **import a WebEngine module before creating QApplication**
  (else `ImportError: QtWebEngineWidgets must be imported …`).
- **Verifying UI work**: per CLAUDE.md there are no UI unit tests. The workflow that
  proved reliable: `python -m py_compile` on touched files; `node --check` on the
  inline JS (extract `<script>` blocks); offscreen launch with seeded sample data;
  numeric asserts through `page().runJavaScript(code, callback)` (e.g. count nodes
  after expand, read a node's width after toggling sizing); screenshots pixel-checked
  with Pillow for 1px-level claims. Squinting at screenshots is not verification —
  the divider "looked fine" twice while the gradient never actually painted.
- **Process**: no `gh` CLI — GitHub via `mcp__github__*` tools only, scoped to
  `abjumb/proj-moros-anb`. Commits must be authored
  `Claude <noreply@anthropic.com>` (a stop-hook enforces this). Develop on the
  session's designated `claude/...` branch, push with `-u`, open draft PRs.

## 5. Hard-won gotchas (not yet in CLAUDE.md)

### 5.1 Qt / QSS
- **Duplicate gradient stop positions are mangled by Qt** (`stop: 0.4 transparent,
  stop: 0.4 #color` renders garbage, silently). Use an epsilon gap (0.399/0.401).
  This silently broke every splitter/separator line until pixel-probed.
- **`QMainWindow::separator` uses VISUAL-orientation pseudo-states** (a tall
  right-dock bar matches `:vertical`) — the *opposite* of `QSplitter::handle`'s
  documented convention (`:horizontal` = vertical bar of a horizontal splitter).
  Both are handled correctly in `theme.py`; don't "fix" the asymmetry.
- QSS pseudo-state availability differs per widget; verify empirically (offscreen
  probe + pixel check), not from docs.

### 5.2 Cytoscape / WebEngine
- **Cytoscape rejects quoted font-family lists** (`'Inter', 'Segoe UI'` → "invalid
  property", silent fallback). Use unquoted space-free stacks: `Inter, sans-serif`.
- `addElements` assumes the **anchor node is already on the canvas**; edges whose
  endpoints are missing are filtered out (deliberate). It also relies on
  `neighbors()` covering both endpoints of every `for_entity()` link — true while
  `for_entity` returns only links incident to the anchor.
- `cy.style(STYLE.concat(rules))` is the working pattern for toggling conditional
  formatting; the base stylesheet lives in the `STYLE` const.

### 5.3 Kuzu (0.11.x)
- `UNWIND $rows AS r` with a Python list-of-dicts parameter works, including
  rel-`MERGE` — this is the backbone of batch performance. Dict keys/types must be
  homogeneous across rows.
- Rel-MERGE costs ~0.75ms/link regardless of batching strategy (measured: chunked
  500/1000/2000 vs single statement — no difference). Don't re-attempt chunking.
- `LinkRepository.upsert_batch` is **ON CREATE only** — re-importing a link id with
  changed attributes does NOT update it. With properties folded into the id this is
  coherent (changed attrs → new id → new parallel link), but if you ever add a
  "link update" feature you must add `ON MATCH SET`.
- Entities table MERGE updates on match (label/type/props) — asymmetric with links
  by design; documented in the repository docstrings.
- `Database.close()`/`Connection.close()` exist and are used; `connection` raises
  `RuntimeError` after close. Note `EntityRepository`/`LinkRepository` capture the
  raw connection at construction — a stale `GraphRepository` kept across
  `_switch_case` would raise an opaque Kuzu error, not the friendly guard. No current
  code path does this; be careful adding async/queued work that captures repos.

### 5.4 pandas / ingestion
- `"N/A"` (and similar tokens) are parsed as **NaN even with `dtype=str`** and
  dropped by `dropna()` — they never reach type inference. Bit a test this session.
- Type inference samples ≤200 values **spread across the column**
  (`iloc[::step]`), not the head — a column that turns mixed late must still
  classify as mixed (tested).
- The pandas-3.x `df.where(pd.notna(df), None)` NaN-leak gotcha from CLAUDE.md
  still applies.

### 5.5 Algorithms
- Sampled Brandes betweenness: `bc[v] *= scale_up / 2.0` is **correct and unbiased**
  (verified empirically: mean sampled/exact ratio 0.997 over 200 seeds). A reviewer
  plausibly argued it double-corrects; it doesn't. There's a regression test
  (`test_betweenness_sampled_is_unbiased`). Don't "fix" the /2.
- All SNA metrics treat the graph as undirected with de-duplicated parallel edges
  (`_undirected_adjacency`); `degree_centrality` intentionally does NOT use that
  helper (it needs direction and parallel edges). That split is correct.

## 6. Known open items (reviewed, consciously deferred)

From the code/security review passes on PR #6 — none are regressions; all are
documented tradeoffs or pre-existing. Triage before "fixing":

1. **GraphML export marks only UNDIRECTED links `directed="false"`** —
   BIDIRECTIONAL links export as plain directed edges, losing two-way semantics in
   Gephi/yEd/i2 (`export/exporters.py::to_graphml`). Pre-existing; smallest real bug
   on the list. A fix needs a decision: emit `directed="false"` for BIDIRECTIONAL
   too, or two opposing edges.
2. **Search counts DB-wide but locates on-canvas only** — `_do_search` reports repo
   match counts; `selectAndFit` can only select nodes present in Cytoscape. Benign
   today (full graph always loaded) but becomes a real mismatch if partial loading
   ever becomes the default. Also: no result cap/ranking — a broad query selects and
   fits to everything it matches.
3. **`find_path` is undirected by design** — for directed semantics (payments,
   ownership) the "path" may traverse edges backward. i2 offers direction-respecting
   options; a "respect direction" toggle in `FindPathDialog` is the natural fix.
4. **`expand_neighbors` makes two JS calls** (`addElements` + `expandNeighbors`);
   the second only clears prior path-highlight fading. Reviewers found it confusing;
   folding the un-fade into `addElements` would simplify the JS API by one function.
5. **`addElements` rings new nodes at the anchor's position** — if the anchor has
   never been laid out (position 0,0) placement is wrong but cosmetic.
6. **`neighborhood()` is two queries** (nodes + links) where one traversal could
   return both. Interactive-path latency, low priority at embedded scale.
7. **Accepted contrast tradeoffs** (from the theme review): white-on-`#3574F0`
   selection = 4.28:1 (just under AA; matches JetBrains' own choice and the task
   spec); muted `#6F737A` on panels ≈ 2.9:1 for secondary chrome (intentional
   Darcula mimicry). Primary text passes at 10.5–12.6:1. Don't churn these without
   a product decision.
8. **Security posture** (reviewed clean): the two untrusted-data interpreter
   boundaries are Cypher (always `$`-parameterized) and the WebEngine page
   (`json.dumps` bridge + `esc()`/`html.escape` at render). Keep them that way.

## 7. Roadmap — the i2 feature-gap tiers not yet built

From the i2 Analyst's Notebook analysis (entity-link-property model, temporal +
geospatial + SNA analysis, schema-driven data model). Quick wins (F1–F3) shipped in
PR #6. Remaining, in dependency order — **each needs product/design input first**:

- **F4 Typed properties** *(foundational — prerequisite for F5/F6)*: per-property
  type tags (STRING/INT/FLOAT/DATE/DATETIME/GEO/BOOL). Storage can stay
  `properties_json`; the type map must surface in the import mapper UI
  (`import_dialog.py` already has per-column controls) and exporters. Decisions:
  schema representation, migration of existing cases, coercion failure UX.
- **F5 Timeline view**: time-axis visualization + time-range filter/animation over
  the network. Needs F4's DATE type. Likely a second WebEngine view or a Cytoscape
  overlay; i2 treats this as a headline differentiator.
- **F6 Geospatial view**: map plotting for `Location` entities (Leaflet in a second
  WebEngine view, reusing the `PythonBridge` pattern). Needs F4's GEO type. Note the
  CDN restriction (§4) — vendoring the JS lib is probably required; that's a
  dependency-policy decision.
- **F7 Open entity/link type schema**: user-defined types beyond the `SemanticType`
  enum (i2's schema-driven model). Touches models, repository, importer, type colors
  in graph.html. Large refactor.
- **F8 Provenance**: record import source (file, row) per entity/link. Cheap start:
  `pipeline._build_graph_objects` already has `row_idx` in scope and discards it.
- **F9 Saved/highlight queries**: persisted searches auto-highlighting matches
  (i2 "highlight queries").

Explicitly out of scope (contradicts local-first): i2's server tier, RBAC/security
schema, Solr/ZooKeeper, COM SDK.

## 8. Verification ledger (what was actually proven, and how)

| Claim | Evidence |
|---|---|
| 53×/19× batch write speedup | `python -m benchmarks.graph_perf --entities 2000` before/after; 10k run passes budget |
| Sampled betweenness unbiased | 200-seed empirical ratio 0.997; regression test in `tests/test_metrics.py` |
| Incremental expand works on partial canvas | offscreen JS probe: 1 node/0 edges → 3/2 after `expand_neighbors` |
| Degree sizing applies | probe: width 60 → 50 (deg 2) / 43 (deg 1), exact formula match |
| Divider lines render 1px in all orientations | pixel probes on right-dock, bottom-dock, splitter grabs |
| HTML/JS injection safe | `Carla <Voss>` entity renders literally; security review traced all sinks |
| Re-import idempotency incl. parallel links | `tests/test_pipeline.py` distinct-links + reimport tests |

Run `pytest -q` (113 tests) as the baseline gate; benchmark with
`python -m benchmarks.graph_perf` when touching `graph/` write paths.

## 9. File map (orientation)

```
src/mdiscovery/
  app.py                 entry point; palette+font+QSS application
  ui/theme.py            TOKENS + build_stylesheet() — single visual source of truth
  ui/main_window.py      MainWindow, EntityInspector, toolbar/menu/search wiring
  ui/import_dialog.py    Simple/Advanced CSV-XLSX import UI
  ui/find_path_dialog.py path picker dialog
  viz/graph_view.py      GraphView + PythonBridge; _run_js is the only JS entry
  graph/database.py      Kuzu lifecycle (explicit close)
  graph/repository.py    ALL Cypher; batch UNWIND upserts; traversal; search
  graph/models.py        Entity/Link/SemanticType/LinkDirection dataclasses
  importer/ingestion.py  CSV/XLSX → StagedDataset (encoding, spread-sample typing)
  importer/pipeline.py   mapping → preview → commit; stable ids
  importer/json_import.py node-link JSON loader (inverse of to_json)
  analysis/metrics.py    degree/components/summary + SNA; sampling policy
  export/exporters.py    GraphML/CSV/JSON/Markdown report
  persistence.py         copy_case + RecentCases
assets/cytoscape/graph.html  canvas: STYLE const, TYPE_COLORS, JS API, tooltip esc()
benchmarks/graph_perf.py     write/query benchmark with budgets
tests/                       113 tests; data/analysis/export/import covered, ui/viz not
```

## 10. PR history

| PR | State | Content |
|---|---|---|
| #3/#4 | merged pre-session | metrics v1, exporters, persistence, analyst UI, CI |
| #5 | merged | Darcula restyle (+ separate launch-blocker fix `6476cc2`) |
| #6 | merged | optimization pass + SNA + quick-win features + review fixes |

The session branch `claude/ecstatic-goodall-vur5vb` carries master plus this handoff.
A new session will get its own designated branch — use that, not this one.
