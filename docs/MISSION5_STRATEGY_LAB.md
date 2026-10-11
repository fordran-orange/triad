# Mission 5 — Strategy Lab and walk-forward carry-over (2026-10-11)

Branch `aegis/strategy-lab`, cut from `main` at `882309e` (the spec at `a73f70e` plus the plan).
Spec: `docs/superpowers/specs/2026-10-11-aegis-strategy-lab-design.md`. Plan:
`docs/superpowers/plans/2026-10-11-aegis-strategy-lab.md` (11 tasks, 14 plan rulings). Executed
natively in one session. The session model changed from Fable 5.1 to Opus 5.5 on 2026-10-11
before the plan was written, because Fable was out of weekly usage; every task, test and commit
of this branch was made on Opus 5.5. At the operator's choice the milestone QA and the
whole-branch review ran on Fable 5.1 (the operator spent a usage reset for them).

Nothing under `app/trading_core/`, `app/platform_host/` or `app/products/triad/` changed
(acceptance item 47 checks it with git). Exchange stays CLOSED; no broker path; Triad suspended;
the `DailySchedule` record `c99fa831` stays disabled.

## Operator decisions (chat, 2026-10-11)

| Decision | Choice |
|---|---|
| Mission shape | Carry positions across walk-forward windows first (the operator's yes to the semantics change), then the Strategy Lab |
| Chart panes | Add pane support now: price-scale kinds on the price pane, oscillators one pane each |
| Contract growth | Extend in place: `IndicatorSpec.params`, string operands, `entry`/`exit` as a rule or a two-condition group; the default strategy's JSON stays byte-identical |
| Design sections | Six sections approved one by one; spec reviewed and approved ("specs reviewed.. proceed") |
| Execution | Native |
| Review model | Stop before the milestone QA and the whole-branch review and ask; the operator chose Fable 5.1 |

## What was built

| Task | Commit | Delivered |
|---|---|---|
| 1 Engine carry-over | `91330a5` | `OpenPosition`; `BacktestSettings.initial_position` and `close_at_end`; side results report `open_position`, `ending_cash`, `ending_equity`; an exit signalled on a run's last bar travels with the position; `carried_from_window` on closing trades; plain-run hashes pinned unchanged |
| 2 Walk-forward carry | `9e9197d` | each window starts from the previous ending cash and open position and closes only at the last window; window metrics rebased on the previous ending equity (P3); records gain `carried_in`, `open_at_end`, `ending_cash`, `ending_equity`, `inherited_from` (P12); Carry column and stitched carried count |
| 3 Indicator kinds | `0f6fb42` | `kinds.py` (one table, no Aegis imports); RSI and ATR with Wilder smoothing, Bollinger (population deviation), Donchian (previous bars only), MACD (outputs wait for the signal line, P5); `IndicatorSpec.params` omitted from dumps when empty, lowercase id pattern, named refusals; cache keyed by parameters |
| 4 Warm-up and paths | `2e55f07` | `side_warmup` replaces `longest_length` (engine check, walk-forward floor); `indicators.<id>.params.<name>` paths; general grid axes with the classic fast ≥ slow skip kept and invalid cells skipped (P6); `skip_reason` |
| 5 Rules | `50ca304` | operands (indicator references, price fields, plain decimals), six operators, `RuleGroup` with exactly two conditions, side validation naming every problem, evaluator in the engine; warm-up readiness over the columns the rules read |
| 6 Series route, kinds, helpers | `ceb8ec3` | `POST /indicators` returns `outputs` and `pane`; generator emits `Record<string, number>` and `INDICATOR_KINDS` (pinned to Python); `rules.ts` (warm-up mirror, references, rule descriptions) |
| 7 Strategy documents | `17a45b3` | repository kind `strategies`; `strategies.py` (document id = spec id, P1; read-only built-in synthesized, P10; usage from persisted summaries including pre-Mission-5 envelopes and running jobs); six routes; `strategy_id` and `strategy_hash` on every envelope, outside every result hash |
| 8 Chart panes | `95129b1` | `Overlay.pane/group/style`; `chartMeta`; Vela `aegis-pane` native (`paneHint: 'new'`), histogram columns; pane-aware crosshair; chart shows the focused side (P9) |
| 9 Right panel | `1a3d171` | Indicators tab (focus side, kind, pane, parameters, source, latest values, add with disabled ranges P14, removal refused while a rule reads it); generic indicator inputs; rule editors in the side cards |
| 10 Strategy Lab | `1496ceb` | Lab page (list, New, Duplicate, Rename, Delete with the server's refusal shown, Use in workspace); document header with unsaved edits, Save, Revert (P2); document sync |
| 11 Acceptance + record | `3f35cc9` | acceptance extended to 47 items; this record; evidence under `docs/evidence/` |
| Fix pass | `172ffa5` | out-of-sample windows on the full history (review #2); document sync rebinding (review #1); rename without false edits (review #5); latest values tied to what was fetched (review #6, QA 4); inherited windows show the configuration they traded (QA 1) |

## Acceptance evidence

Final run `20261011T184458Z`, after the fix pass, against the restarted worker (PID 14020, commit
`172ffa5`): **47/47 PASS, no page errors, 172 s**. Evidence:
`docs/evidence/aegis-acceptance-20261011T184458Z.json`; the pre-fix run
`docs/evidence/aegis-acceptance-20261011T173221Z.json` was also 47/47. Screenshots under `logs/`.
The table quotes the final run. The hashes of items 39 and 44 embed the document's id and name,
which are new on every run, so they differ between runs by design; identical requests reproduce.

| Item | Evidence |
|---|---|
| 37 | New document `untitled-strategy-79708d` renamed "Donchian RSI breakout 20261011T184458Z"; Donchian 20 and RSI 14 added on the long side; entry `price.close crosses_above donchian.upper` AND `rsi less_than 70`; exit `price.close crosses_below donchian.middle`; EMA and SMA removed from the long side; saved, hash `f09675f33f18…`, read back from `GET /strategies/{id}` |
| 38 | QQQ 1h 2023-01-01 → 2024-12-31, 3,493 bars; legend DONCHIAN 20 upper/lower/middle (price pane) and RSI 14 (own pane); hovering the study pane read "RSI 14 60.15 · 2024-12-10 16:30 UTC" |
| 39 | run `23f29fa4`: long 55 trades, net $40,134.92; 236 markers; hash `9f7224d0e8f00f5daa5a42f03e8f9a8b02d5e5f81b13ed885004be4f24ecf38d` |
| 40 | plan "12 valid cells · 0 skipped · 3,493 bars"; 12/12 cells; best DONCHIAN 10 / RSI 14 (net $47,239) applied → "price.close crosses ABOVE DONCHIAN(10).upper AND RSI(14) < 70" |
| 41 | in-sample 1000 / out-of-sample 250: 9/9 windows; 4 joins crossed holding a position, 4 carried trades; no interior edge close; every window's net P&L equals its ending equity minus the previous one's; stitched net $23,042.29 (before the fix pass, with the cold-started lead: $19,369.91); hash `725b217af27aea79f8ba26773db4414646e6086cc5125804c3c2cfb7d83033bf` |
| 42 | copy `breakout-copy-20261011t184458z` (parent the original) renamed and deleted; deleting the original refused: "409: strategy untitled-strategy-79708d is referenced by 2 runs, 1 optimization, 1 walk-forward" |
| 43 | item 22 produced the recorded hash `cdbc9abd2238542ee299e694209241b40561f39bfdd3632f58c93350b237e360` (the built-in strategy after the Mission 3 apply, which sets the long side to EMA 12 / SMA 40 and narrows its range stops to 12 and 40; QQQ 1h 2023–2024); item 22 now asserts it |
| 44 | two unchanged reruns of the new strategy → the same hash `f4401169ffa156d2837b366a098d8bff2fbd6235f03776e02b9f09772b4442a5` |
| 45 | Indicators tab: "DONCHIAN donchian · price pane" with its three latest values, RSI "own pane" with its source and latest 36.72; removing `rsi` refused: "rsi is read by the long entry rule; change that rule before removing it" |
| 46 | 422 naming each problem: unknown operand 'foo'; donchian has outputs; needs a band; a group needs two conditions; at most two conditions in this slice; RSI has no parameter 'x' |
| 47 | `/aegis/api/status` through the gateway human_directed / CLOSED; no change under Core, the platform host or Triad since `a73f70e` |

### Mission 3 and 4 items under carry-over

Items 1–36 pass unchanged in their assertions. Backtest and optimizer hashes are unchanged
(item 22 reproduces `cdbc9abd…`). The Mission 4 walk-forward numbers move, as the spec said they
would, because positions now carry across joins:

| Item 30 (QQQ 1D, 200/50, stitched) | Mission 4 | Mission 5 |
|---|---|---|
| Net P&L | $22,899 | $22,952 |
| Max drawdown | 5.08% | 8.46% |
| MAR | 3.72 | 2.24 |
| Trades | 6 (5 closed at a window edge) | 6 (4 carried, 1 closed at the final edge) |
| Exposure | 51.67% | 77.00% |
| Window efficiencies (item 29) | 2.47, 1.31, 0.62, 0.00, −0.26, 1.12 | 2.47, 0.72, 0.07, 1.15, −0.26, 0.79 |
| Completed-job hash (item 28) | `4f540c989d80…` | `783f07c3146b…` |
| Identical-request hash, 271 cells (item 34) | `1044cddec07f…` | `5d9371614fc09596e6fb2c8b4a36a7182adc0c427d7d333dab88cf337763230a` |

The deeper drawdown is the honest one: Mission 4 closed positions at every join, which hid the
drawdowns of trades that were still open. The fix pass (out-of-sample windows on the full
history) left these EMA/SMA numbers and hashes unchanged, because the cold-started EMAs had
converged before any signal; it moved the RSI walk-forward of item 41.

## Measurements (final acceptance run)

| Measure | Value |
|---|---|
| Gateway `/aegis/api/status` | 323 ms median, 366 max |
| Core `/health/live` | 4 ms median |
| Worker `/aegis/api/status` direct | 51 ms median |
| Backtest server time, QQQ 1h, 3,493 bars | 557–805 ms (6 runs) |
| Optimizer cell, QQQ 1D, completed job | 55 ms |
| Walk-forward unit, QQQ 1D 200/50 | 33.3 ms (246 units in 8.2 s) |

## Verification after the fix pass (`172ffa5`)

| Check | Result |
|---|---|
| `pytest -q -p no:cacheprovider` | 1192 passed, 596 skipped |
| `ruff check` / `ruff format --check` (Aegis sources, Aegis tests, `tools/aegis_contracts.py`) | clean |
| `tools/aegis_contracts.py --check` | current |
| `npm test` | 44 passed (7 files) |
| `npm run build` | built |
| Acceptance | 47/47 PASS (run `20261011T184458Z`) |

## Milestone QA (Fable 5.1, at `3f35cc9`)

Read-only on the repository; artefacts under `logs/qa_m5/` (git-ignored).

- Verdict: **PASS_WITH_OBSERVATIONS**, no failure. Suite 1192 passed; ruff and contracts clean;
  UI 38 passed and built; acceptance 47/47 (run `20261011T183414Z`).
- RSI 14, Donchian 20 and MACD 12/26/9 re-derived by hand from the bars route over QQQ 1h
  2024-06-03 → 2024-06-28: maximum difference 0.0; first values at indices 14, 20 and 33.
- Carry-over to the cent on the acceptance walk-forward: every identity exact at all four joins
  (cash before a carried entry, marked first point after a join, rebased window net P&L,
  stitched net P&L); window 2 reproduced independently over HTTP, five trades and 250 equity
  points identical.
- Every refusal reproduced: 422 for operands, groups, operators, parameters, ids, constants and
  ranges; 404 for unknown documents; 422 for the built-in and blank names; 409 for a referenced
  document, including while a job using it was running. Review Focus 1–5 all PASS. The honesty
  read of the new components found nothing fabricated.
- Observations: (1) an inherited window showed "—" as its configuration and said it only managed
  the carried position — fixed; (2) non-ASCII digits pass as constants over raw HTTP — deferred;
  (3) group refusals reach the UI as a JSON list — deferred; (4) transient stale latest values —
  fixed with review #6; (5) rule-editor defaults — deferred; (6) hashes embed the document id and
  name — recorded under known limits; (7) optimizations carry no result hash — pre-existing.

## Whole-branch review (Fable 5.1, `882309e..3f35cc9`) and fix pass

- Verdict: **with fixes**. No critical findings. Important: (1) document sync could bind the
  workspace to the wrong document after a run reload, and Save would then overwrite that
  document; (2) the out-of-sample lead cold-started recursive indicators, so RSI, ATR, MACD and
  EMA signals in each window differed from a continuous run (reproduced: 5 of 5 flat-start
  windows of an RSI fixture traded differently).
- Raised to important under the honesty rule: (5) false "unsaved edits" after renaming the
  loaded document; (6) the Indicators tab showing the previous configuration's latest value.
- One pass, every fix test-first, commit `172ffa5`: `test_out_of_sample_runs_on_the_full_history`,
  document-sync cases in `documents.test.ts`, rename and latest-value cases in
  `workspace.test.ts`, `chosenFor` in `walkforward.test.ts`; each watched failing, then passing;
  suite 1192 passed, UI 44 passed, acceptance 47/47.

### Deferred minors

- Union validation errors reach the UI as a JSON list with the real reason last.
- A saved document that no longer parses reads as "unknown strategy" (404).
- The empty-grid walk-forward refusal still says "fast >= slow" when MACD cells are invalid.
- A band operator chosen with no band indicator leaves an empty right-hand select.
- Walk-forward and optimize requests accept `initial_position` and `close_at_end=false` from API
  clients without refusal.
- The P12 test's last assertion is guaranteed by the final window; it should assert the carried
  trade closes.
- Fractional parameter grids carry float noise (1.2000000000000002) into applied specs.
- `seriesToOverlay` in the Vela adapter is never pruned.
- Non-ASCII digits pass as constants over raw HTTP and hash differently from ASCII ones.

## Rulings

Plan rulings P1–P14 are in the plan. Rulings made during execution (ledger):

- The branch was cut from `882309e`, the plan commit, which is `a73f70e` plus the plan file.
- Lint scope is the Aegis sources and tests and `tools/aegis_contracts.py`; Triad's tests have
  pre-existing findings outside this mission.
- Two Mission 3 indicator tests and two Mission 3 sync tests were rewritten for the new
  interfaces; one Mission 3 strategy test now matches "unknown operand".
- `IndicatorCache.get` returns the outputs named by output; callers relabel with `named()`, so one
  cached frame serves every indicator id.
- `side_warmup` lives in `strategy.py`, re-exported by `walkforward.py`, because the engine needs
  it and cannot import the walk-forward module.
- The indicator id `price` is reserved, so `price.close` is never ambiguous.
- `ruleReferences` names rules only; ranges never block a removal and are dropped with it.
- The 409 detail pluralizes counts ("1 run", "1 optimization").
- The plan's Task 8 browser check ran after Task 9, when the Indicators tab made it possible.
- The study readout lists every study series at the cursor time; Vela's crosshair event carries
  no pane id per series.
- Deleting the loaded document drops the workspace's link to it (found in the Task 10 browser
  check; verified in the browser only).
- "Use in workspace" switches to Charts; the strategy is built in the same right panel.
- Two acceptance-harness defects were fixed between runs (the document list was read before it
  loaded; a wait read a CSS-uppercased badge); runs `T172313Z` and `T172832Z` failed on them.
- Review finding #2 was fixed in the pass rather than left for a later mission: the spec's intent
  is that every number is real, and a carried position's exit was judged on indicator values a
  continuous run would not show. `lead_bars` is gone.
- QA observation 1 and review findings #5 and #6 were raised from minor to important under the
  honesty rule: each showed a person something untrue.
- The reviewer's "declined to judge" lines stand: settings outside the backtest hash (they change
  the hashed metrics and equity anyway), the cache computing under its lock, usage counting
  reading every sidecar, the Review Focus 3 wording versus P14, Core's proxy latency, and the
  absence of a DOM test harness.

## Known limits

- An exit signalled on a window's last bar travels with a carried position (P4); an entry signal
  on a window's last bar does not, so a window never opens a position on its final bar.
- In-sample cells run on their own window only, so recursive indicators warm up inside the
  in-sample window; out-of-sample windows run on the full prior history.
- Result and strategy hashes embed the strategy's id and name, so the same rules saved under two
  documents hash differently; identical requests reproduce.
- The study readout shows all study series at the cursor time, not only the hovered pane's.
- The UI has no DOM test harness; components are verified by the acceptance walk and browser
  checks, and pure helpers and the reducer by vitest.
- Every acceptance run leaves one referenced strategy document (item 42 proves its deletion is
  refused); on 2026-10-11 those are `untitled-strategy-b16c2e`, `untitled-strategy-314edb` (QA's
  run) and `untitled-strategy-79708d`. A failed run left `untitled-strategy` ("Donchian RSI
  breakout 20261011T172832Z", the built-in spec), referenced by that run's backtest, optimization
  and walk-forward. QA's HTTP probes added about seven runs and one optimization. None can be
  deleted while referenced, by design.
- Item 37's report line shows an empty side-card description because it is read while the
  Indicators tab is open; the saved document is checked through the API instead.
- Core's proxy hop (~320 ms) is unchanged and Core-owned.
