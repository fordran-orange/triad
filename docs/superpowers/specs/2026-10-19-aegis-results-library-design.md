# Mission 9 — The Results library: every saved result in one place, two backtests side by side

Date: 2026-10-19. Product work under `app/products/aegis/` (AGENTS.md: product-first; milestone
QA). The delete feature touches retained data, so it ships with a restorable delete (§6), the
independent milestone QA AGENTS.md requires, and the operator's explicit approval of that design
(chat, 2026-10-19). No Core or Triad change; exchange stays CLOSED; nothing trades.

## 1. Intent

The operator, 2026-10-19: the results view "will only be worse as the testing gets more complex".
The results panel now resizes and maximizes (merged `880c4fd`), but saved results are scattered:

- 360 backtests reopen only from the Runs drawer (newest first, no filters).
- 100 optimizations and 102 walk-forwards cannot be reopened from the page at all.
- 19 experiments and 7 studies live on the Experiments page.

Nothing compares two results. This mission puts every saved result in one filterable Library,
opens any of them read-only without disturbing the workspace, and compares two backtests side by
side.

## 2. Operator decisions (chat, 2026-10-19)

| Decision | Choice |
|---|---|
| What to compare first | Two backtests (other kinds can produce a backtest) |
| Where | A Library page in the side navigation; the Runs drawer stays as a recent-runs shortcut |
| Opening a backtest | View it read-only; Load into workspace only on request |
| Aligning two equity curves | Same calendar axis, as % return from each run's own starting capital; a dollars switch |
| Housekeeping | Label, notes, star, delete |
| Delete | A restorable delete (Recently deleted, restore, an explicit Empty), recommended for the AGENTS.md destructive-operations rule |
| Approach | A: one index route over the summaries every kind already keeps |
| Design sections | Five sections approved one by one |

## 3. Definition of done (the acceptance walks these after the 69 Mission 3–8 items)

1. The Library page lists saved results of all five kinds (backtest, optimization, walk-forward,
   experiment, study), with each kind's headline numbers, 50 rows per page.
2. Filters (kind, symbol, timeframe, strategy, starred, decision), search (names, labels, notes,
   strategy names) and sort (newest, net P&L, MAR) narrow and order the list. A label and star
   set on a backtest are found by search and by the Starred filter.
3. A backtest opens read-only:
   - header, chart with its indicators and markers, Summary, Trades, Equity, Temporal;
   - the workspace (strategy, selection, results, unsaved edits) is provably unchanged;
   - Load into workspace then loads it, asking first when there are unsaved edits.
4. An optimization opens with its matrix and parameter table; a walk-forward opens with its
   windows, stitched equity and stability; an experiment or study opens on the Experiments page
   with that item selected.
5. Two backtests compare:
   - the identical-request pair of item 22 reads "identical result";
   - two runs with different settings list their parameter differences;
   - A, B and B − A metrics carry ▲/▼ by each metric's direction;
   - both equity curves show on one calendar axis as % return.
6. Delete → Recently deleted → restore brings an item back with the same result hash. The
   refusals answer 409 naming the reason: a running job, a parent experiment with studies, a
   restore whose id is taken or whose parent is gone.
7. Governance: `/aegis/api/status` human_directed / CLOSED; no file under `app/trading_core/`,
   `app/platform_host/` or `app/products/triad/` changed; the Mission 3–8 walk stays 69/69. The
   walk never empties Recently deleted on the real store.

## 4. The list

### 4.1 One entry shape

`LibraryEntry`:
- `kind` (backtest | optimization | walkforward | experiment | study), `id`, `name`;
- `label`, `notes`, `starred`;
- `symbols`, `timeframe`, `start`, `end`;
- `strategy_id`, `strategy_name`, `created_at`, `status`, `decision`;
- `headline`, `links` (an experiment's parent, a study's experiment, a backtest's experiment and
  cell).

The headline per kind:

| Kind | Headline |
|---|---|
| backtest | combined net P&L, net return, MAR, max drawdown, trades |
| optimization | side, cells run of total, objective, the best cell's objective value |
| walk-forward | side, windows, stitched net P&L and MAR |
| experiment | mode, cells, objective, whether the latest report recommends a plateau |
| study | symbols, windows, the report's summary line |

### 4.2 Built from the summaries

The worker merges the summary sidecars the repository already keeps per kind (`runs/`,
`optimizations/`, `walkforward/`, `experiments/`, `studies/`). Where a summary lacks the headline,
it is computed once from the full document and the sidecar is rewritten, the existing pattern for
legacy envelopes:

- backtest and optimization metrics;
- walk-forward stitched metrics;
- an experiment's recommendation flag;
- a study's summary line.

New saves write it directly. While a backfill runs, the route answers with what is ready and the
count still preparing; it never blocks for long.

### 4.3 Querying

`GET /aegis/api/library` takes:
- `kind` (repeatable), `symbol`, `timeframe`, `strategy`, `starred`, `decision`;
- `q` (case-insensitive substring over name, label, notes and strategy name);
- `sort` (created, net_pnl, mar; descending by default), `offset`, `limit` (≤ 200; the page
  uses 50).

It returns `{total, entries, preparing, counts_by_kind}`.

## 5. Opening a result

### 5.1 A backtest

The backtest opens read-only on the Library page, full height:

- **Header:** label and star, symbol, timeframe and range, strategy name and hash, result hash,
  saved date, engine, the raw-archive label.
- **The chart:**
  - candles from the archive (`GET /data/bars` for the run's selection);
  - the run's indicators from its stored series;
  - its trade markers.
  - A run whose pinned archive drifted shows the existing `source_unavailable` state instead of
    different data.
  - A run made from supplied bars says it has no archive chart.
- **Results:** the Summary, Trades, Equity and Temporal tabs, fed from the run rather than the
  workspace.
- **Actions:** Load into workspace (as the Runs drawer does, asking first over unsaved edits),
  Compare with…, Label and notes, Star, Delete.

The chart adapter allows one chart per page. The Library and Charts pages are never shown
together, so the Library's chart is that page's only chart.

### 5.2 An optimization

- The matrix and parameter table in the results-panel layout (metric switch, long/short, hover
  numbers, pinned labels).
- "Load the picked cell into the workspace" applies it as the Optimization tab's Apply does.

### 5.3 A walk-forward

- Its window table, stitched out-of-sample equity with window boundaries, and stability.
- "Load the final window's settings into the workspace".

### 5.4 Experiments and studies

They open on the Experiments page with the item selected (their existing report views).

### 5.5 The workspace rule

Nothing in the Library changes the workspace except a Load button the operator presses.

## 6. Housekeeping

### 6.1 Labels, notes, stars

- Any entry: label ≤ 80 characters, notes ≤ 2,000, starred true/false.
- Stored in `library/annotations.json` under the Aegis data root, keyed `<kind>:<id>`, written
  atomically.
- `PUT /aegis/api/library/{kind}/{id}/annotation`.

### 6.2 A restorable delete

`DELETE /aegis/api/library/{kind}/{id}` moves the item to `trash/<kind>/<id>/` under the Aegis data
root:
- its document and sidecar;
- its folders (an experiment's cells, curves and reports; a study's window files).

It records `deleted_at`. Refusals, each 409 naming the reason:
- **backtest:** never refused;
- **optimization, walk-forward:** refused while queued or running;
- **experiment:** refused while queued, running or paused (cancel first), and while any study
  names it;
- **study:** refused while queued, running or paused (cancel first).

The existing experiment and study delete routes (and the Experiments page buttons) move to Recently
deleted too, so deleting means one thing everywhere. An annotation travels with its item.

- **Recently deleted** (a Library filter) lists the trashed items with their deletion time.
- **Ids stay reserved.** The ids of items in Recently deleted stay reserved until Empty: new
  experiments and studies never take them.
- **Restore** (`POST /aegis/api/library/{kind}/{id}/restore`) moves an item back. It is refused
  when a study's parent experiment is not present, or as a safety net when an item with that id
  exists.
- **Empty** (`POST /aegis/api/library/trash/empty`, all or selected) erases trashed items for
  good. It is the one destructive act, always an explicit operator click with a confirmation
  naming the count.
- Trashed items count as gone everywhere else: lists, references (a strategy referenced only by
  trashed runs can be deleted), the Runs drawer.

### 6.3 Selecting several

The list's checkboxes drive Compare (exactly two backtests) and "Delete selected" (each refusal
named, the rest moved).

## 7. Comparing two backtests

`GET /aegis/api/library/compare?a=<run_id>&b=<run_id>` computes on the worker and returns compact
data:

- **Identity:** each run's label, symbol, timeframe, range, strategy, hashes, capital. Notes:
  "same data" (equal data hash), "same strategy" (equal strategy hash), "identical result" (equal
  result hash), "different periods" (unequal ranges, with the shared span).
- **Strategy differences:** every differing path between the two specs and settings, per side
  (indicator lengths and parameters by indicator id, entry and exit rules, execution costs, initial
  capital, allocation), with A and B values; or "same strategy".
- **Metrics:**
  - net P&L, net return, CAGR, max drawdown, MAR, win rate, expectancy, profit factor, trades and
    exposure, for combined, long and short;
  - A, B and B − A, with a direction mark: ▲ better / ▼ worse by each metric's orientation.
    Max drawdown is better lower. Trades and exposure have no direction (no mark).
  - The difference column never uses red and green. Red stays reserved for losing money (a
    negative P&L or return in A or B).
- **Equity:**
  - each run's combined equity as % return from its own initial capital and in dollars, with its
    drawdown;
  - on the union of both runs' dates, each resampled to at most 1,000 points.
- **Trades:** per side for each run: count, average net P&L, win rate, average and longest holding
  time.

The comparison only reads saved results.

## 8. Page

- The side navigation gains **Library**, between Strategy Lab and Experiments.
- The page has three areas: the filter bar and list; the selected item's view; the comparison
  (replacing the view while open).
- Rows can be starred inline. Selecting a row opens its view; ticking two backtests enables
  Compare.
- The Runs drawer keeps listing recent backtests and gains "Open in Library".

## 9. Verification

- **Tests first, on synthetic data:**
  - the index across all five kinds (entry shapes, headlines, the one-time backfill and its
    "preparing" count);
  - each filter, search, sort and page;
  - annotations round trip;
  - delete, restore and empty per kind, with every refusal;
  - the existing experiment and study deletes moving to Recently deleted;
  - comparison identity notes, strategy differences, metric orientation, union-axis curves, trade
    summaries;
  - vitest for the page's pure helpers.
- **Acceptance:** §3 items 1–7 appended to `tests/products/aegis/browser_workstation.py` as items
  70 onward. The walk never empties Recently deleted on the real store; Empty is tested on
  temporary repositories only.
- **Milestone:** `tools\verify.ps1`, UI tests and build, the full browser walk, independent
  milestone QA and a whole-branch review (the operator chooses the model), one fix pass
  test-first, the record `docs/MISSION9_RESULTS_LIBRARY.md`, merge on the operator's call.

## 10. Not in this mission

- Comparing optimizations, walk-forwards, experiments or studies (the natural next step).
- Mission 4's walk-forward dropping an entry signalled on a window's last bar, and Mission 8's
  deferred display items: a separate small targeted run afterwards.
- Moving Neo4j's host ports (a Core decision).
- Deleting strategies (the Strategy Lab already does).
- Anything that trades.

## 11. Build order

1. The index: entry model, headline backfill, `GET /library` with filters, search, sort, paging.
2. Annotations and the restorable delete (per kind, with refusals), restore, empty; the existing
   experiment and study deletes moved to it.
3. The comparison: pure functions and the route.
4. The page:
   - Library list (filters, search, stars, labels, selection, Recently deleted);
   - the backtest view with its own chart, and the optimization and walk-forward views;
   - Load into workspace;
   - the comparison view;
   - Library entries from the Runs drawer and the Experiments page.
5. Acceptance and the record.

## 12. Risks

- **The one-time headline backfill** reads ~560 full documents once (some several MB). It runs
  incrementally and the list says "preparing" meanwhile.
- **Moving the existing experiment and study deletes to Recently deleted** changes what the
  Experiments page's Delete does. A deleted item's id stays reserved until Empty (new items never
  reuse it), so a restore never collides.
- **One chart per page:** the Library's backtest view and the Charts page share the adapter's
  module registries. Only one is mounted at a time.
