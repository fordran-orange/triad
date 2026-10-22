# Mission 12: studies on frames (2026-10-21)

Branch `aegis/study-frames`, cut from `main` at `f9ae2a2` (not merged; merging stays the
operator's answer). Design: `docs/superpowers/specs/2026-10-21-aegis-study-frames-design.md`
(`5fa7c82`). Plan: `docs/superpowers/plans/2026-10-21-aegis-study-frames.md` (`f9ae2a2`, two tasks).
`STUDY_FRAMES_BASE` = `f9ae2a2`. Built natively on Opus 5.5 ("native").

Product work only: nothing under `app/trading_core/`, `app/platform_host/` or `app/products/triad/`
changed (acceptance item 90); no package or environment change. Exchange CLOSED; Triad suspended;
`DailySchedule` `c99fa831` disabled.

## Intent (operator, 2026-10-21)

Offered as the next mission after Mission 11 ("studies on the memory-efficient path from Mission
10, lifting their 200,000-bar cap"): "do it". "yes" to four recommendations:
1. study output byte-identical to today's path, a hard requirement;
2. the study cap lifted to the general 2,000,000-bar guard;
3. the per-bar holders removed, and the study cache bounded by bytes;
4. one acceptance item with a real one-minute study above the old cap.

## What was built

| Commit | Task | What |
|---|---|---|
| `5fa7c82`, `f9ae2a2` | — | The design and the plan (on `main`) |
| `f5ba2d0` | 1 | Before any change, goldens captured from today's code: `tests/fixtures/aegis_study_golden.json` (a synthetic two-symbol study; two runs of today's code agreed on every key) and `tests/products/aegis/study_identity.py` (a real QQQ 1m study, captured and compared). Then: `api._study_bars` hands `StudyJob` each symbol's prepared frame; `IsoTimes` reads the ISO strings the rows path carried one at a time for planning and every record; out-of-sample runs are frame slices through `run_prepared`; held bars come from `searchsorted` over the frame's times; the study cache is bounded by bytes (128 B per bar of the longest symbol) and by 8 data keys; `STUDY_BAR_CAP` is gone |
| `79ad980` | 2 | Acceptance items 89–90 and the memory probe's `study` mode |
| (the record commit) | 2 | This record and the evidence |

## Identity

- The synthetic golden (4 + 3 windows, 5 flat rule-windows, 7 carried-in side runs) is reproduced
  exactly from rows and from frames (`test_study_output_equals_the_golden`), and a study paused on
  rows and resumed on frames finishes with the same hashes.
- The real study, QQQ 1m 2025-01-02 → 2025-04-30 (8 windows, 5 flat rule-windows, 17 carried
  positions), compares "identical" against its capture from the old code.

## Measured (QQQ 1m, the memory probe's `study` mode, nothing saved)

| What | Old path (worktree at `f9ae2a2`) | Frames |
|---|---|---|
| 161,754 bars (2025-01-01 → 2026-09-18, 1 window): after selection | 381–399 MB | 316–324 MB |
| … host peak | 565–581 MB (1,123–1,139 B/bar above the frame) | 457–465 MB (873–875 B/bar) |
| … seconds | 17.4–19.4 s | 15.8 s (a first, cold run read 27.2 s) |
| Ten years (947,519 bars, 18 windows) | refused (over the 200,000-bar study cap) | 990 MB host peak (673 B/bar), 318 s |

The pool workers are separate processes, sized to free memory (Mission 10); their figures are the
Mission 10 measurements.

## Acceptance evidence

`docs/evidence/aegis-acceptance-20261022T003057Z.json`: **90/90 PASS, no page errors**, 910 s.
Items 1–88 are the Mission 3–11 walk, passing. Items 89–90 ran alone first: 2/2.

- **89:** a 4-cell experiment on QQQ 1m (2023 Q1), then a study of it over QQQ 1m 2023-01-01 →
  2026-09-18 (348,826 bars; in-sample 40,000, out-of-sample 20,000). It planned (the old cap
  answered 422 there), ran 15 windows to done with a report in 99.3 s (100.5 s in the trial), and opens from the Library
  on the Experiments page.
- **90:** governance unchanged since `f9ae2a2`; items 1–88 pass.

## Rulings

1. Task 1: `run_window` accepts the symbol's prepared frame or rows, not only a frame as the plan's
   interface said. The existing rule tests keep their rows fixtures as an independent oracle.
   `StudyJob` always passes frames.
2. Task 1: `IsoTimes` lives in `study_rules` and `studies` re-exports it, which avoids a circular
   import.
3. Task 1: `StudyJob` takes a DataFrame as already prepared (the API prepares it) and prepares rows
   once, so a ten-year frame is never prepared twice.

## Verification

- `tools\verify.ps1` on the branch (after the walk): lint and format passed; inventory core 557,
  triad 1,058, aegis 455; all three scopes green (core 386 / 171 skipped; triad 634 / 424 with 209
  subtests; aegis 454 / 1). It stopped at the "Wrong Git branch" check, by design.
