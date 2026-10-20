# Results Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Library page lists every saved result (backtest, optimization, walk-forward, experiment, study), opens any of them read-only without touching the workspace, compares two backtests side by side, and keeps them tidy with labels, stars and a restorable delete.

**Architecture:** A new product module `library.py` (entry model, per-kind headlines cached in the summary sidecars, the query, annotations, the restorable delete) and a pure `compare.py` (identity, strategy differences, oriented metric deltas, union-axis equity, trade summaries), both over the existing `JsonRunRepository`, which gains a trash. Routes live under `/aegis/api/library`. The UI gains a Library page; the existing result views are split into prop-fed components so the Library reuses them without the workspace.

**Tech Stack:** Python 3.12 (`.venv-aegis`), FastAPI, pytest (scope `aegis`), React/Vite/TypeScript, vitest, Playwright acceptance.

**Spec:** `docs/superpowers/specs/2026-10-19-aegis-results-library-design.md`

## Global Constraints

- Product work only: `app/products/aegis/`, `tests/test_aegis_*.py`, `tests/products/aegis/`,
  `tools/aegis_contracts.py`, `docs/`. Nothing under `app/trading_core/`, `app/platform_host/` or
  `app/products/triad/`.
- New test modules are `tests/test_aegis_*.py` with `pytestmark = pytest.mark.aegis`. Run them with
  `TRIAD_PYTEST_SCOPE=aegis .venv-aegis/Scripts/python.exe -m pytest -q -p no:cacheprovider <files>`.
  Lint only through `scratchpad/lint_aegis.sh`.
- Nothing is erased except by `POST /library/trash/empty`. The acceptance never calls it on the real
  store; it is tested on temporary repositories only.
- Red is reserved for losing money. Better/worse marks are ▲/▼ with words, never red and green.
- The Library never changes the workspace except through a Load button.
- Commit messages that contain a backslash are written with the Write tool and `git commit -F`.
- Branch `aegis/results-library` is cut from `main` at the plan commit (`MISSION9_BASE` in the
  acceptance).

## Plan rulings

| # | Ruling |
|---|---|
| P1 | A headline is cached in the item's summary sidecar as `headline` (with `headline_version: 1`). Every save already rewrites the sidecar without it, so a headline is recomputed after any change and is never stale. |
| P2 | Backfill budget: one `GET /library` computes headlines for at most 1.5 s; `preparing` is the count still missing; the page re-queries every 2 s while `preparing > 0`. |
| P3 | Trash layout: `trash/<folder>/<id>/` holds the moved files under their own names, plus `trash.json` `{kind, id, name, deleted_at}`. Folders: `runs`, `optimizations`, `walkforward`, `experiments`, `studies`. The annotation stays in `library/annotations.json` until Empty. |
| P4 | Reserved ids: `ExperimentStore.free_id` and `StudyStore.free_id` treat trashed ids as taken. Runs, optimizations and walk-forwards use uuids. |
| P5 | Comparison equity is each run's `result.combined.equity` (the engine's trade-exit curve, consistent with its combined metrics). % return = equity / initial capital − 1, the capital from `settings.initial_capital`, or 100,000 marked "assumed" for legacy runs without settings. |
| P6 | Strategy differences flatten both specs to dotted paths, indicators addressed by id rather than position, and ignore `id`, `name`, `description` and `version`. Settings add `initial_capital` and `allocation_fraction`. |
| P7 | Orientation: higher is better for net_pnl, net_return, cagr, mar, win_rate, expectancy and profit_factor; lower is better for max_drawdown; trade_count and exposure have no direction. B − A is the plain difference; a null on either side gives no difference and no mark. |
| P8 | The time axis is the union of both runs' first and last equity timestamps. Each series is resampled to at most 1,000 points, first and last kept. |
| P9 | An optimization's best cell is the highest oriented objective among cells with a value, ties to the first. |
| P10 | The deep link to an experiment or study is a workspace field `focus: {experimentId, studyId?} \| null`, set with `SET_PAGE experiments` and consumed once by the Experiments page. |
| P11 | Kind names in routes: `backtest`, `optimization`, `walkforward`, `experiment`, `study`. Each maps to its folder (P3) and its id key (`run_id`, `job_id`, `job_id`, `id`, `id`). |

## Review Focus

1. **A broken or legacy document** (a torn sidecar, a run without `settings` or `data`, an
   optimization saved before matrices existed): the Library lists it with "—" for what it cannot
   read and never fails the whole list. Task 1 `test_index_survives_broken_and_legacy_documents`.
2. **A run with no trades**, or one of two compared runs with null CAGR/MAR: the comparison shows
   "—" and no mark, and the curve is flat at 0%. Task 3 `test_compare_handles_a_run_without_trades`.
3. **Hundreds of items needing a headline at once:** the first query returns within its budget
   with `preparing > 0` and completes over later queries. Task 1
   `test_backfill_is_incremental_and_reports_preparing`.
4. **Name reuse after a delete:** an experiment created with the name of a trashed one gets a new id,
   and the trashed one restores unharmed. Task 2 `test_a_trashed_id_is_never_reused`.
5. **Restore order:**
   - a study whose parent experiment is in the trash is refused, naming the parent;
   - restoring the parent first, then the study, works;
   - an experiment with trashed studies can itself be trashed.

   Task 2 `test_restore_order_of_an_experiment_and_its_studies`.

---

### Task 1: The index

**Files:**
- Create: `app/products/aegis/library.py`
- Modify: `app/products/aegis/runs.py` (`write_summary(folder, id, summary)`, `read_document(folder, id)`), `app/products/aegis/api.py` (`GET /library`)
- Test: `tests/test_aegis_library.py`

**Interfaces:**
- Produces:
  - `KINDS = ("backtest", "optimization", "walkforward", "experiment", "study")`; `FOLDERS` and `ID_KEYS` (P11).
  - `LibraryEntry(BaseModel)`: `kind, id, name, label, notes, starred, symbols: list[str], timeframe, start, end, strategy_id, strategy_name, created_at, status, decision: dict | None, headline: dict, links: dict`.
  - `LibraryQuery(BaseModel)`: `kinds: list[str] = []`, `symbol`, `timeframe`, `strategy`, `starred: bool | None`, `decision: str | None`, `q`, `sort: Literal["created","net_pnl","mar"] = "created"`, `offset = 0`, `limit = 50` (≤ 200), `deleted: bool = False`.
  - `headline(kind: str, document: dict, experiments: ExperimentStore | None) -> dict` per kind (spec §4.1; P9 for optimizations; the store reads an experiment's latest report).
  - `Library(repository, experiments: ExperimentStore)`: `entries(budget_seconds=1.5) -> (list[LibraryEntry], preparing: int)`; `query(q: LibraryQuery) -> {"total", "entries", "preparing", "counts_by_kind"}`.
- Route: `GET /aegis/api/library` (query parameters as `LibraryQuery`).

- [ ] **Step 1: Write the failing tests** (`tests/test_aegis_library.py`, a temporary `JsonRunRepository` seeded with one item of each kind built from the existing test fixtures).
  - `test_every_kind_becomes_one_entry_with_its_headline`:
    - a backtest's headline equals its `result.combined.metrics` (net_pnl, net_return, mar, max_drawdown, trade_count);
    - an optimization's is `cells_run`, `cells_total`, `objective` and `best` (oriented);
    - a walk-forward's is `side`, `windows` and the stitched `net_pnl` and `mar`;
    - an experiment's has `recommended: True` when its latest report recommends;
    - a study's `summary_line` equals `report.summary`.
  - `test_filters_search_sort_and_pages` asserts, each with exact ids:
    - kind (repeatable), symbol, timeframe, strategy, starred and decision filters;
    - `q` over name, label, notes and strategy name, case-insensitive;
    - sort by net_pnl and mar, nulls last;
    - `offset`/`limit` paging and `counts_by_kind`.
  - `test_headline_is_cached_and_recomputed_after_a_save` (P1): the sidecar gains `headline`; saving the document drops it; the next query restores it.
  - `test_backfill_is_incremental_and_reports_preparing` (Review Focus 3): with `budget_seconds=0`, a query of 40 runs returns `preparing == 40` and entries with `headline == {}`; repeated queries reach `preparing == 0`.
  - `test_index_survives_broken_and_legacy_documents` (Review Focus 1): a torn sidecar is skipped; a run without `data` or `settings` lists with `symbols == []` and a `—`-able headline; nothing raises.
  - In `tests/test_aegis_api.py`: `test_library_route_lists_and_filters` (200, `total`, `entries[0]["kind"]`, 422 for `limit=500`).
- [ ] **Step 2: Run, expected FAIL** (`ModuleNotFoundError: products.aegis.library`).
- [ ] **Step 3: Implement.**
  - Entries come from the five `list_*` summaries. A missing `headline` reads the document once (within the budget) and calls `write_summary` with it.
  - The experiment's `recommended` flag reads its latest report through `ExperimentStore.read_report`; a missing report means `None`.
  - Annotations are merged in from Task 2's store (until Task 2, `{}`).
- [ ] **Step 4: Run, expected PASS**, plus `tests/test_aegis_runs.py` unchanged.
- [ ] **Step 5: Commit** "Aegis library: one index of every saved result with cached headlines".

### Task 2: Annotations and the restorable delete

**Files:**
- Modify: `app/products/aegis/runs.py` (trash), `app/products/aegis/library.py`, `app/products/aegis/experiments.py` (`free_id`), `app/products/aegis/studies.py` (`free_id`), `app/products/aegis/api.py` (routes; the experiment and study deletes routed through the trash)
- Test: `tests/test_aegis_library.py`, `tests/test_aegis_runs.py`, `tests/test_aegis_api.py`

**Interfaces:**
- Repository (`JsonRunRepository` and the protocol):
  - `move_to_trash(folder, id, meta: dict) -> None` (document, sidecar and `<id>.*` folders, P3);
  - `restore_from_trash(folder, id) -> None`;
  - `list_trash() -> list[dict]` (each `trash.json`);
  - `erase_from_trash(folder, id) -> None`;
  - `trashed_ids(folder) -> set[str]`.
- `library.py`:
  - `Annotations(repository)` with `get(kind, id)`, `set(kind, id, label, notes, starred)`, `remove(kind, id)`; atomic file `library/annotations.json`; label ≤ 80 and notes ≤ 2,000 (`ValueError`).
  - `delete(kind, id) -> None` raising `Refused(reason)` (spec §6.2 rules).
  - `restore(kind, id) -> None` raising `Refused`.
  - `empty(items: list[tuple[str, str]] | None) -> int`.
- Routes:
  - `PUT /library/{kind}/{id}/annotation` (200 entry; 422 lengths; 404 unknown);
  - `DELETE /library/{kind}/{id}` (200 `{deleted}`; 409 reason);
  - `POST /library/{kind}/{id}/restore` (200; 409);
  - `POST /library/trash/empty` (body `{"items": [{kind, id}] | null}`, 200 `{erased: n}`);
  - `GET /library?deleted=true` lists the trash.
  - `DELETE /experiments/{id}` and `DELETE /studies/{id}` keep their rules and move to the trash.

- [ ] **Step 1: Write the failing tests.**
  - `test_delete_moves_each_kind_to_the_trash_and_restore_brings_it_back`: for every kind, the files leave their folder, `list_trash` shows them, and restore returns them byte-identical (the result hash equal).
  - `test_delete_refusals`, each 409 naming the reason: an optimization/walk-forward queued or running; an experiment queued, running or paused, or with a study; a study queued, running or paused.
  - `test_empty_erases_only_the_trash` (temporary repository): after Empty, the item's files and annotation are gone and live items are untouched.
  - `test_a_trashed_id_is_never_reused` (Review Focus 4).
  - `test_restore_order_of_an_experiment_and_its_studies` (Review Focus 5).
  - `test_trashed_runs_do_not_hold_a_strategy`: `StrategyLibrary.delete` succeeds once the only referencing runs are trashed.
  - `test_annotations_round_trip_and_limits`.
  - In `tests/test_aegis_api.py`: `test_experiment_delete_now_moves_to_the_trash` (the old route; then restore).
- [ ] **Step 2: Run, expected FAIL** (`AttributeError: move_to_trash`).
- [ ] **Step 3: Implement.** Moves use `os.replace`/`shutil.move` within the data root (one volume). `trash.json` is written before the move and removed after a restore.
- [ ] **Step 4: Run, expected PASS**, plus `test_aegis_experiments.py`, `test_aegis_studies.py`, `test_aegis_strategies.py`.
- [ ] **Step 5: Commit** "Aegis library: labels, stars and a restorable delete for every kind".

### Task 3: The comparison

**Files:**
- Create: `app/products/aegis/compare.py`
- Modify: `app/products/aegis/api.py` (`GET /library/compare`)
- Test: `tests/test_aegis_compare.py`

**Interfaces:**
- `compare(a: dict, b: dict) -> dict` (two run envelopes) returning:
  - `identity: {a: {...}, b: {...}}`;
  - `notes: list[str]` ("identical result", "same data", "same strategy", "different periods: shared …");
  - `differences: [{path, a, b}]` (P6);
  - `metrics: {scope: [{metric, a, b, diff, mark: "better" | "worse" | None}]}` for combined/long/short (P7);
  - `equity: {a: [{t, pct, usd, dd}], b: [...]}` (P5, P8);
  - `trades: {a: {side: {count, avg_net, win_rate, avg_hold_hours, max_hold_hours}}, b: …}`;
  - `capital_assumed: {a: bool, b: bool}`.
- Route: `GET /aegis/api/library/compare?a=<run_id>&b=<run_id>` (404 unknown run; 422 when a == b).

- [ ] **Step 1: Write the failing tests** (two `run_backtest` envelopes on `wave_bars` through `results.envelope`):
  - `test_identical_requests_read_identical_result`;
  - `test_strategy_differences_name_each_path` (EMA 9→12 on the long side gives `long_side.indicators.ema.length 9 → 12` and nothing else);
  - `test_metric_marks_follow_orientation` (lower drawdown is ▲ better; trades no mark; a null gives no diff);
  - `test_equity_is_percent_on_one_axis` (first point 0%; the union span; ≤ 1,000 points);
  - `test_different_periods_note_the_shared_span`;
  - `test_compare_handles_a_run_without_trades` (Review Focus 2);
  - `test_legacy_run_without_settings_assumes_capital` (P5);
  - in `test_aegis_api.py`, `test_library_compare_route`.
- [ ] **Step 2: Run, expected FAIL.**
- [ ] **Step 3: Implement** (pure; the route reads both envelopes through the repository).
- [ ] **Step 4: Run, expected PASS.**
- [ ] **Step 5: Commit** "Aegis library: compare two backtests".

### Task 4: The Library page, list and result views

**Files:**
- Create: `ui/src/library.ts`, `ui/src/library.test.ts`, `ui/src/components/LibraryPage.tsx`, `ui/src/components/LibraryList.tsx`, `ui/src/components/LibraryBacktestView.tsx`, `ui/src/components/LibraryChart.tsx`
- Modify:
  - `ui/src/api/client.ts`, `ui/src/results.ts`;
  - `ui/src/state/workspace.tsx` (`page: 'library'`, `focus`);
  - `ui/src/App.tsx`, `ui/src/components/SideNav.tsx`, `RunsDrawer.tsx`;
  - `SummaryTab.tsx`, `TradesTab.tsx`, `EquityTab.tsx` (each exports a `*View({ run })` used by the tab and by the Library);
  - `OptimizationTab.tsx` (export `OptimizationJobView({ side, job, selected, onPick })`);
  - `WalkForwardTab.tsx` (export `WalkForwardJobView({ side, job, onLoad })`);
  - `ExperimentsPage.tsx` (consume `focus`), `styles.css`.

**Interfaces:**
- Consumes the Task 1–3 routes.
- Produces:
  - `api.library(query)`, `api.annotate(kind, id, body)`, `api.libraryDelete(kind, id)`, `api.libraryRestore(kind, id)`, `api.libraryEmpty(items)`, `api.libraryCompare(a, b)`;
  - `library.ts`: `headlineText(entry) -> string`, `queryString(filters) -> string`, `comparable(selected) -> {ok, reason}`, `markText(mark) -> '▲ better' | '▼ worse' | ''`, `kindLabel(kind)`.
- Element ids:
  - page: `#nav-library`, `#library-page`;
  - filters: `#library-kind-<kind>`, `#library-symbol`, `#library-timeframe`, `#library-strategy`, `#library-starred`, `#library-decision`, `#library-search`, `#library-sort`, `#library-deleted`;
  - list: `#library-list`, `#lib-<kind>-<id>`, `#lib-star-<kind>-<id>`, `#lib-check-<kind>-<id>`, `#library-compare`, `#library-delete-selected`, `#library-empty`, `#library-preparing`;
  - view: `#library-view`, `#library-load`, `#library-label`, `#library-notes`, `#library-save-annotation`, `#library-restore`, `#library-chart`.

- [ ] **Step 1: Write the failing vitest cases** (`library.test.ts`):
  - `headlineText` per kind with "—" for nulls;
  - `queryString` drops empty filters;
  - `comparable`: exactly two backtests, with a reason otherwise;
  - `markText`.
- [ ] **Step 2: Run `npm --prefix app/products/aegis/ui test`, expected FAIL.**
- [ ] **Step 3: Implement.**
  - **The view split is behaviour-preserving:** the existing tabs render the new views with `lastRun` and the workspace pick, and the 60-item UI suite stays green.
  - **`LibraryChart`** mounts its own adapter, fetching bars and indicators for the run's selection and strategy as `ChartPanel` does; markers come from the run.
  - **Load:**
    - a backtest dispatches `LOAD_RUN`, after a `confirm` when `unsavedEdits` is true;
    - an optimization cell dispatches `SET_STRATEGY` with `applyConfigs`;
    - a walk-forward dispatches the final window's settings.
  - **Navigation:** Library sits in the side navigation between Strategy Lab and Experiments; experiments and studies set `focus` and switch page; the Runs drawer gains "Open in Library".
- [ ] **Step 4: Run the UI tests and `npm run build`; then a browser check** against a restarted worker: list, filters, a backtest view with the workspace unchanged, Load, an optimization, a walk-forward, deep links. Ledger the evidence.
- [ ] **Step 5: Commit** "Aegis UI: the Library page and read-only result views".

### Task 5: The comparison view and housekeeping in the page

**Files:**
- Create: `ui/src/components/LibraryCompare.tsx`, `ui/src/compare.ts`, `ui/src/compare.test.ts`
- Modify: `LibraryPage.tsx`, `LibraryList.tsx`, `LibraryBacktestView.tsx`, `styles.css`

**Interfaces:**
- `compare.ts`:
  - `curvePaths(equity, width, height, unit: 'pct' | 'usd') -> {a, b, domain, range}`;
  - `diffText(row) -> string` (money and percentages formatted; "—" for nulls).
- Element ids: `#library-compare-view`, `#compare-notes`, `#compare-differences`, `#compare-metrics-<scope>`, `#compare-scope`, `#compare-unit`, `#compare-chart`, `#compare-trades`, `#library-confirm-delete`.

- [ ] **Step 1: Write the failing vitest cases** (`compare.test.ts`): `curvePaths` scales both series to one domain and range in either unit; `diffText` money/percent/null.
- [ ] **Step 2: Run, expected FAIL.**
- [ ] **Step 3: Implement.**
  - **The comparison view:** notes, the differences table, A/B/B − A metrics with marks, a scope switch, the equity and drawdown chart with a % / $ switch, and trades.
  - **Housekeeping:** label and notes, inline stars, Delete with a confirmation naming the item, "Delete selected" naming each refusal, the Recently deleted view with Restore, and Empty with a confirmation naming the count.
- [ ] **Step 4: Run the UI tests and build; a browser check** of a comparison, and of delete → restore on a throwaway backtest. Never Empty on the real store.
- [ ] **Step 5: Commit** "Aegis UI: compare two backtests; labels, stars and Recently deleted".

### Task 6: Acceptance and the record

**Files:**
- Modify: `tests/products/aegis/browser_workstation.py` (items 70–76, `MISSION9_BASE`)
- Create: `docs/MISSION9_RESULTS_LIBRARY.md`, `docs/evidence/aegis-acceptance-<stamp>.json`

- [ ] **Step 1: Write items 70–76**, spec §3 items 1–7 in order.
  - **70:** the five kinds are listed with headlines (the walk's own items exist by then).
  - **71:** a label and star on item 22's run are found by search and by Starred; filters narrow.
  - **72:** item 22's run opens read-only. The workspace's strategy, selection and run id are equal before and after, then Load replaces them.
  - **73:** item 21's optimization opens with its matrix and item 28's walk-forward with its windows; the experiment and study deep links select theirs.
  - **74:** the comparisons:
    - item 22's identical pair compares to "identical result";
    - item 39's breakout run against item 54's centre run (the same strategy, different settings) lists exactly the differing parameters and carries marks;
    - the chart has two paths.
  - **75:** a throwaway backtest is deleted → listed in Recently deleted → restored with the same result hash. The refusals: the item-63 study's parent experiment, a running study (started and cancelled in the item), and a restore of a study whose parent is trashed (on a throwaway pair created via the API).
  - **76:** governance since `MISSION9_BASE`.
- [ ] **Step 2: Rebuild and restart** the worker. **Run** the walk: 76/76. Copy the JSON to `docs/evidence/`.
- [ ] **Step 3: Full verification:** `tools\verify.ps1` on the branch (it stops at the main-branch check by design), the UI tests and the build.
- [ ] **Step 4: Write the record** `docs/MISSION9_RESULTS_LIBRARY.md` and commit "Aegis: Results library acceptance and the Mission 9 record".

### After Task 6

Independent milestone QA at the exact commit and a whole-branch review (the operator chooses the model), one fix pass with every fix test-first, the record completed, `tools\verify.ps1` on `main` after the merge, and merge and push only on the operator's answer.
