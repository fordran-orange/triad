# Aegis limits: longer runs and multi-variable optimizations (2026-10-20)

Branch `aegis/limits`, cut from Mission 9's branch `aegis/results-library` at `f4bbc09` (neither
is merged; merging stays the operator's answer). Design:
`docs/superpowers/specs/2026-10-20-aegis-limits-design.md`. Plan:
`docs/superpowers/plans/2026-10-20-aegis-limits.md` (5 tasks). `LIMITS_BASE` = `9d13297`.

Built natively on Opus 5.5 while the operator was away, on the operator's standing instruction
("continue missions until I get back; save questions for the end") and the scope the operator
approved before leaving ("All three"). The operator asked to see the matrix design before it was
built; it was written down first and built as separate commits so it can be dropped. Milestone QA
and a whole-branch review have not run: the operator chooses their model.

Product work only: nothing under `app/trading_core/`, `app/platform_host/` or `app/products/triad/`
changed (acceptance item 81). Exchange CLOSED; Triad suspended; `DailySchedule` `c99fa831`
disabled.

## Intent (operator, 2026-10-20)

- "why am I limited to 50000 bars, that's not enough for a 10 year run" → "200k after this run.
  goal is no limit."
- "this also doesn't fix multi variable optimize runs."
- "What about only saving relevant runs?" (answered with measurements; part of the "no limit"
  mission, not this change).

## What was built

| Commit | Task | What |
|---|---|---|
| `9d13297` | — | The design and the plan |
| `5b87649` | 1 | `BAR_CAP` 50,000 → 200,000: ten years of 15m (65,107 bars), 30m, 1h and 1D, about two years of 1m |
| `b5d8c6e` | 2 | Grids above 400 cells run on the experiments' process pool in chunks of workers × 32 cells (progress, cancel and the save per chunk), up to a bound of 100,000 cells refused with a pointer to experiments; the plan prices a pooled grid across the workers |
| `e77e642` | 3 | A job of more than 1,000 cells sends its best 1,000 (the saved document keeps every cell); `GET /optimize/{id}/cells` pages all cells; `GET /optimize/{id}/matrix?rows&cols` builds the matrix of any two parameters, each square the best of the rest; the stored heatmap keeps a square's best cell |
| `8003d4c` | 4 | The page: done/total cells and "on the pool"; Rows and Columns for three or more parameters; a square's hover names its cell count and the best cell's other parameters, and a click picks that full cell; the best 1,000 with paging; Start asks first above ten minutes; hours in durations |
| `6c5fd5f` | 5 | Acceptance items 77–81 |

## Measured on this laptop (QQQ, the raw archive)

| What | Value |
|---|---|
| Ten years of 15m bars (2016-09-19 → 2026-09-18) | 65,107 bars; 6.6 MB of bars to the page in ≈ 1 s; the chart drew them with 4,866 markers in ≈ 2–4 s |
| A ten-year 15m backtest (default strategy) | 1.4–1.9 s on the worker, 5 s end to end; a saved run of 26.6 MB |
| One-minute bars | 161,754 from 2025-01-01; from 2024-01-01 refused (254,586 over 200,000) |
| A 560-cell, three-parameter grid on 1h 2023–2024 | planned ≈ 5.3 s on 10 workers; ran in 7.4–9.4 s (the pool's start-up is not priced) |
| A 2,560-cell grid | planned ≈ 24 s; ran in 17–18 s; each status at most 440 KB |
| A 23,684-cell grid on ten years of 15m | planned ≈ 1 h 10 min; Start asked first |

## Acceptance evidence

`docs/evidence/aegis-acceptance-20261020T123641Z.json`: **81/81 PASS, no page errors**, 699 s.
Items 1–76 are the Mission 3–9 walk, unchanged and passing. Items 77–81:

- **77:** QQQ 15m 2016-09-19 → 2026-09-18, 65,107 bars charted in 1.8 s; its backtest in 1.7 s on
  the worker (2,131 trades, 4,262 markers).
- **78:** 560 cells planned on the pool (10 workers, ≈ 4.8 s) and run in 6.4 s; the matrix
  Donchian × RSI (28 squares) switched to Donchian × EMA (140); the best square by MAR loaded
  Donchian 30 / RSI 14 / EMA 10, and its backtest's long MAR (6.0470) equals the pooled cell's.
- **79:** 2,560 cells in 16.5 s; the status sends the best 1,000 in MAR order, the next page
  continues below them, the saved job keeps all 2,560; the table pages from "the best 1,000 of
  2,560" to 1,001–2,000.
- **80:** ten years of 1-minute bars refused (over 200,000); 240,000 cells refused, pointing to an
  experiment; a 23,684-cell grid on ten years of 15m ("≈ 1 h 3 min · on the pool (10 workers)")
  asked "Start it?" and, dismissed, started nothing.
- **81:** governance unchanged since `9d13297`; items 1–76 pass.

Before the full walk, items 77–81 ran alone against the store: 3/5, then 5/5 after two test
fixes (the 26 MB envelope read back from the worker; item 79 waiting for the next page's rows).

## Verification

- `tools\verify.ps1` on the branch (2026-10-20, after the walk): lint and format passed; the
  inventory was core 557, triad 1,058 and aegis 399; all three scopes ran in full and passed (core
  386 passed / 171 skipped; triad 634 / 424 with 209 subtests; aegis 398 / 1). It stopped at the
  foundation audit's "Wrong Git branch" check, by design.
- UI: 16 vitest files, 94 cases; `tsc` clean; the build succeeds.

## Rulings

1. A pooled job reports bars and its planned estimate itself and teaches the host no serial cost
   (as experiments do).
2. The tests that pinned the 400-cell refusal now pin the 100,000 bound.
3. The best-1,000 trim happens in the status route, never in the snapshot the runner saves.
4. The stored heatmap keeps the best cell of a square; two-parameter grids are unchanged.
5. A job that sends only its best cells uses the worker's matrix, so every square hovers and picks.
6. The walk-forward's Start asks above ten minutes too.
7. Durations past an hour read in hours.
8. Item 77 reads the 26 MB ten-year envelope back from the worker: the browser's inspector cannot
   keep a body that large (the page itself is unaffected).

## Deferred minors

- The pooled estimate leaves out the pool's start-up (≈ 2–3 s) and uses the host's serial rate
  until an experiment has measured the pool.
- While the next page of cells loads, the table is briefly empty.

## Questions for the operator

1. Is 100,000 cells the right bound for an exhaustive grid, with experiments for anything larger?
2. Is ten minutes the right threshold for "Start asks first"?
3. A matrix square shows the best over the other parameters. Is that the reading wanted, or also
   the median (robustness) as a second option?
4. Which model runs this branch's milestone QA and whole-branch review?
