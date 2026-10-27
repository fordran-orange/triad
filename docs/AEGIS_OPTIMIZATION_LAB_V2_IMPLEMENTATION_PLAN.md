# Aegis Optimization Lab v2: Implementation Plan (Gate 1)

> **Status: PLAN ONLY.** This is for Codex review, then Randall's approval. No implementation is authorized. Nothing in this document was built. Revised the same day with Randall's answers to the open questions ("Operator decisions", below): the questions are closed, the hard stop is not. Revised again the same day for the MC Architecture Review's seven required revisions R1–R7 ("Architecture review revisions", below): §18 summarizes each change, §19 is the dependency review, §20 the added tests, §21 the residual risks and §22 the approval checklist. Codex's plan review (four rounds, approved; §18) is applied in place.
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

## Operator decisions (2026-10-27)

Randall answered the eleven open questions of §14 in this session, before Codex review. They are recorded here and applied through the plan; §14 keeps each question beside its answer.

| # | Decision |
|---|---|
| Q1 | No Strategy Gate now ("default"). The UI says `Strategy Gate: not built`; nothing in this plan builds a gate. |
| Q2 | Sharpe is **per trade** (§7.12), stored beside the hash-bearing metrics, never inside them. |
| Q3 | HA-MQI, EWO and RocketRSI come **after Phase 4**, each as an indicator kind, combined in a strategy (§11.2). |
| Q4 | Regimes become a **REGIME indicator** a strategy can add if desired (§11.2). |
| Q5 | Left to the builder's discretion: the dock keeps best-of-rest (the 2026-10-20 decision stands); the Lab offers best / median / mean / worst. |
| Q6 | The policy constants and the latency / memory budgets are approved as listed. |
| Q7 | Lab analytics may run while an experiment job runs. |
| Q8 | Visual acceptance at both 1672 × 941 and 1440 × 900. |
| Q9 | The Aegis lint script is committed to the repository (Phase 0). |
| Q10 | 60 / 20 / 20 selection / validation / final OOS, trailing by bars. |
| Q11 | Disk for now; test data can be deleted after use. |

Unchanged by these answers: the hard stop. Codex reviews this revision; implementation needs Randall's explicit approval after that review.

## Architecture review revisions (2026-10-27)

The MC Architecture Review (Randall Ford) accepted the plan as the architectural starting point and required seven revisions before approval. Each is applied in place; §18 summarizes them.

| # | Finding | Where applied |
|---|---|---|
| R1 | Statistical variable intelligence | §7.3, §7.4, §7.4a, §7.5, §8.4–8.7, §11 Phases 3–4, §15 rows 19, 23, 25, §20 |
| R2 | One-million-trial execution verification | §9 (Tracks A and B), §8.6, §11 Phase 2 and milestone, §15 row 24 |
| R3 | Robustness classification | §7.6, §5.2–5.6, §10, §15 rows 5, 26 |
| R4 | Final OOS workflow ownership | §5.3, §5.4, §5.6, §5.10, §6.5, §10.1–10.2, §11 Phases 5–6, §15 rows 13, 28 |
| R5 | Search budget arithmetic | §6.4, §8.5, §14 (Q6), §15 row 29 |
| R6 | Sharpe and DSR validation | §7.12, §13, §15 row 27 |
| R7 | UX implementation strategy | §5.8, §11 Phases 1 and 2c, §12 (charting criteria), §15 rows 17, 30, §16 R2.5 |

Two numbers approved under Q6 change as a result and need re-approval (§22): the budget split (30 / 45 / 20 / 5, R5) and the Lab task budget for importance analytics (≤ 180 s in total after Codex's round 1, R1). Nothing was implemented; the benchmarks of §9.1b were run read-only against the engine, writing only to a scratch folder.

## Global constraints

Every phase implicitly includes these.

**Product boundaries**
- Exchange stays CLOSED and live trading stays disabled.
- No broker, order, account or paper-trade path is touched. The designs' `TRADE` mode tab stays disabled.
- Strategy Gate authority is not changed. **There is no Strategy Gate in the repository today** (§1, finding F1). Randall decided on 2026-10-27 not to build one now (Q1): no phase of this plan builds a gate.
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
- Messages are written with the Write tool and committed with `git commit -F`, with the attribution trailer the session's instructions give (currently `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`).

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
| F1 | **No Strategy Gate exists.** Nothing in `app/products/aegis` or `app/trading_core` computes a gate verdict, validation status, sealed OOS or deployment eligibility. The only "gate" in the UI is `experiment-gate`, the "save or revert the document first" notice in `ExperimentsPage.tsx:109-118`. | Every gate panel, "Send to Validation", "NOT VALIDATED" badge and DSR threshold in screens A–C and F–H has no backend. Randall chose not to build one now (Q1): the UI says `Strategy Gate: not built`, never `pending`, and the gate's sketch stays in §12 for a later decision. |
| F2 | **HA-MQI, EWO and RocketRSI do not exist.** The indicator kinds are EMA, SMA, RSI, ATR, BB, DONCHIAN and MACD (`kinds.py:33-55`). The Mission 6 spec calls HA-MQI "undefined" (`docs/superpowers/specs/2026-10-12-aegis-experiments-design.md:395`). **Randall's thesis document (`C:\Users\fordr\Documents\HA_MQI_Trading_Framework_Thesis.docx`, received 2026-10-27) now defines all three**, with current settings and the trading framework around them (§11.2). | The "~10 HA-MQI variables" sweep cannot run yet, but its definition is no longer missing. The thesis is a **daily-chart** framework: ten years of 1D bars is ≈ 2,500 bars, the cheap end of §9.1b (≈ 190 trials / s). Scenarios 2, 14 and 19 use the existing kinds plus synthetic fixtures until the indicator mission Randall chose (Q3) lands after Phase 4: each as an indicator kind, combined in a reference strategy (§11.2). |
| F3 | **There is no Sharpe metric.** The metrics are `net_pnl, net_return, cagr, max_drawdown, mar, win_rate, expectancy, profit_factor, trade_count, exposure` × `combined/long/short` (`pool.py:22-34`). Every design ranks by Sharpe. Adding a key inside `backtest._metrics` (`backtest.py:992`) would change `canonical_payload` (`results.py:49-66`), so every new run's `result_hash` would differ from an identical old computation, and `materialize`'s identity check would fail. | Randall chose per-trade Sharpe (Q2): defined in §7.12, computed beside the metrics (never inside `_metrics`), stored as `<scope>.sharpe_trade`. The Lab's default objective stays the experiment's own; trade Sharpe is a selectable Lab metric, and DSR builds on it. |
| F4 | **No regimes, no event feed, no IS/validation/OOS partition on experiments.** Event windows are hand-supplied and ANALYZE-only (`temporal.py:1-7`). Experiments run on one range, and all data is `RAW ARCHIVE · NOT RESEARCH-ELIGIBLE` (`data.py:56`, `study_rules.py:45`). Walk-forward (Mission 4) and studies (Mission 8) do have IS/OOS windows. | FOMC/Earnings controls render as "feed unavailable", never as neutral (scenario 7). Regimes: Randall chose a REGIME indicator a strategy can add (Q4, §11.2); until a strategy carries it, regime controls say "not in this strategy". Phase 5 adds partitions. Phase 6 reuses studies for folds. |
| F5 | **The compact optimizer is a different machine.** It is a per-side grid of ≤ 100,000 cells held in one JSON document (`optimize.py:40-41`). Status sends the best 1,000 cells (`:43`). The matrix square is **best of the rest** (max), not an exact slice or a median (`optimize.py:232-333`). Its objectives are `net_pnl, mar, max_drawdown, trade_count`. Randall chose best-of-rest only on 2026-10-20 ("no median view"). | The dock keeps its job. It gains honest labels (`Aggregated: best of the rest`), an `n` overlay and `Expand Lab`. Q5 was left to the builder's discretion: the dock keeps best-of-rest (the 2026-10-20 decision stands), and the Lab offers best / median / mean / worst one click away. |
| F6 | **Experiments are the right base, with five scale limits:** `MAX_PARAMETERS = 10` (`surface.py:34`); `CHUNK_CELLS = 200` gives 5,000 Parquet files per million trials (`experiments.py:62`); `cells()`, `row()` and `done_cells()` read every chunk on every call (`experiments.py:277-306`); `analysis._columns` converts the whole table to Python lists (`analysis.py:36-47`); `GET /experiments/{id}/cells` re-reads all chunks per request (`api.py:964-988`). | Phase 2 replaces the read path (compaction plus a column cache), keeping the proven write path. Phase 4 lifts the parameter cap to 20 with an identity that survives int64 overflow. |
| F7 | **Compute is the binding constraint, not storage or queries.** Measured on the real engine through the real pool on real QQQ bars with a costed ten-parameter strategy (§9.1b): 188 trials / s steady at 2,603 bars, 83 at 9,669, 24 at 46,034 (ten workers); sustained over 100,000 trials at 2,603 bars: 89 / s. The worker's cost per trial is ≈ `27 ms + 0.0079 ms × bars`, not a constant per cell-bar, so the planner's linear rate mis-prices other bar counts by about 2×. | One million trials is ≈ 3.1 h at 2,603 bars (estimated from the sustained rate), ≈ 7.0 h at 9,669 and ≈ 24.3 h at 46,034: a coarse-timeframe or short-range proposition on this laptop (§9.1c), and the UI says so. |
| F8 | **Every stage-1 trial is already costed.** The kernel applies `commission_per_side` and `slippage_bps` (`backtest.py:435-462`, `strategy.py:426-431`). A trial is a complete metrics-only backtest without trades, markers or envelope. | The funnel's stage 1 is not "cost-unaware". Stage 2 is "full envelope plus cost stress". The UI must not call stage-1 rows "backtests" in counts (brief §3). |
| F9 | **The machine:** i7-1255U (10 cores / 12 threads, 2.6 GHz base); 15.8 GB RAM, with **2.5 GB free** while Core and the Aegis worker ran on 2026-10-27; Samsung NVMe SSD (238 GB), **59 GB free on C:**; `data/aegis/experiments` uses 9.8 MB. Randall noted on 2026-10-21 that "a NAS drive is going to be needed soon". | Memory budgets assume about 2 GB usable. The Lab holds projected columns only (§9.2). A 1M-trial experiment is about 0.3 GB on disk. |
| F10 | **Chart stack:** Vela 0.8.3 is a time-axis OHLCV chart only, with no heatmap or scatter primitive. Non-price charts are hand-written SVG paths (MainEffects, EquityTab, StudyReport, …). The heatmap is a DOM CSS grid (`Heatmap.tsx`). React Flow 12.12.0 is installed, and pulls d3-zoom/drag/selection/interpolate and zustand. No chart, scale, virtualization or table library is installed. | Lab charts are hand-built Canvas 2D renderers behind a small `lab/charts` boundary, with server-side aggregation (§12). React Flow is reused for the lineage graph (G). Virtualized rows are hand-written. Each alternative library is listed in §12 for a later decision. |
| F11 | **There are no statistics libraries.** scipy, scikit-learn, statsmodels, duckdb, polars, optuna and plotly are all absent. | All estimators are numpy over Arrow columns (§7), with seeded bootstrap intervals. TPE/Bayesian samplers (Screen D's "TPE + Sobol") are excluded (§13). |
| F12 | **Work in flight.** Mission 14 (`aegis/ai-reading`, 13 commits ahead of main) touches `ui/src/api/client.ts`, `ui/src/styles.css`, `preferences.py`, `phrases.py` and `tests/test_aegis_api.py`, and adds walk items 98–102 in an uncommitted edit in `C:\Triad`. | Phase 1 starts after Mission 14 merges, or rebases onto it. New walk items start at **103**. |
| F13 | **The designs are 1440 px wide.** UX Pilot A–H render at 1440 × 1024–1059. The baseline "Workstation" design is 1672 × 1024. The brief asks for 1672 × 941. The walk's viewport is 1600 × 1000 (`browser_workstation.py:4288`). | Visual acceptance runs at **1672 × 941** (the brief) and **1440 × 900** ("slightly narrower desktop"). Randall chose both widths (Q8). |
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
| Deterministic Strategy Gate that recomputes from raw trades | Absent (F1) | Q1 = not now; no gate in this plan |
| Sharpe, DSR | Absent (F3) | Q2 = per trade; Phase 2b (§7.12) |
| HA-MQI / EWO / RocketRSI, ~10 variables | Absent (F2) | Q3 = indicator mission after Phase 4 (§11.2); fixtures meanwhile |
| Regimes (Trend/Range/HiVol) | Absent | Q4 = REGIME indicator in that mission; "not in this strategy" meanwhile |
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
| Laptop compute | Budgets shown honestly; one million only at coarse bar counts (§9.6b); sustained rates, not burst rates, drive projections |
| A weak marginal effect read as irrelevance | Empirical evidence only deprioritizes, under six conditions (§7.4a); coverage gaps are `unresolved`; the research principle is printed on H |
| A reused holdout shown as fresh validation | `independent` only for the first unseal; `reused holdout` everywhere afterwards; append-only records (§10.1) |
| The linear cell-bar price misestimates other bar counts | The affine fit from Track B beside the planner's estimate (§8.6, §9.1b) |

## 4. Design items that are illustrative or infeasible, and what the product shows instead

| Design element | Product behaviour |
|---|---|
| Sharpe everywhere (A, B, C, E, F, H) | `sharpe_trade` (per trade, not annualized, §7.12) as a Lab metric; the default objective stays the experiment's own |
| HA-MQI / EWO / RocketRSI parameter names | The strategy's real parameter paths, grouped by indicator family (§5.2); those three kinds arrive with §11.2 |
| EURUSD / FX pips | The archive symbol and timeframe; slippage in bps, commission per side |
| "64 workers · 2 stalled · 1 lost", core-hours (D, G) | "N workers on this host"; per-chunk wall time; measured ms per cell-bar; CPU-hours computed as workers × wall time, labelled "on this host" |
| TPE + Sobol sampler (D, G) | "Grid / Latin hypercube + plateau refinement" with seed |
| Authors (R. Chen, A. Patel), "signed" audit trail (G) | Single operator; an append-only event log with timestamps; no signatures (§13) |
| `Interpolated est.` legend cell (B) | Never produced; the label is not shown (no interpolation in scope) |
| Gate panels, `Send to Validation`, `Promote for validation`, DSR thresholds | Not built (Q1): a disabled control labelled `Strategy Gate: not built`; DSR itself is shown as a number with its inputs (§7.12), never as a pass / fail |
| Regime selector, Regime × window grid (B, C, F) | "Regimes: not in this strategy" until the strategy carries the REGIME indicator (§11.2), then its values; the clock windows that exist; event columns "feed unavailable" |
| `TRADE` top tab | Present but disabled ("Exchange closed") |
| "Unseal & confirm once (type ID)" (F) | Phase 5: real, one-time, logged unseal of the final OOS partition for named candidates |
| Bayesian "surrogate fit failed for regime HiVol" (H) | No surrogate models; errors are the real query or job errors |
| "Robust" badges and "stable region" labels (B, C, E) | Four robustness categories with tested / unknown states and their inputs (§7.6); never a single score |
| An "independent OOS" after repeated unseals (F) | `independent final assessment` only for `use_no = 1`; `reused holdout` afterwards (§10.1) |

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
| Validation mini panel | — | `Validation: no partition (grid job)` until Phase 5; `Strategy Gate: not built` (Q1) | — | — | — |
| Trellis entry, convergence preview, Walk-Forward entry (§5 corrections) | — | `Trellis (k pairs) ↗` link; 120 × 28 px convergence sparkline (best-so-far by evaluation order); link to Walk-Forward tab | job cells (order) | click → Lab E / WF tab | E: < 10 cells "not enough cells for a trend" |
| `Expand Lab` | — | primary button → Lab page, `source=opt:<job_id>`, axes/metric/selection carried | — | click | — |
| Right rail | `StrategyPanel` | unchanged | — | — | — |

\* Q5 decided: the dock keeps best-of-rest, labelled; median, mean and worst live in the Lab (§7.2).

### 5.2 Screen B: Expanded Lab ("Trial Lab")

A new page `'optlab'` is added to `SideNav` as "Optimization Lab", between Experiments and Paper Trade. A left sub-nav carries: Run Monitor (D), Trial Lab (B), Parameter Families (E), Variable Intelligence (H), Walk-Forward (F), History & Lineage (G) and Compare (C).

| UX region | Planned component | Data source | Events | States |
|---|---|---|---|---|
| Context toolbar: strategy, experiment + parent breadcrumb, dataset, regime, window, direction (L / S / Both = scope), independent L/S eval, partition, objectives, run status | `LabContextBar` | experiment document; `GET /lab/{src}/summary` | scope / objective / partition change → store | Regime: "not in this strategy" until the strategy carries REGIME (§11.2). Event windows: "feed unavailable". Partition: "none" for legacy experiments |
| KPI strip: trials, coverage of valid space, best, median, robust regions, failed | `LabKpiStrip` | `summary.counts` + `summary.headline` | click count → sets filter | P |
| Parameter rail: search, families (indicator id per side, levels, side), X / Y / fix toggles, range sliders, presets | `ParameterCatalog` (collapsible, searchable; 20 rows fit) | `summary.parameters` (values, types, coverage per value) | set axis; fix value (exact slice); brush range; save preset | E: "no parameters" |
| Centre tabs: Heatmap · Interaction matrix · Parallel coords · Pareto · Importance · Robustness (A–D) | `LabHeatmap` (canvas), `InteractionMatrix`, `ParallelCoords`, `ParetoView`, `ImportanceView`, `RobustnessView` | `POST /lab/{src}/query` views `matrix`, `interactions`, `parallel`, `pareto`, `importance`, `neighbourhood` | cell click; brush; reorder axes; Maximize (Esc to restore) | per panel L/E/P/X; basis label always visible |
| Side mini views (Pareto, parallel, sensitivity) | the same components, `compact` prop | same queries, cached | click → opens that tab | — |
| Trials table: virtualized, filter chips, Pinned A B C, Columns, Compare pinned | `TrialTable` (windowed rows, 22 px, overscan 10) | query view `page` (sort, offset, limit ≤ 500) | sort, pin, select, column chooser, `Compare pinned` → C | E: "0 of N match: <filters>" |
| Intelligence rail: deterministic findings; AI block visibly separate (Phase 8); selected-trial card (`CandidateCard`: the four robustness categories with tested / unknown states, §7.6); risk warnings; tested neighbours; IS / OOS (Phase 5); next-sweep recommendation; `Queue focused follow-up sweep`; gate block; provenance + `Copy JSON` | `IntelligenceRail` | `summary.findings` (deterministic text), `neighbourhood`, experiment document | queue sweep → `POST /experiments/{id}/refine` (existing) or `/lab/{src}/focus` (Phase 4) | gate block: "not built" (Q1) |
| Status line | `StatusStrip` | job status | — | `Partial results: updates every 2 s` while running |

**Keyboard:** arrows move the heatmap cursor; Enter selects; `1`/`2`/`3` pin A/B/C; Esc clears the brush, then the maximize. Each tab is focusable, and table rows are reachable by arrow keys.

### 5.3 Screen C: Candidate Compare

| UX region | Planned component | Data source | States |
|---|---|---|---|
| A/B/C cards (tested only; the four robustness categories A–D with tested / unknown states and their inputs, §7.6; peak vs robust rank) | `CandidateCard` | `GET /lab/{src}/trials/{trial}` + query view `robustness` | E: "pin up to three tested trials" |
| Linked selection column (mini heatmap, parallel, Pareto, rows, `Show A on chart`) | compact Lab views; `Show on chart` → Charts page loads the materialized run | query + runs | — |
| Equity curves with IS / OOS divider | `CompareEquity` (SVG, as LibraryCompare) | stored 128-point curves when kept (≤ 20,000 planned), else materialize on demand (button, job) | P: "materializing A…" |
| All parameters (differences highlighted) | `ParamDiff` | trial rows | — |
| Drawdown, trade return distribution, costs & slippage, temporal windows | reuse `LibraryCompare` parts on materialized runs; costs from stage-2 rows | `GET /runs/{id}`, `GET /lab/{src}/replays` | E: "needs a full run: Materialize" |
| Regimes · trade Sharpe | `ScopeTable` by regime | the trades' `regime` tag when the strategy carries REGIME (§11.2) | E: "Regimes: not in this strategy" |
| Long vs short (independent) | `ScopeTable` | trial rows (long / short / combined) | — |
| IS vs OOS decay | `DecayTable` | Phase 5 partitions | E: "no partition on this experiment" |
| Final OOS (Phase 5) | `FinalOosPanel`: `sealed · 0 uses` · `unsealing` · `evaluated · use 1 · independent final assessment` · `evaluated · use n · reused holdout` (§10.1) | `GET /lab/{exp}/final-oos` | E: "no partition on this experiment" |
| Rail: findings, gate, `Queue focused follow-up sweep`, `Send to Validation` | `IntelligenceRail` | — | gate "not built" |

### 5.4 Screen D: Run Monitor

| UX region | Planned component | Data source | States |
|---|---|---|---|
| Header counts: search space, scheduled, completed, valid, unique, duplicate, failed (retried), filtered, displayed | `CountsHeader` | `summary.counts` (§6.4) | P |
| Search config: method, seed, parameters, families, budget | `SearchConfig` | experiment document | — |
| Budget strip: theoretical space · scheduled · completed · reused · remaining · reserved (§8.5) | `BudgetStrip` | `summary.counts` | shows `reconciles` or `does not reconcile` |
| Run versions (resumes, losses, pauses) | `RunSegments` | `document.run_log` (new, §6.2) | — |
| Snapshots | `SnapshotList` | `summary.snapshots` (manifest generations) | "browse while running" opens a frozen generation |
| Staged funnel 1–4 | `FunnelStrip` + `FinalOosPanel` | stage counts (§10) | stages not started: "not started"; final OOS: the `FinalOosPanel` states (§10.1) |
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
| Robust neighbourhood map for a pair | `NeighbourhoodMap` | view `matrix` (aggregate, median) + `n` + IQR; view `robustness` for the selected candidate | hatched = untested; ring = IQR above P75 of IQRs; the candidate's category A / B state printed with its coverage or n (§7.6) |
| Contributing-trials drill-down (server-indexed, stable tie-break) | `TrialTable` | view `page` | — |

### 5.6 Screen F: Walk-Forward & Robustness

| UX region | Planned component | Data source | States |
|---|---|---|---|
| Fold matrix (train / validation / test per fold) + sealed final OOS bar | `FoldMatrix` | `CandidateFoldsJob` results per (candidate, fold) (§10.3, Phase 6) + the experiment partition + `.final/` records (Phase 5); the Mission 8 study stays a separate "rolling re-selection" view | final OOS `sealed · 0 uses`, or `evaluated · use n` with its `independent` / `reused holdout` label |
| Data partitions panel; cost scenario Base / +50 % / ×2; leg Both / Long / Short | `PartitionPanel`, `CostScenario`, `LegToggle` | experiment partition; stage-2 replays | cost scenarios other than Base need stage 2 |
| Stitched fold equity vs selection backtest; fold metric distribution; fold-level metrics | reuse `StudyReport` charts + new `FoldDistribution` | study windows | — |
| Regime × window | `WindowGrid` | run temporal breakdown (`temporal` tags) | regimes unavailable; windows with n < 30 trades hatched |
| Neighbourhood persistence by fold | `PersistenceStrip` | study per-window plateau membership | — |
| OOS decay & multiple testing (decay, trials in selection, raw trade Sharpe with trade count, P&L, drawdown, exposure and consistency beside it, the DSR for the research-history cohort with its heuristic scenarios and every input, `annualized Sharpe: not computed`) | `MultipleTestingPanel` | `sharpe_trade` + DSR (§7.12) | E: fewer than 20 trades: "too few trades for a Sharpe"; `undefined` with its reason |
| Sealed final OOS: `Unseal & confirm once (type ID)`, which is the evaluation | `UnsealDialog` + `FinalOosPanel` | `POST /lab/{exp}/final-oos/unseal` (Phase 5: a durable submission that refuses a busy runner before any use, then queues the evaluation, §10.1) | irreversible; logged; `use_no ≥ 2` shows `reused holdout` |
| Robustness summary A–D per finalist | `CandidateCard` (compact) | query view `robustness` | unresolved categories named with their reason |
| Gate checks | — | — | "Strategy Gate: not built" (Q1) |

### 5.7 Screen G: History, Lineage & Forensics

| UX region | Planned component | Data source | States |
|---|---|---|---|
| Lineage graph: parent sweep → focused children → refinement → candidates | `LineageGraph` (React Flow, read-only, no edits) | experiments `parent`, `lineage.proposal_id`; studies `experiment_id`; runs `experiment_id` + `cell` | E: single node |
| Saved views (restore) | `SavedViews` | `experiments/<id>.views.json` (new, additive) | — |
| Side-by-side experiment diff (method, seed, budget, ranges, compute, engine, data hash) | `ExperimentDiff` | two documents | — |
| Audit trail (append-only events) | `AuditTrail` | `experiments/<id>.events.jsonl` (new) | legacy experiments: events derived from timestamps, labelled "reconstructed" |
| Trade-level evidence for a candidate | `TradesTab` reuse, virtualized | materialized run | E: "materialize to see trades" |
| Provenance with two named checks | `ProvenancePanel` | `POST /lab/{exp}/verify`: **artifact integrity** (re-hash each stored document against its additive `artifact_sha256`; legacy records say `artifact digest not recorded`), **computational reproducibility** (a pinned rerun recomputes `result_hash` and compares; the stored document alone cannot, `results.py:159`), `strategy_hash` from the pinned spec, the archive file against `sha256` | X: a digest mismatch → "artefact quarantined" (read-only flag, nothing deleted); a rerun mismatch → "not reproduced on engine build …", never a quarantine |
| Return without losing state | URL hash state + the store | — | — |
| `Promote for validation`, `Fork new focused sweep` | `Promote` disabled (no gate, Q1) / existing `refine` + Phase 4 `focus` | — | gate "not built" |

### 5.8 Screen H: Variable Intelligence

Mapped in §8.3, the Screen H contract.

**Sequencing (R7).** H is the upstream search-space intelligence view, and its complete workflow is visible from the first build: a `WorkflowStrip` across the top reads **Define variables → Run screening → Evaluate importance and interactions → Review search-space proposal → Approve large sweep → Monitor results**, each step lit by the experiment's state (defined / screened / evaluated / proposed / applied / running). In Phase 1 only the first step is live and the others are disabled with "available after Phase 4"; Phase 4 wires them. The strip never hides a step.

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
| `POST /lab/{src}/query` | `{filter, view, ...view args}`; view ∈ `counts, matrix, page, top, parallel, pareto, importance, interactions, triples, neighbourhood, robustness, marginals, convergence` | view-specific payload + `scope {space, valid, attempted, completed, unique, duplicates, invalid, failed, filtered, shown, basis, snapshot, provisional, sampled_from?}` |
| `GET /lab/{src}/trials/{trial}` | — | the full trial row + params + identity |
| `POST /lab/{exp}/retry-failed` | — | job id (Phase 5) |
| `POST /lab/{exp}/focus` | pair or region + budget | queued child experiment (Phase 4) |
| `GET/POST /lab/{exp}/searchspaces…` | proposal / apply | §8 (Phase 4) |
| `POST /lab/{exp}/final-oos/unseal` | `{candidates[], confirm: "<experiment id>"}` | the unseal record with `use_no`, `label` and the queued job id (Phase 5, §10.1) |
| `GET /lab/{exp}/final-oos` | — | every unseal record with status and results (Phase 5) |
| `PUT /lab/{exp}/budget` | `{shares, reason}` | the new split for unscheduled trials; refused unless paused (Phase 4, §8.5) |
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
- **`param_key`**: 16-byte BLAKE2b of the canonical `{path: value}` JSON over the **full effective parameter set of the pinned spec** (every tunable path, §8.1 `Defined`; paths outside the surface at their spec values; sorted keys, values rounded as `Parameter.values()` does). It identifies the same configuration across parent and child experiments and across changed surfaces (lineage, duplicates, reuse).
- **Evaluation identity** (§7.3a): `(trial_no, block)`, with `block = 0` the full selection range and `1..K` the screening blocks. Readers deduplicate by `(trial_no, block, attempt)`; every ordinary view filters `block = 0`.
- **`inputs_key`** (per experiment): BLAKE2b of `{strategy_hash, data identity (pinned sha256 + data_hash + range + timeframe), settings, engine_build, partition, blocks}`. Two evaluations are the **same computation** iff `inputs_key`, `param_key` and `block` are equal.

### 6.2 Experiment-level manifest (additive optional fields on `ExperimentDocument`)

| Field | Content |
|---|---|
| `cells_layout` | `1` (legacy chunks) or `2` (chunks + compacted parts + manifest) |
| `search_space` | `{version, hash, parameters:[{path, type: "int"|"float", start, stop, step, n_values, family, status, frozen_value?}], effective_dims, defined_dims}`. `version` increments per applied proposal; `hash` is over the parameters and statuses. |
| `sampler` | `{method: "grid"|"lhs+refine"|"focused"|"rescreen", seed, budget: {total, shares: {screening, interactions, refinement, reserve}}, first_pass, refinement, blocks: K, revision}` (today `plan` and `seed`; shares sum to 100, §8.5; `blocks`, §7.3) |
| `versions` | `{strategy_hash, spec_version, engine, engine_build, numba, numpy, pyarrow}`. `engine_build` = SHA-256 over the source of `kernel.py`, `backtest.py`, `indicators.py`, `kinds.py`, `strategy.py`, `temporal.py`, computed at worker start. |
| `data_pinned` | **new**: the `PinnedSource` the experiment ran on (`sha256`, `data_hash`, vintage, resampling policy, `bar_count`, `research_eligible:false`). Today experiments keep only the `DataReference` (F15). Legacy experiments show "data provenance not recorded". |
| `execution` | `{commission_per_side, slippage_bps}`, copied from the pinned spec for display (the spec stays the source) |
| `partition` | `{selection:{start,end}, validation:{kind:"folds", n, train_bars, test_bars}?, final_oos:{start,end, sealed:true, uses, records:[…]}?}` (Phase 5; the records are §6.5's unseal files) |
| `counts` | reconciled counts (§6.4), written at each commit |
| `run_log` | `[{segment, started_at, ended_at, status, trials_from, trials_to, workers}]`: resumes, pauses, losses |
| `lineage` | `{parent, root, proposal_id?, reason?, derived_from_report?, after_unseal?}` (`parent` exists today; `root` is the lineage's first experiment, itself when there is no parent; `after_unseal` is the ledger's `use_no` at creation, §10.1) |
| `holdout` | on the lineage root only: the append-only ledger `experiments/<root>.holdout/ledger.jsonl` that allocates `use_no` lineage-wide (§10.1) |

### 6.3 Trial row (stage 1, Parquet, layout 2)

| Column | Type | Notes |
|---|---|---|
| `trial_no` | int64 | identity |
| `cell` | int64, nullable | legacy-compatible index |
| `pos.<k>` | uint16 × d | coordinates |
| `<path>` | float64 × d | typed by `search_space.parameters[].type` |
| `param_key` | fixed_size_binary(16) | dedupe |
| `pass` | dictionary\<string\> | `grid`, `sample`, `refine`, `focused`, `rescreen`, `manual` |
| `design` | dictionary\<string\> | `uniform` (grid, Latin hypercube, uniform re-screen) or `adaptive` (refinement, focused, manual): the sampling design that §7.3 reads; `pass` is the workflow purpose |
| `block` | uint8 | `0` = the full selection range; `1..K` = a screening block (§7.3a); part of the evaluation identity |
| `reused_from` | struct, nullable | `{experiment, trial_no}` when copied by value from a parent (§8.5) |
| `status` | dictionary\<string\> | `ok`, `invalid` (skip reason), `failed` (error) |
| `valid` | bool | kept for compatibility (`status == ok`) |
| `skip_reason` / `error` | string | — |
| `attempt` | uint8 | retry count per `(trial_no, block)` |
| `<scope>.<metric>` | float64 × 30 | existing metrics, unchanged |
| `<scope>.sharpe_trade` | float64 | per-trade Sharpe (§7.12), computed in the pool beside the metrics, never inside `backtest._metrics`, so no `result_hash` moves |
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

### 6.4 Counts that must reconcile (scenarios 12, 21; R5)

```
space        = Grid.size                        (product of value counts; Decimal string if > 2^63)
valid        = Grid.valid_count                 (per-indicator validity tables, unchanged)
budget_total = the experiment's trial budget    (runs; or seconds priced into runs by the planner)
reserved     = reserve share × budget_total − reserve spent on focus / re-screen
scheduled    = len(planned trial_nos)           (configurations: first pass + refinement + focused + rescreen)
evaluations  = scheduled × (K + 1)              (engine evaluations; K = 0 without blocks)
remaining    = budget_total − reserved − scheduled        (≥ 0)
reused       = parent trials copied by param_key          (consume no budget; never scheduled)
attempted    = distinct trial_no with a canonical block-0 row
evaluations_done = distinct (trial_no, block) with status ok
completed    = attempted with status ok
invalid      = attempted with status invalid    (skip reasons)
failed       = attempted whose canonical attempt has status failed
pending      = scheduled − attempted
unique       = distinct param_key among completed
duplicates   = extra copies of the same (trial_no, block, attempt) dropped at read (torn compaction)
canonical    = one row per (trial_no, block): the highest attempt, after copies are collapsed (§7.3a)
filtered     = completed matching the filter
shown        = rows / marks actually sent for this view
```

**Invariants (tested):**
- `scheduled + remaining + reserved = budget_total`;
- `attempted + pending = scheduled`;
- `attempted = completed + invalid + failed`;
- `evaluations_done ≤ evaluations`; `completed ≤ evaluations_done`;
- `unique ≤ completed`; `filtered ≤ completed`; `shown ≤ filtered`;
- `reused` is reported beside, never inside, the child's `scheduled` or `completed` (its rows are flagged `reused` and excluded from the child's rate and timing);
- every view's `scope` repeats the same numbers for the same snapshot.

Stage counts (`stage2_replays`, `stage3_candidates`, `final_oos.uses`, `final_oos.evaluations`) are separate. A stage-1 count is never labelled "backtests".

### 6.5 Stage 2–4 records (R4)

- **Stage 2:** `experiments/<id>.replays/part-*.parquet`, one row per (trial_id, cost_scenario). It holds `run_id`, `result_hash`, metrics per scope, `temporal.<tag>.{trades,net_pnl,win_rate,expectancy}`, `trades.long/short`, and `created_at`. Cost scenarios are `base`, `slippage×1.5`, `slippage×2`, `commission×2`, defined in the experiment, not hard-coded per run. The `base` replay is the candidate's **identity run**: its `result_hash` is what later stages cite.
- **Stage 3:** existing study documents (Mission 8), with a new optional `candidates: [trial_id]` field.
- **Stage 4:** `experiments/<id>.final/unseal-<use_no>.json`, append-only, one per unseal:
  `{use_no, idempotency_key, holdout_id, at, confirm, candidates: [{trial_id, param_key, strategy_hash, spec_version, stage2_run_id, stage2_result_hash}], engine_build, data: {sha256, data_hash, final_range}, job_id, status: requested | queued | running | interrupted | done | failed, results: [{trial_id, run_id, result_hash, artifact_sha256, status, error?}]}`. The label (`independent` / `reused`) is derived from the lineage ledger at read time, never stored (§10.1).
  Each evaluated candidate is an ordinary run document under `runs/` with `experiment_id`, `trial_id`, `partition: "final_oos"` and `unseal_no`, so the Library, `Show on chart` and `verify` treat it like any run. The ledger `experiments/<root>.holdout/ledger.jsonl` allocates `use_no` lineage-wide and decides the label (§10.1).

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

### 7.3 Main effects and importance (Screen B/E Importance, Screen H overview; R1)

**Rows used.** Importance reads rows whose sampling **design** is uniform and whose search space is the current one: `design = uniform` (the `design` column of §6.3, set by the sampler, not by the workflow purpose: grid and Latin-hypercube first passes and uniform re-screens are `uniform`; refinement, focused and manual rows are `adaptive`), `search_space.hash` equal to the experiment's, and `block = 0` (the full selection range; §7.3 blocks below). Reused parent rows qualify only when their design was uniform *and* the parent's search space equals the current one, which a range change rules out. The panel prints "computed on n uniform trials of N; adaptive rows excluded".

**What importance is here.** On the discrete grid, a scope's metric Y decomposes as `Var(Y) = Σ_i V_i + Σ_{i<j} V_ij + Σ_{i<j<k} V_ijk + …` (the ANOVA / Sobol decomposition, exact for an orthogonal design). The Lab estimates it twice, for two purposes:
- **Fine-grid estimates, for display and ranking:** `S_i = Var_b(E[Y | X_i = b]) / Var(Y)` over the observed values b, count-weighted, with the finite-bin correction `S_i_adj = max(0, S_i − (B_i − 1) / (N − B_i) · (1 − S_i))` (adjusted η²; `B_i` observed values, `N` uniform rows). Pairs likewise (§7.4). These are the most sensitive estimates and drive the ranked lists.
- **One coarse decomposition, for the deprioritization rule and the residual:** every parameter is binned into `q = 4` quantile bins; mains, all pairs and all triples are estimated on that one grid by `bincount` over group keys, so they form a single decomposition whose residual is meaningful **only when the inputs are mutually independent**. Pairwise checks cannot establish that (three independent bits and `x₄ = x₁ XOR x₂ XOR x₃` are pairwise independent and give `R = −1`), so availability is decided by **provenance, not statistics**: the rows must come from a sampler that draws each axis independently over the **full Cartesian grid** (grid or Latin hypercube with no validity rejections: `Grid.skipped_count == 0`), no filter may be applied (importance always runs on the unfiltered uniform rows and says "ignores the active filter"), the rows must be `design = uniform` of the current `search_space.hash`, and no active pair may be `aliased`. A surface with validity constraints (skipped cells) makes the rule `unavailable: inputs are not a product design (x % of the grid is invalid)`, with the hint to freeze or narrow the constrained ranges; the fine-grid estimates, the ranked lists and `Investigate` still work. The **analysis cohort** must be a product design too: an unconstrained sampler does not help if rows are then dropped because an evaluation failed or the chosen metric is undefined (`profit_factor` without losses, `mar` under a year, `sharpe_trade` with one trade; today's analytics drop such rows, `analysis.py:213`), because outcome-dependent omission re-introduces dependence between the inputs. The rule is therefore available only when **every** uniform configuration of the current space has a valid, finite observation of the chosen metric in block 0 and in every required block (missingness = 0); otherwise `unavailable: n of N configurations have no finite <metric> (k invalid, m failed, u undefined)`, with the counts and reasons printed and the hint to choose a metric defined everywhere (`net_pnl`, `max_drawdown`, `trade_count`, `exposure`) or to retry the failed trials. The descriptive fine-grid estimates stay available on the rows that exist, labelled "on n of N configurations; missingness may bias". As a last sanity check, a residual whose upper bound is below `−0.05` also makes the rule unavailable (`unavailable: decomposition inconsistent`).

- **Three uncertainties, always shown together:**
  1. **Design uncertainty** (which parameter sets happened to be tried): a seeded bootstrap over rows, `B = 200` resamples on at most `IMPORTANCE_ROWS = 50,000` rows (a seeded subsample, stated), 90 % percentile interval, for the fine-grid mains and pairs. Every trial saw the same bars, so this interval is *conditional on this market history* and says nothing about other periods; its label reads `interval: sampling of trials, this data`.
  2. **Period uncertainty** (which market periods): a screening experiment carries `blocks = K` (default `SCREEN_BLOCKS = 4` contiguous, equal-bar blocks of the selection partition). Each sampled configuration is evaluated on the full selection range *and* on each block (§7.3a): `K + 1` evaluations per configuration, priced by the planner, with warm-up from prior history and scoring only inside the block (§10.2 rule 2, implemented by §7.3a). `S_i` is computed per block **with its own bootstrap interval** (mains only, `B = 200` per block, a few milliseconds each), because §7.4a's condition 1 reads per-block upper bounds; the panel shows the block range `[min, max]` of the point estimates beside the full-range estimate. A share that is large in one block and near zero in the others is `period-dependent` and never below `Investigate` (scenario 23, case 8).
  3. **Detection floor** (finite-sample bias): a seeded permutation null (`P = 200` shuffles of Y over the same rows for mains and pairs; `P = 50` for the coarse decomposition) gives the 95th percentile of each share under no effect at this `N` and `B_i`. `Detected` means the point estimate exceeds the floor. It is a detection threshold, not a practical-significance threshold.
- **Labels:** `Measured` when `n_uniform ≥ IMPORTANCE_MIN_N = 30 × B_i` *and* every value of i has at least `IMPORTANCE_MIN_PER_VALUE = 20` rows; otherwise `Insufficient coverage`, which is **unresolved**: excluded from the ranking, shown last with its coverage, and never able to support `Deprioritized` (scenario 25).
- **Correlation check:** Cramér's V between every pair of active parameters over the uniform rows (LHS is near 0; validity tables such as MACD `slow > length`, dedupe and reuse can correlate inputs). A pair with `V > 0.3` is `aliased`: both parameters carry `credit shared with <other>`, and **while any active pair is aliased the coarse decomposition is not orthogonal, so empirical deprioritization is unavailable for the whole experiment** (scenario 23, case 4; §20 case 10).
- **Caveat text, always:** "conditional on these ranges, this data, this sampler and this partition; a share is evidence about where exploration pays, not proof that a parameter is irrelevant".
- **Not used:** permutation importance on a fitted model (no surrogate, §13).

### 7.3a Evaluation identity, blocks and the scoring mask

- **Configuration vs evaluation.** A configuration is identified by `trial_no` (and `param_key`, §6.1). An evaluation is identified by `(trial_no, block)`, `block = 0` for the full selection range and `1..K` for a screening block. Readers canonicalize in two steps: first collapse duplicate **copies** of the same `(trial_no, block, attempt)` (torn compaction, overlapping files: these alone are `duplicates`), then select the **canonical attempt** per `(trial_no, block)`, the highest `attempt`; every status and count is computed from that canonical table, so a failed attempt followed by a successful retry is one `ok` evaluation (`test_canonical_attempt_after_retry_across_compacted_files`). Block evaluations and reused rows are never duplicates; every ordinary view (ranking, heatmaps, Pareto, neighbourhoods, counts, materialize) filters `block = 0` by default and says so; blocks feed only the period-uncertainty computations and category C of §7.6. The budget counts **configurations**; the planner prices and the Run Monitor shows **evaluations = configurations × (K + 1)** beside it (§6.4).
- **Warm-up without scoring.** Today the pool's `window` argument slices the frame and the metrics path scores every bar (`pool.py:142-154`, `backtest.py:876-885`, the all-true evaluating mask). Block evaluation therefore needs one metrics-path change: `run_metrics(..., evaluate_from=None)` and `_side_metrics` accept an optional `evaluate_from` timestamp and build the kernel's `evaluating` mask from it, exactly as the full engine does for walk-forward (`settings.evaluate_from`); `pool._run_cell` passes the block's start as `evaluate_from` and the frame **with prior history** (never a cold slice). With `evaluate_from=None` the paths are byte-identical to today, pinned by the goldens.
- **Parity tests (Phase 3):** `test_block_metrics_equal_full_engine_with_evaluate_from` (each block row's metrics equal `run_backtest` of the same configuration on the same bars with `settings.evaluate_from` set) and `test_warmup_contributes_no_trades_or_equity` (no trade and no scored equity point before the block start). Identity tests: one configuration across its `K + 1` evaluations survives compaction, resume, retry, materialization (block 0) and reconciliation (`test_configuration_identity_across_blocks`).

### 7.4 Interaction screening: pairs, triples and the higher-order residual (R1)

- **Pairs (all `d(d−1)/2`, 190 at d = 20)**, fine grid, uniform rows: the **joint share** `J_ij = Var(E[Y | X_i, X_j]) / Var(Y)` (bias-adjusted as above) and the **incremental share** `Δ_{i|j} = J_ij − S_j`, what adding i explains beyond j. The interaction term `I_ij = J_ij − S_i − S_j` is shown but is only an estimate: under correlated inputs or imbalance it can go negative or share credit, so **no rule reads `I_ij`; the rules read `Δ`**, which is non-negative in expectation and robust to credit sharing.
  - Coverage = the share of the pair's value grid with ≥ `PAIR_MIN_N = 4` rows; balance = the TVD of the pair's joint value distribution from uniform, flagged above `0.25`. Coverage < `PAIR_MIN_COVERAGE = 0.5` makes the pair `unresolved`: listed separately, sorted by `max(S_i upper, S_j upper)` then by lowest coverage.
  - Intervals and the detection floor as in §7.3. One pass over 20 mains and 190 pairs on 50k rows is 61 ms (measured, §9.1a), so bootstrap plus null is ≈ 25 s as a Lab task.
- **The coarse decomposition (q = 4):** one pass computes the coarse mains, all 190 coarse pairs and all 1,140 coarse triples (64 cells per triple, ≈ 780 rows per cell at 50k rows, `bincount` over group keys: ≈ 1.2 s measured scale, §9.4). From it: the coarse shares `S_i^c`, `J_ij^c`, `J_ijk^c`, the three directional increments of every triple, `Δ_{i|jk}^c = J_ijk^c − J_jk^c` and the two others (each variable's proposal reads only its own direction, §7.4a), and the **residual** `R = 1 − Σ S_i^c − Σ I_ij^c − Σ I_ijk^c`, where the coarse interaction terms are the usual differences on the same grid. Triples are ranked by `Δ^c` for display (top `TRIPLE_TOP = 20` with intervals). Coarsening averages within bins, so it can miss structure that cancels inside a bin; such structure then appears in `R`, which is why `R` is a veto (below) and why the fine-grid estimates must *also* pass the rule.
- **Intervals for the rule:** `B_c = 50` bootstrap resamples of the coarse decomposition give 90 % intervals for `R` and for the coarse shares of **candidate variables only** (those passing conditions 1 and 2 of §7.4a on point estimates): for each candidate i, all 171 triples containing it, all three increments. That bounds the cost (§9.4) and still gives every triple containing a candidate an upper bound.
- **Higher orders:** no estimator. `R` mixes unexplained higher-order structure, within-bin cancellation, finite-sample bias and grid roughness, so it is shown as `unexplained share` with its interval and **is a veto, never evidence**: when its lower bound exceeds `RESIDUAL_VETO = 0.3`, no `Deprioritized` proposal is made for any parameter ("structure not captured by mains, pairs and triples: deprioritization unsafe").
- **Threshold:** `θ_min = 0.01` is a practical-significance floor applied to *upper bounds*; detection uses the permutation floor. Both are policy constants (Q6) and are printed on the panel.

### 7.4a Empirical deprioritization: the only empirical proposal (R1)

Empirical evidence never excludes. It can only **propose `Deprioritized`**, which reallocates exploratory trials (fewer levels through the planner's `coarsen` lever, or a smaller budget share, §8.5) and leaves the dimension in the search. The proposal exists only when the coarse decomposition is **available** (§7.3: a product design over the full grid, unfiltered uniform rows of the current space with a finite observation of the chosen metric for every configuration in every required block, no aliased pair, a consistent residual); otherwise the panel shows `empirical deprioritization unavailable: <reason>` and nothing is proposed. A proposal for parameter i then requires **all** of:
1. `S_i upper < θ_min` (fine grid) and `S_i^c upper < θ_min` (coarse), on block 0 and in every block;
2. for every other parameter j, the pair (i, j) is `Measured` (coverage ≥ 0.5, balanced) and both `Δ_{i|j} upper < θ_min` (fine) and `Δ_{i|j}^c upper < θ_min` (coarse);
3. for every triple (i, j, k) containing i, **i's own** coarse increment `Δ_{i|jk}^c` has an interval and `Δ_{i|jk}^c upper < θ_min` (the other two directions are computed for display and for j's and k's own proposals, never for i's: an important j in the triple does not block an irrelevant i); **an unresolved triple blocks the proposal** (the reason names the triple);
4. no `aliased` flag anywhere among the active parameters (the decomposition is orthogonal);
5. the residual veto is not raised;
6. the operator confirms, with conditions 1–5 and their values attached as the evidence (§8.4).

If any condition fails, the status is `Investigate` with the failing condition as the reason, or stays `Active`. Insufficient coverage anywhere in 1–3 is "unresolved", never "low" (scenario 25). A `Deprioritized` status is reversible in one click, scoped to `{strategy_hash, data identity, ranges, partition, sampler, blocks, search_space.hash, snapshot}`, and goes `stale` when any of those changes (§8.5); evidence from one range is never applied to another (scenario 23, case 9).

**Research principle (printed on Screen H):** the Lab chooses where to spend exploratory trials; it never declares a parameter irrelevant because its marginal effect is weak.

### 7.5 Investigating a pair or a triple (targeted experiment)

`Investigate pair (i, j)` or `Investigate triple (i, j, k)` → `POST /lab/{exp}/focus` creates a **child experiment** (lineage `parent`, `reason`, `pass = focused`, `design = adaptive`):
- the full value grid of the chosen parameters;
- every other active parameter sampled by LHS, so the effect is marginalized, not conditioned on one point;
- a budget the operator chooses, priced by the existing planner and drawn from the reserve share first (§8.5).

`Conditional` mode (others fixed at the selected plateau centre) is the second option and is labelled conditional. Any valid pair or triple can be investigated at any time through the manual picker, whatever its screening rank; the picker never hides a valid pair (scenario 20). A **re-screen** (`pass = rescreen`, `design = uniform`) is a fresh Latin-hypercube sample over the current space; its rows are eligible for importance under §7.3, so stale evidence can be refreshed (`test_stale_then_rescreen_refreshes_evidence`).

### 7.6 Robustness: four evidence categories (R3)

Robustness is not one number. Every candidate (a tested trial) carries four categories, each either `resolved` with a classification or `unresolved` with the reason. A candidate card shows all four, says which were tested and which remain unknown, and never sums them (scenario 26). τ is the experiment's existing tolerance band, `tolerance × (P90 − P10)` of the metric, as `analysis.plateaus` uses it. Categories C and D compare **per-unit-time statistics with their orientation** and never use metrics that can be undefined on short ranges (`cagr`, `mar`): net P&L per 1,000 bars, trades per 1,000 bars, expectancy per trade, and max drawdown (a fraction of equity).

| Category | Evidence | Resolved when | Classification | Unresolved reason |
|---|---|---|---|---|
| **A. Local parameter robustness** | tested trials whose positions differ from t's by ≤ `r` steps in ≤ `m` parameters (defaults r = 1, m = 1 on grids; m = 2 on sampled surfaces), found by hashing positions (≤ 840 probes at d = 20, m = 2; never O(n²)) | coverage = tested / valid in that neighbourhood ≥ `PLATEAU_MIN_COVERAGE = 0.5` **and** n ≥ `min(2d + 1, |valid neighbourhood|)`, so a fully tested grid corner resolves | `stable local` when the neighbourhood P25 is within τ of t's value; `isolated peak` when t's value > neighbourhood P75 + 3 × IQR; else `mixed` | `untested surroundings (coverage c of 0.5)`: an untested neighbourhood is never called a peak and never called stable |
| **B. Sampled-region robustness** | the sampled trials within a normalized L∞ radius `REGION_RADIUS = 0.15` of the axis range on the `REGION_AXES ≤ 6` most important axes (§7.3), other axes marginalized | n ≥ `REGION_MIN_N = 30` in the region | `stable region` / `unstable region` by the region P25 against τ; the region's trial density relative to the experiment's mean density is printed, so sparseness is visible | `too few sampled trials in the region (n of 30)` |
| **C. Temporal robustness** | validation folds from stage 3 (§10.3) as the evidence; the screening blocks of §7.3a only as labelled selection-period diagnostics | ≥ 3 validation folds, each with ≥ 30 trades and a defined net P&L (blocks alone leave C `unresolved · selection-period only`) | when the full-range net P&L per 1,000 bars is > 0: `consistent` when **every validation fold** has a positive net P&L per 1,000 bars within `[0.5×, 2×]` of it and max drawdown ≤ 1.5 × the full range's, else `inconsistent`; when the full-range figure is ≤ 0: resolved as `not profitable on the full range` (no ratio is formed). Screening blocks never enter this predicate: they produce a separate, informational finding `selection-period consistency` with the same arithmetic, shown beside C and never changing it | `no blocks or folds` / `too few trades per fold` |
| **D. Execution robustness** | stage-2 replays under the cost scenarios (§10) | the `base` replay and `slippage×1.5` exist with defined net P&L | when base net P&L > 0: `holds` (stressed net P&L > 0 and ≥ 70 % of base, and max drawdown ≤ 1.3 × base), `degrades` (> 0 but below that), `fails` (≤ 0); when base net P&L ≤ 0: resolved as `not profitable at base` (no ratio is formed) | `no replay yet (stage 2)` |

Rules:
- **B is never reported as A.** The labels differ, the card names the radius and n, and a sparse-surface candidate whose A is unresolved says so beside its B result.
- **Isolated peak vs stable region** is decided only with coverage (A) or n (B); otherwise the state is `unresolved`, which ranks below any resolved state and is shown with its reason.
- **Two rankings, side by side** (scenario 5): `peak` (the metric alone) and `robust` (lexicographic over resolved categories: A, or B where A is unresolved and labelled so; then C; then D; unresolved categories sort last and never count). When the two disagree the rail says so and names the stable candidate; the operator chooses.
- **Explanations.** Every classification is rendered with its inputs (n, coverage, P25, P75, IQR, τ, radius, density, the per-1,000-bar figures per block, scenarios), so the operator sees why a candidate received it.
- **Tests (Phase 3 for the rules on fixtures, Phase 6 on real folds):** constant performance per unit time across validation folds of different lengths is `consistent`; blocks alone leave C `unresolved · selection-period only` while producing the diagnostic finding; changing the diagnostic blocks' results cannot change C when the fold evidence is unchanged; a negative and a zero full-range baseline resolve as `not profitable` without forming a ratio; a fully tested grid corner resolves A; sub-year cost replays resolve D without MAR; a negative base replay resolves D as `not profitable at base`; a sparse surface never reports A.
- **Plateaus over a whole experiment** (reports, Run Monitor regions) use the existing `analysis.peaks/plateaus` on the uniform subsample (≤ 50,000) with the hashed neighbour relation, labelled with the subsample and the rule.

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

### 7.12 Trade Sharpe and the deflated Sharpe ratio (Q2: per trade; R6)

**Two Sharpe ratios exist, and the Lab names which one it shows.**
- **Time-series Sharpe** (annualized): mean / std of periodic mark-to-market returns × √(periods per year). It is the comparable one and the one the literature's thresholds refer to. It needs per-bar equity from the kernel on every trial and is **not built** (Q2 chose per trade); where a design shows one, the label is `annualized Sharpe: not computed`.
- **Trade Sharpe** (`sharpe_trade`, per scope): `mean(ret) / std(ret, ddof = 1)` over the scope's trade returns `ret = net / capital_at_entry`, which both engines already write per trade (`kernel.py:188, 266`; `backtest.py:455, 463`); `combined` concatenates both sides' trades (mean and std are order-free). Null with fewer than 2 trades or zero variance; flagged `low n` below `SHARPE_MIN_TRADES = 20`. **It is not annualized and not comparable across strategies with different trade frequencies or holding periods**: a 50-trade and a 2,000-trade strategy with the same `sharpe_trade` have very different time-series Sharpes. The label reads `trade Sharpe · per trade · not annualized`, and the trade frequency (trades per 1,000 bars) is printed beside it.
- **Beside it, always:** net P&L, max drawdown, trade count, exposure and the temporal consistency of category C (§7.6). No candidate table or card shows `sharpe_trade` without those five (scenario 27), and the default sort of every candidate view stays the experiment's own objective.
- **Where it is computed and what it costs:** in the pool worker beside `run_metrics`, from the kernel's trade array column 9 (`trades[:n_trades, 9]`, a zero-copy view of a buffer that already exists) and from `net_pnl / capital_at_entry` on the reference path, returned as a separate `lab_metrics` dict per scope. It is never added to `backtest._metrics` or `_metrics_arrays`, so `canonical_payload` and every `result_hash` stay as they are. Measured (§9.1b, "Sharpe overhead"): a vector mean and std per scope, three per trial, against ≈ 48 ms per trial; three extra floats per row. It stays in stage 1; no deferral is needed. The one engine-adjacent change is that `backtest._side_metrics` returns the `ret` view beside the lite trades (an added return value; its existing outputs are unchanged, pinned by the goldens). For saved runs the Lab computes `sharpe_trade` on read from the stored trades.

**Deflated Sharpe ratio** (Bailey and López de Prado, 2014, *The Deflated Sharpe Ratio: correcting for selection bias, backtest overfitting and non-normality*), for Screen F's multiple-testing panel, validated independently in Phase 2b:
- `PSR(SR₀) = Φ( (SR − SR₀) · √(T − 1) / √(1 − γ₃·SR + ((γ₄ − 1) / 4)·SR²) )`, where `SR` is the candidate's `sharpe_trade` (per trade; the same units throughout), `T` its trade count, `γ₃` the skewness and `γ₄` the kurtosis (non-excess, 3 for a normal) of its `ret`, both as plain moment ratios `m₃ / m₂^{3/2}` and `m₄ / m₂²`.
- `SR₀ = √V · ((1 − γ) · Φ⁻¹(1 − 1/N) + γ · Φ⁻¹(1 − 1/(N·e)))`, γ the Euler–Mascheroni constant; `N` the number of trials in the cohort and `V` the **sample variance (ddof = 1) of the trials' `sharpe_trade` estimates** across that cohort, in the same per-trade units, as the paper defines them (its equations 1–2).
- `DSR = PSR(SR₀)`. It is `undefined`, with the reason printed, when T < 2, the cohort has fewer than 2 members, the variance of `ret` is zero, the denominator is ≤ 0, or any input is not finite.
- **The cohort.** `N` and `V` are computed over the **research history**: the unique configurations (distinct `param_key`) with a defined `sharpe_trade` (T ≥ 2) across the experiment and every ancestor and descendant with the same `strategy_hash` and data identity, counted per experiment and printed ("N = 48,210 across 3 sweeps"). Duplicates, invalid and failed trials are not members. This is the number the paper calls N, and it is the headline.
- **Two sensitivity scenarios, labelled heuristic:** the panel also shows DSR with `N` and `V` taken over (a) the medoid trials of the outcome clusters of `analysis.py` (k by its existing rule) and (b) the centre trials of the plateaus of §7.6. Each is printed as "heuristic scenario: if only the k clusters / m regions counted as distinct strategies". They are **not bounds and not ordered**: the paper does not define these cohorts, and changing the cohort changes V as well as N, so a smaller N need not give a higher DSR. A scenario with fewer than 2 members is `undefined`.
- **Independence is assumed twice, and both assumptions are printed:** (1) across trials: parameter sets are correlated, so N overstates the number of independent strategies; (2) within a trial: trade returns overlap market exposure, so `√(T − 1)` can overstate the evidence. The panel shows the lag-1 autocorrelation of the candidate's `ret` and flags `|ρ₁| > 0.2` as `trades autocorrelated: evidence overstated`.
- `Φ` is `math.erfc`-based; `Φ⁻¹` is Acklam's rational approximation **refined by one Newton step on `math.erfc`** (no scipy), which brings the error to the floating-point floor; the tests check 1e-12 against an independent bisection and against published quantiles.
- **DSR is a number with its inputs (SR, SR₀, T, N, V, γ₃, γ₄, ρ₁, the cohort), never a pass / fail, never "validated", never deployment eligibility** (Q1). Panel text: "a deflated Sharpe near 1 means the best-of-N result is unlikely under no skill, given these assumptions; it is not evidence of profitability out of sample".

**Reference tests (Phase 2b, `test_lab_sharpe.py`), each against values computed independently in the test file, never by calling the implementation's formula:**

| Case | Expected |
|---|---|
| normal returns with known mean and std, T = 500 | `sharpe_trade` within 1e-12 of the hand formula; γ₃ ≈ 0, γ₄ ≈ 3; `PSR(0) = Φ(SR·√(T−1) / √(1 + SR²/2))` within 1e-9, Φ from the test's own `erfc` |
| published quantiles | `Φ⁻¹(0.975) = 1.959963984540054`, `Φ⁻¹(0.99) = 2.3263478740408408`, `Φ⁻¹(0.999) = 3.090232306167813`, `Φ⁻¹(0.5) = 0`, each within 1e-12; the bisection on `erfc` agrees over p ∈ [1e-9, 1 − 1e-9] |
| the paper's worked example | the DSR of the paper's Appendix example, transcribed into the test with its inputs, reproduced within 1e-3 (its printed precision) |
| T = 0, 1 | null, `too few trades` |
| zero variance (all `ret` equal) | null Sharpe; DSR `undefined: zero variance` |
| skew direction | with the other inputs fixed, **positive** skew lowers the denominator, which raises PSR when `SR − SR₀ > 0`, lowers it when `SR − SR₀ < 0` and leaves `PSR = 0.5` when `SR = SR₀`; the test covers all three cases and the values equal its own computation |
| denominator ≤ 0 (constructed moments) | `undefined: moment denominator` |
| repeated strategies (duplicate `param_key`, identical outcomes) | the cohort's N does not grow; the per-experiment counts are reported |
| research history | a child experiment's cohort includes the parent's unique configurations; a sibling lineage with a different `strategy_hash` is excluded |
| invalid metrics (NaN / inf in `ret`) | `undefined: non-finite input`; never ranked |
| pure-noise experiment, 1,000 trials, 20 seeds | the best trial's DSR at the research-history N exceeds 0.95 in at most 2 of 20 seeds (a Monte Carlo sanity check, not a proof) |
| `combined` = long ∪ short | equals the Sharpe of the concatenated returns, independent of order |
| autocorrelated `ret` (AR(1), φ = 0.5) | `ρ₁` ≈ 0.5 and the `autocorrelated` flag is set |
| heuristic scenarios | fewer than 2 clusters → `undefined`; the scenarios are labelled heuristic and are not sorted |

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

### 8.4 Status transitions (all versioned, all with provenance; R1)

```
Defined ─► Active                       default for every non-structural parameter
Active ⇄ Investigate                    evidence (§7.3–7.4: detected, period-dependent, aliased,
                                        unresolved pair / triple) or user; reason required
Active / Investigate ─► Deprioritized   only a §7.4a proposal (all six conditions) confirmed by the user
any ─► Excluded (structural)            only by a §8.2 proof: automatic, shown, reversible when the spec changes
any ─► Excluded (research)              user only; reason text required; the warning lists its unresolved pairs and triples
any ─► Frozen                           user only; value required (default: the spec's current value)
Deprioritized / Excluded (research) / Frozen ─► Active   "Restore": one click, reason optional, always allowed
any empirical status ─► stale           automatic when its evidence scope changes (§8.5); the old evidence stays, struck through
```

**Each transition appends an event:** `{at, path, from, to, actor: "operator" | "structure", reason, evidence_ref (snapshot, method, interval, blocks, floor), scope (strategy_hash, data identity, ranges, partition, sampler, blocks, search_space.hash)}`.

Rules:
- AI text may be attached as a *note*. It is never the actor.
- The only automatic transitions are structural exclusion (proof-based) and `stale` (scope-based). No empirical statistic ever changes a status by itself (scenario 20).
- `Deprioritized` and `Excluded (research)` are reversible, evidence-scoped and reviewed: the dialog shows the §7.4a conditions with their values, and the status card keeps them.
- Automatic structural exclusion needs a valid proof object; a proof that fails to re-verify on the same `spec_hash` is a test failure, not a status.

### 8.5 Search-space proposals, budgets and versioning (R5)

- **Proposal:** `experiments/<exp_id>.searchspaces/<n>.json` (an attachment of the experiment, §9.2) holds `{base_version, statuses, frozen values, coarsenings, reasons, unresolved_pairs, unresolved_triples, budget, created_at, applied: false}`. It is versioned by n and hashed.
- **Budget shares sum to 100 %.** The default split of a sweep's `budget_total` is **screening 30 % / interaction exploration 45 % / refinement 20 % / reserve 5 %**. The earlier 30 / 48 / 22 plus a 5 % reserve summed to 105 %; it is corrected here and flagged for re-approval (§22). Shares are whole percents, validated to sum to exactly 100 (`test_budget_shares_sum_to_100`). The reserve is part of the budget, held back from scheduling, and spent only by `Investigate` (§7.5) or a re-screen; whatever is unspent at finalize is reported as `reserved · unused`, never silently added to refinement.
- **Six numbers, shown together on D and H, defined in §6.4:** theoretical Cartesian size; scheduled trials; completed trials; reused trials; remaining budget; reserved capacity. Each carries its definition, and `scheduled + remaining + reserved = budget_total` is an invariant (`test_budget_counts_invariant`).
- **Reallocation** between shares happens only (a) in a new proposal, which creates a child experiment with its own split, or (b) on a paused experiment, for unscheduled trials only, through `PUT /lab/{exp}/budget` with a reason. Case (b) keeps `search_space.version` (the space is unchanged), increments `sampler.revision`, appends a `budget_reallocated` event with before / after, and is refused while the experiment runs or for trials already scheduled. `Simulate Budget` is a preview and changes nothing.
- **`Review Before Apply`** shows a side-by-side diff of dims, frozen values, removed / coarsened levels, the theoretical Cartesian count before and after (Decimal), the budget split, and the estimated time (§8.6). Every count is labelled "theoretical; a sampler's trials are set by the budget, not by the space" (scenario 21).
- **Apply** never edits the strategy. It creates a **new child experiment** with the same pinned spec, the new surface, `search_space.version = base + 1`, `lineage.proposal_id` and the budget split.
- **Historical trials:** parent trials stay valid evidence for their own space and are never re-labelled. The child **reuses** parent trials whose `inputs_key` matches and whose params lie in the new space, copied **by value** with `reused_from` provenance (a deleted parent cannot break the child, §9.2) and counted as `reused`; they consume no budget and are never counted as new or scheduled.
- **Cache keys** include `search_space.hash` and `sampler.revision`, so no view mixes versions.
- **Re-screen triggers mark empirical statuses `stale`** (scenario 22): a different `strategy_hash`; a different data identity (symbol, timeframe, range, sha256); a changed surface range (evidence from one range is never applied to another, scenario 23 case 9); a changed partition; a different sampler, block count or `sampler.revision`; a new regime / window selection once such selections exist. A stale status still shows its old evidence, struck through, with `Re-screen` (a `rescreen` child: a fresh uniform sample over the current space at the reserve budget, `design = uniform`, so its rows refresh the evidence, §7.5).
- **Final OOS is never read by any H computation.** `lab/partitions.py` is the single bar-access point. It refuses `purpose="screening"` for the final range (scenario 22 test), and `apply` re-reads the lineage's holdout ledger at apply time: any proposal, whenever it was created, is refused once the lineage has an exposed assessment (§10.1).

### 8.6 Budget estimates

- **Projected time** uses two models side by side, both labelled: the existing planner (`trials × bars × measured ms_per_cell_bar / (0.8 × workers)`, "measured on this host" or "starting guess"; the planner itself is unchanged in this plan) and, once Phase 2's Track B benchmark has run on the host, the **affine fit** `trials × (a + b × bars) / parallelism` from §9.1b, which holds across bar counts where the linear model does not (the per-trial cost has a fixed part the cell-bar model misses). The larger of the two is the headline, and the panel says which it is.
- No "speed-up" or "trials saved" claim is made. The counts shown are the six of §8.5.

### 8.7 Answers to the mandatory Screen H review questions

| Question | Answer in this plan |
|---|---|
| What evidence supports each structural exclusion, and how is it reproducible? | §8.2 rules 1–4; the proof is a path in the spec's dependency graph plus `spec_hash`; `structural_status` is pure, and tests pin each rule (scenario 18) |
| How are weak-main, strong-joint interactions protected? | Incremental shares `Δ_{i|j}` on upper bounds; the coarse triple screen; the six-condition rule of §7.4a; the residual veto; XOR and three-way fixtures (scenarios 19, 23) |
| What prioritizes pair / higher-order investigation, and how are uncertainty and sampler bias exposed? | Priority = upper 90 % bound of `Δ`; unresolved lists by coverage; three uncertainties printed (design, period, detection floor); adaptive rows excluded and the exclusion stated; aliasing flags |
| Which variables are frozen vs excluded, and is the strategy unchanged? | §8.1; apply creates a child experiment on the same pinned spec; test `test_apply_proposal_keeps_strategy_hash` |
| Can Randall restore or inspect any valid pair in one or two interactions without losing filters? | `Restore` is one click; `Explore any valid pair / triple` is two selects; the store keeps the filter (walk 115) |
| How do changes affect versioning, historical trials, cache keys, lineage and budget? | §8.5 |
| What QA proves a variable-selection change does not alter OOS usage or deployment eligibility? | `partitions.py` refusal tests; no gate input reads statuses; post-unseal proposals blocked; the `.final/` import boundary (scenarios 13, 20, 22, 28) |

## 9. One-million-trial readiness: two tracks (R2)

The review required that million-result *browsing* be separated from million-trial *execution*. They are different machines with different bottlenecks, so this section has two tracks, two measured tables and two acceptance tables. A Track A number never stands in for engine throughput, and a Track B projection is labelled `estimated` until a run of that size has happened on the host.

- **Track A, result exploration:** query latency, filtering, aggregation, ranking, pagination, visualization, browser memory, concurrent UI responsiveness. Measured on a synthetic 1,000,000-row table shaped like the trial rows (§9.1a).
- **Track B, trial execution:** indicator calculation and caching, kernel execution, worker initialization, per-trial computation, trade-metric calculation, memory, Parquet writes, compaction, failure recovery, concurrent analytical queries. Measured on the real engine through the real pool on real QQQ bars (§9.1b).

### 9.1a Track A, measured on this machine (2026-10-27)

**Setup**
- i7-1255U, 15.8 GB, NVMe SSD.
- `.venv-aegis` (pyarrow 23.0.1, numpy 2.5.3).
- A synthetic table shaped like Aegis cell rows: 1,000,000 rows; 20 parameter columns, 30 metric columns, `cell`, `pass`, `valid`, `elapsed_ms`.
- Random metric values, the **worst case for compression**.
- Scripts are in this session's scratchpad (not committed); Phase 2 commits a reproducible version as `tests/products/aegis/lab_benchmark.py explore`.

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

### 9.1b Track B, measured on this machine (2026-10-27)

**Setup**
- The real engine (the numba kernel) through the real `Pool` (`ProcessPoolExecutor`, `_init_worker`, `_run_cell`, `run_chunk`), driven exactly as `ExperimentJob` drives it: chunks of `CHUNK_CELLS = 200`, each written as a Parquet chunk through `_cells_table` / `_write_atomic`, with equity curves kept when the plan is ≤ 20,000 trials, as the job does.
- Real bars: QQQ from the raw archive (`ArchiveStore.bars`, vintage 20260919) at three bar counts: **2,603** (1h, 2024-01-01 → 2025-06-30), **9,669** (15m, same range) and **46,034** (1m, 2025-01-01 → 2025-06-30).
- A realistic strategy, `lab-bench-10p`: ten ranged parameters on both sides, four indicators per side (EMA, SMA, RSI, MACD), an entry of three conditions, an exit of two, a stop and a target, **commission 1.0 per side and slippage 5 bps**; a Latin-hypercube sample over a grid of 2.87 × 10¹¹ cells; both sides evaluated independently (≈ 29 / 28 trades per side at 2,603 bars, ≈ 99 / 98 at 9,669, ≈ 525 / 520 at 46,034).
- 10 workers (`cpu_count − 2`, memory-fitted); the host process opted out of power throttling. One run with the workers' opt-out off showed no difference (0.0188 vs 0.0180 ms per cell-bar), so pool children spawned from a console process are not throttled on this host. Phase 2's `execute` mode repeats the measurement through the real detached worker, which is how the product runs.
- Concurrent Lab queries: the Track A query set (read 7 columns of the 1M-row file, filter two ranges, 2-D median, top 200) once per second on a thread in the host process.
- Script: this session's scratchpad `bench_engine.py` (not committed; nothing written under `data/`); Phase 2 commits it as `lab_benchmark.py execute`.

| Workload | Bars | Trials | Wall | Steady trials / s | Wall ms / trial | Worker ms / trial | Worker ms / cell-bar | Parallelism (of 10) | 1M at this bar count |
|---|---|---|---|---|---|---|---|---|---|
| A1k | 2,603 | 1,000 | 17.7 s | 123 | 8.1 | 45.8 | 0.0180 | 5.6 (start-up dominated) | — |
| A10k | 2,603 | 10,000 | 63.7 s | **188** | 5.31 | 48.3 | 0.0186 | 9.1 | 1.5 h (burst rate) |
| A10k + Lab queries | 2,603 | 10,000 | 77.7 s | 151 | 6.64 | 60.3 | 0.0231 | 9.1 | 1.8 h |
| B10k | 9,669 | 10,000 | 131.9 s | 83 | 12.0 | 112.3 | 0.0116 | 9.4 | 3.3 h (burst rate) |
| C2k | 46,034 | 2,000 | 96.7 s | 24 | 41.4 | 392.7 | 0.0084 | 9.5 | 11.5 h (burst rate) |
| **A100k** | 2,603 | **100,000** | 19.1 min | **89** | 11.24 | 103.0 | 0.0396 | 9.2 | **3.1 h (sustained rate)** |

Every trial completed (`invalid = 0`, `failed = 0`); the trade statistics were identical across runs for the same cells.

**What the cell-bar model does not see**
- **Per-trial cost is affine in bars, not linear:** worker ms per trial ≈ `27 + 0.0079 × bars` (fit through the three bar counts; the fixed part is signal evaluation in pandas, the trade list and the metric construction). A `ms_per_cell_bar` measured at one bar count therefore mis-prices another: the rate measured at 2,603 bars (0.0186) over-prices a 46,034-bar trial 2.2×, and the rate measured at 46,034 bars (0.0084) under-prices a 2,603-bar trial 2.2×. The planner's model stays (it is conservative when extrapolating upward); the Lab shows the affine projection beside it (§8.6).
- **Start-up:** the first chunk takes 10.6–13 s at ≤ 10k bars and 22 s at 46k bars (process spawn, kernel JIT, first indicators), paid once per job.
- **Concurrent queries cost about a fifth of the throughput** (188 → 151 trials / s), and the queries themselves run about 2× slower (total p95 198 → 416 ms, worst 1.5 s) while the pool saturates the cores. Q7 (concurrent) stands; the UI shows both effects.
- **Sustained vs burst:** over 100,000 trials at 2,603 bars the steady rate was 89 / s against 188 / s over 10,000: a sustained-to-burst ratio of 0.47. The run kept no curves (plan > 20,000), so the gap is not serialization; the worker's own per-trial time rose from 48 to 103 ms, with transient slowdowns of 2–3× for a few chunks, which points at the laptop's sustained all-core clocks (thermal and power limits) rather than at the engine. Projections use the sustained rate, and the Run Monitor shows the live rate so an operator sees the same effect on a real sweep.
- **Writes are negligible:** a 200-row chunk writes in 15–25 ms (max 54 ms under query load); curves add ≈ 0.5 MB per 1,000 trials.
- **Storage per 10,000 trials:** 3.3–3.5 MB of cells (50 chunk files) plus 4.7–7.6 MB of curves; compacted to 2.0–2.1 MB in 34–78 ms; the compacted file's 7-column read is 27 ms. Reading all 50 chunks (today's `cells()`) takes 1.1–1.3 s, so 1M trials ≈ 120 s, consistent with Track A; a resume's `done_cells` read is 0.1–0.25 s per 50 files (≈ 10–25 s at 1M before compaction, ≈ 0.2 s after).
- **Memory:** worker peak working set 155–174 MB (private bytes 473–487 MB, mostly the JIT and libraries); the host process 390–454 MB while holding the ten-year 1m frame. Free memory went from 2.2–3.5 GB before each run to 1.7–2.4 GB during it.

**Trade Sharpe overhead (R2):** measured in-process on the 2,603-bar frame: `run_metrics` 21.3 ms per trial (warm cache, median trade count 59); a per-scope mean and std over the kernel's existing `ret` column 14 µs; three scopes 42 µs, which is 0.2 % of the in-process trial and 0.09 % of a pool trial; the row's pickle grows from 1,040 to 1,086 bytes (three floats); no new array is allocated (`trades[:n_trades, 9]` is a view of the buffer the kernel already fills; for scale, `_metrics_arrays` itself costs 256 µs). **Decision:** compute it in stage 1, in the worker, beside the metrics; no deferral and no alternative method is needed.

### 9.1c What is verified, what is estimated, and when to re-test

| Claim | Status |
|---|---|
| 10,000 real trials at 2,603 and 9,669 bars; 2,000 at 46,034; 100,000 at 2,603 | **measured** (the table above) |
| The Track A latencies at 1,000,000 rows | **measured** on synthetic rows with random metrics; real rows compressed 1.5–2× better in §9.1b (an observation, not a guarantee); the layout-2 figures are re-measured at the milestone |
| 1,000,000 trials at 2,603 bars ≈ 3.1 h | **estimated** from the sustained 100,000-trial rate, not from the 10,000-trial burst |
| 1,000,000 trials at 9,669 bars ≈ 7.0 h; at 46,034 bars ≈ 24.3 h | **estimated**: the 10,000 / 2,000-trial burst rates scaled by the measured sustained-to-burst ratio (0.47) |
| The affine model at the same bar counts: 3.1 h at 2,603, 6.8 h at 9,669, 25.7 h at 46,034 | **a second estimate** (`1e6 × (27 + 0.0079 × bars) ms / 9 / 0.47`), within 10 % of the measured-rate scaling; the UI shows the measured-rate projection where a measurement at that bar count exists and the affine one elsewhere, each labelled |
| Compaction at 1,000,000 rows (≤ 10 s per generation) | **estimated** from Track A's 4.8 s single-file write; measured in Phase 2 |
| Failure recovery at scale (per-trial isolation, retry, torn compaction) | **not measured**: Phase 5 features; their tests are deterministic, not timed |

**Which smaller benchmarks validate the projection:** a 10,000-trial run at 2,603 and 9,669 bars, a 2,000-trial run at 46,034 bars (10,000 there takes ≈ 7 minutes and is run at the milestone), plus one 100,000-trial run at the smallest bar count, on the host, through the real worker, recorded with host details. That is what `lab_benchmark.py execute` runs at R3 and R7. A full 1M real run is not required for approval. Randall's HA-MQI framework (§11.2) is a daily-chart framework: ten years of 1D bars is ≈ 2,500 bars, the A configuration, so its million-trial sweeps are the cheap case here; the 15m and 1m rows bound the other timeframes the archive offers.

**Triggers for re-running Track B:** any change to `engine_build` (kernel, backtest, indicators, kinds, strategy, temporal); a strategy with more than four indicators per side or more than ten ranged parameters (the 20-parameter case of Phase 4); bar counts above 50,000; a new indicator kind (4b); the worker's live rate drifting more than 15 % from the recorded one; free memory under 2 GB at job start; a new host.

### 9.2 Storage, indexing, snapshots and partitioning (Phase 2)

**Write path kept:** chunk files, atomic `.tmp` replace, resumable. `CHUNK_CELLS` stays 200 for progress granularity.
- **One fix:** chunks are named by the highest existing index + 1, not by the count of readable files (F16).

**Compaction (layout 2):**
- Every `COMPACT_EVERY = 50` chunks (≈ 10,000 trials), and at finalize, the job (inside its own unit, never concurrently) merges committed chunks into `cells/part-<gen>.parquet`:
  - zstd;
  - row groups of 65,536;
  - sorted by `trial_no, block`.
- It then writes `cells/manifest.json` atomically: `{generation, parts: [{file, trial_no_min, trial_no_max, rows, sha256}], merged_chunks: [{file, generation}], chunk_watermark}`. **Merged chunks are not deleted at compaction time**; they are listed as merged and reclaimed later (below).
- **Crash at any point:** readers take parts from the manifest plus any chunk file not listed as merged, collapse copies of the same `(trial_no, block, attempt)` (counted as `duplicates`) and then keep the canonical attempt per `(trial_no, block)` (§7.3a). Re-running compaction is idempotent.
- Tests: `test_lab_compaction_torn_is_idempotent`, `test_readers_see_one_set_during_compaction` (threads reading while a compaction runs), `test_reopen_older_snapshot_after_later_generations`.
- **Legacy experiments (layout 1) are not compacted** (retained data, §12). They are ≤ 252 cells today, and their reads go through the same reader.

**Snapshots (immutable file sets):**
- A snapshot is `{generation, chunk_watermark}`: the parts of that generation plus the chunk files with index ≤ the watermark. It is taken when a view or a Lab task starts, and every response carries it; the cache key is `(experiment, generation, chunk_watermark)`, so one key always means one file set. The "latest" snapshot is re-read from the manifest at the start of each request, never mid-request.
- **Retention.** A file listed as merged is reclaimed only when (a) it has been merged for at least `RETAIN_MERGED_SECONDS = 600` and (b) no open snapshot references it. The worker keeps an in-process registry of open snapshots (request-scoped, released when the response is written; Lab tasks hold theirs until they finish; a snapshot **pinned** from Screen D holds its files until unpinned or until the experiment finishes plus the grace period). Reclamation runs at the end of a compaction unit and at finalize, never concurrently with a reader of the same experiment (a per-experiment reader-writer lock).
- A pinned snapshot whose files were reclaimed after a worker restart (the registry is in-process) is reported as `snapshot expired`, never served partially.

**Index:**
- `trial_no` is sorted within parts, and row-group statistics give range push-down.
- Per-part min/max per parameter column come free with Parquet statistics.
- No separate index files.

**Column cache:**
- `LabCache` in the worker holds projected Arrow columns per snapshot.
- LRU by bytes with `LAB_CACHE_BYTES = 400 MB`, sized from 2.5 GB free × the pool's 0.8 headroom, minus the pool's own share. Configurable with `AEGIS_LAB_CACHE_MB`.
- A query loads only the columns it needs: params in the filter, axes, metric, `status`, `design`, `block`, `trial_no`. That is about 140 MB for 7 columns at 1M rows.
- **Never** all 50+ columns (940 MB).

**Lifecycle of the new folders (R-14):**
- `runs.py`'s attachment list (today `<id>.cells`, `<id>.curves`, `<id>.reports`; `runs.py:90`) is extended to `<id>.replays/`, `<id>.final/`, `<id>.folds/`, `<id>.searchspaces/`, `<id>.events.jsonl`, `<id>.views.json` and, on a lineage root, `<id>.holdout/`, so trash, restore and delete move them together (`test_experiment_attachments_travel_with_trash_and_restore`). Search-space proposals therefore live under the experiment (`experiments/<id>.searchspaces/<n>.json`, §8.5), not in a top-level folder.
- Reused rows are **copied by value** into the child with `reused_from = {experiment, trial_no}` provenance, so deleting the parent never breaks the child. A parent with children is nevertheless refused deletion with `ExperimentReferenced` (the pattern of `StrategyReferenced`), because the lineage graph and the holdout ledger live on it; the trash heals as today.
- Older code ignores unknown folders (§11 rollback). The `--decompact` tool and the compaction writer touch experiment data, so they get **mandatory independent QA at R3** (§12, §16).

**Provenance enforcement on resume (R-14):**
- A layout-2 experiment resumes only through `ArchiveStore.load_pinned(data_pinned)` (sha256 and `data_hash` checked) and only when the worker's `engine_build` equals the document's; today's resume path (`api.py:847`) reselects bars by reference and is kept for legacy experiments only. On a mismatch the resume is refused with the reason, and the operator may create a child on the current data and engine (its evidence is new, not reused).
- Tests: `test_resume_refuses_vintage_drift`, `test_resume_refuses_engine_build_drift`, `test_legacy_resume_unchanged`.

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
| `robustness` | one candidate's four categories with their inputs |
| `triples` | the top 20 by upper bound plus the unresolved count |

### 9.4 Background work, progress, cancellation and resume

- **Stage-1 trials:** the existing experiment job (one unfinished job across kinds: `jobs.py`).
- **Heavy Lab analytics** run as **Lab tasks**: a single-thread executor separate from `JobRunner`, one task at a time, cached per `(snapshot, filter_hash, method)`, cancellable at checkpoints between resamples, polled by the view. The importance task is staged so results arrive as they exist (R-13): stage 1, fine-grid mains and pairs with bootstrap 200 and null 200 (≈ 25 s measured scale, delivered first); stage 2, the coarse decomposition's point estimates (one pass over 1,140 triples ≈ 1.2 s) and the per-block mains with their intervals (K × 200 cheap passes); stage 3, the coarse bootstrap `B_c = 50` for the residual interval and for the triples of candidate variables only (≈ 60 s at d = 20). Budget: ≤ 180 s in total, the fine-grid stage within 30 s (§9.6a). The measured concurrency penalty (§9.1b) used light queries, so `lab_benchmark.py analytics` runs this task beside a running job at **R3.5** (the end of Phase 3, where the task is implemented) and records both the task time and the job's throughput loss; if the budget is missed, `B_c` and `P` are reduced before any other change.
- **Lab tasks never start pool processes.** Randall decided (Q7) that they run while an experiment job runs: one task at a time, yielding between resamples so the job's chunks keep their pace, with the UI showing "sharing CPU with the running job" and the task's own progress. §9.1b measured the cost of sharing: about a fifth of the job's throughput and a 2× slower query while both run.
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

### 9.6 Budgets for approval

#### 9.6a Track A (result exploration): pass thresholds for scenario 11

These come from the §9.1a measurements with about a 3× margin for real data, a busy laptop and HTTP overhead. **Approved by Randall on 2026-10-27 (Q6)** as the scenario 11 pass thresholds, with the §7 policy constants; the one changed row is marked.

| Interaction (1,000,000 completed trials, warm cache) | Budget (p95) |
|---|---|
| Lab open: summary + first heatmap + first table page | ≤ 1.5 s (cold, from disk: ≤ 4 s) |
| Filter or axis change → heatmap + counts | ≤ 400 ms |
| Aggregate stat change | ≤ 300 ms |
| Table page (any offset) | ≤ 600 ms |
| Exact-slice change | ≤ 300 ms |
| Parallel coords (bundles) | ≤ 800 ms |
| Pareto (2 objectives) | ≤ 800 ms |
| Neighbourhood of one trial / robustness of one candidate | ≤ 150 ms |
| Importance analytics: fine mains + pairs (bootstrap 200, null 200), the coarse decomposition, coarse bootstrap 50 for the residual and candidate triples, per-block mains | background ≤ 180 s total, the fine-grid stage within 30 s, progress shown (**changed from 30 s by R1 and Codex R-13; needs re-approval, §22**) |
| Progress poll while running | ≤ 100 ms server time |
| UI main thread: no task > 50 ms during any interaction above; ≤ 1,500 DOM table rows; ≤ 40,000 canvas squares | — |

| Resource | Budget |
|---|---|
| Worker additional memory with one 1M-trial experiment open | ≤ 450 MB (cache 400 + transient) |
| Browser tab heap | ≤ 300 MB |
| Disk per 1M-trial experiment (stage 1) | ≤ 350 MB |
| Compaction pause at 1M | ≤ 10 s per generation (one unit) |

#### 9.6b Track B (trial execution): pass thresholds for scenario 24

Set at about 80 % of the §9.1b measurements to absorb a busy laptop. A miss is a finding to investigate, never a silent re-baseline.

| Measure (on this host, through the real worker) | Threshold |
|---|---|
| Steady throughput at 2,603 bars, 10,000 trials | ≥ 150 trials / s (measured 188) |
| Steady throughput at 9,669 bars, 10,000 trials | ≥ 65 trials / s (measured 83) |
| Steady throughput at 46,034 bars, 2,000 trials | ≥ 19 trials / s (measured 24) |
| Sustained throughput over 100,000 trials at 2,603 bars | ≥ 71 trials / s (measured 89) |
| Throughput with concurrent Lab queries | ≥ 75 % of the quiet rate (measured 80 %) |
| Lab query p95 while the pool runs | ≤ 2.5 × the quiet p95 (measured 2.1×) |
| First chunk (start-up) | ≤ 20 s at ≤ 10k bars; ≤ 35 s at 50k bars |
| Chunk write (200 rows) | ≤ 100 ms p95 |
| Worker peak working set | ≤ 160 MB + 400 B / bar (the pool's own model) |
| Host process growth during a job | ≤ 100 MB |
| Compaction per generation | ≤ 10 s |
| `invalid` / `failed` on the benchmark strategy | 0 |

**Throughput statement (labelled `estimated` wherever the UI shows it):** `hours ≈ trials × (27 + 0.0079 × bars) ms / parallelism / 3.6e6`, parallelism ≈ 9 on this host, divided by the sustained-to-burst ratio 0.47. One million trials ≈ 3.1 h at 2,603 bars, ≈ 7.0 h at 9,669 and ≈ 24.3 h at 46,034. The pool fits workers to free memory (160 MB + 400 B/bar each); with 2.5 GB free, 12 workers fit at 10k bars, so the configured 10 hold. The planner already prices this and asks above 10 minutes.

### 9.7 Drill-down and the no-million-node rule

- No view sends more than its bound (§9.3).
- The table is windowed: rendered rows ≈ visible + 20.
- Canvas charts draw bins and bundles.
- Exact marks are sampled and labelled.
- Every drill-down step keeps counts (scenario 14).
- **Test:** the walk counts DOM rows (≤ 1,500) and the response sizes with the 1M synthetic experiment.

### 9.8 The synthetic 1M experiment (scenario 11), the real 12k experiment (scenario 30) and the scratch harness

- `tests/products/aegis/lab_fixture.py` writes a layout-2 experiment directly:
  - deterministic seed;
  - 20 parameters;
  - metrics from a known function, including an XOR pair, a conditional triple and a plateau / spike pair, plus noise;
  - in a temp data root.
- It is not run through the engine (it would take hours). It is marked `DEMO · synthetic` in its name and document.
- The vertical slice (Phase 2c) uses a **real** experiment instead: the §9.1b benchmark strategy, 12,000 LHS trials at 2,603 bars (≈ 1 minute), created through the API on the scratch worker, so every Lab view in the slice shows engine output.
- **The scratch worker and the harness (R-10).** The data root has no override today (§3.4a), the walk's restart helper hard-codes port 8102 and the ordinary launcher (`browser_workstation.py:479`), and `tools/start_product.ps1:18` stops whatever listens on the product port; several walk checks also read `ROOT/data/aegis` directly. Phase 2 therefore adds:
  - a product-only `AEGIS_DATA_ROOT` environment override, read in the same places that default to `DATA_ROOT/"data"/"aegis"`, with the default unchanged;
  - an Aegis-owned scratch launcher `tools/start_aegis_scratch.ps1 -Port 8103 -DataRoot <folder>` that writes a PID file and **never** touches the product port or `start_product.ps1`'s stop logic;
  - walk arguments `--base`, `--port`, `--data-root` and `--pid-file`; the restart helper restarts the PID in the PID file, and every filesystem assertion reads the given data root. The walk **refuses** its restart and deletion items unless `--data-root` is set and differs from `ROOT/data/aegis` (`test_walk_refuses_destructive_items_on_product_root`).
  - The milestone walk runs against `http://127.0.0.1:8103/aegis/` with the fixtures under the scratch root, so nothing enters `C:\Triad\data\aegis` and the 8102 worker is never restarted by a test.
- After the milestone the fixture folder is deleted (Q11: test data can be deleted), and the walk report records its size and the deletion. The Lab warns below 10 GB free on the data root's disk.

## 10. Staged compute funnel

| Stage | What runs | Data | Engine / costs | Selection boundary | Owner |
|---|---|---|---|---|---|
| **1. Fast exploratory** | experiment evaluations (grid / LHS / refine / focused / rescreen configurations, optionally × `K + 1` blocks, §7.3a) | **selection partition only** | kernel, metrics-only plus `sharpe_trade`, the spec's commission + slippage (already costed, F8) | candidates by robust rank (§7.6), never by best point alone | Phase 2 (store), Phase 3 (blocks, rank) |
| **2. Focused refinement + cost stress** | materialize the top-K robust candidates (K per experiment, default 20) as full runs; re-run each under the cost scenarios | selection partition | full envelope with trades; cost scenarios as stage-2 rows | a candidate passes to stage 3 only if it `holds` or `degrades` under `slippage×1.5` (§7.6 D; policy, Q6) | Phase 5 |
| **3. Candidate folds** | `CandidateFoldsJob`: each fixed candidate evaluated on every validation fold (§10.3); selection-period windows only as labelled diagnostics; the existing Mission 8 studies stay available as the separate "rolling re-selection" view | **validation partition** (folds), with warm-up from history | full envelope per fold, fresh capital per fold | fold results never feed back into stage 1's objective; a new stage-1 sweep after seeing folds is a new child, labelled `post-validation` | **Phase 6** (`lab/folds.py`, `CandidateFoldsJob`, `FoldMatrix`) |
| **4. Final untouched OOS** | one materialized run per unsealed candidate on the final range | **final OOS** | full envelope | only through `Unseal`, which is also the evaluation (§10.1) | **Phase 5** (`lab/final_oos.py`, `FinalOosJob`, `FinalOosPanel`); Phase 6 adds Screen F's presentation |

### 10.1 Final OOS: ownership, submission, identity, persistence, verification, display (R4)

- **Owner.** Phase 5 implements the whole of stage 4: the submission state machine, the evaluation job, persistence, the verification hooks and a minimal results panel. Nothing about stage 4 is "record only".
- **Submission is a durable state machine, not one HTTP call.** `POST /lab/{exp}/final-oos/unseal` carries `{candidates: [trial_id], confirm: "<experiment id>", idempotency_key: <client uuid>}` and runs these steps in this order:
  1. **Resolve the idempotency key first.** A request whose key matches a ledger entry returns that entry's record in whatever state it is (requested, queued, running, done, failed), allocates nothing and touches the runner not at all. A retry of a request whose job is running therefore gets its record, not a refusal.
  2. **Validate** the candidates (§ identity below) and the confirm text.
  3. **Reserve the runner slot atomically.** `JobRunner` has one slot and no queue (`jobs.py:103-105` is the atomic admission point, raising `JobBusy`). Phase 5 adds `JobRunner.reserve(kind, owner) -> token`, which takes the runner's lock and holds the slot for the caller (an ordinary experiment or another lineage's unseal started in between is refused with `JobBusy` exactly as if a job were running), or raises `JobBusy`. On `JobBusy` the request is **refused with 409 and the running job's name, before any ledger entry or record exists** ("pause or wait for <job>"). A reservation is released in a `finally` block whenever the request does not reach step 5.
  4. **Allocate `use_no` ledger-first, under the holdout lock.** The lock is an OS file lock on `experiments/<root>.holdout/ledger.lock` (`msvcrt.locking` on Windows, `fcntl.flock` elsewhere), which the operating system releases when the process exits, so a crash never leaves it held; a stale `.lock` file from an older process is simply re-locked. Under it: read `max(use_no)` from the ledger, append the entry `{use_no, holdout_id, idempotency_key, experiment_id, at, candidates, status: allocated}` (the ledger is the allocation authority; an appended number is consumed forever), then write `unseal-<use_no>.json` with `status: requested`. The order is ledger first, record second.
  5. **Submit** `FinalOosJob` under the reservation (`JobRunner.start(job, reservation=token)` converts the reservation into the running job) and mark the record `queued` and the ledger entry `submitted`.
  - **Concurrency:** two unseals in one lineage serialize on the holdout lock; an unseal and an ordinary job race only at step 3, where the runner's own lock decides, and the loser is refused before consuming anything.
  - **Crash recovery runs at worker start, before any request is served** (`final_oos.reconcile()`): a ledger entry without a record (crash between the two writes) gets its record written from the entry with `status: failed · lost before submission` and is marked `void · never exposed`; a record without a ledger entry cannot arise from this code and is reported, never auto-repaired; `requested` / `queued` records whose job is not alive are re-submitted under the same `use_no` (nothing was exposed); `running` records whose job is not alive become `interrupted` and the candidates **without a persisted result** are re-submitted under the same `use_no` (the record is the use, not the evaluation; results already persisted stay); a record with every result persisted becomes `done`. No step allocates a second `use_no` for the same request, and the next allocation always reads the ledger's maximum, so a consumed number is never reused.
  - **Tests (`test_lab_final_oos::test_submission_*`):** fault injection after the reservation, after the ledger append, after the record and after submit; a duplicate request while the original runs returns the record; two concurrent unseals in one lineage; an unseal racing an ordinary experiment for the slot; a busy runner refused before any ledger entry; reconciliation from every state, including the ledger-only crash (the next allocation skips the consumed number) and a restart with a stale lock file present.
- **Candidate identity.** A candidate must be a tested trial (block 0) with a stage-2 `base` replay, so its costs and full envelope were seen before the holdout is touched. The record stores `trial_id`, `param_key`, `strategy_hash`, `spec_version`, `stage2_run_id`, `stage2_result_hash` and the experiment's `engine_build`. The job rebuilds the strategy from the pinned spec and the trial's params (`apply_params`) and refuses to run when `strategy_hash(rebuilt) ≠ strategy_hash(stored)`.
- **Bars.** `partitions.bars_for(document, "final", unseal=record)` returns the final range, with warm-up from prior history through `evaluate_from` (rule 2): bars before the range are never scored. The run envelope pins the data (`sha256`, `data_hash`) for that range.
- **Persistence.** Each result is a run document under `runs/` (`experiment_id`, `trial_id`, `partition: "final_oos"`, `unseal_no`, and an additive `artifact_sha256`), and its `run_id`, `result_hash` and `artifact_sha256` are written into the record as it finishes (atomic replace; a record is never rewritten except for status and results). **`artifact_sha256`** is SHA-256 over the canonical JSON (sorted keys, the serializer `canonical_payload` uses) of the stored document **with the `artifact_sha256` field itself removed**; the same definition applies to every new run document the Lab writes (replays, folds, final).
- **Exposure and the ledger's status.** When `FinalOosJob` starts its first unit it stamps the ledger entry `exposed_at` (and the record `running`). From that moment the holdout is **exposed** for that lineage, whatever happens to the rest of the job.
- **Verification (R-6).** Two different checks, named differently in the UI: **artifact integrity**, re-hashing the stored file against `artifact_sha256` (new records only; legacy runs report `artifact digest not recorded`, never a quarantine); and **computational reproducibility**, a pinned rerun that recomputes `result_hash` from the pinned spec, data and engine and compares it with the stored one (`results.py:159` hashes the full payload before indicator series are dropped and equity is shortened, so the stored document alone cannot reproduce it, as `test_aegis_results.py:118` pins). Also: the `strategy_hash` check before running, and `engine_build` equality with the experiment (when it differs the record says `engine differs from the sweep: evidence only`). The UI reads metrics from the run documents only; nothing is recomputed client-side.
- **Display.** Phase 5's `FinalOosPanel` (on Screens C and D) shows `sealed · 0 uses`; `requested`; `refused: runner busy with <job>` (as the request's error, nothing recorded); `unsealing · use n · k of m evaluated`; `interrupted · re-queued`; `evaluated · use 1 · independent final assessment`; `evaluated · use n · reused holdout`; `failed`; `void · never exposed`. Per candidate: final-range metrics beside the selection and validation numbers, trade count, exposure, drawdown, `sharpe_trade` with its caveats, and `Show on chart`. Never a verdict. Phase 6's Screen F adds the equity on the final range and the fold matrix's sealed bar.
- **Holdout identity and the lineage ledger (R-5).** The holdout is identified by `holdout_id = BLAKE2b({symbol, timeframe, final range, archive sha256, data_hash of the final range})`. Every experiment carries `lineage.root` (itself when it has no parent), and the root owns the append-only **ledger** `experiments/<root>.holdout/ledger.jsonl`: one line per allocation on any experiment in the lineage, with later status lines appended (`submitted`, `exposed`, `done`, `failed`, `void`); the current state of an entry is its last line. `use_no` is allocated from the ledger, so it is lineage-wide: two siblings created before any unseal cannot both be `use 1`, and an existing sibling's later unseal is `use 2`. **The label follows exposure, not completion:** `independent final assessment` belongs to the **earliest exposed** entry for that `holdout_id` in the lineage; every entry allocated after an exposure is `reused holdout`, including a completed second use after a partial or failed first one, re-evaluations of a candidate, and assessments by siblings; an entry that never exposed anything is `void · never exposed`, keeps its number and does not make later entries reused. The label is derived from the ledger at read time, never stored. The panel adds the qualifier "within this lineage's tracked research history" and lists other lineages whose ledgers hold the same `holdout_id` ("also assessed by <lineage> on <date>"), since independence across lineages cannot be established by the Lab. The ledger travels with the root through trash and restore (§9.2) and is never edited.
- **No silent influence on later optimization.** (1) `bars_for` refuses `final` without an unseal record naming the trial, and refuses the final range for every other purpose; (2) `.final/` and the ledger are read only by `lab/final_oos.py`, `lab/lineage.py` and `lab/verify.py`: an import-boundary test asserts that `lab/analytics.py`, `lab/query.py`, `lab/neighbours.py`, `lab/robustness.py`, `lab/pareto.py`, `lab/variables.py`, `lab/searchspace.py` and `lab/folds.py` import nothing from `final_oos` and open nothing under `.final/` or `.holdout/`; (3) every experiment, proposal or focus created on the lineage after its ledger's first exposure carries `lineage.after_unseal = use_no`, shown as `post-unseal` on H, G and D; **`apply` re-reads the ledger at apply time and refuses any proposal when the lineage has an exposure, whenever the proposal was created**; a post-unseal child may run (research continues) but its own final OOS is a reuse by definition; (4) the audit log records each submission state change and each evaluation.

**Holdout policy (printed on the panel):** a sealed holdout is an independent final assessment only until any of its results has been exposed. Any later evaluation is a reused-holdout assessment and is labelled so; it is never shown as fresh independent validation.

### 10.2 Leakage rules (scenario 13 tests)

1. `partitions.bars_for(document, purpose, unseal=None)` is the **only** function that slices bars for Lab work. Purposes `stage1`, `screening` and `block` get the selection range (a block is a sub-range of it); `stage3` gets a validation fold's window with warm-up from history; `diagnostic` gets a selection-period window for the labelled diagnostics of §10.3; `final` gets the final range, and only with a valid unseal record whose candidate list contains the trial.
2. Warm-up for any later range uses prior history through the `evaluate_from` mechanism (§7.3a for the metrics path). Bars before the range are used for warm-up only, never scored.
3. A candidate is promoted only by an explicit operator action, recorded with `{from_stage, to_stage, trial_id, at}`. No code path auto-promotes.
4. **Repeated unsealing is allowed, counted and labelled** (§10.1): the ledger's `use_no` increments, and after the first exposure every final-OOS number carries `reused holdout`.
5. Legacy experiments have no partition. Their views say "no partition: in-sample only", and stages 3–4 are unavailable for them until a partitioned child is created.
6. **Default partition (Q10):** trailing 60 / 20 / 20 by bars: the first 60 % of the range is selection, the next 20 % validation, the last 20 % final OOS, sealed at experiment creation. The planner shows the three bar counts and dates; the operator may move the two boundaries before the experiment starts, never after.
7. Screening blocks (§7.3) subdivide the selection range only; a block never overlaps validation or final.

### 10.3 Stage 3: candidate folds (R-7)

The existing studies (Mission 8) re-optimize a surface in each window and compare plateau, peak and frozen-centre rules (`studies.py:293, 616`); they do not evaluate a fixed list of candidates. Stage 3 therefore has two parts, shown separately and never merged:
- **Candidate fold evaluation (new, Phase 6):** `CandidateFoldsJob`, a `JobRunner` kind in `lab/folds.py`, takes `candidates: [trial_id]` (each with a stage-2 base replay) and the experiment's `partition.validation = {kind: "folds", n}`, which splits the **validation partition alone** into `n` equal, contiguous test windows (default n = 4); the "train" span of a fold is everything before its window and is informational for a fixed candidate. Each candidate is evaluated on each window with the full engine, `evaluate_from` at the window start with warm-up from prior history, fresh `initial_capital` per window, no carried positions (as experiments never carry), and the final range excluded by `bars_for("stage3")`. Fixed candidates were chosen on the whole selection partition, so **no selection-period window ever enters a validation summary**: the validation headline, the per-fold table, the OOS-decay figure and category C's fold evidence use validation folds only. Windows inside the selection period (the screening blocks of §7.3a, or `n_diag` equal windows over selection) may be shown as **"selection-period diagnostics (in-sample)"** in their own panel, marked with the overlap, and `test_selection_windows_never_in_validation_summaries` pins the separation. Results are one run document per (candidate, window) under `runs/` (`partition: "fold"` or `"diagnostic"`, `fold_no`, `artifact_sha256`) plus a summary in `experiments/<id>.folds/<job>.json`; Screen F's `FoldMatrix`, the stitched curve and the per-fold table read them. **The stitched curve** concatenates the folds' per-bar *returns* (each fold normalized to its own starting capital), so it is a chain of fresh-capital segments, labelled "stitched from fresh-capital folds; not a continuous account".
- **Rolling re-selection (existing):** a Mission 8 study on the experiment's surface, labelled "rolling re-optimization (procedure evidence)", unchanged, with the optional `candidates` field only to link it from a candidate card.
- **Tests (Phase 6, `test_lab_folds.py`):** a fold's metrics equal a direct `run_backtest` of the same candidate on the same window with `evaluate_from` (parity); no fold reads past the validation end or before the validation start except for warm-up; selection-period windows never appear in validation summaries; fresh capital per fold; the stitched curve equals the concatenated normalized segments; the job refuses candidates without a stage-2 replay; the summary reconciles with the run documents.

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
| **0. Decisions and prerequisites** (docs and tooling only) | Randall reviews A–H and this plan; signs the §22 checklist; Mission 14 merged; brief and thesis copied into `docs/superpowers/specs/`; a repo-tracked lint script `tools/lint_aegis.sh` replacing the scratchpad one (Q9), which finds the repository root from its own path so it lints the worktree it lives in, not `C:\Triad` | docs; `tools/lint_aegis.sh` | none | none | the lint script runs on the worktree | — |
| **1. Lab shell** | `optlab` page, sub-nav, Screen B layout with real regions bound to existing experiment endpoints (report main effects, cells page); dock `Expand Lab`; honest "not built" / "unavailable" states; `state/lab.tsx` store; keyboard model; **Screen H's `WorkflowStrip`** (R7): the six steps Define → Screen → Evaluate → Propose → Approve → Monitor visible from the first build, steps 2–6 disabled with "available after Phase 4" | `ui/src/App.tsx`, `SideNav.tsx`, `state/workspace.tsx` (Page), new `ui/src/lab/*` (`LabPage`, `LabContextBar`, `ParameterCatalog`, `TrialTable`, `IntelligenceRail`, `WorkflowStrip`, `labStore.ts`), `OptimizationTab.tsx`, `styles.css` | none | none | vitest: `labStore` (selection, filter_hash, pins, persistence across sub-views), `trialWindow` (row windowing math), `workflowStrip` (step states) | 103 Lab opens from Expand Lab with axes / metric kept; 104 sub-nav keeps filter and selection; 105 every unavailable control says why; 106 1672 × 941 and 1440 × 900 with no clipped primary control; 126 H's workflow strip shows all six steps with the later ones disabled and explained |
| **2. Trial store and query layer** | layout 2 (trial_no, positions, param_key over the full effective set, status, `design`, `block`, compaction, manifest with merged-chunk retention, snapshots as immutable file sets, reclamation, §9.2); attachments and `ExperimentReferenced`; pinned resume with vintage / engine checks; `LabCache`; `/lab` summary / query / trials; views counts, matrix (exact + aggregate), page, top, marginals; optimizer source adapter; `engine_build`; dock `n` overlays and mode label; the scratch harness (§9.8: `tools/start_aegis_scratch.ps1`, walk `--port` / `--data-root` / `--pid-file`, the destructive-item refusal); **2b**: `sharpe_trade` per scope beside, not inside, the hash-bearing metrics (§7.12), with `_side_metrics` returning the `ret` view as an added value, and the DSR functions with their reference tests; **2c, the functional vertical slice** (R7): a real 12,000-trial LHS experiment on the §9.1b benchmark strategy, created through the API on the scratch worker, flowing through `LabHeatmap` (exact + aggregate) → `ParallelCoords` (bundle mode, brought forward from Phase 3) → `TrialTable` → shared filters and brushing → pins → linked counts → `ParameterCatalog` → sub-nav B ↔ E ↔ D without losing state; `lab_benchmark.py` with `explore` (Track A) and `execute` (Track B) modes | new `app/products/aegis/lab/{__init__,store,cache,query,sources,policy,identity,sharpe}.py`; `experiments.py` (layout 2 write, compaction, retention, reader, chunk naming fix F16, `data_pinned`, `design`, `block`, pinned resume), `runs.py` (attachments, `ExperimentReferenced`), `api.py` (router include, resume path), `preferences.py` (`AEGIS_DATA_ROOT` override, §9.8), `pool.py` + `backtest.py` (2b: `lab_metrics`, `ret` return value), `results.py` untouched; `tools/start_aegis_scratch.ps1`, `tests/products/aegis/browser_workstation.py` (arguments); `ui/src/lab/{LabHeatmap,ParallelCoords}.tsx` (canvas), `Heatmap.tsx` (n overlay, hatch); `ui/src/lab/charts/canvas.ts` (scales, axes, brush, hit grid, hover, DPR) | none (new layout only for new experiments; legacy untouched) | none | `test_lab_store.py` (compaction torn / idempotent; `test_readers_see_one_set_during_compaction`; `test_reopen_older_snapshot_after_later_generations`; dedupe by `(trial_no, block, attempt)`; legacy read equals today's `cells()`; `test_unreadable_chunk_never_overwritten`; data root override; `test_experiment_attachments_travel_with_trash_and_restore`; `test_resume_refuses_vintage_drift`; `test_resume_refuses_engine_build_drift`; `test_legacy_resume_unchanged`), `test_lab_query.py` (exact slice empty = untested; aggregate n / IQR; `test_lab_undefined_metric_counts`; `test_lab_query_empty_scope`; filter_hash; count invariants incl. evaluations), `test_lab_sharpe.py` (§7.12 table), `test_walk_refuses_destructive_items_on_product_root`, vitest `labHeatmap` (empty, one-axis, losses-red scale), `parallelBundles` (bin math, brush → filter), `test_lab_identity.py` (param_key over the full effective set; stable across surfaces), `tests/products/aegis/lab_benchmark.py`; golden + identity unchanged; **independent QA of the compaction writer, reclamation and `--decompact` (§12)** | 107 exact slice with no match shows untested, no value; 108 aggregate square opens a distribution and cannot be pinned; 109 counts identical across heatmap, table and header; **110 brush updates heatmap, parallel, table and counts coherently on the real 12k experiment; 104 re-run on it (vertical slice, checkpoint R2.5)** |
| **3. Linked analytics** | screening `blocks = K` on experiments with warm-up and the scoring mask (§7.3a: `run_metrics` / `_side_metrics` gain `evaluate_from`; `pool._run_cell` passes the block start with prior history); `design`-based row selection; importance with the three uncertainties (bootstrap, blocks, permutation floor), fine-grid incremental shares `Δ`, the single coarse decomposition (mains, pairs, all triples on q = 4) with the residual veto and candidate-only triple intervals, Cramér's V aliasing that disables the rule (§7.3–7.4a); the four robustness categories with per-unit-time rules, `peak` vs `robust` rankings and `CandidateCard` (§7.6); Pareto; exact-mode parallel coordinates; convergence; `lab_benchmark.py analytics` beside a running job; Screens B tabs and E | `lab/{analytics,robustness,neighbours,pareto,parallel,tasks}.py`; `experiments.py` (`blocks` in the plan and the job's units); `backtest.py` (`evaluate_from` on the metrics path, default unchanged); `pool.py` (block evaluation); `ui/src/lab/{ParetoView,ImportanceView,InteractionMatrix,RobustnessView,CandidateCard,Trellis,NeighbourhoodMap,ConvergenceChart}.tsx`; `ui/src/lab/charts/*` | none | none (§12) | `test_lab_analytics.py` (the sixteen cases of §20; `test_refinement_rows_excluded`; `test_stale_then_rescreen_refreshes_evidence`; `test_interval_coverage_known_variance`; `test_permutation_floor_scales_with_bins`; `test_rule_unavailable_when_aliased_or_adaptive`), `test_lab_blocks.py` (`test_block_metrics_equal_full_engine_with_evaluate_from`; `test_warmup_contributes_no_trades_or_equity`; `test_configuration_identity_across_blocks` through compaction, resume, retry, materialization and reconciliation; `test_canonical_attempt_after_retry_across_compacted_files`), `test_lab_robustness.py` (A unresolved on untested surroundings; a fully tested corner resolves; B never labelled A; isolated peak needs coverage; C constant-per-unit-time across validation folds is consistent; blocks alone leave C unresolved and cannot change it; D resolves on sub-year replays without MAR; rankings disagree → both shown), `test_lab_pareto.py` (2-D / 3-D against brute force); goldens unchanged with `evaluate_from=None`; vitest for bundle drawing math, brush → filter mapping, the candidate card's tested / unknown states | 111 spike vs plateau labelled, with the category and its inputs; 112 20-variable fixture: families, search, trellis, maximize, count-preserving drill-down; 124 a candidate card shows four categories with tested / unknown states and the reason for each |
| **4. Screen H and 20 parameters** | `MAX_PARAMETERS` 10 → 20; identity beyond int64 (positions-based LHS / refine); structural relevance; statuses, events, §7.4a proposals (own-direction triples; availability by product-design provenance), `Review Before Apply`, apply → child with the ledger re-read at apply time; focus (pair / triple investigation); stale detection incl. range and sampler; budgets: shares summing to 100, the six counts, `PUT /lab/{exp}/budget` (R5); the `WorkflowStrip` wired live | `surface.py` (cap, positions-based sampling), `experiments.py` (focus / child, reuse by `inputs_key`, budget shares), new `lab/{structure,variables,searchspace}.py`; `ui/src/lab/{VariableIntelligence,InfluenceView,InteractionExplorer,ProposalPanel,EvidenceRail,SpaceContextBar,BudgetStrip}.tsx` | none (new attachment `<id>.searchspaces/`) | none | `test_lab_structure.py` (rules 1–4; active never excluded), `test_lab_variables.py` (transitions, reasons, restore, frozen ≠ excluded, stale on hash / data / range / partition / sampler, `test_ai_note_never_actor`, `test_insufficient_coverage_is_unresolved`, `test_deprioritize_requires_all_six_conditions`), `test_lab_searchspace.py` (Cartesian before / after as Decimal; apply keeps strategy hash; reuse counted; `test_budget_shares_sum_to_100`; `test_budget_counts_invariant`; `test_reallocation_only_while_paused_keeps_space_version`), `test_lab_grid_beyond_int64_keeps_trial_identity`; existing `test_aegis_surface.py` unchanged for ≤ 10 | 113 structural exclusion shows its proof trail; 114 XOR pair and a three-way triple survive into Investigate; 115 restore and explore-any-pair in ≤ 2 interactions, filters kept; 116 budget labels "theoretical", the six counts reconcile and the shares sum to 100 |
| **4b. Indicator mission** (its own spec, §11.2; Q3 + Q4) | `HA_MQI`, `EWO`, `ROCKET_RSI` and `REGIME` kinds; a `regime` tag on trades only when a strategy carries REGIME; a built-in reference strategy combining the first three | `kinds.py`, `indicators.py`, `backtest.py` (tag only when present), `contracts.ts`, builder palette, `strategies.py` built-ins | none | none | one golden per kind; `test_aegis_engine_golden.py`, `builder_identity.py` and every saved strategy hash unchanged | palette and one backtest per kind; scenario 2's real ten-variable sweep |
| **5. Partitions, funnel, Run Monitor, Compare and the final OOS** | experiment partitions; `partitions.bars_for`; stage-2 replays with cost scenarios; per-trial failure isolation + retry-failed; `run_log`; Screen D (incl. `BudgetStrip` with evaluations beside configurations); Screen C (compare three, materialize on demand); **stage 4 complete (R4)**: `lab/final_oos.py` with the submission state machine (idempotency resolved first, `JobRunner.reserve()` as the atomic admission point, ledger-first allocation under an OS file lock, reconciliation before serving), the lineage-wide holdout ledger and `holdout_id`, identity checks, `FinalOosJob` as a `JobRunner` kind, persistence as runs with `artifact_sha256`, labels derived from the ledger, post-unseal lineage marks; `FinalOosPanel` on C and D | `experiments.py`, `pool.py` (error isolation), `jobs.py` (the new kind and `reserve()`), `runs.py` (`artifact_sha256` on new run documents), new `lab/{partitions,replays,monitor,final_oos}.py`; `ui/src/lab/{RunMonitor,FunnelStrip,CountsHeader,WorkerPanel,CandidateCompare,UnsealDialog,FinalOosPanel}.tsx` | none (additive fields; `.final/` records; the root's `.holdout/` ledger) | none | `test_lab_partitions.py` (screening refuses final; blocks inside selection only; warm-up not scored; promotion only explicit; uses counted), `test_lab_replays.py` (cost scenarios; replay hash = materialize hash), `test_lab_failures.py` (failed trial isolated; retry idempotent; reconciliation invariants), `test_lab_final_oos.py` (`test_submission_*`: fault injection after the record, after the ledger and after submit; duplicate and concurrent requests; a busy runner refused before any use; reconciliation from every state; a candidate without a stage-2 base replay refused; identity fields stored and a tampered spec fails the `strategy_hash` check; results persisted as runs with `result_hash` and `artifact_sha256`; ledger: sibling unseals share one counter, a descendant created before the first unseal is `reused` on its later unseal, failed and partial assessments count; the `.final/` and `.holdout/` import boundary; a mutation check that `bars_for("final")` without a record raises) | 117 four-stage funnel boundaries; 118 cancellation + resume + retry reconcile counts; 119 A/B/C ids and values identical in table, heatmap, parallel, charts and export; 125 unseal → evaluation → `independent final assessment`; a second unseal, on the same or a sibling experiment → `reused holdout` on C, D, G and in the export |
| **6. Walk-forward, lineage and forensics** | **stage 3** (§10.3): `CandidateFoldsJob` in `lab/folds.py` evaluating fixed candidates on validation folds only (selection-period windows as labelled diagnostics) with fresh capital and the scoring mask, results as runs; Screen F on folds + partitions (fold matrix with the sealed bar, stitched equity, final-range equity, the DSR panel with its cohort and heuristic scenarios); the Mission 8 study as the separate rolling view; Screen G lineage (React Flow) with `post-unseal` badges and the ledger, saved views, experiment diff, audit trail, provenance with the two named checks (artifact digest; pinned rerun), trade evidence | `studies.py` (optional `candidates`), `jobs.py` (`CandidateFoldsJob`), new `lab/{folds,lineage,verify,events,views}.py`; `ui/src/lab/{WalkForwardView,FoldMatrix,MultipleTestingPanel,LineageGraph,AuditTrail,ProvenancePanel,ExperimentDiff}.tsx` | none | none | `test_lab_folds.py` (fold metrics equal `run_backtest` with `evaluate_from` on the same window; folds inside the validation partition; `test_selection_windows_never_in_validation_summaries`; fresh capital per fold; the stitched curve; candidates without a replay refused; summary reconciles with the run documents), `test_lab_lineage.py` (incl. `root`, `after_unseal`, the ledger), `test_lab_verify.py` (digest mismatch quarantines read-only; legacy says `not recorded`; a rerun mismatch is reported, never quarantined; final and fold runs verified), `test_lab_events.py` (append-only; reconstructed legacy) | 120 parent → child → trial → candidate with hashes and stable filters; 121 fold matrix from the candidate folds, window × leg, sealed-OOS explanation and the reuse label |
| ~~**7. Strategy Gate**~~ | **Dropped (Q1 = not now).** The sketch (a versioned research policy; metrics recomputed from the raw trades of a materialized run; `strategy_hash`, `inputs_key` and data sha checked; a verdict with per-check evidence) stays in §12 for a later decision | — | — | — | — | 122 becomes: validation controls disabled and labelled `not built`; no AI route can write any state |
| **8. AI explanations (optional, after Mission 14)** | rail "AI explains · gate decides" via Mission 14's Core product-reasoning route; text only; never actor | Aegis caller only if the route fits as-is; **any Core change = shared infrastructure (§12)** | none | none | Aegis tests with a stub route | 123 AI text visibly separate; no state change from AI |
| **Milestone** | Track A: the synthetic 1M walk; Track B: the 100,000-trial real-engine run recorded on the host (§9.1c); verify.ps1 on main; independent milestone QA | — | — | — | scenarios 11, 12 and 24 timings recorded with the host | full walk |

### 11.1 Compatibility rules

- Legacy experiments open in the Lab through the same reader, with `trial_no = cell`, `block = 0`, `design` inferred from `pass`, no partition and no statuses. The existing report (median main effects, plateaus, clusters) is reproduced identically for the same rows (test); the Lab's new estimators (§7.3–7.4) are additional and labelled, and are not expected to equal the report's medians.
- Optimizer jobs open read-only through `opt:` sources. The dock's existing behaviour, ids and walk items 1–97 stay unchanged.
- `ExperimentDocument` gains optional fields only. `contracts.ts` regenerates (`test_aegis_contracts.py`).
- Run envelopes, `canonical_payload`, `strategy_hash`, the engine goldens, `builder_identity.py` and `study_identity.py` are unchanged in every phase.

### 11.2 The indicator mission (after Phase 4; its own spec, not a Lab phase)

Randall's answers to Q3 and Q4 add a separate mission between Phase 4 and Phase 5, brainstormed and specified on its own in the pattern of Missions 5 and 13:

- **Four indicator kinds** in `kinds.py` and `indicators.py`: `HA_MQI`, `EWO`, `ROCKET_RSI` and `REGIME`. Each declares its outputs, pane, inputs, default length, warm-up, parameters and integer parameters exactly as the existing kinds do, so the surface, the grid validity tables, the contracts and the builder pick them up without any Lab change.
- **Definitions come from Randall's thesis** (*HA-MQI Trading Framework: Working Thesis, Operating Rules, and Indicator Definitions*, `C:\Users\fordr\Documents\HA_MQI_Trading_Framework_Thesis.docx`, received 2026-10-27; Phase 0 copies it beside the brief as `docs/superpowers/specs/2026-10-27-ha-mqi-trading-framework-thesis.md`). The mission's spec pins them exactly; in short:
  - *Heikin Ashi:* `HA_Close = (O + H + L + C) / 4`, `HA_Open(t) = (HA_Open(t−1) + HA_Close(t−1)) / 2`, `HA_High = max(H, HA_Open, HA_Close)`, `HA_Low = min(L, HA_Open, HA_Close)`; the input series is the body midpoint `S = (HA_Open + HA_Close) / 2`.
  - *HA-MQI* (`HA_MQI`, outputs `value` and `smooth`): `r(t) = ln(S(t) / S(t−1))`; `MQI(t) = Σ_{i=0}^{N−1} r(t−i) / (σ_r(t, N) · √N)`; `smooth = SMA(MQI, M)`; current settings N = 10, M = 10. The framework enters on `value crosses_above smooth` and hard-exits on `crosses_below`, treating the cross as a state change.
  - *RocketRSI* (`ROCKET_RSI`, Ehlers): `momentum(t) = Close(t) − Close(t − (L − 1))`; `filter = SuperSmoother(momentum, cutoff)`; `raw = Σ Δfilter / Σ |Δfilter|` over L bars; clamp to ±0.999; `0.5 · ln((1 + raw) / (1 − raw))`; current L = 10, cutoff = 8. The thesis reads it as "below −2 within the last 10 bars", so the kind also exposes a rolling-minimum output (`low_k`, k a parameter) that the existing operators can test.
  - *Elliott oscillator* (`EWO`): `EMA_fast(Close) − EMA_slow(Close)`, current 5 / 20 (not the classic 5 / 35 of median price). The thesis uses it as a compression / phase filter ("fast and slow close together", and `EWO < 0.5` as a macro reset), so the kind exposes a numeric compression output (the mission defines it, e.g. `|EWO|` relative to ATR) that a rule can reference.
  - *REGIME* stays the mission's own design question: deterministic from price alone, numeric outputs, trend / range and a volatility tercile as candidates.
  - Details the thesis leaves open, each settled in the mission with a hand-computed golden: `σ_r` with ddof 0 or 1; the first `HA_Open` seed; the SuperSmoother coefficients; the numeric definition of "compressed".
- **A `regime` tag on trades** (the REGIME value at entry), written only when the strategy carries a REGIME indicator, in the pattern of Mission 13's `exit_reason`: every existing strategy's trades serialize byte-identically, so no stored hash moves. The Lab's regime × window breakdowns (C, F) read that tag.
- **A reference strategy**, the thesis's framework on the **1D** timeframe, saved as a built-in document beside `ema9-sma30-cross-v1`: entry `HA_MQI.value crosses_above HA_MQI.smooth` AND `price.close greater_than ema9` (the one-bar blocker) AND `ROCKET_RSI.low_k less_than −2` AND the EWO compression condition; exit `HA_MQI.value crosses_below HA_MQI.smooth` or the stop; the short side mirrored. Ranged parameters: N, M, RocketRSI length / cutoff / threshold / lookback k, EWO fast / slow / compression, the EMA length and the stop percentage (≈ 11), so scenario 2's real ten-variable sweep and Screen H's reading of those three run on real data.
- **Outside the indicator mission, flagged for separate decisions:** the thesis's adaptive *Chandelier stop* (an ATR trailing stop armed on RocketRSI decay that only tightens) and its *RocketRSI size modifier* are engine changes (exit kinds and allocation live in `backtest.py` / `kernel.py`), not indicator kinds; the *event calendar* block (earnings ± 2 days, Fed, NFP) needs a feed the product lacks (F4). None of them is in this plan; the reference strategy uses the stop / target levels and the clock windows that exist, and the Lab shows event controls as `feed unavailable`.
- **Tests:** one golden per kind against a hand-computed fixture; `test_aegis_engine_golden.py`, `builder_identity.py` and every saved strategy hash unchanged; contracts regenerated; walk items for the builder palette and one backtest per kind.
- **Blast radius:** Aegis-only. Phase 5 may run on its own branch beside it, since they touch different files; the Lab's regime states switch from "not in this strategy" to live once a strategy carries REGIME.

## 12. Shared-infrastructure register and dependency reviews

Under `AGENTS.md`, no item in Phases 1–6 is shared infrastructure. All of it is under `app/products/aegis/`, its tests and its docs. The following items **would** be shared infrastructure; each needs the named Core tests and independent QA.

| Item | Why shared | If chosen: Core tests | QA |
|---|---|---|---|
| A Strategy Gate owned by Core (Q1 option b; not chosen on 2026-10-27, kept for a later decision) | governance / contract that products consume | `TRIAD_PYTEST_SCOPE=core .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` over the new module + `tests/test_architecture.py` + `tests/test_product_*` isolation tests | independent QA + Core governance review |
| Any gate output read by a paper / live path | live-money / risk limits | n/a (excluded: Exchange CLOSED) | — |
| Any change to Mission 14's Core route for Phase 8 | provider authority / shared contract | `tests/test_core_product_reasoning*.py`, `tests/test_intelligence_routing.py` | independent QA |
| A new Python package (e.g. scipy, duckdb) | environment-level: both lock files + Core-owned `tests/test_environments.py:31,45-46` | `tests/test_environments.py`, `tests/test_pytest_scope.py`, `tools\verify.ps1` all scopes | measured blocker surfaced first |
| Changing what `result_hash` covers (e.g. Sharpe inside metrics) | retained canonical data | n/a (Aegis-owned), but treated as retained-data change | independent QA |
| Compacting or rewriting existing experiments | retained data | — | explicit operator approval + independent QA |
| The layout-2 compaction writer, merged-chunk reclamation and the `--decompact` tool | they rewrite and delete experiment cell files: retained data under AGENTS.md even for new experiments | n/a (Aegis-owned) | **mandatory independent QA at R3**, not optional (Codex R-14) |
| Moving the store to a NAS | storage / provenance infrastructure | Core storage tests if Core is involved | operator decision |

**Charting decision (R7).** Every visualization was weighed against the costs the review named: axis transformations, brushing, hover inspection, keyboard navigation, accessibility, zooming, cross-view synchronization, hit testing and large-dataset aggregation.
- *Hand-written Canvas 2D* for the five data-heavy views (heatmap, parallel coordinates, Pareto, convergence, sampling histograms), behind one shared primitive module `lab/charts/canvas.ts` (linear / ordinal scales, axes, a 1-D axis brush, a hover hit grid, a keyboard cursor, device-pixel scaling, resize). Aggregation is server-side (§9.3), so hit testing is over ≤ 40,000 squares, ≤ 2,000 bundles or ≤ 2,000 points; zoom is replaced by axis-range filters; cross-view sync is the store (§5). This matches the codebase, where every non-price chart is already hand-written.
- *Accessibility:* Canvas is opaque to assistive technology, so every chart has a DOM twin (the `page` view and a one-line live-region summary such as "heatmap 16 × 17, best at …"), and the keyboard model of §5.2 operates the store, not the pixels.
- *SVG* (the existing pattern) for small charts: sparklines, the fold matrix, equity compare, histograms ≤ 200 bars. *DOM* for tables. *React Flow* (installed) for the lineage graph.
- *Reuse without a new dependency:* `Heatmap.cells()` tones and the losses-red rule; `resample_curve`; `LibraryCompare` parts. `d3-zoom` / `d3-selection` / `d3-interpolate` are only transitive through React Flow and are not imported directly (a transitive import is a hidden dependency).
- *Decision criteria at R2.5:* the primitives stay if they are ≤ 800 lines, pass walk 106 (keyboard, contrast, no clipping) on the vertical slice and keep every interaction inside the §9.6a UI budget; otherwise the `uplot` review opens before Phase 3. Vela and the workstation shell are not replaced in either case.

**JS dependency candidates.** Not adopted; a review is required before use.

| Candidate | Purpose | Licence | Reason not now |
|---|---|---|---|
| `@tanstack/react-virtual` | table virtualization | MIT | a fixed-height window is ~60 lines; adopt only if variable row heights are needed |
| `uplot` | fast line / scatter with brushing, hover and zoom on Canvas; no dependencies; ≈ 45 KB | MIT | **the fallback (R7):** adopted through this review only if, at checkpoint R2.5, the hand-written `lab/charts/canvas.ts` primitives exceed 800 lines or fail walk 106's keyboard or contrast checks on the vertical slice |
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
- **Not Lab phases, though decided:** the HA-MQI, EWO, RocketRSI and REGIME indicator kinds are the separate indicator mission after Phase 4 (§11.2, Q3 and Q4), with their own spec, goldens and review, defined from Randall's thesis.
- **Not decided, from the thesis:** the Chandelier stop (a new exit kind), the RocketRSI size modifier (allocation) and the event-calendar block (a feed). Each is an engine or data change with its own review (§11.2).
- **Excluded trading and data work:**
  - an event / news feed;
  - new data downloads or canonical data promotion.
- **Excluded samplers, models and claims:**
  - Bayesian or TPE samplers and surrogate models;
  - interpolation or smoothing of untested cells;
  - continuous (step-less) parameters;
  - probability-of-better-region-if-stopped claims.
- **Not computed:** an annualized time-series Sharpe (Q2 chose per trade; §7.12 labels it `not computed`); interaction estimators above the third order (the residual is a veto, §7.4).
- **Excluded infrastructure:** multi-machine workers; core-hour accounting beyond this host; signatures on audit records; multi-user authorship.
- **Live trading, paper trading, broker paths and any deployment eligibility.**
- **Rewriting existing data:** existing runs, optimizations or experiments; converting legacy experiments to layout 2.
- **Replacing Vela, the engine, the Strategy Lab builder or the experiment store.**

## 14. Open questions, answered by Randall on 2026-10-27

Each one changed UI behaviour or calculation meaning. The answers are the operator's words; the "Applied as" column says what the plan does with them.

| # | Question | Answer | Applied as |
|---|---|---|---|
| Q1 | No Strategy Gate exists. Build one? (a) Aegis-owned research gate (product code; verdict = "passes research policy vN", no execution meaning), (b) Core-owned (shared contract, independent QA), (c) not now (UI says "not built") | "default" = (c) | No gate in this plan; Phase 7 dropped; `Strategy Gate: not built` everywhere; sketch kept in §12 |
| Q2 | Sharpe: which definition? (a) daily mark-to-market returns, annualized √252, needs per-bar equity from the kernel, (b) per-trade return ratio, labelled "trade Sharpe". Either is stored beside, not inside, hash-bearing metrics. DSR needs it too. | "per trade" = (b) | §7.12 `sharpe_trade` and DSR; Phase 2b |
| Q3 | HA-MQI / EWO / RocketRSI: a separate indicator mission (definitions, goldens) before or after Lab Phase 4? | "add after phase 4.. add each one as an indicator. combine them in a strategy" | §11.2 indicator mission after Phase 4: one kind each, a built-in reference strategy combining them |
| Q4 | Regimes: define a deterministic regime classifier as its own mission, or keep "not available"? | "make a regimes indicator that can be added if desired" | REGIME indicator kind in §11.2, optional per strategy; "not in this strategy" until then |
| Q5 | The dock's square was decided as "best of the rest only, no median view" on 2026-10-20. The brief asks min / median / mean / max. Reverse that decision for the dock? | "use your discretion" | Dock keeps best-of-rest, labelled; the Lab offers best / median / mean / worst (§7.2) |
| Q6 | Approve the initial policy constants: `AGG_MIN_N 8`; TVD 0.25; `IMPORTANCE_ROWS 50k`; bootstrap 200; 90 % intervals; θ_main = θ_int = 0.01; pair coverage 0.5; residual veto 0.3; plateau coverage 0.5; budget split 30 / 48 / 22 + 5 % reserve; stage-2 K = 20; slippage×1.5 pass rule; the §9.6 latency / memory thresholds | "yes" | All in `lab/policy.py`; §9.6a are the scenario 11 pass thresholds; `SHARPE_MIN_TRADES 20` added by Q2. **Two corrections after the architecture review need re-approval (§22):** the budget split becomes 30 / 45 / 20 / 5 (the approved 30 / 48 / 22 + 5 summed to 105 %, R5), and the importance-analytics task budget becomes ≤ 180 s in total with the fine-grid stage within 30 s (blocks, the coarse decomposition, the permutation null and the coarse bootstrap; R1 and Codex R-13). The constants R1 and R3 add are listed in §22 |
| Q7 | May Lab analytics run while an experiment job runs (sharing the laptop's CPU), or wait? | "yes" | §9.4: concurrent, one task at a time, yielding between resamples |
| Q8 | Visual acceptance width: the brief's 1672 × 941, the designs' 1440, or both? | "both" | Walk 106 and every phase's screenshots at 1672 × 941 and 1440 × 900 |
| Q9 | Commit a repo-tracked Aegis lint script (the current one lives in a past session's scratchpad and lints `C:\Triad`, not the worktree)? | "repo" | Phase 0 commits `tools/lint_aegis.sh` |
| Q10 | Final OOS default: the last 20 % of the range by time (designs show 20 %), with selection 60 % / validation 20 %? | "good for now" | §10 rule 6: trailing 60 / 20 / 20 by bars, boundaries movable only before the start |
| Q11 | Storage: the 1M fixture and real 1M experiments need ~0.35 GB each on a 59 GB-free disk. Any cap, or the NAS first? | "disk for now. test data can be deleted" | §9.8: fixture on disk at a scratch root, deleted after the milestone; warn below 10 GB free |

## 15. Acceptance tests: the brief's 22 scenarios, extended to 30 (R1–R7)

Names are the test functions or walk items the phases add. "Phase" is where each is first green. Rows 1–22 are the brief's scenarios, retained; rows 23–30 come from the architecture review.

| # | Scenario | Proof | Phase |
|---|---|---|---|
| 1 | 30-SMA / 9-EMA crossover, small exhaustive grid, known selection, linked consistency | `test_lab_query::test_reference_crossover_grid_matches_optimizer` (Lab on `opt:` and on an experiment of the same grid give the same squares and best); walk 109 | 2 |
| 2 | Ten-variable sweep, sparse 400 and dense 10,000+, repeated axis / filter changes with exact counts | `test_lab_query::test_counts_stable_under_axis_and_filter_churn` (property test, 200 random filter / axis sequences on fixtures of 400 and 12,000 trials, existing kinds); walk 112; after §11.2, the same walk on the real HA-MQI / EWO / RocketRSI reference strategy | 2–3, then 4b |
| 3 | Exact slice with no matching trials | `test_lab_query::test_exact_slice_empty_is_untested`; walk 107 | 2 |
| 4 | Aggregated cell, median and distribution, not executable | `test_lab_query::test_aggregate_square_stats`, vitest `labStore.aggregateNotPinnable`; walk 108 | 2 |
| 5 | Sharp best vs stable cluster; peak and robust rankings compared | `test_lab_robustness::test_isolated_peak_vs_stable_local`, `test_rankings_shown_side_by_side`; walk 111 | 3 |
| 6 | Train vs OOS, distinct metrics, no leakage | `test_lab_partitions::test_stage1_reads_selection_only`, `test_objective_never_reads_final` | 5 |
| 7 | Long / short asymmetric parameters and event windows | `test_lab_query::test_scope_long_short_independent` (asymmetric fixture); `test_lab_query::test_unavailable_windows_not_neutral`; walk 121 | 2, 6 |
| 8 | A / B / C pins identical everywhere and in export | vitest `labStore.pinsCarryIds`; walk 119 compares ids / values / metric versions across table, heatmap, parallel, charts, export JSON | 5 |
| 9 | Duplicate / failed / partial trials, unavailable indicator data, broken metrics, cancellation | `test_lab_failures::*`, `test_lab_store::test_lab_compaction_torn_is_idempotent`, `test_lab_query::test_lab_undefined_metric_counts`; walk 118 | 2, 5 |
| 10 | Validation blocked until the gate; no AI override | Q1 = not now: walk 105 shows `not built` and disabled validation controls; `test_lab_variables::test_ai_note_never_actor` proves no AI text changes any state; walk 122 | 1, 4 |
| 11 | 1M synthetic (Track A): server-side filter / sort / page, density, concurrent progress, memory ceiling, responsiveness, no million-node rendering, cold / warm timings and hardware | `lab_benchmark.py explore` (records host + timings vs §9.6a); milestone walk on `lab_fixture` (DOM rows ≤ 1,500, response bounds, long-task observer ≤ 50 ms) | 2, milestone |
| 12 | Million-trial status reconciliation, snapshots, resume, cancel, retry idempotency | `test_lab_failures::test_reconciliation_invariants` (fixture with every status), `test_retry_idempotent`; walk 118 | 5 |
| 13 | Four-stage funnel boundaries; leakage and improper promotion fail; the final OOS submission is durable and recoverable | `test_lab_partitions::test_promotion_only_explicit`, `test_final_requires_unseal`, `test_unseal_uses_counted`; `test_lab_final_oos::test_submission_*`; walk 117 | 5 |
| 14 | 20 mixed variables: families, search, trellis, brushing, linked selection, maximize, count-preserving drill-down | `test_lab_query::test_drilldown_preserves_counts`; walk 112 on the 20-parameter fixture | 3–4 |
| 15 | Lineage and provenance: parent → child → trial → candidate, hashes, stable filters, trade log | `test_lab_lineage::*`, `test_lab_verify::*`; walk 120 | 6 |
| 16 | Walk-forward matrix from the candidate folds, window × regime, long / short, sealed-OOS explanation, deterministic status | `test_lab_folds::*`, `test_lab_partitions::*`; walk 121 (regime rows present only when the strategy carries REGIME, §11.2; otherwise "not in this strategy" asserted) | 6 |
| 17 | Visual QA: readable labels, contrast, keyboard, nothing clipped at 1672 × 941 or narrower; compared with the UX Pilot screen | walk 106 (bounding boxes inside viewport; computed contrast ≥ 4.5:1 for status and secondary text; keyboard path through every tab; a side-by-side image against the design export per screen; every panel's empty state exercised; selections synchronized across panels asserted) | 1, each phase |
| 18 | Structural relevance: inert excluded with evidence; active never excluded by a wrong heuristic | `test_lab_structure::test_rule_{1..4}`, `test_signal_param_not_excluded`, `test_referenced_param_never_excluded` (property over random rule trees); walk 113 | 4 |
| 19 | Interaction trap (XOR) and conditional triple survive screening | `test_lab_analytics::test_case_2_xor_pair_investigate`, `test_case_3_three_way_investigate` (incremental shares and the coarse triple screen); walk 114 | 3–4 |
| 20 | Status transitions, evidence, restore, warnings, counts; excluded ≠ frozen; any valid pair explorable | `test_lab_variables::*`; walk 115 | 4 |
| 21 | Search-space reduction budget recomputes; reduced space ≠ trials saved | `test_lab_searchspace::test_cartesian_before_after`, `test_labels_theoretical`; walk 116 | 4 |
| 22 | Scope / time stability: stale on change; final OOS never drives elimination | `test_lab_variables::test_variable_status_stale_on_strategy_hash_change` (+ data / range / partition / sampler), `test_lab_partitions::test_screening_refuses_final`, `test_post_unseal_proposal_blocked` | 4–5 |
| 23 | **R1: the sixteen statistical cases** (§20 table): strong first-order; XOR; three-way only; aliased parameters; uneven sampling; sparse coverage; pure noise; one-block regime; range change; correlated inputs; coarse-bin cancellation; higher-order structure; own-direction triples; jointly dependent inputs; a weak constraint; outcome-dependent missingness | `test_lab_analytics::test_case_{1..16}_*`: each a seeded synthetic generator with the expected status and the expected reason string | 3–4 |
| 24 | **R2: Track B execution benchmark** on the real engine: 10,000 trials at three bar counts and 100,000 at one; the costed ten-parameter strategy on both sides; trials per second, worker memory, chunk writes, compaction, resume reads, concurrent Lab queries; measured vs the cell-bar model | `lab_benchmark.py execute` writes the §9.1b table for the host; pass thresholds §9.6b; the §9.1c triggers re-run it | 2, milestone |
| 25 | **R1: insufficient coverage is unresolved, never low** | `test_lab_variables::test_insufficient_coverage_is_unresolved` (a sparsely covered parameter cannot be proposed Deprioritized and is listed last with its coverage); walk 114 asserts the "unresolved" chip | 3–4 |
| 26 | **R3: four robustness categories** on a candidate card with tested / unknown states; B never shown as A; isolated peak needs coverage; stable region preferred when the evidence supports it | `test_lab_robustness::test_sparse_region_never_reported_as_local`, `test_unresolved_when_untested`, `test_four_category_states`; vitest `candidateCard.testedUnknown`; walk 124 | 3 |
| 27 | **R6: Sharpe and DSR reference cases**; `sharpe_trade` never shown alone; annualized Sharpe labelled not computed | `test_lab_sharpe.py` (the §7.12 table); vitest `candidateTable.sharpeNeverAlone`; walk 121 asserts the labels | 2b, 6 |
| 28 | **R4: final OOS workflow**: a durable submission (busy refusal, idempotency, lock-serialized `use_no`, reconciliation); identity and version checks; persistence as runs with `result_hash` and `artifact_sha256`; the lineage-wide ledger deciding `independent` then `reused holdout`, siblings included; post-unseal lineage; the `.final/` and `.holdout/` import boundary | `test_lab_final_oos::*` (§11 Phase 5); walk 125 | 5 |
| 29 | **R5: budget arithmetic**: shares sum to 100; the six counts reconcile; reallocation only while paused, for unscheduled trials, keeping the search-space version | `test_lab_searchspace::test_budget_shares_sum_to_100`, `test_budget_counts_invariant`, `test_reallocation_only_while_paused_keeps_space_version`; walk 116 | 4 |
| 30 | **R7: the functional vertical slice** on a real 12,000-trial experiment: heatmap → parallel coordinates → table → shared filters and brushing → pins → linked counts → catalog → navigation without losing state | walk 110 and 104 on the real experiment at the end of Phase 2c; checkpoint R2.5 | 2c |

Gate 3 parity:
- Lab metrics equal the trusted calculation: `materialize` identity (existing) on a sample of Lab trials per phase, and the stage-2 base replay's `result_hash` for every candidate.
- Screenshots are compared to the UX Pilot output (side-by-side images in the walk report, both widths).

## 16. Reviewer checkpoints

| # | When | Who | Pass condition |
|---|---|---|---|
| R0 | Now | Codex / MC Architecture Review (plan review) | Facts in §1/§3 verified against the repo; the seven revisions R1–R7 addressed (§18); no unreviewed migration, engine replacement or gate authority change |
| R1 | Before any code | Randall | All eight UX views reviewed and aligned with the locked mock; the §22 checklist signed, including the two corrected numbers (budget split, Lab task budget) |
| R2 | End of Phase 1 | Randall (screenshots, walk 103–106, 126) | Shell matches approved designs; honest states; no clipped controls; H's workflow strip shows the whole sequence |
| **R2.5** | **End of Phase 2c (vertical slice)** | **Randall + builder; Codex optional** | The full interaction loop works on a real 12,000-trial experiment (scenario 30); the canvas primitives met the §12 criteria, or the `uplot` dependency review is opened before Phase 3 |
| R3 | End of Phase 2 | builder + Randall + **independent QA, mandatory for the compaction writer, reclamation and `--decompact` (§12)**; Codex optional | §9.6a Track A budgets met on the synthetic benchmark; §9.6b Track B thresholds met at 10,000 trials on the host; legacy reads identical; goldens unchanged; the Sharpe / DSR reference tests green |
| **R3.5** | **End of Phase 3** | **builder + independent QA (statistical fixtures)** | The sixteen §20 cases green with their reasons; `lab_benchmark.py analytics` within ≤ 180 s beside a running job, the job's throughput loss recorded; the four robustness categories' tests green; block parity tests green |
| R4 | End of Phase 4 | **independent QA** (statistical claims) | Scenarios 18–23, 25, 29 green; the sixteen R1 cases pass with their expected reasons; statuses never change OOS use |
| R4b | End of the indicator mission (§11.2) | Randall (definitions) + builder; independent QA recommended for HA-MQI, whose definition has no public reference | One golden per kind; every existing golden and saved hash unchanged; the reference strategy backtests on real data |
| R5 | End of Phase 5 | **independent QA** (leakage boundaries, holdout reuse) | Scenario 13 tests fail on an injected leak (mutation check); scenario 28: a second unseal is labelled `reused holdout` on every surface and in exports; scenario 26 D states from replays |
| R6 | Phase 8, if chosen | **independent QA + Core governance** if Core-touching (§12) | Core tests named in §12 green |
| R7 | Milestone | independent milestone QA + whole-branch review; `tools\verify.ps1` on main | All 30 scenarios; full walk at both widths; Track A and Track B numbers recorded with host details; the 100,000-trial real run recorded |

## 17. The brief's plan-review checklist

| Checklist item | Where answered |
|---|---|
| All eight views (A–H) reviewed and aligned with the locked screenshot | §2 (all exist, unreviewed); R1 |
| One-million-trial journeys from job start to validation | §5.4 D → §5.2 B → §5.5 E → §8 H → §10 funnel → §5.3 C → §5.6 F → §5.7 G; gate per Q1 |
| Measurable latency, memory and throughput criteria | §9.1a / §9.1b measured (two tracks); §9.6a / §9.6b thresholds; §9.1c verified vs estimated |
| Vectorized exploration separated from costed replays and final validation | §10 (noting stage 1 is already costed, F8) |
| Variable selection evidence-backed, revisable, scope / version aware; any valid pair explorable | §7.3–7.5, §8 |
| Every UI box tied to a data source and a deterministic test | §5, §15 |
| No unreviewed migration, engine / chart replacement or Strategy Gate authority change | §11.1, §12, F1 |
| An early functional vertical slice before every visualization (review R7) | §11 Phase 2c; checkpoint R2.5; scenario 30 |

## 18. Revision summary (Deliverable B)

| Finding | Original approach | Revised approach | Affected phase | Verification |
|---|---|---|---|---|
| **R1** Statistical variable intelligence | First-order η², a pairwise interaction residual, a row bootstrap, coverage thresholds; an empirical `Deprioritized` proposal on two conditions; three-way checks on request | §7.3–7.4a: the ANOVA framing; **incremental shares `Δ_{i\|j}`** instead of the interaction residual as the rule input; a **coarse screen over all 1,140 triples**; the residual as a **veto only**; **three uncertainties** (the row bootstrap labelled conditional on this data; `K` screening blocks for period uncertainty; a permutation detection floor for finite samples); Cramér's V aliasing; a minimum of rows per value; **six conditions** for deprioritization, operator-confirmed, reversible, evidence-scoped; insufficient coverage is `unresolved`, never low; evidence never crosses ranges | 3, 4 | `test_lab_analytics` sixteen cases (scenario 23); `test_insufficient_coverage_is_unresolved` (25); `test_deprioritize_requires_all_six_conditions`; walk 114 |
| **R2** One-million-trial execution verification | One §9 mixing a synthetic 1M-row query benchmark with a cell-bar throughput formula taken from 252-cell experiments | §9 split into **Track A** (exploration, synthetic rows) and **Track B** (execution, the real engine): 1,000 / 10,000 / 100,000 trials on real QQQ bars at three bar counts, a costed ten-parameter strategy on both sides, with and without concurrent Lab queries; an affine time model; a verified-vs-estimated statement; re-test triggers; the Sharpe overhead measured (≈ 0.2 % of a trial, +46 bytes per row) and kept in stage 1 | 2, milestone | `lab_benchmark.py execute` (scenario 24); §9.6b thresholds; checkpoints R3 and R7 |
| **R3** Robustness classification | One grid-neighbourhood rule (r, m) with coverage ≥ 0.5, a P25 ranking and a one-off-peak flag | §7.6: **four categories** A local / B sampled-region / C temporal / D execution, each resolved with a classification or unresolved with a reason; B never reported as A; an isolated peak only with coverage; `peak` and `robust` rankings side by side; `CandidateCard` states what was tested and what is unknown | 3, 5 | `test_lab_robustness` (scenario 26); walk 124 |
| **R4** Final OOS workflow ownership | An unseal record in Phase 5; "final runs in stage 4" with no owner, API, identity or persistence defined | §10.1: **Phase 5 owns stage 4 end to end**; unseal = evaluation in one call (`FinalOosJob`); candidate identity (trial_id, param_key, strategy_hash, spec_version, stage-2 run and hash, engine_build); append-only records under `.final/`; results as runs with `result_hash`; four verification steps; `FinalOosPanel` states; `use_no` with the `independent` / `reused holdout` labels; post-unseal lineage marks; a `.final/` import boundary | 5, 6 | `test_lab_final_oos` (scenario 28) incl. the import-boundary and mutation tests; walk 125 |
| **R5** Search budget arithmetic | 30 / 48 / 22 plus a 5 % reserve = 105 % | **30 / 45 / 20 / 5 = 100 %**, validated; six counts defined in §6.4 with invariants; reallocation only in a new proposal or on a paused experiment for unscheduled trials, keeping `search_space.version` and bumping `sampler.revision` with an event | 4 | `test_budget_shares_sum_to_100`, `test_budget_counts_invariant`, `test_reallocation_only_while_paused_keeps_space_version` (scenario 29); walk 116 |
| **R6** Sharpe and DSR validation | Per-trade Sharpe defined; the DSR formula stated; N = unique trials | §7.12: trade vs annualized Sharpe distinguished and labelled (`annualized Sharpe: not computed`); never shown alone; DSR moments, units and undefined cases pinned; both independence assumptions printed with a lag-1 autocorrelation flag; the research-history cohort as the headline with two heuristic sensitivity scenarios (neither bounds nor ordered); Φ⁻¹ refined and checked against an independent bisection and published quantiles; fourteen reference cases | 2b, 6 | `test_lab_sharpe.py` (scenario 27); vitest `sharpeNeverAlone` |
| **R7** UX implementation strategy | Eight screens phased; Canvas charts decided in §12 without criteria; Screen H wired only in Phase 4 | §11 **Phase 2c vertical slice** on a real 12,000-trial experiment with checkpoint R2.5; §12 charting decision with explicit criteria and the `uplot` fallback review; H's `WorkflowStrip` in Phase 1 showing the whole six-step workflow; visual acceptance extended (design comparison per screen, empty states, synchronized selections, both widths) | 1, 2c, 3 | scenario 30; walk 126 and 106 extended; checkpoint R2.5 |

**Codex round 1 (2026-10-27, `gpt-6.1-sol`, read-only, session `01a17e9b-9359-7a61-a647-012c6746a86b`) returned REVISE with fourteen items; each is applied in place:** R-1 block-aware identity, dedupe and budgets → §6.1, §6.3, §6.4, §7.3a; R-2 one coherent coarse decomposition, unresolved triples block, candidate-only triple intervals, new fixtures → §7.3–7.4a, §20 cases 10–12; R-3 re-screen eligibility by sampling design → §6.3 `design`, §7.3, §7.5, §8.5; R-4 durable submission, busy refusal, idempotency, reconciliation → §10.1; R-5 holdout identity and the lineage ledger → §6.2, §6.5, §10.1; R-6 artifact digest vs pinned rerun → §5.7, §10.1; R-7 stage 3 as `CandidateFoldsJob` → §10, §10.3, §11 Phase 6; R-8 the scoring mask on the metrics path → §7.3a, §11 Phase 3, §19; R-9 snapshots as immutable file sets with retention → §9.2; R-10 the scratch harness → §9.8, §11 Phase 2; R-11 per-unit-time robustness rules, attainable neighbourhood support, no MAR → §7.6; R-12 DSR cohort, heuristic scenarios, skew direction, refined Φ⁻¹, published references → §7.12; R-13 the analytics budget and its benchmark → §9.4, §9.6a; R-14 attachments, reuse by value, `ExperimentReferenced`, pinned resume, mandatory QA for compaction → §9.2, §12, §16; minor items → §9.1c, §11 Phase 0, §11.1.

**Codex round 2 (same session) returned REVISE with eight items and five consistency fixes; each is applied:** item 1 own-direction triple rule and case 13 → §7.4, §7.4a, §20; item 2 availability by product-design provenance, the residual sign check, cases 14–15 → §7.3, §7.4a, §20 (round 3 extended it to the analysis cohort: missingness = 0 for the chosen metric, case 16); item 3 idempotency first and `JobRunner.reserve()` → §10.1, §19; item 4 ledger-first allocation under an OS lock and reconciliation before serving → §10.1; item 5 the label follows the earliest exposure, void uses, apply re-reads the ledger → §10.1, §8.5; item 6 validation-only folds, selection-period diagnostics, the stitched curve → §10.3, §7.6; item 7 two-step attempt canonicalization → §7.3a, §6.4, §9.2; item 8 non-positive baselines in C and D, the skew condition at `SR − SR₀` → §7.6, §7.12; consistency: §22 (DSR scenarios, C rule), §21 (busy refusal, lost job), §9.4 and §16 (R3.5 at the end of Phase 3; per-block intervals), §9.2 attachments (`.folds`, real paths, `.searchspaces` under the experiment), `artifact_sha256` defined over the document without its own field.

**Codex round 3 (same session) returned REVISE with two items, both applied:** the availability contract now covers the analysis cohort (every configuration must have a finite observation of the chosen metric in every required block; missingness counts and reasons printed; case 16) → §7.3, §7.4a, §20; screening blocks are removed from category C's predicate and become a separate `selection-period consistency` finding, with tests that blocks alone leave C unresolved and cannot change it → §7.6, §11 Phase 3, §20. The editorial leftovers it listed ("DSR band", R3 for R3.5, the case count) are aligned.

**Codex round 4 (same session, `01a17e9b-9359-7a61-a647-012c6746a86b`) returned APPROVED:** "R1–R7 are adequately addressed at Gate 1 … The plan is ready for Randall's §22 approval. Implementation performance and correctness remain subject to the specified tests and QA checkpoints." Its one nonblocking wording fix (§21, the screening-blocks row) is applied. Codex modified no files and claimed no test pass; the review was static, read-only.

**Preserved capabilities (review §9), where each lives:** exact and aggregated heatmap modes (§7.1–7.2); no interpolation of untested trials (global constraints, §7.1); full-size parallel coordinates (§5.5, §7.9); parameter interaction explorer (§8.3); Pareto analysis (§7.7); robustness landscape (§7.6, §5.5); candidate A/B/C comparison (§5.3); regime and temporal-window investigation (§5.3, §5.6, §11.2); fold-by-fold walk-forward analysis (§5.6); optimization convergence / history (§7.10, §5.4); trade-level investigation (§5.7); provenance and experiment lineage (§5.7, §6.2); Screen H variable intelligence (§8); manual inspection of any valid parameter pair (§7.5, §8.3); reversible variable statuses (§8.4); independent long / short analysis (§6.3, §5.3); tested vs sampled vs estimated labels (global constraints, §7.9); explicit incomplete-data states (§5 conventions, §7.3, §7.6); versioned search spaces (§8.5); preservation of existing experiments and result hashes (§11.1, §7.12). The Strategy Gate stays out of scope (Q1); no Core, broker or paper-trading work is touched.

## 19. Implementation dependency review (Deliverable C)

**Newly required dependencies: none**, Python or JS. The permutation null, blocks, the coarse triple screen, DSR and Acklam's Φ⁻¹ are numpy and `math`. One candidate is held in reserve under the §12 review: `uplot` (MIT), opened only if the R2.5 criteria fail.

**Existing modules that must change (all Aegis-owned):**

| Module | Change | Why | Pinned by |
|---|---|---|---|
| `backtest.py` | `_side_metrics` returns the `ret` view (`trades[:n_trades, 9]`) as an added value; `run_metrics` / `_side_metrics` gain an optional `evaluate_from` that builds the kernel's scoring mask (default `None`: byte-identical today); Phase 4b's `regime` tag only when present | §7.12, §7.3a | `test_aegis_engine_golden.py`, `test_aegis_kernel.py`, real-archive identity scripts |
| `pool.py` | `_run_cell` adds `lab_metrics` per scope; block evaluation passes `evaluate_from` with the frame's prior history instead of a cold slice; per-trial error isolation (Phase 5) | §7.12, §7.3a, §9.5 | `test_aegis_pool.py`, `test_aegis_experiments.py` |
| `experiments.py` | layout 2 write / read, chunk naming (F16), `data_pinned`, `engine_build`, `block` units (`blocks = K`), focus / child, reuse by `inputs_key`, budget shares, `run_log` | §6, §7.3, §8.5, §9.2 | legacy-read equality test; existing experiment tests |
| `surface.py` | `MAX_PARAMETERS` 10 → 20; positions-based LHS / refinement beyond int64; the planner's pricing unchanged | §6.1, §8.6 | `test_aegis_surface.py` unchanged for ≤ 10 |
| `jobs.py` | two new kinds, `FinalOosJob` and `CandidateFoldsJob`; a `reserve(kind, owner)` admission token that holds the single slot under the runner's own lock (`jobs.py:103-105`) and is released when not converted; the one-unfinished-job rule unchanged and **no queue**: `JobBusy` is refused to the operator before any holdout use is consumed | §10.1, §10.3 | `test_aegis_jobs.py` |
| `api.py`, `runs.py`, `preferences.py` | the `/lab` router; layout-2 resume through `load_pinned` with `engine_build` checks (legacy resume unchanged); the attachment list extended to the new folders; `ExperimentReferenced`; `artifact_sha256` on new run documents; the product-only `AEGIS_DATA_ROOT` override with an unchanged default | §5.10, §9.2, §9.8, §10.1 |
| `tools/start_aegis_scratch.ps1` (new), `tests/products/aegis/browser_workstation.py` | an Aegis-only scratch launcher with a PID file; walk arguments `--port` / `--data-root` / `--pid-file` and the destructive-item refusal | §9.8 | `test_aegis_api.py`, a data-root override test |
| `studies.py` | optional `candidates` | §6.5 | `study_identity.py` |
| UI: `App.tsx`, `SideNav.tsx`, `state/workspace.tsx`, `OptimizationTab.tsx`, `Heatmap.tsx`, `styles.css`, `contracts.ts` (regenerated) | the Lab page, dock labels and overlays | §5 | vitest, `test_aegis_contracts.py`, walk 1–97 unchanged |
| `tests/products/aegis/browser_workstation.py` | items 103–126 (after Mission 14's 98–102) | §15 | — |

**Compatibility risks:** legacy experiments must read identically through the new reader (tested); `ExperimentDocument` gains optional fields only and `contracts.ts` must regenerate; `FinalOosJob` shares the single runner slot; the `AEGIS_DATA_ROOT` default must equal today's `DATA_ROOT/"data"/"aegis"`; Phase 1 must follow the Mission 14 merge (F12); walk numbering must not collide with Mission 14's uncommitted items.

**Performance risks:** screening blocks multiply a screening experiment's cost by `K + 1` (priced and shown as evaluations; off by default for non-screening sweeps); the staged importance task is ≈ 25 s + 1.2 s + 60 s at d = 20 (budget ≤ 180 s, cached, yielding to the job; measured beside a running job at R3.5, `B_c` and `P` reduced first if missed); `LabCache` at 400 MB against ≈ 2.5 GB free; sustained engine throughput is below short-burst throughput on this laptop (§9.1b); concurrent Lab queries cost about a fifth of the engine's throughput (measured, §9.1b); the first chunk of every job carries ≈ 11 s of worker start-up (spawn, JIT, first indicators); the compaction pause at 1M (≤ 10 s, one unit).

**Research-integrity risks and their controls:** trade Sharpe read as comparable across strategies (labels; never alone; frequency printed); a single DSR taken as a verdict (the research-history cohort with heuristic scenarios; inputs printed; never pass / fail); bootstrap intervals read as period uncertainty (labelled conditional; blocks added); deprioritization mistaken for exclusion (six conditions; reversible; the research principle printed); holdout reuse shown as fresh validation (`reused holdout` label everywhere; the lineage-wide ledger; append-only records); a local use counter mistaken for lineage-wide independence (the ledger decides, siblings included, with the "within this lineage" qualifier); research after an unseal (post-unseal badges; proposals blocked); screening evidence applied across ranges or samplers (stale); the optimizer `opt:` source has no partitions (labelled in-sample); legacy experiments lack data hashes (`not recorded`, never `verified`).

**Work that can remain deferred:** the Strategy Gate (Q1); an annualized time-series Sharpe; estimators above the third order; TPE / Bayesian samplers and surrogates; regimes until the indicator mission (4b); an event feed; the NAS move; DuckDB beyond 10M rows; multi-host workers; AI explanations (Phase 8).

## 20. Updated acceptance tests (Deliverable D)

The retained 22 scenarios and the eight new ones are mapped in §15. The deterministic tests the review asked for, by area:

**Statistical (R1), `test_lab_analytics.py`, sixteen cases, each on a seeded synthetic experiment of 8–20 parameters, 5,000 uniform rows (plus 4 blocks where stated), with the expected status *and* the expected reason string asserted:**

| Case | Generator | Expected |
|---|---|---|
| 1 strong first-order | `Y = 3·x₁ + ε` | `x₁`: `Active · detected`, `S₁` upper ≫ θ_min; the noise parameters are proposable `Deprioritized` (all six conditions hold) |
| 2 XOR | `Y = 2·[(x₁ > m) XOR (x₂ > m)] + ε` | `S₁`, `S₂` below the floor; `Δ_{1\|2}` upper ≫ θ_min; both `Investigate · interaction not ruled out`; never proposable |
| 3 three-way only | `Y = 2·parity(x₁ > m, x₂ > m, x₃ > m) + ε` | mains and pairs below the floor; the coarse triple's `Δ` upper > θ_min; all three `Investigate · three-way effect not ruled out` |
| 4 aliased | `x₂ = x₁ + small jitter` by construction; `Y = 3·x₁ + ε` | Cramér's V > 0.3 → both `aliased · credit shared`; neither proposable |
| 5 uneven sampling | rows drawn with `P(x₁ = v) ∝ v`; `Y = 3·x₂ + x₁·x₂ + ε` | the (x₁, x₂) squares are flagged `confounded?` (TVD > 0.25); `Δ_{1\|2}` upper > θ_min → `x₁` not proposable |
| 6 sparse coverage | `x₁` has 40 values, 8 of them present | `Insufficient coverage · unresolved`, listed last with its coverage; proposal impossible |
| 7 pure noise | `Y = ε`, 20 parameters | every share below the floor; the residual veto is raised; **no proposal is made**; every status `Active · not detected`; the warning "unexplained share high: noise or higher-order structure" |
| 8 one-block regime | `Y = 3·x₁` in block 2 only, `0` elsewhere, `blocks = 4` | block range `[≈ 0, high]` → `x₁`: `Investigate · period-dependent`; never proposable |
| 9 range change | `Y = 3·max(0, x₁ − 0.8·range) + ε`; a re-screen on `x₁ ∈ [0, 0.7·range]` | on the wide range `x₁` is detected; on the narrow range its old evidence is `stale`, not reused, and the fresh `S₁` from the re-screen's uniform rows is below the floor; the status is scoped to the range it came from |
| 10 correlated inputs | a validity constraint `x₂ ≥ x₁ + 2` correlates the design; `Y = 3·x₁ + ε` | Cramér's V > 0.3 → both `aliased · credit shared`; `empirical deprioritization unavailable: aliased inputs`; no proposal for any parameter |
| 11 coarse-bin cancellation | `Y = sin(8π·x₁ / range) + ε` | the coarse `S₁^c` ≈ 0 (cancels within q = 4 bins) while the fine `S₁` is detected → condition 1 fails on the fine grid; `x₁` stays `Active · detected` |
| 12 higher-order structure | `Y = 2·parity(x₁ > m, x₂ > m, x₃ > m, x₄ > m) + ε` | mains, pairs and triples ≈ 0; the residual's lower bound > 0.3 → veto raised; no proposal; the warning "structure not captured by mains, pairs and triples" |
| 13 own-direction triple rule | independent inputs, `Y = 3·x₁ + ε`, candidate `x₂` | in triple (x₁, x₂, x₃) `Δ_{1\|23}^c ≈ 1` but `Δ_{2\|13}^c ≈ 0`: `x₂` is proposable (Codex round 2, item 1) |
| 14 pairwise-independent, jointly dependent | three independent binary inputs and `x₄ = x₁ XOR x₂ XOR x₃`, fed as rows of a surface whose grid has skipped cells (`x₄` is defined by a validity table) | `empirical deprioritization unavailable: inputs are not a product design`; the fine-grid lists still work |
| 15 weak constraint below the alias threshold | a validity constraint skipping 2 % of the grid, Cramér's V ≈ 0.2 | not `aliased`, yet `unavailable: inputs are not a product design (2 % of the grid is invalid)` with the freeze / narrow hint |
| 16 outcome-dependent missingness | an unconstrained Cartesian sample where `profit_factor` is undefined (no losing trades) exactly when `x₁` is high and `x₂` is low | after the undefined rows are dropped the remaining inputs are dependent; `unavailable: 1,240 of 5,000 configurations have no finite profit_factor (0 invalid, 0 failed, 1,240 undefined)`; the descriptive estimates carry "on 3,760 of 5,000; missingness may bias"; switching the metric to `net_pnl` makes the rule available |

Plus `test_refinement_rows_excluded` (adaptive rows change nothing), `test_stale_then_rescreen_refreshes_evidence`, `test_rule_unavailable_when_aliased_or_adaptive`, `test_interval_coverage_known_variance` (90 % interval covers the true share in ≥ 85 of 100 seeds) and `test_permutation_floor_scales_with_bins`.

**Blocks and identity (R-1, R-8), `test_lab_blocks.py`:** one configuration across its `K + 1` evaluations through compaction, resume, retry, materialization and reconciliation; a failed attempt followed by a successful retry across overlapping compacted files yields one canonical `ok` evaluation; block metrics equal the full engine with `evaluate_from`; warm-up contributes no trades and no scored equity.

**Storage (R-9, R-14), `test_lab_store.py`:** concurrent readers see one file set during compaction; an older pinned snapshot reopens after later generations; attachments travel with trash and restore; resume refuses vintage and engine-build drift; legacy resume unchanged.

**Performance (R2):** `lab_benchmark.py explore` (Track A, synthetic 1M rows) and `lab_benchmark.py execute` (Track B, the real engine at 10,000 trials × three bar counts and 100,000 × one), both writing a JSON record with host details, compared with §9.6a / §9.6b by `test_lab_benchmark_record` (a unit test over the record format and the thresholds, not a timing test).

**Robustness (R3), `test_lab_robustness.py`:** untested surroundings → A unresolved with the coverage printed; a sampled-only surface → B resolved, A unresolved, the card never says "local"; an isolated peak needs coverage ≥ 0.5; validation folds → C, while blocks alone leave C `unresolved · selection-period only` and changing them cannot change C; cost scenarios → D; rankings that disagree are both returned; every classification carries its inputs.

**Final OOS (R4), `test_lab_final_oos.py`:** the submission state machine under fault injection after the reservation, the ledger append, the record and the submit, with a duplicate request while the original runs, two concurrent unseals in one lineage, an unseal racing an ordinary job for the slot, and a busy runner refused before any ledger entry; reconciliation from every state before any request is served, including the ledger-only crash (the consumed number is skipped) and a stale lock file; the label follows exposure: a partial first use followed by a completed second use keeps use 1 `independent` and use 2 `reused`, and a never-exposed first use is `void` so the next exposed one is independent; a proposal created before an exposure is refused at apply time; a candidate without a stage-2 base replay is refused; identity fields are stored and a tampered spec fails the `strategy_hash` check; results persist as runs whose `result_hash` and `artifact_sha256` verify; the ledger allocates `use_no` lineage-wide (sibling unseals, a descendant created before the first unseal, failed and partial assessments) and the label flips from `independent` to `reused`; post-unseal experiments and proposals are marked and proposals cannot be applied; the `.final/` and `.holdout/` import boundary (AST scan of `lab/*.py`); the mutation check that `bars_for("final")` without a record raises.

**Stage 3 (R-7), `test_lab_folds.py`:** fold metrics equal a direct backtest with `evaluate_from`; folds lie inside the validation partition and selection-period windows never enter validation summaries; fresh capital per fold; the stitched curve equals the concatenated normalized segments; the summary reconciles with the run documents.

**Budgets (R5), `test_lab_searchspace.py`:** shares sum to 100 or the proposal is refused; the six counts satisfy `scheduled + remaining + reserved = budget_total` on fixtures with reuse, focus and rescreen; reallocation is refused while running and keeps `search_space.version`.

**Sharpe / DSR (R6), `test_lab_sharpe.py`:** the eleven cases of §7.12.

**UX (R7):** scenario 30 (the vertical slice on real data), walk 126 (the workflow strip), walk 106 extended (design comparison, empty states, synchronized selections, both widths).

## 21. Residual risks (Deliverable E)

| Risk | Severity | Mitigation / decision needed |
|---|---|---|
| Period uncertainty costs `K + 1` evaluations per screened set; an operator who turns blocks off loses the per-block importance intervals (§7.4a condition 1 then cannot be met) and the selection-period diagnostics; category C itself depends on validation folds, not on blocks | High | Blocks default on for screening experiments (K = 4) and off for large sweeps; when off, the panel says "period uncertainty: not measured" and no deprioritization proposal is possible. **Decision: confirm the default (§22).** |
| The effective number of strategies for DSR has no single correct estimate | High | The research-history cohort as the headline with heuristic sensitivity scenarios, inputs printed; never a verdict; the DSR panel text says so |
| Sustained engine throughput on this laptop is well below short-burst throughput (§9.1b), so projections from short benchmarks overstate | High | Projections use the sustained rate from the 100,000-trial run; the Run Monitor shows the measured live rate; hardware is Randall's call (the 2026-10-21 NAS note) |
| Canvas charts are opaque to assistive technology | Medium | DOM twins and live-region summaries; the keyboard model operates the store; R2.5 criteria; `uplot` fallback does not remove this risk either |
| `FinalOosJob` shares the single runner slot: a final evaluation cannot start while an experiment runs | Medium | Refused with 409 before any ledger entry exists, naming the running job; the operator pauses or waits (§10.1) |
| The coarse triple screen (q = 4) can miss fine-grained three-way structure | Medium | The residual veto; `Investigate triple` focus child; the coarsening is printed |
| Importance analytics at d = 20 take ≈ 90 s per snapshot (fine stage 25 s, coarse bootstrap 60 s) while sharing CPU with a job; unmeasured beside a heavy job | Medium | Staged delivery; cached per snapshot; one task at a time; yields between resamples; the budget is ≤ 180 s (needs re-approval, §22); measured beside a running job at R3.5, `B_c` and `P` reduced first if missed |
| The holdout ledger is per lineage; two lineages on the same data can each claim an independent assessment | Medium | The label carries "within this lineage's tracked research history" and the panel lists other lineages with the same `holdout_id`; cross-lineage independence is explicitly not claimed |
| `CandidateFoldsJob` is new engine-adjacent work | Medium | Parity tests against `run_backtest` with `evaluate_from`; the existing studies stay untouched as the rolling view |
| The runner has no queue: a final evaluation or a folds job is refused while an experiment runs | Low | `JobRunner.reserve()` decides atomically; refused before any ledger entry exists, with the running job named |
| `AEGIS_DATA_ROOT` is new surface area in product code | Medium | Default unchanged and tested; used only by the fixture worker |
| A lost `FinalOosJob` | Medium | Reconciliation before serving re-submits the candidates without a persisted result under the same `use_no`; the label follows the first exposure, so a partial first use stays the independent one (§10.1) |
| HA-MQI, RocketRSI and EWO are defined by Randall's thesis, not by a public reference; `σ_r`'s ddof, the HA seed, the SuperSmoother coefficients and "compressed" are unspecified | Low | The indicator mission pins each with a hand-computed golden (§11.2); Phase 0 copies the thesis into the repo |
| The thesis's Chandelier stop, size modifier and event calendar are not indicator kinds | Medium | Named as separate decisions (§11.2, §13); the reference strategy runs without them, which the mission's spec states |
| Legacy experiments cannot be data-verified | Low | `not recorded`, never `verified` |
| Walk item numbers collide with Mission 14's uncommitted items | Low | Phase 1 after the merge; items start at 103 |

**Decisions not hidden in tasks:** (1) re-approve the corrected budget split 30 / 45 / 20 / 5; (2) re-approve the ≤ 180 s Lab task budget (fine-grid stage within 30 s); (3) confirm screening blocks default on (K = 4); (4) accept the `uplot` fallback criteria, or forbid the dependency outright; (5) confirm the final-OOS exposure rule (the earliest exposed assessment is the independent one; never-exposed uses are void) and the reconciliation rule for a lost job; (6) the REGIME definition and the four unspecified details of the thesis's indicators are the indicator mission's design questions; (7) the Chandelier stop and the RocketRSI size modifier are engine changes needing their own decision; (8) the busy-refusal rule (no job queue) for final evaluations.

## 22. Approval checklist (Deliverable F)

Randall approves, by signing this list, exactly the following and nothing more:

- [ ] **Architecture:** experiments as the Lab's base; an Aegis-owned `lab/` query layer; the eight screens A–H; phases 0, 1, 2 (+2b, +2c), 3, 4, 4b, 5, 6, 8 and the milestone; Phase 7 (Strategy Gate) dropped. Core untouched in every phase.
- [ ] **R1 statistics (§7.3–7.4a):** empirical evidence can only deprioritize, under six conditions, operator-confirmed and reversible; structural exclusion only with a proof; insufficient coverage is unresolved; blocks default K = 4 for screening, priced and shown as evaluations = configurations × 5, with the scoring mask on the metrics path; empirical deprioritization unavailable under aliasing or adaptive-only rows; unresolved triples block; constants `θ_min = 0.01`, `B_c = 50`, permutation floor at the 95th percentile with P = 200, bootstrap B = 200, `IMPORTANCE_MIN_PER_VALUE = 20`, `TRIPLE_TOP = 20`, `RESIDUAL_VETO = 0.3`, aliasing at Cramér's V > 0.3.
- [ ] **R2 verification (§9):** Track A and Track B kept separate; the §9.6b thresholds; the verified-vs-estimated statement; the re-test triggers; the Sharpe computation stays in stage 1.
- [ ] **R3 robustness (§7.6):** four categories with resolved / unresolved states; `REGION_RADIUS = 0.15`, `REGION_AXES = 6`, `REGION_MIN_N = 30`; C consistent only when every validation fold keeps a positive per-1,000-bar P&L within [0.5×, 2×] of the full range's with drawdown ≤ 1.5×, and `not profitable` resolutions for non-positive baselines; D's 70 % / 1.3× hold rule on a positive base; peak and robust rankings side by side.
- [ ] **R4 final OOS (§10.1, §10.3):** Phase 5 owns stage 4 as a durable submission (idempotency resolved first, atomic runner admission, ledger-first `use_no`, reconciliation before serving); the lineage-wide holdout ledger decides `independent` for the earliest **exposed** assessment and `reused holdout` for everything allocated after an exposure, siblings and partial first uses included, everywhere; `JobRunner.reserve()` as the admission point; ledger-first allocation under an OS lock; post-unseal badges; stage 3 as `CandidateFoldsJob` in Phase 6 beside the unchanged studies.
- [ ] **R5 budgets (§8.5):** 30 / 45 / 20 / 5, replacing the 30 / 48 / 22 + 5 approved under Q6; the six counts and their invariant; reallocation rules.
- [ ] **R6 Sharpe / DSR (§7.12):** per-trade Sharpe labelled and never alone; `annualized Sharpe: not computed`; DSR over the research-history cohort as the headline with two heuristic sensitivity scenarios that are neither bounds nor ordered; never a verdict.
- [ ] **R7 UX (§11, §12):** the Phase 2c vertical slice and checkpoint R2.5; Canvas-first with the stated `uplot` criteria; H's workflow strip from Phase 1; acceptance at 1672 × 941 and 1440 × 900 with design comparison.
- [ ] **Lab task budget:** the staged importance task ≤ 180 s in total, the fine-grid stage within 30 s (replacing the 30 s approved under Q6); measured beside a running job at R3.5.
- [ ] **Code boundaries:** no new dependency; `_side_metrics` gains a return value and `run_metrics` / `_side_metrics` an optional `evaluate_from` (default unchanged); `pool._run_cell` gains `lab_metrics` and block evaluation; `jobs.py` gains `FinalOosJob`, `CandidateFoldsJob` and `reserve()`; `runs.py` gains attachments (incl. `.folds` and `.searchspaces`), `ExperimentReferenced` and `artifact_sha256`; layout-2 resume goes through `load_pinned`; `tools/start_aegis_scratch.ps1` and the walk arguments; reuse by value; `AEGIS_DATA_ROOT` with an unchanged default; result hashes, goldens and legacy experiments unchanged; independent QA on the compaction writer at R3.
- [ ] **Unchanged:** Exchange CLOSED, live trading disabled, no Strategy Gate, no broker or paper-trade path, no Core change; Mission 14 merges before Phase 1; the indicator mission (4b) is specified separately from Randall's thesis (§11.2); the thesis's Chandelier stop, size modifier and event calendar are not in this plan.
- [ ] **Nothing is implemented until this list is signed.**

PLAN REVIEW REQUIRED — DO NOT IMPLEMENT UNTIL RANDALL APPROVES.
