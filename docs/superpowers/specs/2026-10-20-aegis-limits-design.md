# Aegis limits: longer runs and multi-variable optimizations (design, 2026-10-20)

Status: written and built while the operator was away, on the operator's standing instruction
("continue missions until I get back; save questions for the end"). The operator approved the
scope ("All three") before leaving; this document is the design the operator asked to see first
for the matrix, and it is up for review on return. Branch `aegis/limits`, cut from Mission 9's
branch `aegis/results-library` (not merged; merge stays the operator's answer).

## 1. Intent (operator, 2026-10-20)

- "why am I limited to 50000 bars, that's not enough for a 10 year run" → "200k after this run.
  goal is no limit."
- "this also doesn't fix multi variable optimize runs."
- Approved: bars to 200,000; the optimizer's 400-cell cap replaced by an estimate the operator
  confirms; a matrix that shows three or more variables.

What blocked, measured on QQQ 2016-09-19 → 2026-09-18: 15m is 65,107 bars and was refused at the
50,000-bar cap (30m, 1h and 1D fit); a third optimization parameter takes a grid past 400 cells and
was refused "grid too large"; the heatmap draws two parameters and hides the rest (one cell per
square); all 40 recent optimizations had exactly two parameters.

## 2. Bars

- `BAR_CAP` 50,000 → 200,000 (`app/products/aegis/data.py`). The 422 "range too large … narrow the
  range" stays for anything above it. 200,000 covers ten years at 15m (65,107), 30m, 1h and 1D, and
  about two years of 1-minute bars.
- Every path keeps going through the one cap: the chart, indicators, backtest, optimization,
  walk-forward, experiments, studies.
- Costs that grow with it, measured in the acceptance: a saved run is about 0.4 KB per bar on disk
  (a 15m ten-year run ≈ 26 MB); the chart's bar payload is about 100 bytes per bar.
- Not in scope: ten years of 1-minute bars (≈ 980,000). That needs slimmer saved runs and a
  downsampled chart (the "no limit" mission).

## 3. Cells

- **Small grids are unchanged.** A grid of at most 400 cells runs exactly as today: one cell per
  unit, serial, progress and cancel per cell. The Mission 3–9 acceptance items that watch progress,
  cancel mid-run and read progressive cells keep their meaning.
- **Large grids run on the worker pool.** Above 400 cells the optimization runs on the experiments'
  process pool (`pool.py`): the strategy with the other side disabled, the cell's side-relative
  paths prefixed with the side, the metrics-only kernel path, in chunks of `workers × 32` cells per
  unit. Progress, cancel and the save happen per chunk. The pool starts with the job and stops in
  `release()`. A pooled cell's metrics equal the serial path's for the same parameters (tested).
- **The bound.** A grid is enumerated in memory, so it keeps a bound: 100,000 cells. Above it the
  refusal names the count and points to an experiment (sampled search with refinement) for larger
  surfaces. At the measured pool rate 100,000 cells on 3,493 bars is about 11 minutes; on ten years
  of 15m bars it is hours, which the estimate says before the start.
- **The estimate is the confirmation.** The plan line already prices the run; a pooled grid is
  priced at the pool's measured rate divided across its workers. When the estimate exceeds ten
  minutes, Start asks first and names the estimate and the cell count.
- **Walk-forward** uses the same bound per window and keeps its serial units; its plan line prices
  it and the same ten-minute question applies.

## 4. What a job sends the page

- A job of more than 1,000 cells sends the best 1,000 by its objective in `cells` (max drawdown
  ascending, every other objective descending, undefined values last), with `cells_done` (every
  evaluated cell) and `cells_shown`. Smaller jobs send every cell, as today.
- `GET /aegis/api/optimize/{id}/cells?offset&limit&sort` pages through every evaluated cell
  (limit ≤ 5,000), as the experiment cells route does. The table says "best 1,000 of N" and pages
  with "Next 1,000".
- The persisted document keeps every cell.

## 5. The matrix for three or more parameters

- `GET /aegis/api/optimize/{id}/matrix?rows=<path>&cols=<path>` returns, for the two chosen
  parameters, the row and column values and, per metric, a value matrix and a matrix of cell
  indexes: each square holds the best cell among those sharing its two values (best by that
  metric's orientation: max drawdown lower is better, trades by count), and `cells` lists the
  referenced cells' parameters and metrics. With exactly two parameters it equals today's
  matrices.
- The job head shows "Rows" and "Columns" selects when the job has three or more parameters; the
  defaults are today's axes (the crossover's fast and slow lengths, else the first two paths).
- A square's hover names how many cells it summarises and the other parameters of its best cell
  ("best of 9 · RSI 14 · SMA 40"). Clicking a square picks its best cell, so Apply and Load use
  that cell's full parameter set.
- While the job runs, the page refetches the matrix with each poll.
- The Library's optimization view gets the same selects.
- Colours follow the operator's rule: red only for losing money.

## 6. Verification

- Tests first: the bound and its message; a pooled grid's cells equal the serial path's;
  progress, cancel and the save per chunk; the best-1,000 payload and the cells route; the matrix
  route's best-per-square with each metric's orientation, ties and undefined values; the 200,000
  cap; vitest for the new pure helpers.
- Acceptance items after Mission 9's 76: a three-parameter grid of more than 400 cells on the
  pool (its matrix, an axis switch, a square's best cell applied and rerun), a ten-year 15m
  backtest and chart, the honest refusals above both bounds, and governance.

## 7. Questions for the operator (asked on return)

1. Is 100,000 cells the right bound for an exhaustive grid, with experiments for anything larger?
2. Is ten minutes the right threshold for "Start asks first"?
3. The matrix's square shows the best over the other parameters: is that the reading wanted, or
   the median (robustness) as a second option?
