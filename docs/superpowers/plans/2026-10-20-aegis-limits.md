# Aegis limits Implementation Plan

> Executed natively (superpowers:executing-plans) while the operator is away, on the operator's
> standing instruction. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 200,000-bar runs and multi-variable optimizations of up to 100,000 cells, with a matrix
that shows any two of three or more parameters.

**Architecture:** the bar cap is one constant. Grids above 400 cells run as chunked units on the
experiments' process pool inside the existing optimization job kind; small grids keep the serial
per-cell path. The job sends the best 1,000 cells; two new routes page all cells and build the
matrix for any two parameters on the worker.

**Tech Stack:** Python 3.12 (`.venv-aegis`), FastAPI, pytest (scope `aegis`), React/Vite/TypeScript,
vitest, Playwright acceptance.

**Spec:** `docs/superpowers/specs/2026-10-20-aegis-limits-design.md`

## Global Constraints

- `BAR_CAP = 200_000`; `SERIAL_MAX_CELLS = 400`; `MAX_CELLS = 100_000`; `CELLS_SENT = 1_000`;
  confirmation above 600 s of estimate.
- Grids of at most 400 cells behave exactly as before (acceptance items 17–21, 41 unchanged).
- Product code only: nothing under `app/trading_core/`, `app/platform_host/`, `app/products/triad/`.
- Red only for losing money. Lint only through the scope script.

## Review Focus

1. A pooled cell's metrics equal the serial path's for the same parameters (one test compares
   every cell of a small grid run both ways).
2. Cancel during a pooled job stops between chunks and keeps every finished chunk's cells.
3. A matrix square with every cell undefined is undefined, not zero; ties keep the first cell.
4. A two-parameter job's matrix route equals its stored matrices.
5. A grid between 400 and 1,000 cells sends every cell; above 1,000 it sends exactly the best
   1,000 in objective order.

---

### Task 1: The bar cap

**Files:** `app/products/aegis/data.py`, `tests/test_aegis_data.py`.

- [ ] Change the test's pinned value to `BAR_CAP == 200_000`; run it → FAIL.
- [ ] Set `BAR_CAP = 200_000`; run `tests/test_aegis_data.py tests/test_aegis_api.py` → PASS.
- [ ] Commit "Aegis: the bar cap rises to 200,000".

### Task 2: Pooled large grids, the bound, the estimate

**Files:** `app/products/aegis/optimize.py`, `app/products/aegis/api.py` (plan and start),
`app/products/aegis/walkforward.py` (the bound message), `tests/test_aegis_optimize.py`.

**Interfaces:** `expand_grid(side, limit=MAX_CELLS)`; `OptimizerJob(request, frame, pinned,
pool_factory=Pool)` with `pooled: bool`, `chunk: int`, `total_units`; the plan adds `pooled`,
`workers`.

- [ ] Tests: `test_grid_bound_names_the_count_and_points_to_experiments` (100,001 cells refused,
  message contains "experiment"); `test_pooled_cells_equal_serial_cells` (a 6×6 grid run pooled
  with a 2-worker pool and serially: same params → same metrics); `test_pooled_job_progress_and_cancel_by_chunk`;
  `test_plan_prices_a_pooled_grid_across_workers`.
- [ ] Implement; run → PASS. Commit "Aegis optimizer: grids above 400 cells run on the pool".

### Task 3: What a job sends, the cells route, the matrix route

**Files:** `app/products/aegis/optimize.py`, `app/products/aegis/api.py`,
`tests/test_aegis_optimize.py`, `tests/test_aegis_api.py`.

**Interfaces:** `best_cells(cells, objective, n) -> list`; `axis_matrix(cells, rows, cols,
paths_values) -> dict`; `GET /optimize/{id}/cells`, `GET /optimize/{id}/matrix`.

- [ ] Tests for Review Focus 3–5 and the routes' 404/422s.
- [ ] Implement; run → PASS. Commit "Aegis optimizer: the best 1,000 cells, all cells by page,
  and a matrix of any two parameters".

### Task 4: The page

**Files:** `ui/src/components/OptimizePopover.tsx`, `OptimizationTab.tsx`, `Heatmap.tsx` (if
needed), `ui/src/results.ts`, `ui/src/api/client.ts`, `ui/src/optimizer.ts` (+ test).

- [ ] vitest: `squareTitle(...)`, `needsConfirm(estimate)`, `axisChoices(job)`.
- [ ] Implement the confirmation, the Rows/Columns selects, the matrix from the route for 3+
  parameters, square hover and pick, "best 1,000 of N" with paging. Browser check. Commit.

### Task 5: Acceptance and the record

- [ ] Items 77–81 in `tests/products/aegis/browser_workstation.py` (`LIMITS_BASE`); the walk 81/81;
  `tools\verify.ps1`; `docs/LIMITS_RECORD.md`. Commit.
