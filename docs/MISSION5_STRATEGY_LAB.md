# Mission 5 — Strategy Lab and walk-forward carry-over (2026-10-11)

Branch `aegis/strategy-lab`, cut from `main` at `882309e` (the spec at `a73f70e` plus the plan).
Spec: `docs/superpowers/specs/2026-10-11-aegis-strategy-lab-design.md`. Plan:
`docs/superpowers/plans/2026-10-11-aegis-strategy-lab.md` (11 tasks, 14 plan rulings). Executed
natively in one session. The session model changed from Fable 5.1 to Opus 5.5 on 2026-10-11
before the plan was written, because Fable was out of weekly usage; every task, test and commit
of this branch was made on Opus 5.5.

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
| Review model | Stop before the milestone QA and the whole-branch review and ask whether to run them on Fable 5.1 (operator instruction, 2026-10-11) |

## What was built

| Task | Commit | Delivered |
|---|---|---|
| 1 Engine carry-over | `91330a5` | `OpenPosition`; `BacktestSettings.initial_position` and `close_at_end`; side results report `open_position`, `ending_cash`, `ending_equity`; an exit signalled on a run's last bar travels with the position; `carried_from_window` on closing trades; plain-run hashes pinned unchanged |
| 2 Walk-forward carry | `9e9197d` | each window starts from the previous ending cash and open position and closes only at the last window; window metrics rebased on the previous ending equity (P3); records gain `carried_in`, `open_at_end`, `ending_cash`, `ending_equity`, `inherited_from` (P12); Carry column and stitched carried count |
| 3 Indicator kinds | `0f6fb42` | `kinds.py` (one table, no Aegis imports); RSI and ATR with Wilder smoothing, Bollinger (population deviation), Donchian (previous bars only), MACD (outputs wait for the signal line, P5); `IndicatorSpec.params` omitted from dumps when empty, lowercase id pattern, named refusals; cache keyed by parameters |
| 4 Warm-up and paths | `2e55f07` | `side_warmup` replaces `longest_length` (engine check, walk-forward floor and lead); `indicators.<id>.params.<name>` paths; general grid axes with the classic fast ≥ slow skip kept and invalid cells skipped (P6); `skip_reason` |
| 5 Rules | `50ca304` | operands (indicator references, price fields, plain decimals), six operators, `RuleGroup` with exactly two conditions, side validation naming every problem, evaluator in the engine; warm-up readiness over the columns the rules read |
| 6 Series route, kinds, helpers | `ceb8ec3` | `POST /indicators` returns `outputs` and `pane`; generator emits `Record<string, number>` and `INDICATOR_KINDS` (pinned to Python); `rules.ts` (warm-up mirror, references, rule descriptions) |
| 7 Strategy documents | `17a45b3` | repository kind `strategies`; `strategies.py` (document id = spec id, P1; read-only built-in synthesized, P10; usage from persisted summaries including pre-Mission-5 envelopes and running jobs); six routes; `strategy_id` and `strategy_hash` on every envelope, outside every result hash |
| 8 Chart panes | `95129b1` | `Overlay.pane/group/style`; `chartMeta`; Vela `aegis-pane` native (`paneHint: 'new'`), histogram columns; pane-aware crosshair; chart shows the focused side (P9) |
| 9 Right panel | `1a3d171` | Indicators tab (focus side, kind, pane, parameters, source, latest values, add with disabled ranges P14, removal refused while a rule reads it); generic indicator inputs; rule editors in the side cards |
| 10 Strategy Lab | `1496ceb` | Lab page (list, New, Duplicate, Rename, Delete with the server's refusal shown, Use in workspace); document header with unsaved edits, Save, Revert (P2); document sync |
| 11 Acceptance + record | this commit | acceptance extended to 47 items; this record; evidence under `docs/evidence/` |

## Acceptance evidence

Run `20261011T173221Z` against the restarted worker (PID 15128, branch code): **47/47 PASS, no
page errors, 162 s**. Evidence: `docs/evidence/aegis-acceptance-20261011T173221Z.json`;
screenshots under `logs/`.

| Item | Evidence |
|---|---|
| 37 | New document `untitled-strategy-b16c2e` renamed "Donchian RSI breakout 20261011T173221Z"; Donchian 20 and RSI 14 added on the long side; entry `price.close crosses_above donchian.upper` AND `rsi less_than 70`; exit `price.close crosses_below donchian.middle`; EMA and SMA removed from the long side; saved, hash `17a5d24eafc4…`, read back from `GET /strategies/{id}` |
| 38 | QQQ 1h 2023-01-01 → 2024-12-31, 3,493 bars; legend DONCHIAN 20 upper/lower/middle (price pane) and RSI 14 (own pane); hovering the study pane read "RSI 14 60.15 · 2024-12-10 16:30 UTC" |
| 39 | run `90870985`: long 55 trades, net $40,134.92; 236 markers; hash `3dee3b770fc3556d43bcb69901bc861787bdd6bca7bc21499503c50bbde50633` |
| 40 | plan "12 valid cells · 0 skipped · 3,493 bars"; 12/12 cells; best DONCHIAN 10 / RSI 14 (net $47,239) applied → "price.close crosses ABOVE DONCHIAN(10).upper AND RSI(14) < 70" |
| 41 | in-sample 1000 / out-of-sample 250: 9/9 windows; 4 joins crossed holding a position, 4 carried trades; no interior edge close; every window's net P&L equals its ending equity minus the previous one's; stitched net $19,369.91; hash `de554d73d9b2dcd84cabdc1e58e6181e1c4c2284a39160145b46cfb720f9dd3a` |
| 42 | copy `breakout-copy-20261011t173221z` (parent the original) renamed and deleted; deleting the original refused: "409: strategy untitled-strategy-b16c2e is referenced by 2 runs, 1 optimization, 1 walk-forward" |
| 43 | item 22 (the built-in strategy after the Mission 3 apply, QQQ 1h 2023–2024) produced the recorded hash `cdbc9abd2238542ee299e694209241b40561f39bfdd3632f58c93350b237e360`; item 22 now asserts it |
| 44 | two unchanged reruns of the new strategy → the same hash `33b129e2119f2fd57cd9b27a1bcda66cc3685ca4107ea4f81b1466fed9b76f59` |
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
drawdowns of trades that were still open.

## Measurements (acceptance run, 2026-10-11)

| Measure | Value |
|---|---|
| Gateway `/aegis/api/status` | 320 ms median, 415 max |
| Core `/health/live` | 5 ms median |
| Worker `/aegis/api/status` direct | 49 ms median |
| Backtest server time, QQQ 1h, 3,493 bars | 532–1,009 ms (6 runs) |
| Optimizer cell, QQQ 1D, completed job | 55.0 ms |
| Walk-forward unit, QQQ 1D 200/50 | 33.3 ms (246 units in 8.2 s) |

## Verification at the end of Task 11

| Check | Result |
|---|---|
| `pytest -q -p no:cacheprovider` | 1192 passed, 596 skipped |
| `ruff check` / `ruff format --check` (Aegis sources, Aegis tests, `tools/aegis_contracts.py`) | clean |
| `tools/aegis_contracts.py --check` | current |
| `npm test` | 38 passed (7 files) |
| `npm run build` | built |
| Acceptance | 47/47 PASS |

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
  check; there is no DOM test harness, so this fix is verified in the browser only).
- "Use in workspace" switches to Charts; the strategy is built in the same right panel.

## Known limits

- The study readout shows all study series at the cursor time, not only the hovered pane's.
- The UI has no DOM test harness; components are verified by the acceptance walk and browser
  checks, and pure helpers and the reducer by vitest.
- Every acceptance run leaves one referenced strategy document (item 42 proves its deletion is
  refused). A failed run on 2026-10-11 left `untitled-strategy` ("Donchian RSI breakout
  20261011T172832Z", the built-in spec), referenced by that run's backtest, optimization and
  walk-forward, so it cannot be deleted.
- Item 37's report line shows an empty side-card description because it is read while the
  Indicators tab is open; the saved document is checked through the API instead.
- Core's proxy hop (~320 ms) is unchanged and Core-owned.

## Milestone QA, whole-branch review, fix pass

Pending: the operator chooses the review model (Fable 5.1 or Opus 5.5) before these run.
