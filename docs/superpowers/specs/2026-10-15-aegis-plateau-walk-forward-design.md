# Mission 8 — Plateau walk-forward studies: does peaks to plateaus hold out of sample?

Date: 2026-10-15. Product work under `app/products/aegis/` (AGENTS.md: product-first; milestone
QA). No Core or Triad change; exchange stays CLOSED; nothing trades.

## 1. Intent

Mission 6 maps a strategy's whole control surface and recommends a plateau's centre, never a lone
peak (the operator's principle: "find the peaks, mark them as fragile, and move on to a region; a
peak is still valid if it is supported by a plateau"). Every experiment report says "in-sample on
one symbol and range; no out-of-sample evidence until walked forward", and the accepted decisions
carry the note "walk it forward before any use". Mission 4's walk-forward re-optimizes a two-axis,
one-side grid per window and trades the best single cell — the peak-picking the principle warns
against.

This mission tests the method itself out of sample: in rolling windows, map the experiment's
surface in-sample, choose by peaks to plateaus, trade the choice on the bars that follow, and
compare it with the peak rule and with the original centre held fixed — on QQQ, SPY and ITOT, each
walking itself.

## 2. Operator decisions (chat, 2026-10-15)

| Decision | Choice |
|---|---|
| What to test first | The plateau rule, per window (not one accepted setting held out) |
| A window with no plateau | Stay flat and say so: no new entry; a position carried in exits at the window's first bar |
| Other symbols | Each symbol walks itself (no transfer of QQQ-chosen regions) |
| Approach | A: a new study kind built on the Experiments machinery, started from an experiment |
| Design sections | Five sections approved one by one |

## 3. Definition of done (the acceptance walks these, after the 60 Mission 3–6 items)

1. A study is planned from a finished experiment with a report: the plan line names, per symbol,
   the windows, the cells per window (exhaustive or sampled under the experiment's budget), the
   total runs and an estimate priced from the measured experiment cost.
2. From the accepted breakout experiment (QQQ 1h, 252 cells, objective MAR, tolerance 0.15):
   symbols QQQ, SPY, ITOT; range 2016-09-19 → 2026-09-18; in-sample 3,493 bars; out-of-sample 873
   bars. Start it; progress advances by window while the status route answers under 500 ms.
3. Pause; restart the worker; the study is paused, not lost; resume; it finishes with every
   window of every symbol present exactly once.
4. The report shows, per symbol, the three rules side by side over the stitched out-of-sample
   period, the count of flat windows, the stability block, the equity chart and the window table;
   a cross-symbol line; the raw-archive label.
5. One window recomputed independently: the in-sample cells re-analysed give the same plateau
   centre (or the same no-plateau statement), and the plateau rule's out-of-sample run equals a
   direct backtest of that window (same bars, evaluate_from, capital, carried position) by result
   hash.
6. An identical study reproduces every per-rule result hash.
7. Every refusal of §5.4 answers 422 or 409 naming the problem.
8. The decision (accepted / rejected / deferred, notes) is shown on the study and in the list
   under its experiment.
9. Governance: `/aegis/api/status` human_directed / CLOSED; no file under `app/trading_core/`,
   `app/platform_host/` or `app/products/triad/` changed; the Mission 3–6 walk stays 60/60.

## 4. What a study is

A study belongs to one finished experiment and inherits everything its in-sample maps need: the
experiment's pinned strategy spec (not the document's current one), surface, objective, tolerance,
budget, seed and timeframe. The operator chooses:

- **symbols**: default QQQ, SPY, ITOT (any non-empty subset of the archive's symbols);
- **range**: default the whole archive (2016-09-19 → 2026-09-18 today);
- **window lengths in bars**: in-sample default = the experiment's own bar count (3,493 for the
  breakout experiments, so each window maps as much history as the experiment did); out-of-sample
  default = a quarter of it, rounded down (873).

Windows are rolling, as in Mission 4: window *w* covers in-sample `[w·o, w·o + i)` and
out-of-sample `[w·o + i, w·o + i + o)` of the selected range, with *i* and *o* the two lengths; the
last partial out-of-sample span is dropped and named as unused tail bars. Ten years of 1h bars give
about 16 windows per symbol.

A study is one document: id, name, parent experiment, the inherited definition, symbols, range,
window lengths, plan, status, progress, per-window records, report, decision, timestamps. It is
listed under its experiment and in the study list.

## 5. The procedure per symbol

### 5.1 In-sample map

Every planned cell of the surface runs on the window's in-sample bars only, through the Mission 6
process pool and metrics-only engine. Exhaustive when the surface's valid cells fit the budget;
otherwise Latin-hypercube first pass plus plateau refinement, seeded with the experiment's seed and
the window index. Cells the engine would refuse on the window's bars (warm-up) are skipped with the
reason, as in an experiment.

### 5.2 Choice

The Mission 6 analysis (`analysis.analyse`) runs on the window's cells with the experiment's
objective and tolerance. It yields either a recommendation (the plateau's centre) or a statement
with no recommendation. The window also records its best single cell (the highest objective among
valid cells; ties to the lower cell index).

### 5.3 Three rules traded out of sample

Each rule has its own capital chain, starting at the experiment's initial capital in the first
window:

1. **Plateau rule** (under test): the window's plateau centre. With no plateau the window is
   **flat**: no new entry; a position carried in exits at the window's first bar open (the
   engine's travelling exit), then the chain holds cash to the window's end; the next window starts
   flat.
2. **Peak rule** (comparison): the window's best cell; flat only when no cell is valid.
3. **Frozen centre** (baseline): the parent report's recommended centre, never re-chosen, traded
   through every out-of-sample window; omitted, with the reason, when the parent report has no
   recommendation.

Each out-of-sample span runs on the full history before it with `evaluate_from` at its first bar,
so indicators equal a continuous run's (the Mission 5 rule). Within a chain, ending cash and any
open position carry into the next window; only the last window closes at its edge. A window's net
P&L is its ending equity minus the previous window's.

### 5.4 Refusals

422: the experiment is not finished or has no report; a symbol is unknown or lacks the
experiment's timeframe; the range is too short for one in-sample plus one out-of-sample span
(named with the bar counts); window lengths below the engine's floor (35 bars plus the surface's
longest warm-up) or above the range; a window's map over budget with no way to sample it (the
experiment's levers apply). 409: another job is running; pause on a study not running; delete of a
running or paused study (cancel first).

### 5.5 Window record

Per window and symbol: dates; the in-sample plateau (id, size, median, cliff, centre parameters) or
the no-plateau statement; peaks and fragile count; the best cell and its in-sample objective; for
each rule its out-of-sample metrics, trades, carried in and out, and flat flag; for the plateau
rule, whether its centre lies inside the previous window's plateau and the distance it moved
(Euclidean over parameters normalized by each range).

## 6. Execution and storage

- **Job kind.** The runner's fourth kind, `study`, under the one-job-at-a-time rule. A unit is one
  window of one symbol: its in-sample map, then the three out-of-sample runs. Symbols run in
  order; windows in order within a symbol (the chains depend on it).
- **Resumable** like an experiment: a pause lands at a unit boundary (status `paused`); a worker
  restart leaves it paused; resume continues from the first unfinished unit; a paused study can be
  cancelled and then deleted.
- **Pool.** Started once per symbol with that symbol's bars held by each worker; each window's
  cells run on the window's slice.
- **Files** (a new kind in the Aegis repository): `studies/<id>.json` (definition, plan, status,
  progress, window records, report, decision); `studies/<id>.windows/<symbol>/<w>.parquet` (the
  window's in-sample cells, written atomically per unit; a torn write is ignored and the unit
  reruns); per-rule out-of-sample equity as resampled points for the chart.
- **Hashes.** Each rule's stitched out-of-sample result has a result hash; an identical study
  reproduces it.
- **Routes** under `/aegis/api/studies`: `POST /plan`, `POST /` (create and start, 202), `GET /`,
  `GET /{id}`, `POST /{id}/pause`, `POST /{id}/resume`, `POST /{id}/cancel`, `DELETE /{id}`,
  `PUT /{id}/decision`, `GET /{id}/windows/{symbol}/{w}/cells`, `GET /{id}/report.md`.

## 7. Report

- **Per symbol**: the three rules side by side over the stitched out-of-sample period — net P&L,
  return, CAGR, max drawdown, MAR, trades, exposure — and the plateau rule's flat windows ("flat in
  3 of 16 windows"); one comparison sentence by the study's objective (for example "On SPY the
  plateau rule's out-of-sample MAR was 0.61, against 0.42 for the peak rule and 0.55 for the frozen
  centre").
- **Across symbols**: one line ("plateau rule ahead of the peak rule on 2 of 3 symbols by MAR"),
  with the caveats beside it: the number of windows, the flat windows, and that no significance
  test is claimed.
- **Stability**: the share of windows that found a plateau; the share whose centre lay inside the
  previous window's plateau; the median distance moved; per parameter, the centre's value window by
  window.
- **Chart**: per symbol, the three stitched out-of-sample equity curves with window boundaries and
  flat windows shaded.
- **Window table**: as §5.5, each row opening the window's in-sample cells.
- **Honesty**: "—" for an absent value; a no-plateau window states its reason; the frozen column
  states why it is absent when it is; the RAW ARCHIVE · NOT RESEARCH-ELIGIBLE label on every report;
  Markdown export like an experiment's.

## 8. Page

The experiment's report gains **Walk forward**: the study planner (symbols, range, window lengths,
the live plan line, the experiment's levers when a window's map is over budget) and the list of the
experiment's studies. The study view shows progress (symbol, window, cells, measured cost,
remaining) with Pause, Resume, Cancel and Delete, then the report and the decision form.

## 9. Verification

- Test first, on synthetic bars and surfaces with known answers: window cutting; each rule's
  choice per window (centre, best cell, frozen, flat); the carry identities (cash and positions per
  chain; a flat window closes a carried position at its first bar and opens nothing; window net =
  ending equity − previous); stitching and per-rule hashes; pause, restart and resume with no unit
  twice or missing; every refusal; the report's statements; vitest for the page's pure helpers.
- Acceptance: §3 items 1–9 appended to `tests/products/aegis/browser_workstation.py`.
- Milestone: `tools\verify.ps1`, UI tests and build, the browser acceptance; then independent
  milestone QA and a whole-branch review, one fix pass test-first, the record
  `docs/MISSION8_PLATEAU_WALK_FORWARD.md`, merge and push on the operator's call. The operator is
  asked which model runs the QA and the review.

## 10. Not in this mission

A transfer test of QQQ-chosen regions on other symbols; significance testing; new data sources;
changes to Mission 4's walk-forward; any Core change; anything that trades or touches the exchange.

## 11. Build order

1. Window planning and the study request/document; the plan route.
2. The per-window procedure: map, choice, the three rules' out-of-sample runs with carry and flat
   windows; stitching and hashes (pure functions, synthetic tests).
3. The study job kind, storage and routes (pause, resume, restart, cancel, delete).
4. The report and its Markdown.
5. The page: planner, study list, progress, report, decision.
6. Acceptance and the record.

## 12. Risks

- Cost: three symbols × ~16 windows × the experiment's cells; the plan prices it before start.
- A surface with long warm-ups shrinks every window's valid cells; the planner names the skips.
- Out-of-sample spans of a few months hold few trades; the report states the trade counts beside
  every comparison.
