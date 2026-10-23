# Aegis Strategy Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Type "buy when 9 ema crosses 30 sma and price is above 200 sma" in the Strategy Lab and get an editable canvas of blocks (logic tree, stops, targets) that saves and runs, with every existing result unchanged.

**Architecture:** The rule model grows into a tree and each side gains an optional stop and target. Signals are still two boolean arrays, so the kernel changes only by one exit check on the close. A deterministic phrase reader in the worker turns text into whole replacement sides. The Strategy Lab becomes a React Flow canvas that is a view of the workspace strategy; block positions live in the strategy document, outside the hash.

**Tech Stack:** Python 3.12, Pydantic, pandas, numba (`.venv-aegis`); React 18, TypeScript, Vite, vitest, `@xyflow/react` 12.12.0; Playwright for the walk.

**Spec:** `docs/superpowers/specs/2026-10-22-aegis-strategy-builder-design.md` (including §9, the planning amendments).

## Global Constraints

- Product work only: `app/products/aegis/` (UI and its package files included), `tests/`, `docs/`, `tools/aegis_contracts.py`. Nothing under `app/trading_core/`, `app/platform_host/`, `app/products/triad/`. No model call, no provider, no credential, no environment change. Exchange CLOSED.
- **Identity:** every result without stops is byte-identical to today's (the Task 1 goldens, the Mission 12 study golden `tests/fixtures/aegis_study_golden.json`, the real-archive compare); every saved strategy document's `strategy_hash` is unchanged; every rule expressible today dumps byte-identically.
- One new package: `@xyflow/react` exactly `12.12.0` (no caret) in `app/products/aegis/ui/package.json` and its lock. No other new package.
- Values: default stop loss `2`, take profit `5` (percent); `stop_loss_pct` > 0 and < 100; `take_profit_pct` > 0 and finite; nesting ≤ 32 levels (`MAX_RULE_DEPTH = 32`); canvas JSON ≤ 262,144 bytes.
- Exact copy: "long side has no exit: add a rule, a stop or a target" (and "short side …"); "Entry has nothing wired in"; "Exit has nothing wired in"; reading back "Long entry: EMA 9 crosses above SMA 30 AND close above SMA 200. Exit: stop loss 2%, take profit 5% (default)"; trade labels "stop loss" / "take profit".
- Tests: `TRIAD_PYTEST_SCOPE=aegis .venv-aegis/Scripts/python.exe -m pytest -q -p no:cacheprovider <paths>` (written `PYTEST` below); UI `npm --prefix app/products/aegis/ui test` and `npm --prefix app/products/aegis/ui run build`; lint only `bash "$TEMP/claude/C--Triad/022ed4b7-ef3f-4cba-b67b-3929564904e2/scratchpad/lint_aegis.sh" fix` (written `LINT`); contracts `.venv-aegis/Scripts/python.exe tools/aegis_contracts.py` then `--check`.
- Commits: message written with the Write tool, `git -c core.hooksPath=NUL commit -F <file>`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Colours: red only for losing money. The save preference stays "every". No jobs started in the app while the walk runs. Never touch `data/raw`.

## Review Focus

1. A side whose only exit is a stop, through every job kind (backtest, experiment, walk-forward, study): it runs, with no missing-exit error and no exit signal column assumed. Test in Task 3.
2. A stop or target written without "%" ("stop at 2"): refused, naming the words, never read as 2%. Test in Task 5.
3. A saved canvas that no longer reads as its strategy (an indicator removed or a rule changed from the panel since it was saved): the strategy opens laid out automatically, never a broken canvas. Test in Task 6.
4. Two sides in one line with a stop after the second clause ("buy when …; short when …, stop at 3%"): the stop belongs to the short side. Test in Task 5.
5. Removing an indicator in the Indicators tab while a nested condition reads it: still refused, naming the rule, as today. Test in Task 2.

---

### Task 1: Identity goldens from today's code

**Files:**
- Create: `tests/products/aegis/engine_golden.py` (the cases and `capture`)
- Create: `tests/fixtures/aegis_engine_golden.json`
- Create: `tests/test_aegis_engine_golden.py`
- Create: `tests/products/aegis/builder_identity.py` (real archive: `capture OUT`, `compare OUT`, `hashes`)

**Interfaces:**
- Produces: `engine_golden.cases() -> dict[str, dict]` (case name → canonical output); `python tests/products/aegis/engine_golden.py capture` writes the fixture. Later tasks run `tests/test_aegis_engine_golden.py` as their identity check.

- [ ] **Step 1: Write `engine_golden.cases()`.** Keys and contents (each value is `canonical_payload(...)` plus its `result_hash`, so a diff is readable):
  - `backtest/<strategy>/<engine>` for strategies `default_strategy()`, `_breakout()`, `_long_only()` (from `test_aegis_backtest`) on `bars()`, engines `reference` and `kernel`;
  - `travelling_exit/<engine>` and `travelling_entry/<engine>`: the same requests `test_aegis_kernel.test_kernel_matches_reference_on_a_travelling_exit` / `…_entry` build;
  - `walkforward`: `rsi_walkforward_request()` on `wave_bars()` through `run_sync` (from `test_aegis_walkforward`), every window's result hash and metrics;
  - `experiment`: a 4-cell surface (donchian length 10/20 × rsi length 7/14 on `_breakout()`), run to done with the experiments test helper, every cell row's metrics.
- [ ] **Step 2: Capture twice.** Run `capture`, copy the file, run `capture` again; the two files are byte-identical (`cmp`). Expected: identical. (A golden pins today's behaviour, so it passes by construction; the two-capture agreement is its proof.)
- [ ] **Step 3: Write `test_engine_output_equals_the_golden`** in `tests/test_aegis_engine_golden.py` (`pytestmark = pytest.mark.aegis`), parametrized over the fixture's keys: `cases()[key] == golden[key]`, reporting the first differing path. Run: `PYTEST tests/test_aegis_engine_golden.py`. Expected: PASS for every key.
- [ ] **Step 4: Write `builder_identity.py`.** `capture OUT`: on QQQ 1h 2016-01-01 → 2026-09-18 from the archive, backtests of the reference strategy and the newest saved "Donchian RSI breakout" document (both engines), a 9-cell experiment of the breakout and one walk-forward; writes the canonical outputs. `compare OUT` runs them again and prints the first difference or `identical`. `hashes` recomputes `strategy_hash(doc.spec)` for every document under `data/aegis` (read-only) and prints `N strategies, 0 changed`, listing any change. Run `capture` into the scratchpad (`m13_identity_before.json`) and `hashes`. Expected: a file written; `0 changed`.
- [ ] **Step 5: LINT, commit** "Mission 13 Task 1: identity goldens from today's engine".

### Task 2: The rule tree

**Files:**
- Modify: `app/products/aegis/strategy.py` (`RuleGroup`, `conditions`, `referenced_columns`, `_check_condition` callers)
- Modify: `app/products/aegis/backtest.py:284-290` (`evaluate`)
- Modify: `app/products/aegis/ui/src/rules.ts`, `app/products/aegis/ui/src/contracts.ts` (regenerated), `app/products/aegis/ui/src/components/RuleEditor.tsx` (compile only)
- Test: `tests/test_aegis_strategy.py`, `tests/test_aegis_backtest.py`, `app/products/aegis/ui/src/rules.test.ts`, `app/products/aegis/ui/src/state/workspace.test.ts`

**Interfaces:**
- Produces: `RuleGroup.all_of / any_of: list[RuleSpec | RuleGroup] | None`; `MAX_RULE_DEPTH = 32`; `members(group: RuleGroup) -> list[Rule]`; `conditions(rule: Rule) -> list[RuleSpec]` (every leaf, left to right); `evaluate(frame, rule)` recursive. TS: `membersOf(group)`, `conditionsOf(rule)` (leaves), `describeRule(rule, indicators)` with brackets around a nested group of the other join ("A AND (B OR C)").

- [ ] **Step 1: Write the failing Python tests.**
  - `test_groups_take_any_number_of_members`: an `all_of` of four conditions validates and dumps them in order.
  - `test_groups_nest`: `{"all_of": [A, {"any_of": [B, C]}]}` validates; `conditions()` returns `[A, B, C]`.
  - `test_a_group_needs_two_members`: one member → "a group needs two members".
  - `test_nesting_past_32_levels_is_refused`: 33 nested levels → message contains "nested deeper than 32 levels"; 32 validate.
  - `test_nested_operands_are_checked`: an unknown operand inside a nested group is refused naming it ("entry rule references unknown operand 'vwap'").
  - `test_referenced_columns_walk_the_tree`: a nested band condition contributes `bb.upper` and `bb.lower`.
  - `test_evaluate_walks_nested_groups` (backtest): close = 1…8; A `close > 2`, B `close < 7`, C `close > 5`; `A AND (B OR C)` → `[F, F, T, T, T, T, T, T]`; `(A AND B) OR C` → `[F, F, T, T, T, T, T, T]`; `A AND B AND C` → `[F, F, F, F, F, T, F, F]`.
  - Existing `test_default_strategy_json_is_byte_identical` and `test_groups_and_bands_validate_and_dump_without_the_unused_key` stay unchanged.
- [ ] **Step 2: Run them.** `PYTEST tests/test_aegis_strategy.py tests/test_aegis_backtest.py`. Expected: the new tests FAIL ("at most two conditions in this slice" / validation of nested groups).
- [ ] **Step 3: Implement.** Members are `RuleSpec | RuleGroup` (Pydantic forward reference, `model_rebuild()`); each group's validator computes its depth (1 + its deepest member group) and refuses past 32; `conditions` recurses; `evaluate` combines the members' series with `&` or `|` in order, then `fillna(False).astype(bool)` once at the top. Two-condition groups dump exactly as today.
- [ ] **Step 4: Run.** Same command plus `PYTEST tests/test_aegis_engine_golden.py tests/test_aegis_studies.py -k golden`. Expected: PASS; goldens unchanged.
- [ ] **Step 5: Regenerate contracts.** Run the generator, then `--check`. Expected: `contracts.ts is current`; `RuleGroup.all_of?: (RuleSpec | RuleGroup)[] | null`.
- [ ] **Step 6: Write the failing UI tests** (`rules.test.ts`): `describeRule` of `A AND (B OR C)` reads `price.close > 2 AND (price.close < 7 OR price.close > 5)`; `conditionsOf` of a nested tree returns the three leaves; (`workspace.test.ts`) `ruleReferences` finds `rsi` inside a nested exit group and REMOVE_INDICATOR of `rsi` is refused (Review Focus 5). Run `npm --prefix app/products/aegis/ui test`. Expected: the new cases FAIL.
- [ ] **Step 7: Implement in `rules.ts`** (`membersOf`, recursive `conditionsOf`, bracketing `describeRule`); `RuleEditor.tsx` edits only flat rules of one or two conditions and shows the rule as text otherwise (it retires in Task 8). Run UI tests and build. Expected: PASS; build clean.
- [ ] **Step 8: LINT, commit** "Mission 13 Task 2: rules form a tree".

### Task 3: Stops and targets in the model and both engines

**Files:**
- Modify: `app/products/aegis/strategy.py` (`StrategySide`)
- Modify: `app/products/aegis/kernel.py` (`_simulate`, `simulate_arrays`, `TRADE_COLUMNS`, `SCALARS`, a shared `level_reason`)
- Modify: `app/products/aegis/backtest.py` (`OpenPosition`, `_side_frame`, `_simulate_side`, `_simulate_side_kernel`, `_side_metrics`)
- Modify: `app/products/aegis/ui/src/contracts.ts` (regenerated), `app/products/aegis/ui/src/rules.ts` (`describeRule` of an absent exit)
- Test: create `tests/test_aegis_stops.py`; `tests/test_aegis_kernel.py`

**Interfaces:**
- Consumes: Task 2's `conditions`, `evaluate`.
- Produces: `StrategySide.stop_loss_pct: float | None`, `take_profit_pct: float | None`, `exit: Rule | None = None` (left out of dumps when None); `OpenPosition.exit_reason: Literal["stop_loss", "take_profit"] | None` (left out of dumps when None); trade dicts gain `exit_reason` only for those two; `kernel.level_reason(close: float, entry_price: float, sign: int, stop: float, target: float) -> int` (0 none, 1 stop loss, 2 take profit; `stop`/`target` are fractions, 0 means off); `kernel.simulate_arrays(..., carried, stop_loss: float = 0.0, take_profit: float = 0.0)`; `TRADE_COLUMNS` gains `exit_reason` (index 11); `SCALARS` gains `open_exit_reason` (index 11); the carried array grows to 8 (index 7: the travelling exit's reason).

- [ ] **Step 1: Write the failing tests** in `tests/test_aegis_stops.py` (`pytestmark = pytest.mark.aegis`), on hand-made bars where each fill is worked out in a comment, each run on both engines with identical payloads:
  - `test_a_side_needs_an_exit` ("long side has no exit: add a rule, a stop or a target"); `test_a_stop_alone_is_an_exit`;
  - `test_stops_are_left_out_of_dumps_when_unset` (and an absent exit); `test_stop_bounds_are_refused_by_name` (0, 100, -1, inf);
  - `test_a_long_stop_fires_on_the_close_and_fills_next_open` (entry 100.0 filled; close 97.9 ≤ 98.0 → exit at the next open, `exit_reason == "stop_loss"`);
  - `test_a_long_target_fires_on_the_close` (close 105.0 ≥ 105.0 → `"take_profit"`);
  - `test_a_gap_past_the_stop_fills_at_the_next_open` (next open 93.0, below the level, is the fill);
  - `test_a_stop_and_a_rule_on_one_bar_report_stop_loss`;
  - `test_short_levels_mirror_the_long` (stop at entry × 1.02, target at entry × 0.95);
  - `test_rule_exits_add_no_field` (no `exit_reason` key on rule exits);
  - `test_a_level_on_the_last_bar_travels_with_the_open_position` (`close_at_end=False`: `open_position["exit_reason"] == "stop_loss"`; a second run with that `initial_position` fills it at its first evaluated open with the reason);
  - `test_a_stop_carried_across_a_window_join` (a position carried in by `initial_position` is stopped from its carried `entry_price`);
  - `test_a_stop_only_side_runs_every_job_kind` (Review Focus 1): backtest, a 2-cell experiment, a walk-forward and a study over a side whose exit is a 2% stop only, each finishing with trades labelled `"stop_loss"`.
  - In `test_aegis_kernel.py`: `test_kernel_matches_reference_with_stops` over `_breakout()` and `default_strategy()` with stops 1.5% / target 3%, on `bars()` and `wave_bars()`.
- [ ] **Step 2: Run.** `PYTEST tests/test_aegis_stops.py tests/test_aegis_kernel.py`. Expected: FAIL (unknown fields `stop_loss_pct`, exit required).
- [ ] **Step 3: Implement the model.** `exit` optional; a model validator requires an exit rule, a stop or a target; the bounds; a serializer that drops `exit`, `stop_loss_pct`, `take_profit_pct` when None (as `IndicatorSpec` drops empty `params`). `conditions`/`referenced_columns` skip an absent exit.
- [ ] **Step 4: Implement the engines.** `level_reason` lives in `kernel.py` (njit, so with numba absent it is plain Python) and is called by both engines, so the arithmetic is the same: `stop_level = entry_price * (1.0 - sign * stop)`, hit when `sign * (close - stop_level) <= 0.0`; `target_level = entry_price * (1.0 + sign * target)`, hit when `sign * (close - target_level) >= 0.0`; stop checked first; a fraction of 0 is never checked (without the guard a long with no stop would exit whenever the close is at or below its entry). In both loops the exit branch becomes "in position and (exit signal or a level)", setting the pending exit and its reason; nothing else moves, so with both fractions 0 every operation is today's. The last-bar branch carries the reason; the carried reason is read back on the fill. `_side_frame` sets `exit_signal` all False when `exit` is None. `_simulate_side_kernel` and `_side_metrics` pass `stop_loss_pct / 100` and `take_profit_pct / 100` (0 when unset). Trades and open positions carry `exit_reason` only when it is 1 or 2.
- [ ] **Step 5: Run.** The Step 2 command, then the identity check: `PYTEST tests/test_aegis_engine_golden.py tests/test_aegis_studies.py tests/test_aegis_kernel.py tests/test_aegis_backtest.py tests/test_aegis_walkforward.py`. Expected: PASS; goldens unchanged.
- [ ] **Step 6: Regenerate contracts; UI.** `describeRule` and the side summary handle an absent exit; run UI tests and build. Expected: PASS.
- [ ] **Step 7: LINT, whole Aegis suite** (`PYTEST` with no paths, from `C:\Triad`). Expected: all pass. Commit "Mission 13 Task 3: stop loss and take profit on the close, both engines".

### Task 4: Stop and target ranges

**Files:**
- Modify: `app/products/aegis/strategy.py` (`_resolve_path`, `apply_parameters`, `side_warmup`, the side's range validation)
- Modify: `app/products/aegis/surface.py` (`resolve_path`, `_whole_number`, `current_value`)
- Test: `tests/test_aegis_strategy.py`, `tests/test_aegis_surface.py`, `tests/test_aegis_experiments.py`, `tests/test_aegis_optimize.py`

**Interfaces:**
- Consumes: Task 3's side fields.
- Produces: side-relative paths `stop_loss_pct` and `take_profit_pct` (surface paths `long_side.stop_loss_pct`, `short_side.take_profit_pct`); `_resolve_path(side, "stop_loss_pct") -> ("", "stop_loss_pct")`.

- [ ] **Step 1: Write the failing tests.** `test_stop_paths_round_trip` (`apply_parameters(side, {"stop_loss_pct": 1.5})` sets it; fractional values kept); `test_ranging_an_unset_stop_is_refused` ("long_side.stop_loss_pct: the long side has no stop loss to range"); `test_a_surface_ranges_the_stop` (`current_value` is the side's value; not whole-number); `test_an_experiment_over_the_stop_runs_and_cells_differ` (stop 1, 2, 3 → three cells, at least two metrics differ); `test_the_optimizer_ranges_a_target` (a side range on `take_profit_pct` 3–5 step 1 → three cells).
- [ ] **Step 2: Run.** `PYTEST tests/test_aegis_strategy.py tests/test_aegis_surface.py tests/test_aegis_experiments.py tests/test_aegis_optimize.py`. Expected: the new tests FAIL ("unknown parameter path").
- [ ] **Step 3: Implement** the two paths in `_resolve_path` / `resolve_path` (a stop path is valid only when that side has the stop set), `apply_parameters` (sets the field), `side_warmup` (ignores them), `_whole_number` (False).
- [ ] **Step 4: Run** the Step 2 command and the goldens. Expected: PASS.
- [ ] **Step 5: LINT, commit** "Mission 13 Task 4: stop and target percentages can be ranged".

### Task 5: The phrase reader

**Files:**
- Create: `app/products/aegis/phrases.py`
- Modify: `app/products/aegis/api.py` (route)
- Test: create `tests/test_aegis_phrases.py`; `tests/test_aegis_api.py`

**Interfaces:**
- Consumes: Tasks 2–3 models.
- Produces: `ReadRequest(text: str [1–2,000 chars], strategy: StrategySpec)`; `Reading(sides: dict[Literal["long_side", "short_side"], StrategySide], reading: str, defaults: list[str])`; `class Unread(ValueError)` with `.spans: list[dict]` (`start`, `end`, `text`, character offsets into the text); `read(text: str, strategy: StrategySpec) -> Reading`; `POST /aegis/api/strategies/read` → 200 `Reading` or 422 `{"detail": {"message": str, "unread": [...]}}`. A returned side keeps the ranges of indicators it reused from the current side and has none for new ones (the builder adds their defaults, spec §9.3).

- [ ] **Step 1: Write the failing table test** `test_sentences_build_these_sides`, parametrized; each expected side is written out as JSON and validated as `StrategySide`:
  - the operator's sentence → long: indicators `ema` (EMA 9), `sma30` (SMA 30), `sma200` (SMA 200); entry `all_of [ema crosses_above sma30, price.close greater_than sma200]`; no exit rule; stop 2, target 5; `defaults == ["long_side.stop_loss_pct", "long_side.take_profit_pct"]`; reading exactly the Global Constraints string;
  - item 37's sentence (spec §9.6) → long: `donchian` (20), `rsi` (14); entry `all_of [price.close crosses_above donchian.upper, rsi less_than 70]`; exit `price.close crosses_below donchian.middle`; no stops, no defaults;
  - "short when rsi crosses below 70 and (close below 50 sma or close below 20 ema)" → nested `all_of [.., any_of [..]]`, default stops on the short side;
  - "buy when macd line crosses above macd signal; stop at 1.5%; take profit at 4%" → one `macd` block, stops 1.5 / 4, no defaults;
  - "go long when close inside bb 20 2. sell when close outside bb 20 2" → one `bb`, band operators with right `bb`;
  - "BUY when 9 EMA > 30 SMA" (case, symbols) → `greater_than`;
  - "sell when rsi above 70" on `default_strategy()` → only `long_side` returned: its entry and `ema`/`sma` kept, `rsi` added, exit replaced, stops unchanged;
  - "buy when 9 ema crosses 30 sma; short when 9 ema crosses 30 sma, stop at 3%" → long gets the default stop and target; short has stop 3, no target and no defaults, because a named stop is an exit (Review Focus 4).
- [ ] **Step 2: Write the failing refusals** `test_unread_text_is_refused_naming_it`, parametrized with the expected spans: "buy when vwap crosses 30 sma" (`vwap`); "buy when 9 ema crosses" (the missing right side: message "crosses needs something on its right"); "buy when 9 ema crosses 30 sma, stop at 2" (Review Focus 2: `stop at 2`, "write a stop as a percentage, e.g. 2%"); "buy when rsi above 70, stop at 2%, stop at 3%" ("two stop losses"); and the route test `test_read_route_answers_a_reading_or_422` in `test_aegis_api.py`.
- [ ] **Step 3: Run.** `PYTEST tests/test_aegis_phrases.py tests/test_aegis_api.py -k read`. Expected: FAIL (no module `products.aegis.phrases`).
- [ ] **Step 4: Implement `phrases.py`.** Lowercase, keep offsets; tokens are words, numbers (with an optional `%`), `(`, `)`, `>`, `<`, `,`, `;`, `.` (a `.` inside a number is part of it). Grammar:
  ```
  text    := clause ((";" | ".") clause)*
  clause  := opener expr tail* | level
  opener  := "buy when" | "go long when" | "long when"          -> long entry
           | "short when" | "sell short when" | "go short when" -> short entry
           | "sell when" | "exit when" | "close when"           -> long exit
           | "cover when"                                       -> short exit
  expr    := term ("or" term)*          term := factor ("and" factor)*
  factor  := "(" expr ")" | condition
  condition := operand compare operand | operand ("inside" | "outside") ["the"] band
  compare := "crosses" ["above"|"over"|"below"|"under"] | "is"? ("above"|"greater than"|">"|"below"|"less than"|"<")
  operand := number | price | indicator [output]
  price   := "price" | "close" | "open" | "high" | "low"
  indicator := N kind | kind N* | kind "(" N ("," N)* ")"   (kind: ema sma rsi atr bb bollinger donchian macd)
  output  := "line" | "signal" | "histogram" | "upper" | "middle" | "lower" ["band"]   (also before the kind: "upper bb 20")
  tail    := ("," | "with" | "and") level        level := stop | target
  stop    := "stop" ["loss"] ["at"] P | P "stop"  target := ("take profit" | "target" | "profit target") ["at"] P | P "target"
  ```
  `P` is a number followed by `%`. "and" before a level ends the expression. A level clause alone belongs to the side of the clause before it (long when first). Bare "crosses" is above in a long entry or short exit, below otherwise (spec §9.4). Settings after a kind are its length then its parameters in `kinds` order (bb: multiplier; macd: slow, signal). Ids follow spec §9.2; an exit-only clause reuses an existing indicator with equal kind, length, source and params. An entry clause returns a whole new side (direction, enabled, indicators in first-mention order, entry, its exit clause if any, levels); with no exit clause and no level, the default stop 2 / target 5 and their `defaults` paths. The side is validated as `StrategySide`; a validation error becomes `Unread` naming the clause. Any token not consumed is an unread span.
- [ ] **Step 5: Add the route** (`ReadRequest` body; `Unread` → `HTTPException(422, {"message": str(exc), "unread": exc.spans})`).
- [ ] **Step 6: Run** the Step 3 command. Expected: PASS. LINT, commit "Mission 13 Task 5: the phrase reader".

### Task 6: The builder's graph model (TypeScript, no UI)

**Files:**
- Create: `app/products/aegis/ui/src/builder/graph.ts`, `app/products/aegis/ui/src/builder/graph.test.ts`
- Create: `app/products/aegis/ui/src/builder/history.ts`, `app/products/aegis/ui/src/builder/history.test.ts`

**Interfaces:**
- Consumes: the regenerated contracts (`StrategySide`, `RuleGroup`, `RuleSpec`, `IndicatorSpec`).
- Produces:
  ```ts
  type BlockType = 'price' | 'indicator' | 'condition' | 'and' | 'or' | 'stop_loss' | 'take_profit' | 'entry' | 'exit';
  interface Block { id: string; type: BlockType; x: number; y: number; settings: BlockSettings }
  // indicator: { indicator: IndicatorSpec }; condition: { operator: string; left?: number; right?: number }
  // stop_loss / take_profit: { pct: number | null; badge?: 'default' }; others: {}
  interface Wire { id: string; from: string; fromPort: string; to: string; toPort: string }
  interface SideGraph { blocks: Block[]; wires: Wire[] }
  interface Canvas { version: 1; long: SideGraph; short: SideGraph }
  function graphFromSide(side: StrategySide): SideGraph;              // laid out automatically
  function sideFromGraph(graph: SideGraph, base: StrategySide):
    { side: StrategySide; problem: null } | { side: null; problem: string };
  function canConnect(graph: SideGraph, wire: Omit<Wire, 'id'>): string | null;  // null = allowed
  function readsAs(graph: SideGraph, side: StrategySide): boolean;    // ignoring optimization
  function looseBlocks(graph: SideGraph): Set<string>;
  function autoLayout(graph: SideGraph): SideGraph;
  class History<T> { constructor(first: T); push(next: T): void; undo(): T | null; redo(): T | null; current: T }
  ```
  Ports: price outputs `close|open|high|low`; an indicator outputs `value` (single series) or its kind's outputs, plus `band` for band kinds; condition inputs `left|right`, output `out`; and/or inputs `in0…inN` (one spare), output `out`; stop_loss / take_profit output `out`; entry input `rule`; exit inputs `rule|stop|target`. Block ids: indicators use the indicator id; Entry `entry`, Exit `exit`, Price `price`; others `<type>-<n>`.

- [ ] **Step 1: Write the failing tests** (`graph.test.ts`):
  - round trips `sideFromGraph(graphFromSide(s), s).side` equals `s` for `default_strategy`'s long side, the breakout, a nested tree, a stop-only exit, a side with a rule exit and both levels;
  - an AND with one wired input counts as that input; loose blocks are ignored by `sideFromGraph` and listed by `looseBlocks`;
  - problems, exactly: "Entry has nothing wired in"; "Exit has nothing wired in"; "condition-1: left input is empty"; "and-1 has nothing wired in"; "Stop loss needs a percentage above 0";
  - `canConnect` reasons: stop_loss → entry.rule "a stop goes into Exit"; a series → and-1 "a series goes into a condition"; a second wire into entry.rule "Entry takes one input: join conditions with AND or OR first"; a series into the right of an `inside_band` condition "inside band needs a band on the right"; a wire closing a loop "that would make a loop";
  - `readsAs` is false when the graph names an indicator the side no longer has, or a rule differs (Review Focus 3), true for an untouched round trip;
  - `autoLayout`: every price/indicator block's x < every condition's x < every group's x < Entry/Exit x, with no two blocks at the same position.
  - `history.test.ts`: push, undo, redo; a push after an undo clears redo; undo at the start returns null.
- [ ] **Step 2: Run** `npm --prefix app/products/aegis/ui test`. Expected: FAIL (no module `./graph`).
- [ ] **Step 3: Implement** `graph.ts` and `history.ts`. `sideFromGraph` walks from `entry.rule` and `exit.rule/stop/target`; operands: a price port → `price.<port>`; an indicator's `value` → its id; a named output → `<id>.<output>`; `band` → the bare id; an unwired input with a typed number → the number as a constant string. Indicators of the side are every indicator block (wired or not), keeping `base`'s order for existing ids, new ones appended. `autoLayout` places columns by depth from Entry/Exit (price and indicators leftmost), rows in tree order.
- [ ] **Step 4: Run** UI tests and build. Expected: PASS. Commit "Mission 13 Task 6: the builder's graph model".

### Task 7: The builder canvas in the Strategy Lab

**Files:**
- Modify: `app/products/aegis/ui/package.json`, `app/products/aegis/ui/package-lock.json`
- Create: `app/products/aegis/ui/src/components/builder/BuilderPage.tsx`, `Canvas.tsx`, `Blocks.tsx`, `Palette.tsx`, `StrategyList.tsx`
- Modify: `app/products/aegis/ui/src/components/LabPage.tsx` (composes the builder; the list moves into `StrategyList.tsx` keeping its ids), `app/products/aegis/ui/src/App.tsx` (the Lab page shows the builder), `app/products/aegis/ui/src/state/workspace.tsx`, `app/products/aegis/ui/src/components/DocumentHeader.tsx`, `app/products/aegis/ui/src/api/client.ts`, `app/products/aegis/ui/src/styles.css`
- Modify: `app/products/aegis/strategies.py` (`StrategyDocument.canvas`, `update(..., canvas)`, `duplicate` copies it), `app/products/aegis/api.py` (`StrategyUpdate.canvas`, `StrategyCreate.canvas`)
- Test: `tests/test_aegis_strategies.py`, `tests/test_aegis_api.py`, `app/products/aegis/ui/src/state/workspace.test.ts`

**Interfaces:**
- Consumes: Task 6 (`graphFromSide`, `sideFromGraph`, `canConnect`, `readsAs`, `looseBlocks`, `History`).
- Produces: `StrategyDocument.canvas: dict | None` (left out when None; refused over 262,144 bytes: "canvas too large"); workspace `canvas: Canvas | null`; actions `{ type: 'SET_SIDE_GRAPH'; side: Side; graph: SideGraph; spec: StrategySide | null }` (a null spec keeps the strategy and records the graph only, for positions and loose blocks) and `{ type: 'SET_BUILDER_SIDE'; side: Side }`; `SET_DOCUMENT` / `ADOPT_DOCUMENT` load `document.canvas` (each side kept when `readsAs`, else `graphFromSide`); the document counts as edited when the strategy or the canvas differs; `api.updateStrategy(id, { name?, spec?, canvas? })`. Element ids for the walk: `#builder`, `#builder-tab-long`, `#builder-tab-short`, `#palette-<type>` and `#palette-indicator-<KIND>`, `#builder-status`, `#builder-run`, `#builder-save`, `#builder-canvas` (React Flow nodes carry `data-id` = block id; handles carry `data-handleid` = port). The list keeps `#lab-page`, `#lab-new`, `.lab-table tbody tr#doc-<id>`, `#use-<id>`, `#rename-<id>`, `#rename-input`, `#rename-confirm`, `#duplicate-<id>`, `#delete-<id>`, `#lab-error`.

- [ ] **Step 1: Install and check the policy.** `npm --prefix app/products/aegis/ui install --save-exact @xyflow/react@12.12.0`; confirm `package.json` reads `"@xyflow/react": "12.12.0"`. A throwaway `<ReactFlow>` with two nodes on the Lab page; build; restart the worker detached; open `http://127.0.0.1:8102/aegis/` in the built-in browser (which enforces the worker's policy) on the Lab page and read console errors. Expected: the nodes render, no content-security-policy errors. If there are errors, stop and report them (a blocker for the operator).
- [ ] **Step 2: Write the failing Python tests.** `test_the_canvas_is_kept_outside_the_hash` (saving a canvas leaves `strategy_hash` unchanged and returns the canvas); `test_a_document_without_a_canvas_dumps_without_one`; `test_a_canvas_over_256_kb_is_refused`; `test_duplicate_copies_the_canvas`; `test_update_saves_the_canvas` (route). Run `PYTEST tests/test_aegis_strategies.py tests/test_aegis_api.py -k canvas`. Expected: FAIL.
- [ ] **Step 3: Implement the document field and routes.** Run the Step 2 command. Expected: PASS. Regenerate contracts.
- [ ] **Step 4: Write the failing reducer tests** (`workspace.test.ts`): `SET_SIDE_GRAPH` replaces the side and its graph; a graph-only change (moved block) marks the document edited and keeps the strategy; `SET_DOCUMENT` with a stale canvas side lays that side out automatically and keeps the other. Run UI tests. Expected: FAIL.
- [ ] **Step 5: Implement the state and the builder.** The Lab page: `BuilderPage` (text line placeholder for Task 8, Long/Short tabs, `Palette` left, `Canvas` centre, `StrategyList` right, collapsible), editing the workspace strategy. `Canvas` maps the side's graph to React Flow nodes and edges; `Blocks` render each type (indicator length and settings inputs, a condition's operator select and number inputs on unwired sides, a level's percentage, the "default" badge); `isValidConnection` uses `canConnect` and shows its reason in `#builder-status` for 4 s; drag from the palette (HTML drag, dropped at `screenToFlowPosition`); a new indicator block uses `newIndicator` and `defaultRanges` as `ADD_INDICATOR` does; Delete and right-click remove blocks (Entry and Exit never); every edit pushes `{ strategy side, graph }` onto a `History`, and Ctrl+Z / Ctrl+Y move through it; each edit dispatches `SET_SIDE_GRAPH` with `sideFromGraph`'s side, or a null spec and the problem in `#builder-status` (loose blocks greyed). `#builder-run` (enabled when Ready) goes to the charts page and starts the run the chart's Run starts; `#builder-save` (enabled when Ready and edited) saves spec and canvas through `api.updateStrategy`. Clicking a saved strategy's row opens it in the builder. The built-in strategy opens read-only (no edits, no Save).
- [ ] **Step 6: Run** UI tests and build; restart the worker; in the built-in browser drag an RSI, a condition and an AND in, wire them, delete, undo, save, reload. Expected: tests PASS, build clean, the canvas behaves, no console errors.
- [ ] **Step 7: LINT, commit** "Mission 13 Task 7: the builder canvas in the Strategy Lab".

### Task 8: The text line, the panel summary, trade labels and ranges

**Files:**
- Create: `app/products/aegis/ui/src/components/builder/PhraseBar.tsx`, `app/products/aegis/ui/src/builder/apply.ts`, `app/products/aegis/ui/src/builder/apply.test.ts`
- Modify: `app/products/aegis/ui/src/api/client.ts` (`readText`), `app/products/aegis/ui/src/components/SideCard.tsx`, `app/products/aegis/ui/src/components/StrategyPanel.tsx`, `app/products/aegis/ui/src/components/OptimizationRanges.tsx`, `app/products/aegis/ui/src/components/TradesTab.tsx`, `app/products/aegis/ui/src/rules.ts`
- Delete: `app/products/aegis/ui/src/components/RuleEditor.tsx`
- Test: `apply.test.ts`, `rules.test.ts`, a `TradesTab` label test

**Interfaces:**
- Consumes: Task 5's route; Task 6–7 graph, state and history.
- Produces: `api.readText(text: string, strategy: StrategySpec): Promise<Reading>` (a 422 surfaces its `message` and `unread` spans); `applyReading(strategy: StrategySpec, reading: Reading): { strategy: StrategySpec; graphs: Partial<Record<Side, SideGraph>> }` (sides replaced; each new indicator gets `defaultRanges`, a reused one keeps its ranges; graphs from `graphFromSide`, levels named in `defaults` badged "default"); `describeSide(side, indicators)` → "ENTRY: … / EXIT: … OR stop loss 2% OR take profit 5%"; `exitLabel(trade) -> '' | 'stop loss' | 'take profit'`. Ids: `#phrase-input`, `#phrase-reading`, `#phrase-apply`, `#phrase-error` (unread spans underlined), `#edit-in-builder-long`, `#edit-in-builder-short`.

- [ ] **Step 1: Write the failing tests.** `applyReading` on the operator's reading: long side replaced, `ema`, `sma30`, `sma200` get their default (disabled) ranges, the short side untouched, the two level blocks badged; on "sell when rsi above 70" over the reference: `ema`/`sma` ranges kept, `rsi` ranges added; `describeSide` with a stop-only exit reads "EXIT: stop loss 2% OR take profit 5%"; `exitLabel` maps the two reasons and nothing else. Run UI tests. Expected: FAIL.
- [ ] **Step 2: Implement.** `PhraseBar` over the canvas: Enter calls `readText`; the reading shows in `#phrase-reading` with `#phrase-apply`; Apply dispatches the new strategy and graphs and pushes the history (Ctrl+Z undoes it); a refusal shows `#phrase-error` with the unread words underlined and changes nothing. `SideCard` drops the rule editors and shows `.logic` from `describeSide`, plus `#edit-in-builder-<side>` (Lab page, that tab). `OptimizationRanges` lists `stop_loss_pct` / `take_profit_pct` ranges of sides that have them ("stop loss %", "take profit %"). `TradesTab` shows `exitLabel` beside the exit time. Delete `RuleEditor.tsx`.
- [ ] **Step 3: Run** UI tests and build; restart the worker; in the built-in browser type the operator's sentence, Apply, Run. Expected: PASS; the blocks appear; trades show "stop loss" / "take profit".
- [ ] **Step 4: Commit** "Mission 13 Task 8: the text line, the panel summary and trade labels".

### Task 9: Acceptance, item 37 and the record

**Files:**
- Modify: `tests/products/aegis/browser_workstation.py` (item 37; items 91–97; `BUILDER_BASE`; the counts in its docstring)
- Create: `docs/MISSION13_STRATEGY_BUILDER.md`; `docs/evidence/aegis-acceptance-<stamp>.json`

**Interfaces:**
- Consumes: every element id above; `self.item`, `self.api`, `self.post`, `self.js`, `self.experiment_body`, `self.wait_until`.
- Produces: `BUILDER_BASE = "<this plan's commit>"`; a 97-item walk.

- [ ] **Step 1: Convert item 37** to type the spec §9.6 sentence into `#phrase-input`, Apply, save, and keep its assertions (indicators `["donchian", "rsi"]`, the same entry, exit on `donchian.middle`) and `.side-card.long .logic`.
- [ ] **Step 2: Write items 91–97** in `strategy_builder()`, called after item 90:
  - 91 the operator's sentence: reading shown, Apply, blocks `ema`, `sma30`, `sma200`, a condition, an AND, a "default" stop and target; Run; the run's trades include at least one `exit_reason`, and the Trades tab shows "stop loss" or "take profit";
  - 92 drag an RSI, a condition and an AND in; wire RSI → condition left, type 50 on the right, the crossover condition and the new one into the AND, the AND into Entry; status Ready; delete the RSI block → status names the empty input; Ctrl+Z → Ready again; save;
  - 93 reload; open the strategy from the list: block positions equal the saved canvas; open a document saved before this mission (the newest "Donchian RSI breakout" created before `MISSION13_STARTED`, a constant beside `BUILDER_BASE`): its blocks are laid out, it is not marked edited, its hash is unchanged;
  - 94 an experiment over `long_side.stop_loss_pct` 1–3 step 1 on item 91's strategy runs to done with three cells;
  - 95 on the charts page `.side-card.long .logic` reads the tree and "stop loss 2%"; `#edit-in-builder-long` opens the Lab on the Long tab;
  - 96 "buy when vwap crosses 30 sma": `#phrase-error` names `vwap`, the strategy is unchanged;
  - 97 governance: nothing under the three Core paths changed since `BUILDER_BASE`; aegis `human_directed` / `CLOSED`; DailySchedule `c99fa831` disabled; items 1–96 PASS.
- [ ] **Step 3: Trial** items 37 and 91–97 alone (a scratchpad trial script in the Mission 12 pattern). Expected: all PASS.
- [ ] **Step 4: The walk.** `.venv/Scripts/python.exe tests/products/aegis/browser_workstation.py`. Expected: 97/97 PASS, no page errors. Copy the evidence into `docs/evidence/`.
- [ ] **Step 5: Identity on real data and the store.** `builder_identity.py compare <m13_identity_before.json>` and `hashes`. Expected: `identical`; `0 changed`.
- [ ] **Step 6: `tools\verify.ps1`** on the branch. Expected: lint and format clean, all three scopes green, stopping at "Wrong Git branch" by design. Plus UI tests and build.
- [ ] **Step 7: Write the record** (intent, decisions, what was built per task, identity evidence, measurements, rulings, verification) and commit "Aegis: Mission 13 acceptance and the record".
