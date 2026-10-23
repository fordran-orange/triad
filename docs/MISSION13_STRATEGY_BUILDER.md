# Mission 13: the strategy builder (2026-10-22/23)

Branch `aegis/strategy-builder`, cut from `main` at `abd47a7` (not merged; merging stays the
operator's answer). Design: `docs/superpowers/specs/2026-10-22-aegis-strategy-builder-design.md`
(`a55ea00`, with §9 planning amendments). Plan: `docs/superpowers/plans/2026-10-22-aegis-strategy-builder.md`
(`abd47a7`, nine tasks). `BUILDER_BASE` = `abd47a7`. Built natively on Opus 5.5 ("native").

Product work only: nothing under `app/trading_core/`, `app/platform_host/` or `app/products/triad/`
changed (acceptance item 97); no model call, no provider or credential, no environment change.
One new UI package, approved by the operator: `@xyflow/react` 12.12.0, pinned exactly (it brings
zustand, classcat, `@xyflow/system` and d3 drag / zoom / selection / interpolate; production audit:
0 vulnerabilities). Exchange CLOSED; Triad suspended; `DailySchedule` `c99fa831` disabled.

## Intent (operator, 2026-10-22)

"can we work on the strategy builder. i'm thinking an AI assisted text based interface. so i say
buy when 9 ema crosses 30 sma and price is above 200 sma and it builds the nodal model. i can then
edit the nodal model, adding and deleting blocks as i see fit."

Decisions: "A" (a deterministic phrase reader now, the AI through Core later); "1" (a logic tree of
blocks, nesting AND / OR); a default 2% stop loss and 5% take profit when the text names no exit,
and stops as drag-and-drop blocks ("so 1 will not work for every strategy. can we do a simple
default rule for testing. i like the 2% and 5%. also, in the nodes. we can build stop conditions.
drag and drop"); "2" (stops checked on the close, filled at the next open); "1" (the Strategy Lab
becomes the builder); "1" (React Flow). Design sections 1–6 "yes"; spec "no" changes; plan
"native".

## What was built

| Commit | Task | What |
|---|---|---|
| `87071a1` | 1 | Before any change, goldens from today's engine: `tests/fixtures/aegis_engine_golden.json` (backtests of three strategies on both engines, the travelling exit and entry cuts, four experiment cells through `run_metrics`, a walk-forward; two captures byte-identical) and `tests/products/aegis/builder_identity.py` (a real-archive capture / compare, and a read-only check of every saved strategy's hash) |
| `02c8677` | 2 | Rules form a tree: a group's members are conditions or groups, at least two, nested at most 32 levels (a guard); `evaluate` combines members in order, so a two-condition group computes what it did |
| `f20b668` | 3 | `stop_loss_pct` / `take_profit_pct` on each side, the exit rule optional (a side needs a rule, a stop or a target); one level check (`kernel.level_reason`) on the close in both engines, filled at the next open, travelling on the last bar; trades closed by a level carry `exit_reason` |
| `2371d8c` | 4 | Stop and target percentages can be ranged in experiments, the optimizer and walk-forwards |
| `b01b1ab` | 5 | The phrase reader (`products.aegis.phrases`) and `POST /strategies/read` |
| `5ee5e1a` | 6 | The builder's graph model (`builder/graph.ts`: side ↔ blocks and wires, wiring rules, layout) and undo / redo |
| `f2d58a0` | 7 | The canvas in the Strategy Lab (React Flow), the saved-strategy list beside it, the canvas saved in the strategy document outside its hash |
| `401801c` | 8 | The text line (preview, Apply, refusals underlined), the panel's text summary with Edit in builder, "stop loss" / "take profit" in Trades, level ranges; the dropdown rule editor is gone |
| `d495244` | 9 | Levels laid out below the rule wires (found by item 92) |
| (the record commit) | 9 | Items 37 (typed), 46 (new messages), 91–97; this record and the evidence |

## Identity

- **Engine goldens** (`test_aegis_engine_golden`, 14 cases) and Mission 12's study golden pass after
  every task: results without stops are byte-identical, on both engines.
- **Real archive** (QQQ 1h, 2016-01-01 → 2026-09-18, 17,533 bars): backtests of the reference
  strategy and a saved Donchian / RSI breakout on both engines, a 9-cell experiment and a
  walk-forward, captured before Task 2 and compared after Task 9: **identical**.
- **Saved strategies:** every document's hash recomputed after the walk: 43 strategies, 0 changed.
  A strategy saved before the builder opens laid out automatically and is not marked edited.

## Acceptance evidence

`docs/evidence/aegis-acceptance-20261023T042021Z.json`: **97/97 PASS, no page errors**.

- **37** (converted): types "buy when close crosses above donchian upper and rsi below 70; sell when
  close crosses below donchian middle" and asserts the same strategy the dropdowns built.
- **46** (updated): "a group needs two members"; three members are now valid, so the case is the
  33-level nesting refusal.
- **91:** the operator's sentence reads back "Long entry: EMA 9 crosses above SMA 30 AND close above
  SMA 200. Exit: stop loss 2%, take profit 5% (default)"; Apply builds 11 blocks with two default
  badges; the backtest's 16 long trades are all closed by a level, shown as stop loss / take
  profit in Trades.
- **92:** RSI, a condition and an AND dragged in and wired; a second wire into Entry refused with its
  reason; RSI deleted ("condition-3: left input is empty"); Ctrl+Z; saved as a nested AND.
- **93:** after a reload 14 blocks are where they were saved; an older breakout opens laid out, not
  edited, hash unchanged.
- **94:** an experiment over `long_side.stop_loss_pct` 1–3 runs three cells.
- **95:** the panel reads the side with its levels; Edit in builder opens the Long tab.
- **96:** "buy when vwap crosses 30 sma" is refused naming and underlining `vwap`; nothing changes.
- **97:** governance unchanged since `abd47a7`; items 1–96 pass.

## Rulings

From the ledger, each with its cost if wrong:

1. Task 2: the refusal "a group needs two conditions" reads "a group needs two members"; three
   members are valid. Cost: a message string.
2. Task 3: the stop-only experiment case compares `run_metrics` with the backtest's metrics
   (`run_metrics` returns no trades). Cost: none.
3. Task 3: `describeExit` came early, so the panel could type-check an absent exit. Cost: none.
4. Task 4: the stop-range experiment test ranges the short side's stop: on those synthetic bars the
   breakout's long side never trades. Cost: none.
5. Task 5: the reader skips words that carry no meaning ("the", "is", "band(s)", "a" before a
   level). Cost: none.
6. Task 5: a parameter equal to its kind's default is not stored ("bb 20 2" = "bb 20"). Cost: a
   typed default reads as unset.
7. Task 5: two refusals beyond the plan's list (a multi-output indicator without its output; inside
   / outside without a band), and a clause of levels alone reads "Long side: stop loss 2%". Cost:
   none.
8. Task 6: a number typed into an unwired input is kept as its text, so "1.50" round-trips. Cost:
   none.
9. Task 6: level block ids follow `<type>-<n>`; an unreferenced indicator is greyed as loose.
   Cost: a visual choice.
10. Task 7: the Lab page shows the builder and the saved list, not the Strategy panel; the builder
    has its own Run and Save. Cost: execution and temporal settings are one page away.
11. Task 7: a moved or loose block marks the document edited by a flag, so a strategy laid out
    automatically is never reported as edited. Cost: none.
12. Task 7: a side's graph stands while its strategy is unchanged or still reads as it; otherwise it
    is laid out afresh keeping known positions. Cost: a panel edit can move new blocks.
13. Task 7: React Flow's attribution stays visible; the canvas was checked in headless Chromium
    because the built-in browser pane does not draw while behind other windows. Cost: none.
14. Task 7: layout rows 150 px apart; a refusal in the status line clears on the next edit. Cost:
    none.
15. Task 8: a stop or target also gets a disabled default range, so the panel's ranges can offer
    "stop loss %" and "take profit %". Cost: two disabled rows per side with levels.
16. Task 8: applying a reading gives default ranges to each indicator without a range (the reader
    reuses ids such as `ema`). Cost: none.
17. Task 8: `exitLabel` lives in `format.ts`; `describeSide` returns two lines. Cost: none.
18. Task 9: levels are laid out below every other row of their column. Cost: levels drawn low.
19. Task 9: the walk waits for the builder's save response, right-clicks a wire at its own
    midpoint, accepts the "unsaved edits" confirmation when opening a strategy, and reopens the
    operator-sentence strategy where item 93 left another open. Cost: none.

## Left in the operator's store

Made by the trials and the two walks, kept (nothing deleted): the scratch strategy
`builder-check-m13` ("Builder check M13", one run); "Operator sentence <stamp>" strategies and
"stop surface <stamp>" experiments from the trials and walks; each walk's usual items. An "Untitled
strategy" (`untitled-strategy-7546d4`, created 2026-10-23 02:55 UTC) predates anything this mission
ran in the app and was not touched.

## Verification

- Aegis suite after Task 3: 495 passed, 1 skipped; each later task ran its modules (tests named in
  the ledger) and the goldens.
- `tools\verify.ps1` on the branch (after the walk): lint and format clean; inventory core 557,
  triad 1,058, aegis 523; all three scopes green (core 386 / 171 skipped; triad 634 / 424 with 209
  subtests; aegis 522 / 1). It stopped at the "Wrong Git branch" check, by design.
- UI: vitest 141 passed; the production build (tsc + vite) clean.
