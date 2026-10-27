# Aegis Optimization Lab v2: Implementation Plan (Gate 1)

> **Status: PLAN ONLY.** This is for Codex review, then Randall's approval. No implementation is authorized. Nothing in this document was built.
>
> When a phase is approved, it gets its own task-level plan in the writing-plans format, executed with superpowers:subagent-driven-development or superpowers:executing-plans. This document fixes the decisions, interfaces, budgets and tests those task plans must follow.

**Goal:** Turn Aegis's two-parameter optimization view into a high-dimensional research Lab. It must:
- understand 5–20 variables;
- navigate up to 1,000,000 evaluated trials without rendering them all;
- direct the search with evidence-backed variable intelligence (Screen H);
- keep the compact dock, the existing engine and the workstation shell.

**Architecture:**
- The Lab is built on Aegis **experiments**, not on the results-strip optimizer. Experiments (Mission 6) already have:
  - surfaces over both sides;
  - stable mixed-radix cell indexes;
  - Latin-hypercube sampling and refinement;
  - Parquet cell rows;
  - pause and resume;
  - parent lineage;
  - materialization with a metric-identity check.
- A new Aegis-owned **Lab query layer** (`app/products/aegis/lab/`) answers filtered, sliced, aggregated, paged and ranked views over an experiment's cells. It works server-side over Arrow columns, so the browser never receives more rows or marks than it draws.
- The React UI adds an **Optimization Lab** page whose sub-views are screens B–H. The compact dock (A) stays in the results strip.
- Everything lives under `app/products/aegis/`, its tests and its docs. Nothing in Phases 1–6 touches Core.

**Tech stack:**
- Python 3.12, FastAPI and Pydantic.
- numpy 2.5.3, pandas 2.3.3, pyarrow 23.0.1 and numba 0.68.0. All are already locked in `.venv-aegis`.
- React 18, TypeScript and Vite 5, with vitest (node environment) and Playwright.
- **No new dependency in any phase** unless a phase's review approves one (§12, §14).

**Inputs (the spec this plan argues from):**
- The brief: `C:\Users\fordr\Documents\AEGIS_OPTIMIZATION_LAB_V2_UXPILOT_CLAUDE_BRIEF.md` (2026-10-27).
  - It lives outside the repository. Phase 0 copies it to `docs/superpowers/specs/2026-10-27-aegis-optimization-lab-v2-brief.md` so the spec travels with the plan.
- The UX Pilot canvas: <https://uxpilot.ai/a/ui-design?page=lTHZGNbkbJqGnXSWW4IR>.
- The locked Aegis mock: `C:\Users\fordr\Downloads\9f13379470-f3cb9153e52dcd44fea4.png`.
- `AGENTS.md` and `docs/CORE_CHAT_VISION.md`, including its 2026-10-09 and 2026-10-13 operator corrections.
- The repository at `main` 042d5c9. Reconnaissance used this worktree and read-only inspection of `C:\Triad`.

## Global constraints

Every phase implicitly includes these.

**Product boundaries**
- Exchange stays CLOSED and live trading stays disabled.
- No broker, order, account or paper-trade path is touched. The designs' `TRADE` mode tab stays disabled.
- Strategy Gate authority is not changed. **There is no Strategy Gate in the repository today** (§1, finding F1), so any gate is new and needs Randall's decision (Q1).
- AI may explain and propose. It never writes a gate verdict, a variable status, a search-space version or a validation state. Only deterministic code does, after a human action.

**Engine and saved data**
- The existing engine (reference plus numba kernel), the Vela chart behind `chart/adapter.ts`, the experiment store and the pool are kept. No engine rewrite and no speed claim without a benchmark.
- Existing saved documents are never rewritten or converted. New fields are additive and optional, and old experiments open exactly as before.
- Result hashes and strategy hashes of existing runs must not move. `tests/test_aegis_engine_golden.py` and the real-archive identity scripts stay identical.

**Honesty rules for every surface**
- No interpolation and no smoothing of untested cells.
- Every chart states its basis: `Tested (exact)`, `Aggregated from tested (n)`, `Sampled subset (n of N)` or `Estimate (model)`.
- Mock values only in the UX Pilot designs, never in the product. Any illustrative fixture shown in the product is labelled `DEMO`.
- Losing money is red, always (operator, 2026-10-19). A negative P&L-signed value is never green or blue-best. The designs' blue Sharpe scale is used only for metrics without a profit sign, and for the gain side of signed metrics.

**Dependencies and environments**
- No new Python or JS package without the review in §12.
- A Python package changes `requirements-aegis.lock`, `requirements.lock` (the Aegis lock must equal the Core lock plus numba and llvmlite, `tests/test_environments.py:45-46`) and the Core-owned `tests/test_environments.py:31`. That is an environment-level change, which AGENTS.md says needs a measured blocker surfaced first.

**Testing by blast radius (AGENTS.md)**
- Ordinary phase checks:
  - `TRIAD_PYTEST_SCOPE=aegis .venv-aegis/Scripts/python.exe -m pytest -q -p no:cacheprovider <paths>`;
  - the architecture and isolation tests;
  - `npm --prefix app/products/aegis/ui test` and `run build`;
  - `tools/aegis_contracts.py --check`;
  - Aegis lint over the scope `tools/verify.ps1:32-39` lints. Never a bare `ruff format`.
- A milestone additionally runs `tools\verify.ps1` (on `main` in `C:\Triad` only), the full browser walk and the UI tests.

**Worktree caveat**
- `.venv-aegis` imports `C:\Triad\app` through its editable install, and the worker serves `C:\Triad`'s built UI.
- Implementation in a worktree must set `PYTHONPATH="<worktree>/app;<worktree>/tests"` and check `products.aegis.__file__`.
- Browser evidence must come from a worker started on the branch under test.

**Commits**
- Messages are written with the Write tool and committed with `git commit -F`, with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review focus

These are the five inputs or conditions the brief implies but that no single phase's happy path exercises, most likely first. Each one has a pinned test in the phase that owns the code.

1. **A grid larger than int64.** About 20 parameters with ≥ 9 values each exceeds `cell` int64 (2^63 ≈ 9.2 × 10^18).
   - Expected: the experiment still plans, samples and stores trials by `trial_no` and positions; nothing overflows silently.
   - Test: Phase 4 `test_lab_grid_beyond_int64_keeps_trial_identity`.
2. **The worker restarts in the middle of compaction**, leaving chunk files and a part file that overlap.
   - Expected: reads deduplicate by trial and count the duplicates; no trial is lost or double-counted.
   - Test: Phase 2 `test_lab_compaction_torn_is_idempotent`.
3. **A filter that leaves zero trials, or a heatmap axis with one value.**
   - Expected: explicit empty states with the filter scope named; no division-by-zero colour scale.
   - Tests: Phase 2 `test_lab_query_empty_scope` and vitest `labHeatmap.empty`.
4. **A metric that is undefined for some trials** (`cagr`/`mar` need ≥ 365 days, `profit_factor` needs losses).
   - Expected: null-valued trials are counted as "undefined", never ranked as zero, never coloured, and listed in the scope counts.
   - Test: Phase 2 `test_lab_undefined_metric_counts`.
5. **The operator changes the strategy document after an experiment pinned it.**
   - Expected: Lab views keep reading the pinned spec, and Screen H statuses derived from it are marked stale for the new spec hash (scenario 22).
   - Test: Phase 4 `test_variable_status_stale_on_strategy_hash_change`.

---

## 1. Key findings (read first)

| # | Finding | Consequence for this plan |
|---|---|---|
| F1 | **No Strategy Gate exists.** Nothing in `app/products/aegis` or `app/trading_core` computes a gate verdict, validation status, sealed OOS or deployment eligibility. The only "gate" in the UI is `experiment-gate`, the "save or revert the document first" notice in `ExperimentsPage.tsx:109-118`. | Every gate panel, "Send to Validation", "NOT VALIDATED" badge and DSR threshold in screens A–C and F–H has no backend. Phase 7 builds a gate only if Randall chooses it (Q1). Until then the UI says `Strategy Gate: not built`, never `pending`. |
| F2 | **HA-MQI, EWO and RocketRSI do not exist.** The indicator kinds are EMA, SMA, RSI, ATR, BB, DONCHIAN and MACD (`kinds.py:33-55`). The Mission 6 spec calls HA-MQI "undefined" (`docs/superpowers/specs/2026-10-12-aegis-experiments-design.md:395`). | The "~10 HA-MQI variables" sweep cannot run. Scenarios 2, 14 and 19 use the existing kinds plus synthetic fixtures. New indicators are a separate mission (Q3) with their own definitions and goldens. |
| F3 | **There is no Sharpe metric.** The metrics are `net_pnl, net_return, cagr, max_drawdown, mar, win_rate, expectancy, profit_factor, trade_count, exposure` × `combined/long/short` (`pool.py:22-34`). Every design ranks by Sharpe. Adding a key inside `backtest._metrics` (`backtest.py:992`) would change `canonical_payload` (`results.py:49-66`), so every new run's `result_hash` would differ from an identical old computation, and `materialize`'s identity check would fail. | Sharpe (and DSR in F) needs a definition and a home **outside** the hash-bearing metrics (Q2). Until then the Lab's default objective is the experiment's own objective. |
| F4 | **No regimes, no event feed, no IS/validation/OOS partition on experiments.** Event windows are hand-supplied and ANALYZE-only (`temporal.py:1-7`). Experiments run on one range, and all data is `RAW ARCHIVE · NOT RESEARCH-ELIGIBLE` (`data.py:56`, `study_rules.py:45`). Walk-forward (Mission 4) and studies (Mission 8) do have IS/OOS windows. | Regime and FOMC/Earnings controls render as "unavailable", never as neutral (scenario 7). Phase 5 adds partitions. Phase 6 reuses studies for folds. |
| F5 | **The compact optimizer is a different machine.** It is a per-side grid of ≤ 100,000 cells held in one JSON document (`optimize.py:40-41`). Status sends the best 1,000 cells (`:43`). The matrix square is **best of the rest** (max), not an exact slice or a median (`optimize.py:232-333`). Its objectives are `net_pnl, mar, max_drawdown, trade_count`. Randall chose best-of-rest only on 2026-10-20 ("no median view"). | The dock keeps its job. It gains honest labels (`Aggregated: best of the rest`), an `n` overlay and `Expand Lab`. Adding median/mean/worst to the dock reverses a 2026-10-20 decision (Q5). |
| F6 | **Experiments are the right base, with five scale limits:** `MAX_PARAMETERS = 10` (`surface.py:34`); `CHUNK_CELLS = 200` gives 5,000 Parquet files per million trials (`experiments.py:62`); `cells()`, `row()` and `done_cells()` read every chunk on every call (`experiments.py:277-306`); `analysis._columns` converts the whole table to Python lists (`analysis.py:36-47`); `GET /experiments/{id}/cells` re-reads all chunks per request (`api.py:964-988`). | Phase 2 replaces the read path (compaction plus a column cache), keeping the proven write path. Phase 4 lifts the parameter cap to 20 with an identity that survives int64 overflow. |
| F7 | **Compute is the binding constraint, not storage or queries.** Measured cost is 0.0245–0.0304 ms per cell-bar per worker (the 8 newest 252-cell experiments in `data/aegis/experiments`). With 10 workers × 0.8 efficiency (`surface.py:40-41`), one million trials takes about `bars × 0.94 ms`, or **≈ 1.9 h at 2,000 bars and ≈ 9.4 h at 10,000 bars**. At 200,000 bars it is ≈ 7.8 days. | The Lab shows the funnel's real budget. One million trials is a coarse-timeframe or short-range proposition on this laptop (§9.6), and the UI says so. |
| F8 | **Every stage-1 trial is already costed.** The kernel applies `commission_per_side` and `slippage_bps` (`backtest.py:435-462`, `strategy.py:426-431`). A trial is a complete metrics-only backtest without trades, markers or envelope. | The funnel's stage 1 is not "cost-unaware". Stage 2 is "full envelope plus cost stress". The UI must not call stage-1 rows "backtests" in counts (brief §3). |
| F9 | **The machine:** i7-1255U (10 cores / 12 threads, 2.6 GHz base); 15.8 GB RAM, with **2.5 GB free** while Core and the Aegis worker ran on 2026-10-27; Samsung NVMe SSD (238 GB), **59 GB free on C:**; `data/aegis/experiments` uses 9.8 MB. Randall noted on 2026-10-21 that "a NAS drive is going to be needed soon". | Memory budgets assume about 2 GB usable. The Lab holds projected columns only (§9.2). A 1M-trial experiment is about 0.3 GB on disk. |
| F10 | **Chart stack:** Vela 0.8.3 is a time-axis OHLCV chart only, with no heatmap or scatter primitive. Non-price charts are hand-written SVG paths (MainEffects, EquityTab, StudyReport, …). The heatmap is a DOM CSS grid (`Heatmap.tsx`). React Flow 12.12.0 is installed, and pulls d3-zoom/drag/selection/interpolate and zustand. No chart, scale, virtualization or table library is installed. | Lab charts are hand-built Canvas 2D renderers behind a small `lab/charts` boundary, with server-side aggregation (§12). React Flow is reused for the lineage graph (G). Virtualized rows are hand-written. Each alternative library is listed in §12 for a later decision. |
| F11 | **There are no statistics libraries.** scipy, scikit-learn, statsmodels, duckdb, polars, optuna and plotly are all absent. | All estimators are numpy over Arrow columns (§7), with seeded bootstrap intervals. TPE/Bayesian samplers (Screen D's "TPE + Sobol") are excluded (§13). |
| F12 | **Work in flight.** Mission 14 (`aegis/ai-reading`, 13 commits ahead of main) touches `ui/src/api/client.ts`, `ui/src/styles.css`, `preferences.py`, `phrases.py` and `tests/test_aegis_api.py`, and adds walk items 98–102 in an uncommitted edit in `C:\Triad`. | Phase 1 starts after Mission 14 merges, or rebases onto it. New walk items start at **103**. |
| F13 | **The designs are 1440 px wide.** UX Pilot A–H render at 1440 × 1024–1059. The baseline "Workstation" design is 1672 × 1024. The brief asks for 1672 × 941. The walk's viewport is 1600 × 1000 (`browser_workstation.py:4288`). | Visual acceptance runs at **1672 × 941** (the brief) and **1440 × 900** ("slightly narrower desktop"). Q8 asks whether 1440 is the review width. |
| F14 | **Some design content is illustrative and infeasible here:** a 64-worker cluster and core-hours; TPE sampler; authors "R. Chen" and "A. Patel"; a "signed" audit trail; FX symbols (EURUSD) where the archives are US equities and ETFs (QQQ, SPY, ITOT, …); "Interpolated est." cells. | §4 lists each item and what the product shows instead. |
| F15 | **Experiments store weaker provenance than runs.** Runs, optimizations and walk-forwards carry the pinned source (`sha256`, `data_hash`, vintage, resampling policy). An experiment stores only the `DataReference` {symbol, timeframe, start, end} (`experiments.py:119`; confirmed on a saved document). No Aegis document records an engine or code version, only `"kernel"`/`"reference"`. Optimization and walk-forward documents record `"kernel" if kernel.AVAILABLE`, not the engine a cell actually used (`optimize.py:532`, `walkforward.py:476`). | Phase 2 pins data provenance and an `engine_build` on new experiments (§6.2). Provenance verification (Screen G) can only be "not recorded" for legacy experiments' data, never "verified". |
| F16 | **A latent overwrite in today's chunk writer.** `chunks_done` counts *readable* chunk files (`experiments.py:452`, `_readable`), and the next chunk is named `f"{chunks_done:06d}.parquet"` (`experiments.py:286`). If an earlier chunk is unreadable, the next write replaces an existing readable file, and its cells are lost after already being counted as done. Found by reading the code; not reproduced. | Phase 2 names chunks by the highest existing index + 1 and adds a regression test (`test_lab_store::test_unreadable_chunk_never_overwritten`). This touches the existing write path, so the experiment tests run in full. |

## 2. Design inventory (UX Pilot, read-only)

The canvas holds 14 designs, all `completed`. **All eight Lab screens exist, including Screen H.**

Randall has not yet reviewed them (brief §4 step 1), so this plan treats them as **unapproved**. Every UI commitment below is contingent on that review.

| Screen | Design | Size | Notes |
|---|---|---|---|
| A — Compact Optimization Dock | `wN1uwNnd3nDSujXzkXCD` "AegisQuant - Optimization Dock" | 1440×1024 | Heatmap "FAST MA × SLOW MA · other 10 vars fixed", `EXACT SLICE · empty = untested`, Top-10 by Sharpe, validation-status mini panel, `Expand Lab` |
| B — Expanded Lab | `ZaslUVrP3YsPnEfVCUmi` "Expanded Optimization Lab" | 1440×1024 | Context toolbar, KPI strip, parameter rail, 6 centre tabs, virtualized trials table, intelligence rail with a gate block |
| C — Candidate Compare | `7hbjydEsoHpcy6fUuESv` "Candidate Compare" | 1440×1024 | A/B/C cards, equity IS/OOS, parameter diff, regimes, long/short, costs, temporal windows, IS vs OOS decay |
| D — Million-Run Monitor | `Wxef1vuIX8p38sy6sVZl` "Run Monitor" | 1440×1024 | Reconciled counts header, staged funnel, convergence, workers and batches, top robust regions, sampling distribution |
| E — Parameter Families | `g9iUzZy6mY2l7PnDTjhg` "Parameter Families" | 1440×1035 | Scope breadcrumb, family tree, aggregated parallel coordinates, trellis, importance plus interaction, robust neighbourhood, drill-down |
| F — Walk-Forward & Robustness | `7G6vte5dXqR1JLui4tRV` "Walk-Forward Validation" | 1440×1024 | Fold matrix plus sealed final OOS, stitched equity, fold metrics, regime × window, cost stress, DSR panel, unseal dialog |
| G — Lineage & Forensics | `KBeXgDVVc9QYTxKaPXGU` "Experiment Lineage" | 1440×1059 | Lineage graph, saved views, side-by-side diff, audit trail, trade evidence, provenance verification |
| H — Variable Intelligence | `VVOsme6275ULO1u0dISZ` "Variable Intelligence" | 1440×1024 | Status catalog, dimensions defined → effective, budget split, main effects with 90% interval, prioritized interactions "7 of 190", structural dependency trail, reduced-vs-original, evidence rail |
| (baseline) | `M6jJxXlO0mhr67jR2OG9` "AegisQuant - Workstation" | 1672×1024 | Accepted workstation; matches the locked Downloads mock |
| (older) | `3GMmJ…`, `Qo4CI…`, `mnItC…`, `rgh0d…`, `wSsqN…` "Strategy Workbench" | — | Earlier workbench variants; not part of this plan |

Locked mock (`9f13379470-…png`):
- Top tabs RESEARCH · TEST · TRADE · ADVANCE.
- Left nav: Dashboard, Charts, Strategy Lab, Indicators, Data, Experiments, Paper Trade, Settings.
- Bottom tabs: Backtest Summary · Trades · Optimization · Equity Curve · Walk-Forward · Logs, with Param 1/Param 2/Metric on the right.
- KPI strip at the bottom.

The Lab must keep this shell: chart-dominant, thin separators, the 12 px base font (`styles.css:8`) and the palette tokens (`styles.css:3-5`).

## 3. Current-state audit

### 3.1 Repository and other people's work in progress

**Branch state**
- `main` is 042d5c9, pushed. This worktree (`claude/zen-thompson-50e9bb`) is clean at 042d5c9.
- `C:\Triad` is on `aegis/ai-reading` 57bcb34 (Mission 14, unmerged). It has another session's **uncommitted** edit to `tests/products/aegis/browser_workstation.py` (+284/−46, items 98–102). That checkout must not be touched by this work.
- The running worker (8102) and Core serve `C:\Triad`, so its code and UI are Mission 14's, not main's.

**Store**
- QA leftovers from Missions 11 and 13 are in the store:
  - runs `3b5359d6`, `bba0e913`;
  - strategy "QA M11 compressed v2";
  - `builder-check-m13`;
  - Operator sentence/stop surface trial docs.
- `untitled-strategy-7546d4` belongs to someone else. The Lab must list these honestly, not hide them.

**Pending decisions from earlier missions**
- Mission 13 merged without milestone QA or whole-branch review, at Randall's call. Its review can still run on main.
- The Mission 6/10 open items still stand: in-sample cells cold-start recursive indicators; first-plan pricing.

### 3.2 UI structure and chart stack (`app/products/aegis/ui`)

**Shell**
- `App.tsx` lays out `TopBar`, `SideNav`, `main` and `StatusStrip`.
- Pages: `'charts' | 'lab' | 'library' | 'experiments'` (`state/workspace.tsx:15`).
- On Charts, the results panel is a draggable, maximizable strip (`ResultsTabs`). Its tabs are Summary, Trades, Optimization, Equity, Walk-Forward and Logs (disabled).
- `SideNav` shows Dashboard, Indicators, Data, Paper Trade and Settings as disabled.

**State**
- One React context reducer (`state/workspace.tsx`, 490 lines, 33 vitest cases). No external store.
- `JobPoller` polls jobs every second.

**Optimization surfaces**
- `OptimizationTab.tsx` (365 lines): per-side job view; axis pickers for ≥ 3 parameters; metric; paged "Parameter sets" table; `Apply selected long + short`.
- `OptimizePopover.tsx`: ranges and the time estimate.
- `Heatmap.tsx`: DOM grid with discrete tones and the losses-red rule (8 vitest cases).
- `ExperimentsPage`, `ExperimentPlanner` (surface rows, budget, levers), `ExperimentReport` (plateaus, recommendation, uncertainty, clusters, decision, refine) and `CellsTable` (paged cells, plateau filter, curve overlay, Materialize/Use).
- `MainEffects`, `StudyPlanner/StudyView/StudyReport`, `WalkForwardTab`.
- `LibraryPage/LibraryCompare`: two-run compare.
- `builder/*`: React Flow canvas, Mission 13.

**Charts**
- Price: Vela via `chart/adapter.ts`, used only by `ChartPanel` and `LibraryChart`.
- Everything else is hand-written SVG or DOM.

**Tests**
- 21 vitest files, 137 cases, node environment. No DOM test environment is installed, so component behaviour is proven by the Playwright walk.

### 3.3 Optimization, experiments and analysis (Python)

| Module | What it does today | Limits / facts |
|---|---|---|
| `optimize.py` | Per-side grid; serial ≤ 400 cells, pooled above; cells as JSON in the job document; `axis_matrix` best-of-rest; `page_view` sends the best 1,000 | `MAX_CELLS=100_000`, `MAX_SQUARES=2_500`, `OBJECTIVES` 4 |
| `surface.py` | `Surface` of 1–`MAX_PARAMETERS=10` paths across both sides; `Grid` mixed-radix index, per-indicator validity tables, `neighbours()`; `latin_hypercube`; `refinement_cells`; planner levers (`coarsen`, `narrow`, `freeze`, `shorten`, `coarser_timeframe`, `raise_budget`) | Index is a Python int but is stored as Parquet `int64`; a `freeze` lever already exists (start = stop) |
| `experiments.py` | `ExperimentRequest/Document`; `ExperimentJob` (chunks of `CHUNK_CELLS=200` on the pool, one Parquet file per chunk, atomic `.tmp` replace, resumable); reports; `decide` (accepted/rejected/deferred); `refine` → child with `parent`; `materialize` (rerun one cell, metrics must equal, saved as a run with `experiment_id` and `cell`) | Curves kept only when `planned_runs ≤ 20,000`; reads scan every chunk |
| `analysis.py` | Peaks; plateaus (BFS within τ = tolerance × (P90−P10)); `main_effects` (median per value); `interactions` (all pairs, residual variance of the median matrix; report keeps the top 3); `sensitivity` (first-order share); k-means outcome clusters; recommendation = top plateau's centre | `neighbours_sampled` is brute-force O(n²) on a seeded `NEIGHBOUR_SUBSAMPLE=50_000`; no uncertainty intervals; sampler bias not separated |
| `pool.py` | `ProcessPoolExecutor`; workers hold the prepared frame, cache and kernel; rows carry 3 × 10 metrics | Workers default to `cpu_count − 2` = 10, or `AEGIS_POOL_WORKERS`; memory-fitted at 160 MB + 400 B/bar each, 80 % of free memory |
| `jobs.py` | `JobRunner`: one worker thread, **one unfinished job across all kinds**, cooperative cancel, persisted from start, `lost` on restart (experiments and studies resume) | Lab queries must not take the runner's lock |
| `walkforward.py`, `studies.py`, `study_rules.py` | Rolling IS/OOS windows in bars; per-side chained capital; plateau / peak / frozen-centre rules per window and symbol | `MAX_WINDOWS=50`, `MIN_OOS_BARS=20` |
| `strategy.py`, `kinds.py` | `StrategySpec` with independent long/short sides, rule trees (Mission 13), stop/target levels, `ExecutionSpec` (commission, slippage), `TemporalContext`; `referenced_columns(side)` lists the indicator columns the rules read | The basis of Screen H's structural relevance (§8.2) |
| `results.py` | `canonical_payload` → `result_hash` (SHA-256); `strategy_hash` of the spec | Anything added inside result metrics changes hashes |
| `data.py` | Raw archives, pinned by file SHA-256 plus `data_hash` of the bars; `BAR_CAP=2_000_000` | `research_eligible=False` everywhere |

### 3.4 Routes, storage and jobs

**Storage (§3.4a).** Aegis uses no database; everything is JSON or Parquet under `data/aegis/` of whichever checkout runs the worker.
- **Root:** `DATA_ROOT = parents[3]` of `data.py`. There is **no environment override**. The only Aegis environment variable is `AEGIS_POOL_WORKERS`.
- **Core:** Aegis uses Core's Postgres `Store` only for `list_work()` in `GET /status` (`server.py:71`).
- **Documents:** `<id>.json.gz` (gzip 6, `mtime=0`, sorted keys, Mission 11), or legacy plain `.json`, plus a plain `<id>.summary.json` sidecar that doubles as the Library's headline cache.
- **Writes:** `.tmp` + `replace` with a Windows retry. No fsync and no cross-process locks.
- **Experiments:** `experiments/<id>.json.gz`, `<id>.cells/NNNNNN.parquet`, `<id>.curves/…`, `<id>.reports/<n>.json|md`.
- **Studies:** `studies/<id>.windows/<SYMBOL>/<w>.json|parquet`.
- **Trash:** `trash/<folder>/<id>/` with `trash.json`, healed at startup.

Measured `C:\Triad\data\aegis`, 2026-10-27: **1.5 GB**.

| Folder | Size | Contents |
|---|---|---|
| `runs` | 1.1 GB | 670 docs; 509 still plain JSON, 990 MB |
| `studies` | 268 MB | 1,540 window files |
| `trash` | 77 MB | — |
| `optimizations` | 43 MB | — |
| `walkforward` | 20 MB | — |
| `experiments` | 9.8 MB | 55 docs, 75 cell files |

**Listing and paging**
- Listing globs and parses every sidecar on each call (`runs.py:305-331`).
- `GET /experiments/{id}/curves` returns at most 64 cells (`api.py:1002`).
- `offset` on `GET …/cells` has no lower bound (`api.py:966`).

**Jobs**
- A restart marks unfinished optimizations and walk-forwards `lost`, and unfinished experiments and studies `paused` (`jobs.py:282-294`).
- Resume is manual. There is no idempotency key.
- The live `preferences.json` already holds Mission 14's `reader_provider`, which main's `Preferences.set` would drop. This is one more reason to merge Mission 14 before Lab work (F12).

**Worker routes** (prefix `/aegis/api`, `api.py`), with line numbers:

| Area | Routes |
|---|---|
| Data and indicators | `GET /data/symbols` 167, `GET /data/bars` 190, `POST /indicators` 232 |
| Preferences | `GET`/`PUT /preferences` 320/325 |
| Backtest and runs | `POST /backtest` 330, `GET /runs` 348, `POST /runs/{id}/keep` 354, `GET /runs/{id}` 381 |
| Optimizer | `POST /optimize/plan` 429, `POST /optimize` 459, `GET /optimize` 488, `GET /optimize/{id}` 500, `GET …/cells` 508, `GET …/matrix` 528, `GET …/square` 553, `POST …/cancel` 574 |
| Walk-forward | plan/start/list/get/cancel, 594–658 |
| Strategies | list/get/create/put/read/duplicate/delete, 741–788 |
| Experiments | `POST /experiments/plan` 817; `POST /experiments` 862; list/get 893/898; pause/resume/cancel 905/922/943; `GET …/cells` 964 (offset, limit ≤ 5000, sort, valid_only: **reads every chunk per request**); `GET …/curves` 991; `POST …/cells/{cell}/materialize` 1006; report POST/GET/md 1043–1079; `PUT …/decision` 1096; `POST …/refine` 1107; delete 1131 |
| Studies | plan/start/list/get/pause/resume/cancel/delete/decision, window cells, report.md, 1212–1394 |
| Library | list/get/annotation/delete/restore/compare/trash-empty, 1418–1547 |

### 3.5 Engine, metrics and costs

- **Signals:** `backtest.evaluate` over the rule tree (pandas). The numba kernel (`kernel.py`) reads only signal arrays and levels, and is byte-identical to the reference engine (`test_aegis_kernel.py`, `test_aegis_engine_golden.py`, 14 cases).
- **Pool path:** `run_metrics` (`backtest.py:915`) runs both sides on the kernel and combines them. `combined.exposure` is the union of both sides' exposure.
- **Fills:**
  - Entry is at the next bar's open after a bar-close signal; exit by rule is the same.
  - Stop and target fire on the bar's close and fill at the next open (Mission 13).
  - Slippage is `slippage_bps`; commission is per side.
- **Execution versions:** only `engine: "kernel" | "reference"` is recorded. There is no engine build hash, so Phase 2 adds `engine_build` (§6.2).

### 3.6 What the brief assumes that does not exist

| Assumed | Reality | Plan |
|---|---|---|
| Deterministic Strategy Gate that recomputes from raw trades | Absent (F1) | Q1; Phase 7 optional |
| Sharpe, DSR | Absent (F3) | Q2; Phase 2b if approved |
| HA-MQI / EWO / RocketRSI, ~10 variables | Absent (F2) | Q3; fixtures meanwhile |
| Regimes (Trend/Range/HiVol) | Absent | Q4; "unavailable" state |
| FOMC / earnings windows | No feed; ANALYZE-only, hand-supplied | "Feed unavailable" state |
| Train / Validation / sealed OOS partitions | Not on experiments; WF/studies have IS/OOS windows. Core's Triad-era `trading_core/research/contracts.py:132-171` has `Partition` (training / validation / test) and refuses parameter search on `test` (`research/service.py:565-566`), but Aegis does not import it | Phase 5: Aegis-owned partitions (`selection / validation / final_oos`) mirroring Core's names and its rule. Adopting Core's research contract would be a new product → Core dependency on a contract built for another path, so it is not proposed |
| Search-space versioning, variable statuses | Absent (`freeze` lever only) | Phase 4 |
| TPE / Bayesian sampler | Absent (LHS + plateau refinement) | Excluded (§13) |
| Multi-node workers, core-hours | One laptop pool | Show "workers on this host", measured ms/cell-bar |
| Million-trial store and query | Chunk files, whole-table reads | Phase 2 |

### 3.7 Known limits (constants)

| Constant | Value | Where |
|---|---|---|
| `BAR_CAP` | 2,000,000 | `data.py:26` |
| `MAX_PARAMETERS` | 10 | `surface.py:34` |
| `SERIAL_MAX_CELLS` / `MAX_CELLS` | 400 / 100,000 | `optimize.py:40-41` |
| `CELLS_SENT` / `MAX_SQUARES` | 1,000 / 2,500 | `optimize.py:43-44` |
| `CHUNK_CELLS` | 200 | `experiments.py:62` |
| `CURVES_LIMIT` / `CURVE_POINTS` | 20,000 / 128 | `experiments.py:63`, `pool.py:35` |
| `NEIGHBOUR_SUBSAMPLE` | 50,000 | `analysis.py:24` |
| Pool worker memory | 160 MB + 400 B/bar | `pool.py:39-40` |
| `GET …/cells` limit | ≤ 5,000 | `api.py:968` |
| One unfinished job | all kinds | `jobs.py:1-5` |

### 3.8 Reuse map

| Need | Reuse | Gap |
|---|---|---|
| Trial rows, resumable chunks, lineage | `ExperimentJob`, `ExperimentStore`, `parent` | Compaction, column cache, trial identity beyond int64, counts |
| Sampling | `latin_hypercube`, `refinement_cells`, levers | "Investigate pair" focused design (Phase 4) |
| Exact candidate proof | `materialize` (metrics must equal) | Cost-stress variants (Phase 5) |
| Plateaus / neighbours | `analysis.peaks/plateaus/_centre`, `Grid.neighbours` | Hash-based neighbour lookup at 1M; coverage ratio |
| Main effects / interactions | `analysis.main_effects/interactions/sensitivity` | Uniform-design restriction, bias correction, bootstrap intervals (§7) |
| Walk-forward folds | `walkforward.py`, `studies.py` (plateau rule per window) | Calendar fold presentation, cost scenarios |
| Compare | `LibraryCompare` (two runs) | Three pins; stage-1 rows |
| Lineage graph | `@xyflow/react` (already installed) | Graph of experiments, studies, runs and candidates |
| Heatmap tones | `Heatmap.cells()` + losses-red rule | Canvas for > 2,500 squares, `n` overlay, hatch for untested |

### 3.9 Risks

| Risk | Mitigation |
|---|---|
| Hash drift from a new metric | Lab metrics kept outside `canonical_payload` (§6.3); golden and identity scripts in every phase that touches `backtest.py` |
| Memory: a full 1M-trial table is about 0.9 GB per worker | Projected columns only (≈ 140 MB per 7 columns at 1M), LRU by bytes, one open experiment per view (§9.2) |
| Stale or partial reads while running | Snapshots by manifest generation; every response carries `snapshot` and `provisional` |
| Statistical over-claiming | Basis labels, minimum support, uniform-design-only importance, intervals, "conditional on ranges and sampler" text (§7) |
| UI scope creep: eight screens | UI-first but phased; each phase must ship an independently useful slice and walk items |
| Mission 14 merge conflicts | Phase 1 begins after Mission 14 merges |
| Laptop compute | Budgets shown honestly; one million only at coarse bar counts (§9.6) |

## 4. Design items that are illustrative or infeasible, and what the product shows instead

| Design element | Product behaviour |
|---|---|
| Sharpe everywhere (A, B, C, E, F, H) | The experiment's objective metric, until Q2 is decided; then `sharpe` appears as a Lab metric |
| HA-MQI / EWO / RocketRSI parameter names | The strategy's real parameter paths, grouped by indicator family (§5.2) |
| EURUSD / FX pips | The archive symbol and timeframe; slippage in bps, commission per side |
| "64 workers · 2 stalled · 1 lost", core-hours (D, G) | "N workers on this host"; per-chunk wall time; measured ms per cell-bar; CPU-hours computed as workers × wall time, labelled "on this host" |
| TPE + Sobol sampler (D, G) | "Grid / Latin hypercube + plateau refinement" with seed |
| Authors (R. Chen, A. Patel), "signed" audit trail (G) | Single operator; an append-only event log with timestamps; no signatures (§13) |
| `Interpolated est.` legend cell (B) | Never produced; the label is not shown (no interpolation in scope) |
| Gate panels, `Send to Validation`, `Promote for validation`, DSR thresholds | Phase 7 only if Q1 = yes; before that a disabled control with `Strategy Gate: not built` |
| Regime selector, Regime × window grid (B, C, F) | "Regimes: not available" plus the clock windows that exist; event columns "feed unavailable" |
| `TRADE` top tab | Present but disabled ("Exchange closed") |
| "Unseal & confirm once (type ID)" (F) | Phase 5: real, one-time, logged unseal of the final OOS partition for named candidates |
| Bayesian "surrogate fit failed for regime HiVol" (H) | No surrogate models; errors are the real query or job errors |

## 5. UI map: screens A–H and the restored modes

**Conventions**
- **Source** names the API in §5.9.
- Every panel has four states: **L** loading (skeleton with the panel's title); **E** empty (a sentence naming why, e.g. "no trials match: 3 filters active"); **P** partial (running: `PROVISIONAL · snapshot hh:mm:ss · n of N`); **X** error (message plus `Retry`; other panels unaffected).
- **Selection model (one store, `state/lab.tsx`):**
  - `source` (experiment id, or `opt:<job_id>`);
  - `filter` (per-parameter ranges and values, scope `combined|long|short`, pass set, status set, partition);
  - `axes {x, y}`, `mode exact|aggregate`, `stat best|median|mean|worst`;
  - `metric`, `objectives[]`;
  - `selected` (trial ids, or one aggregate cell `{x, y}`);
  - `pins {A, B, C}` (trial ids only);
  - `brush` (axis ranges).
- Every view reads this store, and every interaction writes it. Navigation between sub-views keeps it (scenario 15).
- **Linked state is visible:** every linked panel shows a `Linked · k filters` chip, and clicking it lists the active filters with `Clear`.
- **Text:** 12 px base, nothing below 11 px. Status and secondary text keep ≥ 4.5:1 contrast on `--panel` (walk 106).

### 5.0 The brief's binding corrections (§5 table) → where they land

| Finding | Response in this plan |
|---|---|
| Expanded Lab: illegible base text; flat list hits a 20-variable wall | 11 px floor + contrast check (walk 106); `ParameterCatalog` collapsible, searchable families (§5.2, §5.5) |
| Expanded Lab: missing provenance; unclear linked interactions | Parent / child breadcrumb in `LabContextBar`; `Linked · k filters` chip on every panel |
| Compact Dock: two axes insufficient | `Trellis (k pairs) ↗` entry + `Expand Lab` (§5.1) |
| Compact Dock: no convergence or walk-forward | Convergence sparkline + Walk-Forward entry (§5.1) |
| Candidate Compare: contrast, million-trial drill-down | Maximize on every C panel, `n of N` context on every card, readable state chips |
| Candidate Compare: sealed OOS unclear; walk-forward implicit | `UnsealDialog` with consequences (§10 rule 4), and Screen F as its own view (§5.6) |

### 5.1 Screen A: Compact Optimization Dock (Charts page, results strip)

| UX region | Current component | Planned | Data source | Events | States |
|---|---|---|---|---|---|
| Results tabs | `ResultsTabs` | unchanged | — | tab click | — |
| X / Y / Metric | `OptimizationJobView` (rows/cols only at ≥ 3 params) | `DockControls`: X and Y always (≥ 2 params), metric, mode chip `Exact slice` / `Aggregated: best of the rest`* | job status; `GET /optimize/{id}/matrix` | change → refetch matrix | E: 1-parameter job "one axis: no matrix" |
| Heatmap | `Heatmap` (DOM) | `Heatmap` + `n` badge per square + hatch for untested + legend (Tested / Untested / Selected / Robust plateau) | matrix `values` + `counts` | click → select trial (exact) or square distribution (aggregate) | E: "No two-axis grid for this job" (existing); too many squares (existing notice) |
| Trial count, progress | job head + progress | unchanged + `PROVISIONAL` while running | job status | Cancel | lost / failed (existing) |
| Top-10 table | "Parameter sets" table | adds trial number and `Tested` badge; first page = top 10 in the dock | `cells` | row click selects | — |
| Validation mini panel | — | `Validation: no partition (grid job)` + `Strategy Gate: not built` until Phases 5/7 | — | — | — |
| Trellis entry, convergence preview, Walk-Forward entry (§5 corrections) | — | `Trellis (k pairs) ↗` link; 120 × 28 px convergence sparkline (best-so-far by evaluation order); link to Walk-Forward tab | job cells (order) | click → Lab E / WF tab | E: < 10 cells "not enough cells for a trend" |
| `Expand Lab` | — | primary button → Lab page, `source=opt:<job_id>`, axes/metric/selection carried | — | click | — |
| Right rail | `StrategyPanel` | unchanged | — | — | — |

\* Median, mean and worst in the dock depend on Q5.

### 5.2 Screen B: Expanded Lab ("Trial Lab")

A new page `'optlab'` is added to `SideNav` as "Optimization Lab", between Experiments and Paper Trade. A left sub-nav carries: Run Monitor (D), Trial Lab (B), Parameter Families (E), Variable Intelligence (H), Walk-Forward (F), History & Lineage (G) and Compare (C).

| UX region | Planned component | Data source | Events | States |
|---|---|---|---|---|
| Context toolbar: strategy, experiment + parent breadcrumb, dataset, regime, window, direction (L / S / Both = scope), independent L/S eval, partition, objectives, run status | `LabContextBar` | experiment document; `GET /lab/{src}/summary` | scope / objective / partition change → store | Regime: "not available". Event windows: "feed unavailable". Partition: "none" for legacy experiments |
| KPI strip: trials, coverage of valid space, best, median, robust regions, failed | `LabKpiStrip` | `summary.counts` + `summary.headline` | click count → sets filter | P |
| Parameter rail: search, families (indicator id per side, levels, side), X / Y / fix toggles, range sliders, presets | `ParameterCatalog` (collapsible, searchable; 20 rows fit) | `summary.parameters` (values, types, coverage per value) | set axis; fix value (exact slice); brush range; save preset | E: "no parameters" |
| Centre tabs: Heatmap · Interaction matrix · Parallel coords · Pareto · Importance · Robust plateaus | `LabHeatmap` (canvas), `InteractionMatrix`, `ParallelCoords`, `ParetoView`, `ImportanceView`, `PlateauView` | `POST /lab/{src}/query` views `matrix`, `interactions`, `parallel`, `pareto`, `importance`, `neighbourhood` | cell click; brush; reorder axes; Maximize (Esc to restore) | per panel L/E/P/X; basis label always visible |
| Side mini views (Pareto, parallel, sensitivity) | the same components, `compact` prop | same queries, cached | click → opens that tab | — |
| Trials table: virtualized, filter chips, Pinned A B C, Columns, Compare pinned | `TrialTable` (windowed rows, 22 px, overscan 10) | query view `page` (sort, offset, limit ≤ 500) | sort, pin, select, column chooser, `Compare pinned` → C | E: "0 of N match: <filters>" |
| Intelligence rail: deterministic findings; AI block visibly separate (Phase 8); selected-trial card; risk warnings; tested neighbours; IS / OOS (Phase 5); next-sweep recommendation; `Queue focused follow-up sweep`; gate block; provenance + `Copy JSON` | `IntelligenceRail` | `summary.findings` (deterministic text), `neighbourhood`, experiment document | queue sweep → `POST /experiments/{id}/refine` (existing) or `/lab/{src}/focus` (Phase 4) | gate block: "not built" (Q1) |
| Status line | `StatusStrip` | job status | — | `Partial results: updates every 2 s` while running |

**Keyboard:** arrows move the heatmap cursor; Enter selects; `1`/`2`/`3` pin A/B/C; Esc clears the brush, then the maximize. Each tab is focusable, and table rows are reachable by arrow keys.

### 5.3 Screen C: Candidate Compare

| UX region | Planned component | Data source | States |
|---|---|---|---|
| A/B/C cards (tested only; peak vs plateau badge; neighbours n) | `CandidateCard` | `GET /lab/{src}/trials/{trial}` + `neighbourhood` | E: "pin up to three tested trials" |
| Linked selection column (mini heatmap, parallel, Pareto, rows, `Show A on chart`) | compact Lab views; `Show on chart` → Charts page loads the materialized run | query + runs | — |
| Equity curves with IS / OOS divider | `CompareEquity` (SVG, as LibraryCompare) | stored 128-point curves when kept (≤ 20,000 planned), else materialize on demand (button, job) | P: "materializing A…" |
| All parameters (differences highlighted) | `ParamDiff` | trial rows | — |
| Drawdown, trade return distribution, costs & slippage, temporal windows | reuse `LibraryCompare` parts on materialized runs; costs from stage-2 rows | `GET /runs/{id}`, `GET /lab/{src}/replays` | E: "needs a full run: Materialize" |
| Regimes · Sharpe | — | — | "Regimes: not available" |
| Long vs short (independent) | `ScopeTable` | trial rows (long / short / combined) | — |
| IS vs OOS decay | `DecayTable` | Phase 5 partitions | E: "no partition on this experiment" |
| Rail: findings, gate, `Queue focused follow-up sweep`, `Send to Validation` | `IntelligenceRail` | — | gate "not built" |

### 5.4 Screen D: Run Monitor

| UX region | Planned component | Data source | States |
|---|---|---|---|
| Header counts: search space, scheduled, completed, valid, unique, duplicate, failed (retried), filtered, displayed | `CountsHeader` | `summary.counts` (§6.4) | P |
| Search config: method, seed, parameters, families, budget | `SearchConfig` | experiment document | — |
| Run versions (resumes, losses, pauses) | `RunSegments` | `document.run_log` (new, §6.2) | — |
| Snapshots | `SnapshotList` | `summary.snapshots` (manifest generations) | "browse while running" opens a frozen generation |
| Staged funnel 1–4 | `FunnelStrip` | stage counts (§10) | stages not started: "not started"; final OOS "sealed" |
| Pause / Snapshot / Retry failed / Stop early | existing pause/resume/cancel + new `retry-failed` | `POST /experiments/{id}/pause|resume|cancel`, `POST /lab/{id}/retry-failed` | — |
| Convergence (best-so-far + robust-region median per 5,000-trial batch, IQR band) | `ConvergenceChart` (canvas) | query view `convergence` | P "provisional"; < 2 batches: empty |
| Workers & batches | `WorkerPanel` | job status: workers, chunks done / total, chunk wall times, ms per cell-bar | stalled = chunk running > 3 × median chunk time |
| Top robust regions (live) | `RegionTable` | latest provisional plateau pass on the uniform subsample (§7.6) | click → Lab with the region's filter |
| Sampling distribution per parameter | `SamplingHistogram` | query view `marginals` | — |
| Rail: errors, uneven sampling, stall watch, cost (time used / remaining at measured rate), browsing-while-running | `MonitorRail` | counts + marginals + job | no probability claims about early stopping (§13) |

### 5.5 Screen E: Parameter Families

| UX region | Planned component | Data source | States |
|---|---|---|---|
| Scope breadcrumb: completed → valid unique → filtered → brushed | `ScopeBreadcrumb` | `summary.counts` + query `counts` | — |
| Data mode: Aggregated / Exact (≤ 5,000 sampled; stratified label) | toggle in `ParallelCoords` | view `parallel` (`bundles` or `sample`) | "sampled 4,000 of 6,904 (stratified by decile of metric)" |
| Family tree with counts; pinned filters & slices; `Pin brush`, `Clear` | `ParameterCatalog` (family mode) | `summary.parameters` | — |
| Full-size parallel coordinates, 12 of 18 axes, colour = metric median | `ParallelCoords` (canvas) | view `parallel` | 0 raw lines drawn in aggregated mode (stated) |
| Trellis of top pairs (aggregated 16 × 16, n shown) | `Trellis` | view `interactions` (top k by priority) + `matrix` per pair | cells n < 30 hatched and excluded from importance |
| Importance & interaction strength with 90 % whiskers | `ImportanceView` | view `importance` | method and sample shown |
| Robust neighbourhood map for a pair | `NeighbourhoodMap` | view `matrix` (aggregate, median) + `n` + IQR | hatched = untested; ring = IQR above P75 of IQRs |
| Contributing-trials drill-down (server-indexed, stable tie-break) | `TrialTable` | view `page` | — |

### 5.6 Screen F: Walk-Forward & Robustness

| UX region | Planned component | Data source | States |
|---|---|---|---|
| Fold matrix (train / validation / test per fold) + sealed final OOS bar | `FoldMatrix` | study document windows (Mission 8) + experiment partition (Phase 5) | final OOS "sealed · 0 evaluations" |
| Data partitions panel; cost scenario Base / +50 % / ×2; leg Both / Long / Short | `PartitionPanel`, `CostScenario`, `LegToggle` | experiment partition; stage-2 replays | cost scenarios other than Base need stage 2 |
| Stitched fold equity vs selection backtest; fold metric distribution; fold-level metrics | reuse `StudyReport` charts + new `FoldDistribution` | study windows | — |
| Regime × window | `WindowGrid` | run temporal breakdown (`temporal` tags) | regimes unavailable; windows with n < 30 trades hatched |
| Neighbourhood persistence by fold | `PersistenceStrip` | study per-window plateau membership | — |
| OOS decay & multiple testing (decay, trials in selection, raw and deflated Sharpe) | `MultipleTestingPanel` | Q2-dependent | "needs Sharpe (Q2)" |
| Sealed final OOS: `Unseal & confirm once (type ID)` | `UnsealDialog` | `POST /lab/{id}/final-oos/unseal` (Phase 5) | irreversible; logged |
| Gate checks | `GatePanel` | Phase 7 | "not built" |

### 5.7 Screen G: History, Lineage & Forensics

| UX region | Planned component | Data source | States |
|---|---|---|---|
| Lineage graph: parent sweep → focused children → refinement → candidates | `LineageGraph` (React Flow, read-only, no edits) | experiments `parent`, `lineage.proposal_id`; studies `experiment_id`; runs `experiment_id` + `cell` | E: single node |
| Saved views (restore) | `SavedViews` | `experiments/<id>.views.json` (new, additive) | — |
| Side-by-side experiment diff (method, seed, budget, ranges, compute, engine, data hash) | `ExperimentDiff` | two documents | — |
| Audit trail (append-only events) | `AuditTrail` | `experiments/<id>.events.jsonl` (new) | legacy experiments: events derived from timestamps, labelled "reconstructed" |
| Trade-level evidence for a candidate | `TradesTab` reuse, virtualized | materialized run | E: "materialize to see trades" |
| Provenance with hash verification | `ProvenancePanel` | `POST /lab/{id}/verify`: recompute `strategy_hash` from the pinned spec, re-hash the archive file against `sha256`, and check each named run's `result_hash` by streaming | X: mismatch → "artefact quarantined" (read-only flag, nothing deleted) |
| Return without losing state | URL hash state + the store | — | — |
| `Promote for validation`, `Fork new focused sweep` | Phase 7 gate / existing `refine` + Phase 4 `focus` | — | gate "not built" |

### 5.8 Screen H: Variable Intelligence

Mapped in §8.3, the Screen H contract.

### 5.9 Restored historical modes

| Mode | Where it is today | Plan |
|---|---|---|
| Backtest Review | Charts → Summary / Trades / Equity; Library run view | unchanged; Lab candidates open here via `Show on chart` |
| Compare | Library compare (two runs) | Screen C extends it to three pinned trials; Library compare unchanged |
| Optimization Lab | — | new page (B–H) |
| Provenance | run envelopes, Library | Screen G `ProvenancePanel` |
| Experiment Comparison / AI Investigation (brief §1 modes) | Experiments page; no AI investigation | Experiments page stays; AI explanations are Phase 8 (optional) |

### 5.10 Lab API (new routes, all under `/aegis/api/lab`)

These are interfaces only. Bodies are fixed by each phase's task plan.

| Route | Request | Response (always includes `scope`) |
|---|---|---|
| `GET /lab/{src}/summary` | — | `{counts, parameters[{path, side, family, type, values, tested_per_value}], headline, snapshots, provisional}` |
| `POST /lab/{src}/query` | `{filter, view, ...view args}`; view ∈ `counts, matrix, page, top, parallel, pareto, importance, interactions, neighbourhood, marginals, convergence` | view-specific payload + `scope {space, valid, attempted, completed, unique, duplicates, invalid, failed, filtered, shown, basis, snapshot, provisional, sampled_from?}` |
| `GET /lab/{src}/trials/{trial}` | — | the full trial row + params + identity |
| `POST /lab/{exp}/retry-failed` | — | job id (Phase 5) |
| `POST /lab/{exp}/focus` | pair or region + budget | queued child experiment (Phase 4) |
| `GET/POST /lab/{exp}/searchspaces…` | proposal / apply | §8 (Phase 4) |
| `POST /lab/{exp}/final-oos/unseal` | `{candidates[], confirm: "<experiment id>"}` | unseal record (Phase 5) |
| `POST /lab/{exp}/verify` | — | per-artefact hash checks (Phase 6) |

`{src}` is `exp:<experiment_id>` or `opt:<job_id>`. The optimizer source is read-only and has no partitions, statuses or proposals.

## 6. Trial data model

### 6.1 Identity

- **`trial_id` = `<experiment_id>#<trial_no>`.**
  - `trial_no` is an int64 assigned at scheduling, in schedule order. It is stable forever within the experiment and never reused, including after retries.
  - For legacy experiments (layout 1), `trial_no` is defined as the row's `cell` (legacy grids fit int64), so legacy trial ids are `<id>#<cell>`.
  - For an optimizer source it is `opt:<job_id>#<k>`, where k is the position in the saved `cells` list. That list is deterministic: plan order, extended by chunk.
- **`cell`**: the mixed-radix grid index, int64, nullable. It is present when the grid size is < 2^63 (every legacy experiment), and null beyond. Materialize keeps addressing by `cell` for legacy experiments and by `trial_no` for layout 2.
- **`pos.<k>`**: uint16 value position per parameter (≤ 65,535 values each). These are the true grid coordinates: neighbours, LHS and dedupe work on positions, never on `cell`.
- **`param_key`**: 16-byte BLAKE2b of the canonical `{path: value}` JSON (sorted keys, values rounded as `Parameter.values()` does). It identifies the same configuration across parent and child experiments (lineage, duplicates across sweeps).
- **`inputs_key`** (per experiment): BLAKE2b of `{strategy_hash, data identity (pinned sha256 + data_hash + range + timeframe), settings, engine_build, partition}`. Two trials are the **same computation** iff `inputs_key` and `param_key` are equal.

### 6.2 Experiment-level manifest (additive optional fields on `ExperimentDocument`)

| Field | Content |
|---|---|
| `cells_layout` | `1` (legacy chunks) or `2` (chunks + compacted parts + manifest) |
| `search_space` | `{version, hash, parameters:[{path, type: "int"|"float", start, stop, step, n_values, family, status, frozen_value?}], effective_dims, defined_dims}`. `version` increments per applied proposal; `hash` is over the parameters and statuses. |
| `sampler` | `{method: "grid"|"lhs+refine"|"focused"|"rescreen", seed, budget, first_pass, refinement}` (today in `plan` and `seed`) |
| `versions` | `{strategy_hash, spec_version, engine, engine_build, numba, numpy, pyarrow}`. `engine_build` = SHA-256 over the source of `kernel.py`, `backtest.py`, `indicators.py`, `kinds.py`, `strategy.py`, `temporal.py`, computed at worker start. |
| `data_pinned` | **new**: the `PinnedSource` the experiment ran on (`sha256`, `data_hash`, vintage, resampling policy, `bar_count`, `research_eligible:false`). Today experiments keep only the `DataReference` (F15). Legacy experiments show "data provenance not recorded". |
| `execution` | `{commission_per_side, slippage_bps}`, copied from the pinned spec for display (the spec stays the source) |
| `partition` | `{selection:{start,end}, validation:{kind:"folds", n, train_bars, test_bars}?, final_oos:{start,end, sealed:true, unsealed:[…]}?}` (Phase 5) |
| `counts` | reconciled counts (§6.4), written at each commit |
| `run_log` | `[{segment, started_at, ended_at, status, trials_from, trials_to, workers}]`: resumes, pauses, losses |
| `lineage` | `{parent, proposal_id?, reason?, derived_from_report?}` (`parent` exists today) |

### 6.3 Trial row (stage 1, Parquet, layout 2)

| Column | Type | Notes |
|---|---|---|
| `trial_no` | int64 | identity |
| `cell` | int64, nullable | legacy-compatible index |
| `pos.<k>` | uint16 × d | coordinates |
| `<path>` | float64 × d | typed by `search_space.parameters[].type` |
| `param_key` | fixed_size_binary(16) | dedupe |
| `pass` | dictionary\<string\> | `grid`, `sample`, `refine`, `focused`, `rescreen`, `manual` |
| `status` | dictionary\<string\> | `ok`, `invalid` (skip reason), `failed` (error) |
| `valid` | bool | kept for compatibility (`status == ok`) |
| `skip_reason` / `error` | string | — |
| `attempt` | uint8 | retry count |
| `<scope>.<metric>` | float64 × 30 | existing metrics, unchanged |
| `<scope>.sharpe` … | float64 | **only if Q2 approves.** Computed in the pool beside the metrics, never inside `backtest._metrics`, so no `result_hash` moves |
| `elapsed_ms` | float32 | — |
| `engine` | dictionary\<string\> | `kernel` / `reference` |
| `chunk` | int32 | commit unit |
| `finished_at` | timestamp[ms, UTC] | — |

**Split / long-short / regime / window / fees:**
- Stage-1 rows carry long, short and combined scopes (independent scoring), and evaluate only the **selection partition** (Phase 5).
- Fees and slippage come from the experiment's `execution`.
- Regime and window breakdowns exist only for stage-2 rows, because they need trades.

**Result hash:**
- Stage-1 rows have no result hash: they are metrics-only, which keeps the existing design.
- A stage-2 row is a materialized run with its `result_hash`, linked by `trial_id`.
- **Coverage metadata** is computed, not stored: tested unique / valid grid count, per-value and per-pair coverage.

### 6.4 Counts that must reconcile (scenarios 12, 21)

```
space      = Grid.size                         (product of value counts; Decimal string if > 2^63)
valid      = Grid.valid_count                  (per-indicator validity tables, unchanged)
scheduled  = len(planned trial_nos)            (first pass + refinement + focused)
attempted  = distinct trial_no with any row
completed  = attempted with status ok
invalid    = attempted with status invalid     (skip reasons)
failed     = attempted whose latest attempt has status failed
unique     = distinct param_key among completed
duplicates = rows beyond the first per trial_no (torn compaction, retries) + completed − unique
filtered   = completed matching the filter
shown      = rows / marks actually sent for this view
```

**Invariants (tested):**
- `attempted = completed + invalid + failed`;
- `unique ≤ completed`;
- `filtered ≤ completed`;
- `shown ≤ filtered`;
- every view's `scope` repeats the same numbers for the same snapshot.

Stage counts (`stage2_replays`, `stage3_candidates`, `final_oos_evaluations`) are separate. A stage-1 count is never labelled "backtests".

### 6.5 Stage 2–4 records

- **Stage 2:** `experiments/<id>.replays/part-*.parquet`, one row per (trial_id, cost_scenario). It holds `run_id`, `result_hash`, metrics per scope, `temporal.<tag>.{trades,net_pnl,win_rate,expectancy}`, `trades.long/short`, and `created_at`. Cost scenarios are `base`, `slippage×1.5`, `slippage×2`, `commission×2`, defined in the experiment, not hard-coded per run.
- **Stage 3:** existing study documents (Mission 8), with a new optional `candidates: [trial_id]` field.
- **Stage 4:** `experiments/<id>.final/` holds the unseal record (`unsealed_at`, candidates, confirm text) and one materialized run per candidate on the final OOS range.

## 7. Algorithms

All of these are numpy/pyarrow over projected columns, seeded and pure. The constants live in `lab/policy.py` with these initial values; Q6 asks Randall to confirm them.

### 7.1 Exact slice

- **Input:** axes (x, y), fixed values for every other active parameter, defaulting to the selected trial's values or else the pinned spec's current values. The filter applies too.
- **Output:** one square per (x, y) value pair.
  - A square is observed iff ≥ 1 completed trial has exactly those values. It holds that trial's metric and `trial_id`. Ties (duplicates) show the first `trial_no`, with a duplicate count.
  - A square with no trial is `untested` and drawn hatched. It holds no value and is never filled from neighbours.
- **Basis:** `Tested (exact)`. The legend reads "empty = untested".

### 7.2 Aggregated projection

- **Input:** axes, `stat ∈ {best, median, mean, worst}` (dock: Q5), and the filter. All other parameters vary.
- **Per square:** `n`, the stat, `p25`, `p75`, `min`, `max`, and the contributing `trial_no` list (paged on click).
- **Minimum support:**
  - `n ≥ 1` to show a value;
  - `n < AGG_MIN_N = 8` is shown dim and labelled `low n`;
  - the legend reads `Aggregated n ≥ 8 / n < 8 low`.
- **Uneven-sampling warning per square:** for each other parameter k, total-variation distance between its value distribution inside the square and in the filtered population. A square is flagged `confounded?` when `max_k TVD > 0.25` and `n ≥ 8`. The panel lists the top flagged parameters.
- **A clicked aggregate square:**
  - opens a distribution panel (histogram, n, IQR, contributing trials);
  - never selects a "configuration";
  - `Pin` and `Send to Validation` are disabled with "an aggregate is not a runnable strategy" (scenario 4).

### 7.3 Main effects and importance (Screen B/E Importance, Screen H overview)

- **Rows used:** **uniform-design rows only**, `pass ∈ {grid, sample}`. Refinement, focused and rescreen rows are excluded because their sampling is biased. The panel says "computed on n uniform trials of N; refinement rows excluded (adaptive)".
- **First-order index:** `S_i = Var_b(E[Y | X_i = b]) / Var(Y)`, over the values b of parameter i, weighted by count. It uses a bias correction for finite bins: `S_i_adj = max(0, (S_i − (B_i − 1)/(N − B_i)·(1 − S_i)))`, i.e. adjusted η², where `B_i` is the number of observed values.
- **Interval:** seeded bootstrap over rows. `B = 200` resamples, on at most `IMPORTANCE_ROWS = 50,000` rows (a seeded subsample, stated). The output is a **90 % percentile interval**.
  - Measured: one pass over 20 mains and 190 pairs on 50k rows is 61 ms, so ≈ 12 s for 200 resamples. It runs as a background Lab task, cached per snapshot.
- **Labels:**
  - `Measured` when `n_uniform ≥ IMPORTANCE_MIN_N = 30 × B_i`;
  - `Insufficient coverage` otherwise (no ranking, shown last).
- **Caveat text, always:** "conditional on these ranges, this data and this sampler; correlated or aliased inputs share credit".
- **Correlation check:** Cramér's V between every parameter pair over the uniform rows. LHS should be near 0; pairs with V > 0.3 are flagged `aliased`.
- **Not used:** permutation importance on a fitted model, because there is no model library and no surrogate (§13).

### 7.4 Pairwise interaction screening (not exhaustive display)

- **Computation:** every valid pair, d(d−1)/2 (190 at d = 20), is computed server-side on the same uniform rows: `S_ij = Var(E[Y | X_i, X_j]) / Var(Y) − S_i − S_j` (bias-adjusted as above, interval by the same bootstrap). This is cheap (measured above).
  - **Coverage** = the share of the pair's value grid with ≥ `PAIR_MIN_N = 4` trials.
- **Display:**
  - The UI shows the ranked list ("7 of 190 pairs") plus `Show all valid pairs` and `Explore any valid pair` (a manual pair picker).
  - It never shows 190 mini plots by default.
- **Priority for investigation:**
  - `priority = S_ij upper 90 % bound` when coverage ≥ `PAIR_MIN_COVERAGE = 0.5`;
  - otherwise the pair goes to the `unresolved` list, sorted by `max(S_i_upper, S_j_upper)` and then by lowest coverage.
  - Uncertain pairs rank high by design: upper bound, not point estimate.
- **Weak-main / strong-joint protection (scenario 19):**
  - A variable may be **proposed** `Deprioritized` only if both hold:
    - (a) `S_i upper < θ_main = 0.01`; and
    - (b) every pair containing it has coverage ≥ 0.5 and `S_ij upper < θ_int = 0.01`.
  - Otherwise it is `Investigate`, with the reason "interaction not ruled out" or "pair coverage insufficient".
- **Higher-order residual:** `R = 1 − Σ S_i − Σ S_ij`. When the lower bound of `R > 0.3`, a global warning reads "higher-order interactions or noise unexplained: deprioritization unsafe", and no `Deprioritized` proposal is made at all.
- **3-way checks:** only on request (`+3-way` in H). It uses the same estimator on a triple, and needs coverage ≥ 0.5 of the triple's grid on the uniform rows, else `unresolved`.

### 7.5 Investigating a pair (targeted experiment)

`Investigate pair (i, j)` → `POST /lab/{exp}/focus` creates a **child experiment** (lineage `parent`, `reason`):
- the full value grid of i × j;
- every other active parameter sampled by LHS, so the pair's effect is marginalized, not conditioned on one point;
- a budget the operator chooses, priced by the existing planner;
- `pass = focused`.

`Conditional` mode (others fixed at the selected plateau centre) is offered as the second option and labelled as conditional.

### 7.6 Robustness neighbourhoods and plateaus

**Neighbourhood of a trial t (interactive, any size):**
- Tested trials whose positions differ from t's by **at most `r` steps in at most `m` parameters**. Defaults: r = 1 and m = 1, which is today's exhaustive rule.
  - On sampled surfaces the default is m = 2, because one-step neighbours are mostly untested.
- Lookup is by hashing positions, `O(d · r · C(d, m))` probes per trial (840 at d = 20, m = 2): milliseconds, no O(n²).
- **Output:** n tested, n valid in the neighbourhood, coverage = tested / valid, median, IQR, min, and the share within τ of t.
- **Plateau assessment needs coverage:** coverage ≥ `PLATEAU_MIN_COVERAGE = 0.5` and `n ≥ 2d + 1` (today's minimum), else "not enough tested neighbours for a plateau assessment".

**Robust ranking:**
- Candidates are ranked by the neighbourhood **P25**, among trials with an assessable neighbourhood. This is shown separately from best-single-point ranking (scenario 5).
- A trial whose value exceeds its neighbourhood P75 + 3 × IQR is marked `one-off peak`.

**Plateaus over a whole experiment** (reports, Run Monitor regions):
- Use the existing `analysis.peaks/plateaus` on the uniform subsample (≤ 50,000), with the hashed neighbour relation instead of brute-force kNN.
- The subsample and rule are named.

### 7.7 Pareto selection

- **Objectives:** two or three chosen metrics with their orientation (max drawdown minimized).
- **Rows:** observed completed trials in the filter only.
- **Method:**
  - 2-D: sort plus sweep, O(n log n).
  - 3-D: sort by the first objective plus block-nested skyline over the sorted stream.
- **Output:** front `trial_id`s, the rank-1 front size, and the dominated count.
- **Drawing:** a density bitmap for the dominated cloud (64 × 64 bins) plus exact front points (front size ≤ 2,000 drawn; else sampled with a label).

### 7.8 Linked filtering and selection

- One `filter` object is applied server-side to every view. The UI never filters client-side.
- Brushes are ranges in the filter.
- A selection is either a set of trial ids (≤ 5,000), or an aggregate square, which is stored as its defining filter. That keeps "selected in heatmap" equal to "highlighted in table/parallel/Pareto" by construction.
- Every response echoes `filter_hash`. The UI discards responses whose `filter_hash` is not current, which prevents races.
- **Count-preserving drill-down:** a square's `n` equals the `page` total for the same filter plus square. This is tested (scenario 14).

### 7.9 Parallel coordinates

- **Aggregated mode (default):** bundles = groups of trials sharing a quantile-bin vector over the shown axes (`q = 4` bins per axis).
  - A bundle draws as one polyline through bin centres, with opacity ∝ count and colour = the bundle's median metric.
  - At most `PARALLEL_MAX_BUNDLES = 2,000`. Beyond that only the largest bundles are drawn, with "k of K bundles (≥ x trials each)" stated.
- **Exact mode:** a stratified sample of ≤ `PARALLEL_MAX_LINES = 5,000` trials, stratified by metric decile and seeded, labelled `Sampled n of N`.
- Highlights (top / bottom / pinned) are always exact lines drawn over either mode.

### 7.10 Convergence

- Best-so-far by `trial_no` order.
- The robust-region median is taken per batch of 5,000 trials: the median of the neighbourhood-P25 of that batch's top 1 %, with an IQR band.
- Labelled `PROVISIONAL` while running. Never extrapolated.

### 7.11 Assumptions stated on every analytic panel

- Discrete grids only: every parameter has a step.
- Uniform-design rows for importance and interactions.
- Metrics are in-sample on the selection partition unless the panel says otherwise.
- Data are raw archives, not research-eligible.

## 8. Screen H contract: Variable Intelligence and search-space design

**H is the upstream entry point to a large run, not a dashboard.** The research flow is:
1. Define the surface in the Experiments planner (every typed parameter, with structural statuses pre-filled by §8.2).
2. Run a **screening experiment**: uniform Latin hypercube at a modest budget (the planner prices it).
3. Read the screen in H.
4. `Propose Search Space` → `Review Before Apply`.
5. The applied proposal **is** the large run: a child experiment with the budget split (§8.5), watched in D.
6. Re-screen when the scope changes.

A large run started elsewhere (the Experiments planner) is allowed. H then shows "no screening evidence: all parameters Active".

### 8.1 Concepts (exact semantics)

| Status | Meaning | In the next sweep | Strategy definition |
|---|---|---|---|
| **Defined** | a tunable path exists in the pinned spec (indicator length / params, stop / target %) | — | unchanged |
| **Active** | varied in the broad search | full range | unchanged |
| **Investigate** | unresolved or interaction-sensitive | targeted trials (§7.5) and kept varied | unchanged |
| **Deprioritized** | lower exploration share in an evidence-scoped study; **not disproven** | still varied, with fewer levels (coarsened by the planner's `coarsen` lever) or a smaller budget share | unchanged |
| **Excluded** | out of the search set. Either **structural** (deterministically proven inert, §8.2) or **research decision** (user-approved, reversible, reason required) | not varied; strategy keeps its current value | unchanged |
| **Frozen** | fixed at a pinned value **for this sweep only** | `start = stop = value` | unchanged (the spec keeps its own value; the frozen value lives in the search space) |

**Effective dimensions** = the number of parameters varied (Active + Investigate + Deprioritized). It is shown beside the scope: strategy hash, data, range, partition.

**Excluded ≠ Frozen.** Excluded means "not a search dimension" and the spec's own value is used. Frozen means "a search dimension pinned to a chosen value for this sweep". Both are reversible; neither edits the strategy.

### 8.2 Structural relevance (deterministic, reproducible)

`lab/structure.py::dependency_graph(spec) -> Graph` and `structural_status(spec, path) -> (status, proof)`.

**Nodes:**
- the parameter paths;
- indicators;
- indicator outputs;
- rule conditions;
- entry and exit trees per side;
- stop and target levels;
- the side switch;
- temporal windows.

**Edges:** "value flows into", read from the spec. The edges come from `referenced_columns(side)` (`strategy.py:222`), `conditions(rule)`, `side.enabled`, the level fields and window modes.

**A parameter is `Excluded (structural)` iff no path exists from it to an order decision.** The concrete, exhaustive rules:
1. The parameter is on a disabled side. (The surface already refuses these, `surface.py:120-121`; H shows them for completeness.)
2. Its indicator's outputs appear in no condition of that side's entry or exit (`referenced_columns`).
3. It is a level (`stop_loss_pct`, `take_profit_pct`) that is unset on that side.
4. It belongs to a temporal window whose mode is `ANALYZE` (tags only; it never gates an entry, `temporal.py:3-6`).

**Proof object:** `{rule: 1–4, path: [node…], spec_hash}`, rendered as the "Structural dependency trail". Re-running on the same `spec_hash` reproduces it exactly.

**Never a structural exclusion:**
- a parameter that changes results under some value of another parameter (e.g. the MACD `signal` when only `line` is referenced still changes the warm-up, so it stays Active with the note "affects warm-up only");
- any parameter whose path reaches a condition, however weak its observed effect.

**Aliases:** two parameter paths that resolve to the same indicator field (duplicate surface rows) are refused at plan time (existing duplicate-path check). Two indicators with identical kind, length and source on one side are flagged `alias` (informational, not excluded).

### 8.3 UI regions (design H) → components → data → events → states

| Region | Component | Data | Events | States |
|---|---|---|---|---|
| Top context: strategy + search-space version, data / regime / window, direction, partition, defined vs effective dims, run / seed / engine hashes, budget, `IS-only · no OOS touched` | `SpaceContextBar` | experiment + `search_space` | — | partition badge: `IS-only` or `OOS sealed` |
| Parameter catalog: families, five statuses, conditional-dependency badge, `Restore`, `Pin` | `ParameterCatalog` (status mode) | `GET /lab/{exp}/variables` | status chip → opens the transition dialog | filter chips by status |
| Centre overview: main / conditional influence with 90 % interval, coverage, method; projected Cartesian size original vs effective | `InfluenceView` + `SpaceSize` | `importance` + `searchspaces/preview` | — | `Measured` / `Insufficient coverage`; "Feasible space (theoretical Cartesian count): not trials saved" |
| Interaction explorer: ranked pairs, mini matrix, `Show all valid pairs`, manual `Explore any valid pair`, `+3-way` | `InteractionExplorer` | `interactions` | pick pair → the pair's matrix in place; `Investigate Pair` → focus dialog | `unresolved` list separate |
| Proposal / impact: original vs candidate space, dims, frozen values, reasons, unresolved interaction risks, tested coverage; `Propose Search Space`, `Review Before Apply` | `ProposalPanel` | `POST /lab/{exp}/searchspaces/preview` | propose → draft; review → diff dialog → apply → child experiment | `No OOS endorsement` badge always |
| Bottom evidence table: contributing trial ids, partition, ranges, n, status, outcome, proposed trials | `TrialTable` (evidence mode) | `page` with the pair / variable filter | click → filter | — |
| Right evidence rail: why this status; proof or method; scope; uncertainty; interaction warnings; contradictory evidence; re-screen triggers; provenance; focused-test suggestion | `EvidenceRail` | `variables[path].evidence` | `Restore Parameter`, `Pin Setting`, `Simulate Budget` | contradiction alert when two scopes disagree (§8.5) |

### 8.4 Status transitions (all versioned, all with provenance)

```
Defined ─► Active (default for every non-structural parameter)
Active ⇄ Investigate        (evidence or user; reason required)
Active/Investigate ─► Deprioritized   only when §7.4 (a)+(b) hold AND no global higher-order warning; user confirms
any ─► Excluded(structural) only by §8.2 proof (automatic, shown, reversible if the spec changes)
any ─► Excluded(research)   user only; reason text required; warning lists its unresolved pairs
any ─► Frozen               user only; value required (default the spec's current value)
Deprioritized/Excluded(research)/Frozen ─► Active   "Restore": one click, reason optional, always allowed
```

**Each transition appends an event:**
`{at, path, from, to, actor: "operator"|"structure", reason, evidence_ref (snapshot + method + interval), scope (strategy_hash, data identity, partition, surface hash)}`.

Rules:
- AI text may be attached as a *note*. It is never the actor.
- There is no automatic empirical transition except structural exclusion, and that one is proof-based.

### 8.5 Search-space proposals and versioning

- **Proposal:** `searchspaces/<exp_id>/<n>.json` holds `{base_version, statuses, frozen values, coarsenings, reasons, unresolved_pairs, budget_split, created_at, applied: false}`. It is versioned by n and hashed.
- **`Review Before Apply`** shows a side-by-side diff of dims, frozen values, removed / coarsened levels, the theoretical Cartesian count before and after (Decimal), and the estimated time at the measured rate.
  - Every number is labelled "theoretical; a sampler's trials are set by the budget, not by the space" (scenario 21).
- **Apply** never edits the strategy. It creates a **new child experiment** with:
  - the same pinned spec;
  - the new surface;
  - `search_space.version = base + 1`;
  - `lineage.proposal_id`;
  - a budget split: screening / interactions / refinement / re-entry reserve (default 30 / 48 / 22 % with 5 % reserve; Q6).
- **Historical trials:**
  - Parent trials stay valid evidence for their own space and are never re-labelled.
  - The child can **reuse** parent trials whose `inputs_key` matches and whose params lie in the new space. They are copied by reference (`param_key` lookup) and counted as `reused`, never as new.
- **Cache keys** include `search_space.hash`, so no view mixes versions.
- **Re-screen triggers mark statuses `stale` (scenario 22):**
  - a different `strategy_hash`;
  - a different data identity (symbol, timeframe, range, sha256);
  - a changed surface range;
  - a changed partition;
  - a new regime / window selection, once such selections exist.
- A stale status still shows its old evidence, struck through, with `Re-screen` (a `rescreen` child: uniform sample over the current space at the reserve budget).
- **Final OOS is never read by any H computation.** `lab/partitions.py` is the single bar-access point. It refuses `purpose="screening"` for the final range (scenario 22 test), and any proposal created after an unseal is badged `post-unseal: cannot drive re-tuning` and cannot be applied.

### 8.6 Budget estimates

- **Projected time** = `trials × bars × measured ms_per_cell_bar / (0.8 × workers)`, using the existing planner arithmetic, with "measured on this host" or "starting guess".
- No "speed-up" or "trials saved" claim is made. The two counts shown are "theoretical Cartesian space" and "scheduled trials".

### 8.7 Answers to the mandatory Screen H review questions

| Question | Answer in this plan |
|---|---|
| What evidence supports each structural exclusion, and how is it reproducible? | §8.2 rules 1–4; the proof is a path in the spec's dependency graph plus `spec_hash`; `structural_status` is pure, and tests pin each rule (scenario 18) |
| How are weak-main, strong-joint interactions protected? | Uniform-row pair screening with upper bounds, coverage gating, the §7.4 (a)+(b) rule, the higher-order residual veto, XOR fixture tests (scenario 19) |
| What prioritizes pair / higher-order investigation, and how are uncertainty and sampler bias exposed? | Priority = upper 90 % bound of `S_ij`; unresolved list by coverage; refinement rows excluded and the exclusion stated; Cramér's V aliasing flags |
| Which variables are frozen vs excluded, and is the strategy unchanged? | §8.1; apply creates a child experiment on the same pinned spec; test `test_apply_proposal_keeps_strategy_hash` |
| Can Randall restore or inspect any valid pair in one or two interactions without losing filters? | `Restore` is one click; `Explore any valid pair` is two selects; the store keeps the filter (walk item) |
| How do changes affect versioning, historical trials, cache keys, lineage and budget? | §8.5 |
| What QA proves a variable-selection change does not alter OOS usage or deployment eligibility? | `partitions.py` refusal tests; no gate input reads statuses; post-unseal proposals blocked (scenarios 13, 20, 22) |

## 9. One-million-trial readiness

### 9.1 Measured on this machine (2026-10-27)

**Setup**
- i7-1255U, 15.8 GB, NVMe SSD.
- `.venv-aegis` (pyarrow 23.0.1, numpy 2.5.3).
- A synthetic table shaped like Aegis cell rows: 1,000,000 rows; 20 parameter columns, 30 metric columns, `cell`, `pass`, `valid`, `elapsed_ms`.
- Random metric values, the **worst case for compression**.
- Scripts are in this session's scratchpad (not committed); Phase 2 commits a reproducible version as `tests/products/aegis/lab_benchmark.py`.

| Operation | Cold | Warm |
|---|---|---|
| Arrow table in memory (all columns) | 426 MB | — |
| Write one Parquet file (zstd, 64k row groups) | 4.8 s | — |
| ↳ size on disk | 311 MB | — |
| Write 5,000 chunk files of 200 rows (**today's layout**) | 25.4 s | — |
| ↳ size on disk | 398 MB | — |
| Read 5,000 chunks + concat (**today's `ExperimentStore.cells`**) | **155.9 s** | **24.0 s** |
| Read `cell` column of 5,000 chunks (**today's `done_cells`**) | 12.6 s | 12.3 s |
| Read one file, all columns | 395 ms | 150 ms |
| Read one file, 7 projected columns | 18.5 ms | 16.4 ms |
| Filter two ranges in memory (→ 367,595 rows) | 22 ms | 14 ms |
| 2-D median + count over the filtered rows | 110 ms | 95 ms |
| Exact slice (two fixed values) | 37 ms | 31 ms |
| Top 200 by a metric (1M rows) | 25 ms | 23 ms |
| Full sort + page at offset 500,000 | 204 ms | 195 ms |
| Dataset push-down filter from disk (7 columns) | 36 ms | 24 ms |
| 64 × 64 density histogram (1M) | 137 ms | 136 ms |
| `to_pylist` of 100,000 rows (**today's `analysis._columns`**) → ≈ 18 s per 1M | 1.8 s | — |
| 20 mains + 190 pair screens, 50k rows, one pass (× 200 bootstrap ≈ 12 s) | 61 ms | — |

**Process memory (working set)**

| State | Working set |
|---|---|
| Baseline | 39 MB |
| 7 columns of 1M rows held | 178 MB |
| All columns held | **940 MB** |

### 9.2 Storage, indexing and partitioning (Phase 2)

**Write path kept:** chunk files, atomic `.tmp` replace, resumable. `CHUNK_CELLS` stays 200 for progress granularity.
- **One fix:** chunks are named by the highest existing index + 1, not by the count of readable files (F16).

**Compaction (layout 2):**
- Every `COMPACT_EVERY = 50` chunks (≈ 10,000 trials), and at finalize, the job (inside its own unit, never concurrently) merges committed chunks into `cells/part-<gen>.parquet`:
  - zstd;
  - row groups of 65,536;
  - sorted by `trial_no`.
- It then writes `cells/manifest.json` (`{generation, parts[{file, trial_no_min, trial_no_max, rows, sha256}], chunks_after}`) atomically, and only then deletes the merged chunks.
- **Crash at any point:** readers take parts from the manifest plus any chunk file not listed, and deduplicate by `trial_no`, keeping the latest attempt and counting duplicates. Re-running compaction is idempotent.
- Test: `test_lab_compaction_torn_is_idempotent`.
- **Legacy experiments (layout 1) are not compacted** (retained data, §12). They are ≤ 252 cells today, and their reads go through the same reader.

**Index:**
- `trial_no` is sorted within parts, and row-group statistics give range push-down.
- Per-part min/max per parameter column come free with Parquet statistics.
- No separate index files.

**Column cache:**
- `LabCache` in the worker holds projected Arrow columns per `(experiment, generation)`.
- LRU by bytes with `LAB_CACHE_BYTES = 400 MB`, sized from 2.5 GB free × the pool's 0.8 headroom, minus the pool's own share. Configurable with `AEGIS_LAB_CACHE_MB`.
- A query loads only the columns it needs: params in the filter, axes, metric, `status`, `pass`, `trial_no`. That is about 140 MB for 7 columns at 1M rows.
- **Never** all 50+ columns (940 MB).

### 9.3 Server-side filtering, aggregation and paging

- All views run in FastAPI's thread pool, outside `JobRunner`'s lock. They read a manifest generation snapshot, so a running job never blocks a query and vice versa.
- Paging is by `(sort column, trial_no)` keyset where possible. Offset pages are allowed up to `PAGE_LIMIT = 500` rows.
- `top` uses `select_k`.
- The response size is bounded per view:

| View | Bound |
|---|---|
| `matrix` | ≤ 200 × 200 squares |
| `page` | ≤ 500 rows |
| `parallel` | ≤ 2,000 bundles or 5,000 lines |
| `pareto` | front ≤ 2,000 + 64 × 64 density |
| `marginals` | ≤ 65,535 values per parameter, bucketed to ≤ 200 |
| `convergence` | ≤ 1,000 points |

### 9.4 Background work, progress, cancellation and resume

- **Stage-1 trials:** the existing experiment job (one unfinished job across kinds: `jobs.py`).
- **Heavy Lab analytics** (bootstrap importance, interaction screen, plateau pass) run as **Lab tasks**: a single-thread executor separate from `JobRunner`, one task at a time. The result is cached per `(experiment, generation, filter_hash, method)` and is cancellable at checkpoints between bootstrap resamples. Status is polled by the view.
- **Lab tasks never start pool processes.** They share the CPU with a running experiment, and the UI shows "analysis waits while a job runs" when the measured CPU share is above 90 % (Q7: may Lab tasks run concurrently with a job?).
- **Progressive results:** each compaction generation is a snapshot. Responses carry `snapshot` and `provisional`. The UI shows `PROVISIONAL · snapshot hh:mm:ss`. A live best-so-far curve is never labelled complete.
- **Cancellation / pause / resume:** existing behaviour (pause = cancel with pause flag; resume continues from the trials on disk).
- **New:** `run_log` segments record every start, pause, loss and resume.

### 9.5 Failures and duplicates

- **Per-trial isolation (Phase 5):**
  - Today a pool exception fails the whole job.
  - Stage 1 will record a trial raising an unexpected error as `status=failed`, with the error text and `attempt`, and continue.
  - A chunk whose worker process died is re-queued once. If it dies again, its trials are marked failed.
- **`Retry failed`** re-queues `status=failed` trials with `attempt + 1`, under the same `trial_no`. It is idempotent: a trial already `ok` is never re-run.
- **Duplicates** from a torn compaction or a retry overlap are dropped on read (latest attempt wins) and counted in `duplicates`.
- **Unavailable indicator data** (warm-up longer than the data) stays `invalid: insufficient bars`. It is not `failed`.

### 9.6 Budgets for approval (pass thresholds proposed for scenario 11)

These are proposed from the §9.1 measurements with about a 3× margin for real data, a busy laptop and HTTP overhead. Randall sets the final values (Q6).

| Interaction (1,000,000 completed trials, warm cache) | Budget (p95) |
|---|---|
| Lab open: summary + first heatmap + first table page | ≤ 1.5 s (cold, from disk: ≤ 4 s) |
| Filter or axis change → heatmap + counts | ≤ 400 ms |
| Aggregate stat change | ≤ 300 ms |
| Table page (any offset) | ≤ 600 ms |
| Exact-slice change | ≤ 300 ms |
| Parallel coords (bundles) | ≤ 800 ms |
| Pareto (2 objectives) | ≤ 800 ms |
| Neighbourhood of one trial | ≤ 150 ms |
| Importance + interactions (bootstrap 200) | background ≤ 30 s, progress shown |
| Progress poll while running | ≤ 100 ms server time |
| UI main thread: no task > 50 ms during any interaction above; ≤ 1,500 DOM table rows; ≤ 40,000 canvas squares | — |

| Resource | Budget |
|---|---|
| Worker additional memory with one 1M-trial experiment open | ≤ 450 MB (cache 400 + transient) |
| Browser tab heap | ≤ 300 MB |
| Disk per 1M-trial experiment (stage 1) | ≤ 350 MB |
| Compaction pause at 1M | ≤ 10 s per generation (one unit) |

**Throughput (not a promise; measured rate × formula):**
- `hours ≈ trials × bars × 0.027 ms / (0.8 × 10 workers) / 3.6e6`.
- 1M trials at 2,000 bars ≈ 1.9 h; at 10,000 bars ≈ 9.4 h; at 50,000 bars ≈ 47 h.
- The pool fits workers to free memory (160 MB + 400 B/bar each). With 2.5 GB free, 12 workers fit at 10k bars, so the configured 10 hold.
- The planner already prices this and asks above 10 minutes.

### 9.7 Drill-down and the no-million-node rule

- No view sends more than its bound (§9.3).
- The table is windowed: rendered rows ≈ visible + 20.
- Canvas charts draw bins and bundles.
- Exact marks are sampled and labelled.
- Every drill-down step keeps counts (scenario 14).
- **Test:** the walk counts DOM rows (≤ 1,500) and the response sizes with the 1M synthetic experiment.

### 9.8 The synthetic 1M experiment (scenario 11)

- `tests/products/aegis/lab_fixture.py` writes a layout-2 experiment directly:
  - deterministic seed;
  - 20 parameters;
  - metrics from a known function, including an XOR pair, a conditional triple and a plateau / spike pair, plus noise;
  - in a temp data root.
- It is not run through the engine (it would take hours).
- It is marked `DEMO · synthetic` in its name and document.
- The data root has no override today (§3.4a). Phase 2 therefore adds a product-only `AEGIS_DATA_ROOT` environment override, read in the same places that default to `DATA_ROOT/"data"/"aegis"`. The milestone walk then runs against a **scratch worker on port 8103** holding the fixture (`--base http://127.0.0.1:8103/aegis/`), and the fixture never enters `C:\Triad\data\aegis`.

## 10. Staged compute funnel

| Stage | What runs | Data | Engine / costs | Selection boundary |
|---|---|---|---|---|
| **1. Fast exploratory** | experiment trials (grid / LHS / refine / focused) | **selection partition only** | kernel, metrics-only, the spec's commission + slippage (already costed, F8) | Selects candidates by robust rank (§7.6), not by best point |
| **2. Focused refinement + cost stress** | materialize top-K robust candidates (K set per experiment, default 20) as full runs; re-run each under the cost scenarios | selection partition | full envelope with trades; cost scenarios as stage-2 rows | Candidates pass to stage 3 only if they hold under `slippage×1.5` (policy, Q6) |
| **3. Walk-forward folds** | Mission 8 study on the candidates: rolling windows inside the **selection + validation** span | folds | plateau / peak / frozen-centre rules per window | Fold metrics never feed back into stage 1's objective; a new stage-1 sweep after seeing folds is a new child, labelled `post-validation` |
| **4. Final untouched OOS** | one materialized run per finalist on the sealed final range | **final OOS** | full envelope | Only after `Unseal`: typed confirmation, append-only record, **single use per candidate set**; results cannot be re-tuned on |

**Leakage rules (scenario 13 tests):**
1. `partitions.bars_for(document, purpose)` is the **only** function that slices bars for Lab work. Purposes `stage1` and `screening` get the selection range; `stage3` gets selection plus validation; `final` gets the final range, and only with a valid unseal record whose candidate list contains the trial.
2. Warm-up for any later range uses prior history through the existing `evaluate_from` mechanism. Bars before the range are used for warm-up only, never scored.
3. A candidate is promoted only by an explicit operator action, recorded with `{from_stage, to_stage, trial_id, at}`. No code path auto-promotes.
4. **Repeated unsealing for a different candidate set is allowed but counted.** Each unseal increments `final_oos.uses`, the multiple-testing panel shows it, and once `uses > 1` every final-OOS number carries "re-used holdout".
5. Legacy experiments have no partition. Their views say "no partition: in-sample only", and stages 3–4 are unavailable for them until a partitioned child is created.

## 11. Phases

**Order:** UI shell and interactions first, then data wiring, then analytical extensions (brief Gate 2). Each phase ends with:
- its tests;
- `npm test` + `build`;
- `aegis_contracts --check`;
- lint;
- the new walk items;
- screenshots at 1672 × 941 and 1440 × 900, saved beside the walk report;
- a reviewer checkpoint (§16).

**Rollback:** every phase is one branch of additive commits, reverted by `git revert` of its merge.
- New documents and folders (`*.replays`, `*.final`, `searchspaces/`, `*.events.jsonl`, `*.views.json`, `cells/manifest.json`) are ignored by older code. Older code lists `experiments/*.json` only.
- A rollback therefore needs no data change. Layout-2 experiments created before a rollback become unreadable to layout-1 code only for their compacted parts; Phase 2 keeps a `--decompact` tool for that case (tested).

| Phase | Scope | Touched files (main) | Migrations | Dependencies | Tests (new) | Walk items |
|---|---|---|---|---|---|---|
| **0. Decisions and prerequisites** (no code) | Randall reviews A–H and this plan; answers §14; Mission 14 merged; brief copied into `docs/superpowers/specs/`; a repo-tracked lint script `tools/lint_aegis.sh` replacing the scratchpad one (Q9) | docs only | none | none | — | — |
| **1. Lab shell** | `optlab` page, sub-nav, Screen B layout with real regions bound to existing experiment endpoints (report main effects, cells page); dock `Expand Lab`; honest "not built" / "unavailable" states; `state/lab.tsx` store; keyboard model | `ui/src/App.tsx`, `SideNav.tsx`, `state/workspace.tsx` (Page), new `ui/src/lab/*` (`LabPage`, `LabContextBar`, `ParameterCatalog`, `TrialTable`, `IntelligenceRail`, `labStore.ts`), `OptimizationTab.tsx`, `styles.css` | none | none | vitest: `labStore` (selection, filter_hash, pins, persistence across sub-views), `trialWindow` (row windowing math) | 103 Lab opens from Expand Lab with axes / metric kept; 104 sub-nav keeps filter and selection; 105 every unavailable control says why; 106 1672 × 941 and 1440 × 900 with no clipped primary control |
| **2. Trial store and query layer** | layout 2 (trial_no, positions, param_key, status, compaction, manifest); `LabCache`; `/lab` summary / query / trials; views counts, matrix (exact + aggregate), page, top, marginals; optimizer source adapter; `engine_build`; benchmark script; dock `n` overlays and mode label; **2b (if Q2 = yes)**: lab metrics (Sharpe) beside, not inside, the hash-bearing metrics | new `app/products/aegis/lab/{__init__,store,cache,query,sources,policy,identity}.py`; `experiments.py` (layout 2 write, compaction, reader, chunk naming fix F16, `data_pinned`), `api.py` (router include), `runs.py` + `preferences.py` (`AEGIS_DATA_ROOT` override, §9.8), `pool.py` (2b only), `results.py` untouched; `ui/src/lab/LabHeatmap.tsx` (canvas), `Heatmap.tsx` (n overlay, hatch) | none (new layout only for new experiments; legacy untouched) | none | `test_lab_store.py` (compaction torn / idempotent; dedupe; legacy read equals today's `cells()`; `test_unreadable_chunk_never_overwritten`; data root override), `test_lab_query.py` (exact slice empty = untested; aggregate n / IQR; `test_lab_undefined_metric_counts`; `test_lab_query_empty_scope`; filter_hash; count invariants), vitest `labHeatmap` (empty, one-axis, losses-red scale), `test_lab_identity.py` (param_key canonicalization), `tests/products/aegis/lab_benchmark.py`; golden + identity unchanged | 107 exact slice with no match shows untested, no value; 108 aggregate square opens a distribution and cannot be pinned; 109 counts identical across heatmap, table and header |
| **3. Linked analytics** | parallel coords (bundles / sample), Pareto, importance + interactions with bootstrap intervals (Lab tasks), neighbourhoods, robust rank, convergence; Screens B tabs and E | `lab/{analytics,neighbours,pareto,parallel,tasks}.py`; `ui/src/lab/{ParallelCoords,ParetoView,ImportanceView,InteractionMatrix,PlateauView,Trellis,NeighbourhoodMap,ConvergenceChart}.tsx`; `ui/src/lab/charts/*` (canvas primitives) | none | none (§12) | `test_lab_analytics.py` (XOR fixture: S_i≈0, S_ij high; conditional triple; refinement rows excluded; interval coverage on a known-variance fixture), `test_lab_neighbours.py` (spike vs plateau; coverage gate), `test_lab_pareto.py` (2-D / 3-D against brute force); vitest for bundle drawing math, brush → filter mapping | 110 brush updates heatmap, table, Pareto and counts coherently; 111 spike vs plateau labelled; 112 20-variable fixture: families, search, trellis, maximize, count-preserving drill-down |
| **4. Screen H and 20 parameters** | `MAX_PARAMETERS` 10 → 20; identity beyond int64 (positions-based LHS / refine); structural relevance; statuses, events, proposals, apply → child; focus (pair investigation); stale detection | `surface.py` (cap, positions-based sampling), `experiments.py` (focus / child, reuse by `inputs_key`), new `lab/{structure,variables,searchspace}.py`; `ui/src/lab/{VariableIntelligence,InfluenceView,InteractionExplorer,ProposalPanel,EvidenceRail,SpaceContextBar}.tsx` | none (new docs `searchspaces/…`) | none | `test_lab_structure.py` (rules 1–4; active never excluded), `test_lab_variables.py` (transitions, reasons, restore, frozen ≠ excluded, stale on hash / data / range / partition), `test_lab_searchspace.py` (Cartesian before / after as Decimal; apply keeps strategy hash; reuse counted), `test_lab_grid_beyond_int64_keeps_trial_identity`; existing `test_aegis_surface.py` unchanged for ≤ 10 | 113 structural exclusion shows its proof trail; 114 XOR pair survives into Investigate; 115 restore and explore-any-pair in ≤ 2 interactions, filters kept; 116 budget labels "theoretical" |
| **5. Partitions, funnel and Run Monitor** | experiment partitions; `partitions.bars_for`; stage-2 replays with cost scenarios; per-trial failure isolation + retry-failed; `run_log`; Screen D; Screen C (compare three, materialize on demand); unseal (record only, final runs in stage 4) | `experiments.py`, `pool.py` (error isolation), new `lab/{partitions,replays,monitor}.py`; `ui/src/lab/{RunMonitor,FunnelStrip,CountsHeader,WorkerPanel,CandidateCompare,UnsealDialog}.tsx` | none (additive fields) | none | `test_lab_partitions.py` (screening refuses final; warm-up not scored; promotion only explicit; uses counted), `test_lab_replays.py` (cost scenarios; replay hash = materialize hash), `test_lab_failures.py` (failed trial isolated; retry idempotent; reconciliation invariants) | 117 four-stage funnel boundaries; 118 cancellation + resume + retry reconcile counts; 119 A/B/C ids and values identical in table, heatmap, parallel, charts and export |
| **6. Walk-forward, lineage and forensics** | Screen F on studies + partitions; Screen G lineage (React Flow), saved views, experiment diff, audit trail, provenance verification, trade evidence | `studies.py` (optional `candidates`), new `lab/{lineage,verify,events,views}.py`; `ui/src/lab/{WalkForwardView,FoldMatrix,LineageGraph,AuditTrail,ProvenancePanel,ExperimentDiff}.tsx` | none | none | `test_lab_lineage.py`, `test_lab_verify.py` (hash mismatch quarantines read-only), `test_lab_events.py` (append-only; reconstructed legacy) | 120 parent → child → trial → candidate with hashes and stable filters; 121 fold matrix, window × leg, sealed-OOS explanation |
| **7. Strategy Gate (only if Q1 = yes)** | deterministic research gate: policy JSON versioned; recompute metrics from raw trades of a materialized run; check `strategy_hash`, `inputs_key`, data sha; verdict + per-check evidence; `Send to Validation` | new `lab/gate.py` (or Core, see §12); UI `GatePanel` | none | none | `test_lab_gate.py` (recompute equals; tampered trade fails; strategy edit invalidates; AI route cannot write) | 122 validation blocked until gate checks; no AI override |
| **8. AI explanations (optional, after Mission 14)** | rail "AI explains · gate decides" via Mission 14's Core product-reasoning route; text only; never actor | Aegis caller only if the route fits as-is; **any Core change = shared infrastructure (§12)** | none | none | Aegis tests with a stub route | 123 AI text visibly separate; no state change from AI |
| **Milestone** | 1M synthetic dataset walk; verify.ps1 on main; independent milestone QA | — | — | — | scenario 11 / 12 timings recorded with the host | full walk |

### 11.1 Compatibility rules

- Legacy experiments open in the Lab through the same reader, with `trial_no = cell`, no partition and no statuses. Their analytics are identical to today's report for the same rows (test).
- Optimizer jobs open read-only through `opt:` sources. The dock's existing behaviour, ids and walk items 1–97 stay unchanged.
- `ExperimentDocument` gains optional fields only. `contracts.ts` regenerates (`test_aegis_contracts.py`).
- Run envelopes, `canonical_payload`, `strategy_hash`, the engine goldens, `builder_identity.py` and `study_identity.py` are unchanged in every phase.

## 12. Shared-infrastructure register and dependency reviews

Under `AGENTS.md`, no item in Phases 1–6 is shared infrastructure. All of it is under `app/products/aegis/`, its tests and its docs. The following items **would** be shared infrastructure; each needs the named Core tests and independent QA.

| Item | Why shared | If chosen: Core tests | QA |
|---|---|---|---|
| A Strategy Gate owned by Core (Q1 option b) | governance / contract that products consume | `TRIAD_PYTEST_SCOPE=core .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` over the new module + `tests/test_architecture.py` + `tests/test_product_*` isolation tests | independent QA + Core governance review |
| Any gate output read by a paper / live path | live-money / risk limits | n/a (excluded: Exchange CLOSED) | — |
| Any change to Mission 14's Core route for Phase 8 | provider authority / shared contract | `tests/test_core_product_reasoning*.py`, `tests/test_intelligence_routing.py` | independent QA |
| A new Python package (e.g. scipy, duckdb) | environment-level: both lock files + Core-owned `tests/test_environments.py:31,45-46` | `tests/test_environments.py`, `tests/test_pytest_scope.py`, `tools\verify.ps1` all scopes | measured blocker surfaced first |
| Changing what `result_hash` covers (e.g. Sharpe inside metrics) | retained canonical data | n/a (Aegis-owned), but treated as retained-data change | independent QA |
| Compacting or rewriting existing experiments | retained data | — | explicit operator approval + independent QA |
| Moving the store to a NAS | storage / provenance infrastructure | Core storage tests if Core is involved | operator decision |

**JS dependency candidates.** Not adopted; a review is required before use.

| Candidate | Purpose | Licence | Reason not now |
|---|---|---|---|
| `@tanstack/react-virtual` | table virtualization | MIT | a fixed-height window is ~60 lines; adopt only if variable row heights are needed |
| `uplot` | fast scatter / line | MIT | canvas primitives suffice at the bounded mark counts (§9.3) |
| `d3-scale`, `d3-array` | scales, bins | ISC | colour / bin math is small; d3-interpolate is already transitive |
| Plotly, ECharts, visx | full chart kits | MIT / Apache-2.0 | heavy, a second chart stack beside Vela; the brief forbids adopting Plotly for its references |

**Python candidates.** Rejected for now, with numbers.

| Candidate | Verdict |
|---|---|
| DuckDB | the in-memory pyarrow path meets every budget in §9.1 at 1M rows; revisit beyond 10M |
| scipy / statsmodels | the bootstrap covers the intervals needed |
| Optuna (TPE) | out of scope (§13) |

## 13. Scope exclusions

- **Strategy-structure search:** turning indicators or filters on and off, or changing dependencies. Brief §1: a separately versioned future capability.
- **Excluded trading and data work:**
  - new indicator kinds (HA-MQI, EWO, RocketRSI: Q3);
  - regime detection (Q4);
  - an event / news feed;
  - new data downloads or canonical data promotion.
- **Excluded samplers, models and claims:**
  - Bayesian or TPE samplers and surrogate models;
  - interpolation or smoothing of untested cells;
  - continuous (step-less) parameters;
  - probability-of-better-region-if-stopped claims.
- **Excluded infrastructure:** multi-machine workers; core-hour accounting beyond this host; signatures on audit records; multi-user authorship.
- **Live trading, paper trading, broker paths and any deployment eligibility.**
- **Rewriting existing data:** existing runs, optimizations or experiments; converting legacy experiments to layout 2.
- **Replacing Vela, the engine, the Strategy Lab builder or the experiment store.**

## 14. Open questions for Randall

Each one changes UI behaviour or calculation meaning.

| # | Question | Default if unanswered |
|---|---|---|
| Q1 | No Strategy Gate exists. Build one? (a) Aegis-owned research gate (Phase 7; product code; verdict = "passes research policy vN", no execution meaning), (b) Core-owned (shared contract, independent QA), (c) not now (UI says "not built") | (c) |
| Q2 | Sharpe: which definition? (a) daily mark-to-market returns, annualized √252, needs per-bar equity from the kernel (cost to be measured), (b) per-trade return ratio, labelled "trade Sharpe". Either is stored beside, not inside, hash-bearing metrics. DSR needs it too. | none: the objective stays the experiment's own metric |
| Q3 | HA-MQI / EWO / RocketRSI: a separate indicator mission (definitions, goldens) before or after Lab Phase 4? | after; the Lab uses existing kinds |
| Q4 | Regimes: define a deterministic regime classifier (e.g. trend / range by ADX-like rule, volatility tercile) as its own mission, or keep "not available"? | keep "not available" |
| Q5 | The dock's square was decided as "best of the rest only, no median view" on 2026-10-20. The brief asks min / median / mean / max. Reverse that decision for the dock? | Lab offers all four; dock keeps best-of-rest |
| Q6 | Approve the initial policy constants: `AGG_MIN_N 8`; TVD 0.25; `IMPORTANCE_ROWS 50k`; bootstrap 200; 90 % intervals; θ_main = θ_int = 0.01; pair coverage 0.5; residual veto 0.3; plateau coverage 0.5; budget split 30 / 48 / 22 + 5 % reserve; stage-2 K = 20; slippage×1.5 pass rule; the §9.6 latency / memory thresholds | as listed, all in `lab/policy.py` |
| Q7 | May Lab analytics run while an experiment job runs (sharing the laptop's CPU), or wait? | run, at lowest priority, one task at a time |
| Q8 | Visual acceptance width: the brief's 1672 × 941, the designs' 1440, or both? | both |
| Q9 | Commit a repo-tracked Aegis lint script (the current one lives in a past session's scratchpad and lints `C:\Triad`, not the worktree)? | yes, in Phase 0 |
| Q10 | Final OOS default: the last 20 % of the range by time (designs show 20 %), with selection 60 % / validation 20 %? | 60 / 20 / 20 by bars, trailing |
| Q11 | Storage: the 1M fixture and real 1M experiments need ~0.35 GB each on a 59 GB-free disk. Any cap, or the NAS first? | warn below 10 GB free |

## 15. Acceptance tests: the brief's 22 scenarios

Names are the test functions or walk items the phases add. "Phase" is where each is first green.

| # | Scenario | Proof | Phase |
|---|---|---|---|
| 1 | 30-SMA / 9-EMA crossover, small exhaustive grid, known selection, linked consistency | `test_lab_query::test_reference_crossover_grid_matches_optimizer` (Lab on `opt:` and on an experiment of the same grid give the same squares and best); walk 109 | 2 |
| 2 | Ten-variable sweep, sparse 400 and dense 10,000+, repeated axis / filter changes with exact counts | `test_lab_query::test_counts_stable_under_axis_and_filter_churn` (property test, 200 random filter / axis sequences on fixtures of 400 and 12,000 trials, existing kinds); walk 112 | 2–3 |
| 3 | Exact slice with no matching trials | `test_lab_query::test_exact_slice_empty_is_untested`; walk 107 | 2 |
| 4 | Aggregated cell, median and distribution, not executable | `test_lab_query::test_aggregate_square_stats`, vitest `labStore.aggregateNotPinnable`; walk 108 | 2 |
| 5 | Sharp best vs stable cluster | `test_lab_neighbours::test_spike_vs_plateau_ranked_apart`; walk 111 | 3 |
| 6 | Train vs OOS, distinct metrics, no leakage | `test_lab_partitions::test_stage1_reads_selection_only`, `test_objective_never_reads_final` | 5 |
| 7 | Long / short asymmetric parameters and event windows | `test_lab_query::test_scope_long_short_independent` (asymmetric fixture); `test_lab_query::test_unavailable_windows_not_neutral`; walk 121 | 2, 6 |
| 8 | A / B / C pins identical everywhere and in export | vitest `labStore.pinsCarryIds`; walk 119 compares ids / values / metric versions across table, heatmap, parallel, charts, export JSON | 5 |
| 9 | Duplicate / failed / partial trials, unavailable indicator data, broken metrics, cancellation | `test_lab_failures::*`, `test_lab_store::test_lab_compaction_torn_is_idempotent`, `test_lab_query::test_lab_undefined_metric_counts`; walk 118 | 2, 5 |
| 10 | Validation blocked until the gate; no AI override | Q1 (c): walk 105 shows "not built" and disabled controls; Q1 (a / b): `test_lab_gate::*`, walk 122 | 1 / 7 |
| 11 | 1M synthetic: server-side filter / sort / page, density, concurrent progress, memory ceiling, responsiveness, no million-node rendering, cold / warm timings and hardware | `tests/products/aegis/lab_benchmark.py` (records host + timings vs §9.6); milestone walk on `lab_fixture` (DOM rows ≤ 1,500, response bounds, long-task observer ≤ 50 ms) | 2, milestone |
| 12 | Million-trial status reconciliation, snapshots, resume, cancel, retry idempotency | `test_lab_failures::test_reconciliation_invariants` (fixture with every status), `test_retry_idempotent`; walk 118 | 5 |
| 13 | Four-stage funnel boundaries; leakage and improper promotion fail | `test_lab_partitions::test_promotion_only_explicit`, `test_final_requires_unseal`, `test_unseal_uses_counted`; walk 117 | 5 |
| 14 | 20 mixed variables: families, search, trellis, brushing, linked selection, maximize, count-preserving drill-down | `test_lab_query::test_drilldown_preserves_counts`; walk 112 on the 20-parameter fixture | 3–4 |
| 15 | Lineage and provenance: parent → child → trial → candidate, hashes, stable filters, trade log | `test_lab_lineage::*`, `test_lab_verify::*`; walk 120 | 6 |
| 16 | Walk-forward matrix, window × regime, long / short, sealed-OOS explanation, deterministic status | `test_lab_partitions::*` + study tests; walk 121 (regimes "not available" asserted) | 6 |
| 17 | Visual QA: readable labels, contrast, keyboard, nothing clipped at 1672 × 941 or narrower | walk 106 (bounding boxes inside viewport; computed contrast ≥ 4.5:1 for status and secondary text; keyboard path through every tab) | 1, each phase |
| 18 | Structural relevance: inert excluded with evidence; active never excluded by a wrong heuristic | `test_lab_structure::test_rule_{1..4}`, `test_signal_param_not_excluded`, `test_referenced_param_never_excluded` (property over random rule trees); walk 113 | 4 |
| 19 | Interaction trap (XOR) and conditional triple survive screening | `test_lab_analytics::test_xor_pair_kept_investigate`, `test_conditional_triple_unresolved_not_deprioritized`; walk 114 | 3–4 |
| 20 | Status transitions, evidence, restore, warnings, counts; excluded ≠ frozen | `test_lab_variables::*`; walk 115 | 4 |
| 21 | Search-space reduction budget recomputes; reduced space ≠ trials saved | `test_lab_searchspace::test_cartesian_before_after`, `test_labels_theoretical`; walk 116 | 4 |
| 22 | Scope / time stability: stale on change; final OOS never drives elimination | `test_lab_variables::test_variable_status_stale_on_strategy_hash_change` (+ data / range / partition), `test_lab_partitions::test_screening_refuses_final`, `test_post_unseal_proposal_blocked` | 4–5 |

Gate 3 parity:
- Lab metrics equal the trusted calculation: `materialize` identity (existing) on a sample of Lab trials per phase.
- Screenshots are compared to the UX Pilot output (side-by-side images in the walk report).

## 16. Reviewer checkpoints

| # | When | Who | Pass condition |
|---|---|---|---|
| R0 | Now | Codex (plan review) | Facts in §1/§3 verified against the repo; no unreviewed migration, engine replacement or gate authority change; open questions complete |
| R1 | Before any code | Randall | All eight UX views reviewed and aligned with the locked mock; §14 answered; **explicit approval** of this plan (revised as needed) |
| R2 | End of Phase 1 | Randall (screenshots, walk 103–106) | Shell matches approved designs; honest states; no clipped controls |
| R3 | End of Phase 2 | builder + Randall; Codex optional | §9.6 budgets met on the benchmark; legacy reads identical; goldens unchanged |
| R4 | End of Phase 4 | **independent QA recommended** (statistical claims) | Scenarios 18–22 green; statuses never change OOS use |
| R5 | End of Phase 5 | **independent QA** (leakage boundaries) | Scenario 13 tests fail on an injected leak (mutation check) |
| R6 | Phase 7 / 8, if chosen | **independent QA + Core governance** if Core-owned or Core-touching (§12) | Core tests named in §12 green |
| R7 | Milestone | independent milestone QA + whole-branch review; `tools\verify.ps1` on main | All 22 scenarios; full walk; budgets recorded with host details |

## 17. The brief's plan-review checklist

| Checklist item | Where answered |
|---|---|
| All eight views (A–H) reviewed and aligned with the locked screenshot | §2 (all exist, unreviewed); R1 |
| One-million-trial journeys from job start to validation | §5.4 D → §5.2 B → §5.5 E → §8 H → §10 funnel → §5.3 C → §5.6 F → §5.7 G; gate per Q1 |
| Measurable latency, memory and throughput criteria | §9.1 measured, §9.6 proposed thresholds |
| Vectorized exploration separated from costed replays and final validation | §10 (noting stage 1 is already costed, F8) |
| Variable selection evidence-backed, revisable, scope / version aware; any valid pair explorable | §7.3–7.5, §8 |
| Every UI box tied to a data source and a deterministic test | §5, §15 |
| No unreviewed migration, engine / chart replacement or Strategy Gate authority change | §11.1, §12, F1 |

PLAN REVIEW REQUIRED — DO NOT IMPLEMENT UNTIL RANDALL APPROVES.
