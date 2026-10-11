# Aegis Mission 5 — Strategy Lab and walk-forward carry-over Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry open positions across walk-forward windows, add six indicator kinds with panes,
a two-condition rule builder and saved strategy documents, so a non-crossover strategy can be
built, run, optimized and walked forward with every number real and reproducible.

**Architecture:** Everything stays inside `app/products/aegis/`. Indicator metadata is declared
once in a dependency-free module (`kinds.py`) that the contracts, the engine and the generated
TypeScript all read; compute functions stay in `indicators.py`. Rules evaluate operands to
series and operators to boolean series inside the existing simulation loop. Strategy documents
are a fourth repository kind behind the existing JSON repository; the Strategy Lab page is a
document list beside the same right panel the workspace uses.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pandas; React 18, Vite 5, TypeScript, vitest;
Vela 0.8.3 behind `ChartAdapter`; Playwright 1.63 for acceptance.

**Spec:** `docs/superpowers/specs/2026-10-11-aegis-strategy-lab-design.md`

## Global Constraints

- Work on branch `aegis/strategy-lab` in the `C:\Triad` checkout, cut from `main` at `a73f70e`.
- No file under `app/trading_core/`, `app/platform_host/` or `app/products/triad/` changes.
- The default strategy's `model_dump(mode="json")` stays byte-identical, and the recorded
  identical-request hash `cdbc9abd2238542ee299e694209241b40561f39bfdd3632f58c93350b237e360`
  must still be produced by acceptance item 22.
- Backtest and optimizer hashes never change; walk-forward hashes change once (recorded).
- Honesty rule: nothing fabricated is shown; absent values render as `—`, unbuilt surfaces say
  "Not yet built".
- Exchange stays CLOSED, no broker or order path, Triad stays suspended, no scheduler change.
- Python tests: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`; lint:
  `.venv/Scripts/python.exe -m ruff check app/products/aegis tests tools` and
  `.venv/Scripts/python.exe -m ruff format --check app/products/aegis tests tools`.
- UI commands run only from `app/products/aegis/ui`: `npm test`, `npm run build`.
- Any Pydantic model change is followed by `.venv/Scripts/python.exe tools/aegis_contracts.py`;
  `tests/test_aegis_contracts.py` fails when `contracts.ts` is stale.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; commit
  with `git -c core.hooksPath=NUL commit -F <file>`.
- Indicator ids match `^[a-z][a-z0-9_]*$`; constants match `^-?\d+(\.\d+)?$`; at most two
  conditions per rule; six indicator kinds beyond the existing two, no more.

## Plan rulings against the spec

These refine the spec where it was silent or where a literal reading would be wrong. Each is
binding for the tasks below.

| # | Ruling | Why |
|---|---|---|
| P1 | A document's `id` **is** its spec's `id` and its `name` is the spec's `name`; the envelope's `strategy_id` is `strategy.id`. | One source of truth; every persisted envelope since Mission 3 already embeds `strategy.id`, so usage counts cover old runs. |
| P2 | "Unsaved edits" compares `canonical(document.spec)` with `canonical(strategy)` in the browser; the browser never computes SHA-256. The hash prefix shown comes from the server. | Matching Python's JSON float formatting in the browser is fragile; the reducer already has `canonical()`. |
| P3 | Per-window out-of-sample metrics are rebased on the previous window's `ending_equity` (drawdown from a running peak starting there). | Without it, unrealized P&L carried across a join is counted in both windows' net P&L and efficiency. Stitched metrics are unchanged. |
| P4 | An exit signal on a window's last bar travels with the open position (`exit_signal_time`, `exit_tags`) and fills at the next window's first evaluated bar open. Entry signals on a last bar do not travel. | Otherwise every carried trade would be held one bar longer than a continuous run would hold it. |
| P5 | MACD warm-up is `slow + signal − 1`, and all three MACD outputs are NaN until the signal line exists. | The spec's `slow + signal` contradicts its own "every output is NaN until its warm-up is complete"; this is the exact count. |
| P6 | Heatmap axes: a single `crosses_above`/`crosses_below` rule between two bare single-output ids whose lengths are both in the grid keeps today's fast/slow axes and fast ≥ slow skip; otherwise the axes are the first two enabled paths. Cells whose applied side fails validation (MACD fast ≥ slow) are skipped too. The plan route gains `skip_reason`. | `expand_grid` assumed `entry.left`/`entry.right` were indicator ids. |
| P7 | Kind metadata (outputs, pane, parameter defaults, integer parameters, default length, warm-up terms) lives in `kinds.py` and is emitted into `contracts.ts` as `INDICATOR_KINDS` by the generator. | One source; the staleness test pins TypeScript to Python. |
| P8 | The Strategy Lab page is the document list in the main area beside the same right panel; editing happens in the right panel on either page. | Spec §8 puts the editors in the side cards and the Save/Revert in the right panel. |
| P9 | The chart and the Indicators tab show one side at a time, the focused side (default long), chosen in the Indicators tab. | Independent sides may carry different indicators under the same id. |
| P10 | The built-in document is synthesized from `default_strategy()` on every read, never written to disk; its `created_at`/`updated_at` are `null`. | It cannot drift and cannot be deleted. |
| P11 | The link toggle mirrors length and parameter edits to the other side only where an indicator with the same id exists; adding and removing indicators act on the focused side only. | Mirroring a removal would break the other side's rules. |
| P12 | When a window has no valid in-sample cell but a position was carried into it, its out-of-sample run uses the most recent earlier window's chosen configuration and the record carries `inherited_from`; efficiency is null. | Otherwise the carried position is orphaned and never closed. |
| P13 | No Python `describe()`; the rule description helper exists only in TypeScript. | No Python consumer exists. |
| P14 | Adding an indicator also adds disabled optimization ranges for its length and numeric parameters; removing it drops them. | The ranges panel edits existing ranges only; this keeps the item-4 grid buildable without a new widget. |

## Review Focus

1. **Runs persisted before this mission** (no `params`, no `strategy_hash`, no carry fields) must
   reload, rerun to the same hash and count toward a document's usage. Test in Task 7.
2. **Unusually written constants** (`1e3`, `+5`, ` 70`, `NaN`, `Infinity`, `.5`) are refused
   with the operand named; only plain decimals pass. Test in Task 5.
3. **Removing an indicator that a rule or range still references** is refused with the
   reference named, over HTTP (422) and in the reducer; never a 500, never a silent drop. Tests
   in Tasks 5 and 9.
4. **A carried position followed by a window with no valid in-sample cell** is still managed and
   closed (P12). Test in Task 2.
5. **Deleting a document while a job using it is running** is refused, since the running job's
   persisted summary is a reference. Test in Task 7.

---

### Task 1: Engine carry-over

**Files:**
- Modify: `app/products/aegis/backtest.py` (`BacktestSettings`, `_simulate_side`)
- Test: `tests/test_aegis_backtest.py`

**Interfaces:**
- Produces: `OpenPosition` (Pydantic, `extra="forbid"`): `side: Literal["LONG","SHORT"]`,
  `entry_time: str`, `signal_time: str`, `entry_price: float`, `quantity: int (>0)`,
  `entry_fee: float`, `capital_at_entry: float`, `entry_tags: list[str]`,
  `origin_window: int | None = None`, `exit_signal_time: str | None = None`,
  `exit_tags: list[str] = []`.
- Produces: `BacktestSettings.initial_position: OpenPosition | None = None`,
  `BacktestSettings.close_at_end: bool = True`.
- Produces: every enabled side result gains `open_position: dict | None`, `ending_cash: float`,
  `ending_equity: float`; a trade closed from a carried position gains
  `carried_from_window: int | None`. None of these is in `SIDE_KEYS`.

- [ ] **Step 1: Write the failing tests** in `tests/test_aegis_backtest.py`, using the existing
  `bars()` fixture and `default_strategy()` with the short side disabled:
  - `test_close_at_end_false_reports_the_open_position`: find a cut index where the full run's
    long side is holding a position, run on `bars()[:cut]` with `close_at_end=False`; assert
    `open_position["side"] == "LONG"`, `quantity > 0`, no trade has
    `exit_signal_time == exit_time`, `ending_cash` equals the cash before entry and
    `ending_equity == equity[-1]["equity"]`.
  - `test_carried_position_reproduces_the_continuous_run`: run the full fixture once; run the
    first part with `close_at_end=False`, then the rest (with a 35-bar lead and
    `evaluate_from` at the cut) with `initial_position=OpenPosition(**open, origin_window=0)`
    and `initial_capital=ending_cash`; assert the carried trade's `exit_time`, `exit_price` and
    `net_pnl` equal the continuous run's trade (`pytest.approx`, `abs=1e-9`) and
    `carried_from_window == 0`.
  - `test_exit_signal_on_the_last_bar_travels_with_the_position`: cut exactly at a bar whose
    exit signal fires; assert `open_position["exit_signal_time"]` is that bar's time and the
    next part fills the exit at its first evaluated bar's open.
  - `test_initial_position_side_mismatch_is_refused`: a LONG position given to a run whose long
    side is disabled and short side enabled raises `ValueError` whose message contains
    `does not match`.
  - `test_plain_run_result_is_unchanged`: the default run's `canonical_payload` hash equals the
    hash computed at `a73f70e` for the same fixture (compute it once on `main` and paste the
    hex into the test).
- [ ] **Step 2: Run them.** `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_aegis_backtest.py`
  Expected: the four new carry tests FAIL (`OpenPosition` import error or missing keys); the
  unchanged-hash test PASSES.
- [ ] **Step 3: Implement.** In `_simulate_side`: start from `initial_position` when set (side
  mismatch raises `ValueError("initial_position side LONG does not match the short side")`);
  a carried position with `exit_signal_time` becomes a pending exit that fills only once
  `evaluating` is true (compute `evaluating` at the top of the loop); on the last bar with
  `close_at_end=False`, a firing exit signal on a warm bar is recorded on the reported
  `open_position` instead of being dropped; the end-of-data close runs only when
  `close_at_end` is true. `ending_equity` is the last curve point or `initial_capital` when
  the curve is empty.
- [ ] **Step 4: Run.** Same command. Expected: all PASS. Then the whole Aegis suite:
  `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_aegis_*.py` → PASS.
- [ ] **Step 5: Regenerate contracts and commit.** `.venv/Scripts/python.exe tools/aegis_contracts.py`,
  then commit `backtest.py`, the test file and `ui/src/contracts.ts` as
  "Aegis engine: carry an open position in and out of a run".

### Task 2: Walk-forward carry-over and the tab columns

**Files:**
- Modify: `app/products/aegis/walkforward.py` (`pending_record`, `WalkForwardJob.run_unit`,
  `commit`), new helper `rebase`
- Modify: `app/products/aegis/ui/src/results.ts` (`WindowRecord`, `Trade`),
  `ui/src/components/WalkForwardTab.tsx`
- Test: `tests/test_aegis_walkforward.py`, `ui/src/components/walkforward.test.ts`

**Interfaces:**
- Consumes: Task 1's `OpenPosition`, `initial_position`, `close_at_end`, `open_position`,
  `ending_cash`, `ending_equity`, `carried_from_window`.
- Produces: `rebase(trades: list[dict], equity: list[dict], baseline: float, exposure: float) -> dict`
  returning `{"equity": [...], "metrics": {...}}` with drawdown from a running peak starting at
  `baseline` and `_metrics(trades, equity, baseline, exposure)`.
- Produces: window records gain `carried_in: bool`, `open_at_end: bool`,
  `ending_cash: float | None`, `ending_equity: float | None`, `inherited_from: int | None`
  (all present from `pending_record`: `False, False, None, None, None`).
- Produces (TS): `WindowRecord.carried_in/open_at_end/ending_cash/ending_equity/inherited_from`,
  `Trade.carried_from_window?: number | null`; `carryLabel(r: WindowRecord): string` exported
  from `WalkForwardTab.tsx` returning `"in"`, `"out"`, `"in · out"` or `"—"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_aegis_walkforward.py` with the module's
  existing job fixtures (a short-window walk on synthetic bars that holds positions across
  joins; tune the fixture so at least one window ends holding):
  - `test_only_the_final_window_can_close_at_its_edge`: every trade of a non-final window has
    `window_edge_exit` false.
  - `test_open_at_end_and_carried_in_agree_across_every_join`: for each k,
    `records[k]["open_at_end"] == records[k+1]["carried_in"]`, and each carried trade's
    `carried_from_window` names a window with `open_at_end` true.
  - `test_window_net_pnl_is_rebased_on_the_previous_ending_equity`: for each k ≥ 1 with an
    `oos`, `oos.metrics.net_pnl == ending_equity[k] − ending_equity[k−1]` (`abs=1e-6`); for
    k = 0 the baseline is the request's capital.
  - `test_stitched_net_pnl_equals_the_final_ending_equity_minus_capital`.
  - `test_no_valid_cell_after_a_carry_inherits_the_previous_configuration` (P12): force window
    k+1's cells to have no valid objective (monkeypatch `select_best` to return `None` for
    that window) while window k ends holding; assert record k+1 has `status == "done"`,
    `inherited_from == k`, `efficiency is None`, and the position is closed by the last window.
  - `test_walkforward_hash_is_stable_across_two_runs` (re-assert the existing determinism test
    still holds with the new fields).
- [ ] **Step 2: Run them.** `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_aegis_walkforward.py`
  Expected: the new tests FAIL on missing keys or edge exits in non-final windows.
- [ ] **Step 3: Implement.** The job keeps `_carry` (an `OpenPosition` dump or `None`),
  `_chained_cash` and `_chained_equity` (both start at the request's capital). The OOS unit
  passes `initial_capital=_chained_cash`, `initial_position=OpenPosition(**_carry)` when set
  and `close_at_end = (window is the last)`. On commit: the record's `oos` holds the engine's
  trades (through `flag_edge_exits`) and `rebase(...)` output against `_chained_equity`;
  `carried_in` is whether `_carry` was set when the unit ran; `open_at_end`,
  `ending_cash`, `ending_equity` come from the side result; `_carry` becomes the reported
  `open_position` with `origin_window` kept when already set, else the window index; efficiency
  uses the rebased metrics. P12: when `best` is `None` and `_carry` is set, run with the most
  recent earlier record's `best["params"]` and set `inherited_from`.
- [ ] **Step 4: Run.** Same command → PASS; then `tests/test_aegis_*.py` → PASS.
- [ ] **Step 5: UI.** Write `walkforward.test.ts` cases for `carryLabel` (four outcomes) and a
  stitched carried-trade count, run `npm test` (FAIL), add the types, the helper, a "Carry"
  column in `#walkforward-windows-<side>` and "N carried" in the stitched row
  (`#walkforward-stitched-<side>`), run `npm test` and `npm run build` → PASS.
- [ ] **Step 6: Commit** "Aegis walk-forward: carry positions across windows, rebase window metrics".

### Task 3: Indicator kinds, compute frames and the contract's parameters

**Files:**
- Create: `app/products/aegis/kinds.py`
- Modify: `app/products/aegis/indicators.py`, `app/products/aegis/strategy.py` (`IndicatorSpec`)
- Test: `tests/test_aegis_indicators.py`, `tests/test_aegis_strategy.py`

**Interfaces:**
- Produces (`kinds.py`, no Aegis imports): `@dataclass(frozen=True) KindInfo(outputs: tuple[str, ...],
  pane: Literal["price","own"], params: dict[str, float], integer_params: frozenset[str],
  requires: tuple[str, ...], default_length: int, warmup_terms: tuple[str, ...],
  warmup_offset: int)`; `KINDS: dict[str, KindInfo]` for `EMA, SMA, RSI, ATR, BB, DONCHIAN,
  MACD` with the spec §5.1 values (`default_length`: EMA 9, SMA 30, RSI 14, ATR 14, BB 20,
  DONCHIAN 20, MACD 12; warm-up: EMA/SMA/BB `("length",)+0`, RSI/ATR/DONCHIAN `("length",)+1`,
  MACD `("slow","signal")−1` per P5); `kind_info(kind: str) -> KindInfo` (case-insensitive,
  `ValueError("unknown indicator kind 'X'")`); `warmup(kind: str, length: int, params: dict[str, float]) -> int`.
- Produces (`indicators.py`): `compute(spec: IndicatorSpec, frame: pd.DataFrame) -> pd.DataFrame`
  with one column per reference spelling (`id` for single-output kinds, `id.output` otherwise);
  `references(spec: IndicatorSpec) -> list[str]`; `IndicatorCache.get(...) -> pd.DataFrame`
  keyed by `(data_key, KIND, source, length, tuple(sorted(effective params)))`.
- Produces (`strategy.py`): `IndicatorSpec.params: dict[str, float] = {}` omitted from dumps
  when empty (a `model_serializer(mode="wrap")`), `id` pattern `^[a-z][a-z0-9_]*$`, a validator
  refusing unknown kinds, unknown parameter names (`"MACD has no parameter 'x'"`), non-positive
  values, non-integral integer parameters, and MACD `length >= slow`
  (`"MACD fast length 26 must be below slow 26"`); `IndicatorSpec.effective_params() -> dict[str, float]`
  (defaults merged).

- [ ] **Step 1: Write the failing tests.**
  - `test_default_strategy_json_is_byte_identical`: the default strategy's
    `json.dumps(model_dump(mode="json"), sort_keys=True)` sha256 equals the value computed on
    `main` at `a73f70e` (paste the hex).
  - Hand-computed values (`pytest.approx(abs=1e-4)`):
    RSI(2) on closes `[1,2,3,2,3]` → `[nan, nan, 100, 50, 75]`;
    ATR(2) on H `[10,12,13,11]`, L `[9,10,11,8]`, C `[9.5,11,12,9]` → `[nan, nan, 2.25, 3.125]`;
    DONCHIAN(2) on the same H/L → upper `[nan,nan,12,13]`, lower `[nan,nan,9,10]`, middle
    `[nan,nan,10.5,11.5]`;
    BB(2, multiplier 2) on closes `[1,3,5]` → middle `[nan,2,4]`, upper `[nan,4,6]`, lower
    `[nan,0,2]`;
    MACD(length 2, slow 3, signal 2) on closes `[1..6]` → line `[nan,nan,nan,0.39352,0.44367,0.47081]`,
    signal `[nan,nan,nan,0.36420,0.41718,0.45293]`, histogram
    `[nan,nan,nan,0.02932,0.02649,0.01788]`.
  - `test_first_value_index_is_warmup_minus_one` for every kind at default parameters on 200
    synthetic bars.
  - `test_cache_distinguishes_parameters`: BB multiplier 2 and 3 are two cache entries; the
    same spec twice is one entry plus one hit.
  - Contract refusals: unknown kind, `params={"x": 1}` on RSI, `params={"slow": 0}`,
    `params={"slow": 26.5}` on MACD, MACD `length=26` with default slow, id `"EMA"` and id
    `"1x"`; each `ValidationError` message contains the named value.
- [ ] **Step 2: Run.** `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_aegis_indicators.py tests/test_aegis_strategy.py`
  Expected: new tests FAIL; the byte-identical test PASSES.
- [ ] **Step 3: Implement** `kinds.py`, the compute functions (Wilder smoothing seeded by the
  mean of the first `length` changes or true ranges, then `avg = (avg·(n−1)+x)/n`; RSI is 100
  when the average loss is zero; BB uses the population standard deviation; DONCHIAN uses
  `shift(1)` before the rolling max/min; MACD masks all outputs before the signal line exists),
  `compute`/`references`/the cache key, and the `IndicatorSpec` changes. Update the two existing
  callers (`api.indicators`, `backtest._side_frame`) to read columns from the frame.
- [ ] **Step 4: Run.** Same command → PASS; then `tests/test_aegis_*.py` → PASS (backtest and
  optimizer hashes in existing tests unchanged).
- [ ] **Step 5: Regenerate contracts and commit** "Aegis indicators: kinds registry, RSI, ATR,
  Bollinger, Donchian, MACD, parameters".

### Task 4: Warm-up by kind and parameter paths

**Files:**
- Modify: `app/products/aegis/strategy.py` (`_resolve_path`, `apply_parameters`,
  `OptimizationParameter`), `backtest.py` (`_check_warmup`), `walkforward.py`
  (`longest_length` → `side_warmup`, `plan`, `lead_bars` call), `optimize.py` (`expand_grid`,
  `GridPlan`), `api.py` (`optimize_plan` returns `skip_reason`)
- Test: `tests/test_aegis_strategy.py`, `tests/test_aegis_optimize.py`,
  `tests/test_aegis_walkforward.py`, `tests/test_aegis_backtest.py`

**Interfaces:**
- Consumes: Task 3's `warmup`, `KINDS`, `IndicatorSpec.effective_params`.
- Produces: parameter paths `indicators.<id>.length` and `indicators.<id>.params.<name>`;
  `_resolve_path(side, path) -> tuple[str, str]` returns `(id, "length")` or
  `(id, "params.<name>")`; `apply_parameters` rounds lengths and integer parameters only.
- Produces: `side_warmup(side: StrategySide) -> int` in `walkforward.py` (max over indicators of
  `warmup` with each enabled range on that indicator set to its `stop`); the floor becomes
  `MIN_BARS + side_warmup(side)` and the lead `max(chosen warmup + 1, MIN_BARS)` where chosen
  warmup is `side_warmup` of the applied side with no ranges. `longest_length` is removed.
- Produces: `GridPlan.skip_reason: str | None` (`"fast ≥ slow"` for P6's classic cross,
  `"invalid parameter combinations"` when only validation skips occurred, `None` when nothing
  was skipped); `fast_path`/`slow_path` keep their names and now mean row/column axes.

- [ ] **Step 1: Write the failing tests.**
  - `test_warmup_check_uses_the_kind`: RSI 40 (warm-up 41) on exactly 41 bars is refused by
    the engine and on 42 accepted (the 35-bar floor would hide a shorter length); the rule stays
    "refuse when bars ≤ warm-up".
  - `test_side_warmup_counts_parameter_ranges`: MACD with an enabled `params.slow` range to 40
    and default signal → `40 + 9 − 1`.
  - `test_params_path_round_trips`: `apply_parameters(side, {"indicators.bb.params.multiplier": 2.5})`
    sets 2.5 unrounded; `indicators.macd.params.slow: 30.0` sets integer 30.
  - `test_unknown_params_path_is_refused`: `indicators.rsi.params.slow` → `ValueError` naming
    the path.
  - `test_grid_axes_for_a_group_rule_are_the_first_two_paths`: a side with a group entry and
    ranges on `donchian.length` (10–40 step 10) and `rsi.length` (7–21 step 7) → 12 cells,
    `fast_path == "indicators.donchian.length"`, `skip_reason is None`.
  - `test_grid_skips_invalid_macd_cells`: MACD length 10–30 step 10 × `params.slow` 20–30 step
    10 → cells with fast ≥ slow are skipped and `skip_reason == "invalid parameter combinations"`.
  - `test_reference_grid_is_unchanged`: the default side's grid keeps 271 cells, 1 skipped,
    `skip_reason == "fast ≥ slow"`.
- [ ] **Step 2: Run** the four test files. Expected: new tests FAIL.
- [ ] **Step 3: Implement** the path grammar, the rounding rule, `side_warmup`, the
  generalized `_check_warmup` message (`"... cannot complete the warm-up of RSI(40) (41 bars)"`),
  P6 in `expand_grid`, and `skip_reason` in the plan route. The optimizer range validator
  requires integral start/stop/step for `.length` and for integer parameters.
- [ ] **Step 4: Run** → PASS; `tests/test_aegis_*.py` → PASS.
- [ ] **Step 5: Commit** "Aegis: warm-up by kind, parameter paths, general grid axes".

### Task 5: Rules — operands, operators, groups, evaluation

**Files:**
- Modify: `app/products/aegis/strategy.py` (`RuleSpec`, new `RuleGroup`, `StrategySide`
  validation), `app/products/aegis/backtest.py` (`_signal` → evaluator, `_side_frame`, warm flag)
- Test: `tests/test_aegis_strategy.py`, `tests/test_aegis_backtest.py`, `tests/test_aegis_api.py`

**Interfaces:**
- Consumes: Task 3's `KINDS`, `references`.
- Produces: `OPERATORS = ("crosses_above","crosses_below","greater_than","less_than","inside_band","outside_band")`;
  `PRICE_OPERANDS = {"price.close": "close", "price.open": "open", "price.high": "high", "price.low": "low"}`;
  `RuleGroup(all_of: list[RuleSpec] | None = None, any_of: list[RuleSpec] | None = None)` with the
  unset key omitted from dumps; `StrategySide.entry/exit: RuleSpec | RuleGroup`;
  `conditions(rule) -> list[RuleSpec]`; `referenced_columns(side) -> set[str]`.
- Produces: `evaluate(data: pd.DataFrame, rule: RuleSpec | RuleGroup) -> pd.Series[bool]` in
  `backtest.py`; `_side_frame` adds every reference column of every indicator; `warm` is true
  where every referenced indicator column is non-null (true everywhere when none is referenced).

- [ ] **Step 1: Write the failing tests.**
  - Validation messages (each a `ValidationError` containing the quoted text): unknown operand
    `"foo"` → `unknown operand 'foo'`; bare `"donchian"` with a non-band operator →
    `donchian has outputs upper, lower, middle`; `"rsi.upper"` → `rsi has no output 'upper'`;
    `inside_band` with right `"rsi"` → `inside_band needs a band (bb or donchian)`; two
    constants → `compares two constants`; `all_of` with one condition →
    `a group needs two conditions`; three → `at most two conditions in this slice`; both
    `all_of` and `any_of` set → `exactly one of all_of or any_of`; unknown operator →
    `unknown operator 'between'`.
  - Review Focus 2: constants `"1e3"`, `"+5"`, `" 70"`, `"NaN"`, `"Infinity"`, `".5"` are each
    refused as unknown operands; `"70"`, `"-1"`, `"0.5"` accepted.
  - Evaluation on a small frame: `greater_than`/`less_than` against a constant;
    `crosses_above` against a constant (`rsi crosses_above 30`); `inside_band`/`outside_band`
    with a Donchian frame (boundary values inclusive for inside); `all_of`/`any_of` truth tables.
  - `test_breakout_strategy_trades_on_synthetic_bars`: long entry
    `all_of[price.close crosses_above donchian.upper, rsi less_than 70]`, exit
    `price.close crosses_below donchian.middle` on `bars()` produces at least one trade and a
    stable `result_hash` across two runs.
  - `test_side_without_indicators_runs`: `price.close greater_than 100` with no indicators runs.
  - API (Review Focus 3): POST `/aegis/api/backtest` with a rule referencing a removed id →
    422 whose detail names the operand; with an optimization range on a removed id → 422 naming
    the path.
- [ ] **Step 2: Run** the three test files → new tests FAIL.
- [ ] **Step 3: Implement** operand resolution (indicator reference, price field, constant by
  the constant pattern), side-level validation in `StrategySide`, the evaluator, the columns and
  the warm flag. The simulation loop is untouched.
- [ ] **Step 4: Run** → PASS; `tests/test_aegis_*.py` → PASS (the default strategy's hashes in
  existing tests unchanged).
- [ ] **Step 5: Regenerate contracts, commit** "Aegis rules: operands, six operators,
  two-condition groups".

### Task 6: Series route, generated kinds and the TypeScript rule helpers

**Files:**
- Modify: `app/products/aegis/api.py` (`indicators` route), `tools/aegis_contracts.py`
- Create: `app/products/aegis/ui/src/rules.ts`, `app/products/aegis/ui/src/rules.test.ts`
- Modify: `app/products/aegis/ui/src/api/client.ts` (indicators response type),
  `ui/src/components/WalkForwardTab.tsx` and `OptimizePopover.tsx` (`longestLength` → `warmupBars`)
- Test: `tests/test_aegis_api.py`, `tests/test_aegis_contracts.py`

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces (HTTP): `POST /aegis/api/indicators` → `{times, series, outputs: {id: [output…]},
  pane: {id: "price"|"own"}, data}`; `outputs[id]` is `[]` for single-output kinds; `series`
  keys are reference spellings.
- Produces (generated `contracts.ts`): object schemas with `additionalProperties` render as
  `Record<string, T>`; `export const INDICATOR_KINDS: Record<string, {outputs: string[]; pane: 'price' | 'own';
  params: Record<string, number>; integer_params: string[]; requires: string[]; default_length: number;
  warmup_terms: string[]; warmup_offset: number}>` emitted from `kinds.KINDS`.
- Produces (`rules.ts`): `kindOf(spec)`, `referencesOf(spec): string[]`,
  `warmupOf(spec): number`, `warmupBars(side: StrategySide | undefined): number` (mirrors
  `side_warmup`), `describeRule(rule, indicators): string` (e.g.
  `price.close crosses ABOVE DONCHIAN(20).upper AND RSI(14) < 70`), `conditionsOf(rule)`,
  `ruleReferences(side, id): string[]` (names like `"entry rule"`, `"exit rule"`,
  `"range indicators.rsi.length"`).

- [ ] **Step 1: Write the failing tests.** API: the series route for `[donchian, rsi, macd]`
  returns keys `donchian.upper/.lower/.middle`, `rsi`, `macd.line/.signal/.histogram`, the
  `outputs` and `pane` maps. Contracts: the staleness test plus
  `test_indicator_kinds_constant_matches_python`. vitest `rules.test.ts`: `warmupBars` equals
  the Python values for the reference side (31 with ranges to 100 → 100) and a MACD side;
  `describeRule` for a single rule and an `all_of` group; `ruleReferences` finds rule and range
  references.
- [ ] **Step 2: Run** `pytest tests/test_aegis_api.py tests/test_aegis_contracts.py` and
  `npm test` → FAIL.
- [ ] **Step 3: Implement** the route, the generator changes, `rules.ts`, and replace
  `longestLength` with `warmupBars` in the walk-forward tab and popover (same
  `defaultWindowBars` contract). Regenerate contracts.
- [ ] **Step 4: Run** both suites and `npm run build` → PASS.
- [ ] **Step 5: Commit** "Aegis: series route outputs and panes, generated kinds, rule helpers".

### Task 7: Strategy documents — repository, library, routes, envelope fields

**Files:**
- Create: `app/products/aegis/strategies.py`
- Modify: `app/products/aegis/runs.py` (strategies kind, `delete_strategy`, per-kind summary,
  `SUMMARY_KEYS` gains `strategy_id`, `strategy_hash`), `results.py` (`strategy_hash`),
  `api.py` (routes, `_envelope`), `optimize.py` and `walkforward.py` (`snapshot`),
  `tools/aegis_contracts.py` (add `StrategyDocument` to the models)
- Test: `tests/test_aegis_strategies.py` (new), `tests/test_aegis_runs.py`, `tests/test_aegis_api.py`

**Interfaces:**
- Produces: `results.strategy_hash(spec: StrategySpec) -> str` (sha256 of `canonical_json` of
  the spec dump).
- Produces: `BUILTIN_ID = "ema9-sma30-cross-v1"`; `StrategyDocument(id, name, spec, created_at:
  str | None, updated_at: str | None, strategy_hash: str, parent: str | None, builtin: bool)`;
  `slug(name: str) -> str` (lowercase, runs of non-alphanumerics → `-`, trimmed, max 48,
  `"strategy"` when empty); `StrategyLibrary(repository)` with `list() -> list[dict]` (summaries
  with `kinds`, `usage: {runs, optimizations, walkforwards}`), `get(id)`, `create(name, spec,
  parent=None)`, `update(id, name=None, spec=None)`, `duplicate(id, name)`, `delete(id)`,
  `usage(id)`; exceptions `BuiltinRefused(ValueError)` and `StrategyReferenced(Exception)` with
  `.counts`.
- Produces: repository `save_strategy(doc: dict) -> str`, `get_strategy(id) -> dict`,
  `list_strategies() -> list[dict]`, `delete_strategy(id) -> None`; documents live in
  `data/aegis/strategies/`.
- Produces (HTTP): `GET /aegis/api/strategies`, `GET /aegis/api/strategies/{id}`,
  `POST /aegis/api/strategies` `{name, spec}` → 201, `PUT /aegis/api/strategies/{id}`
  `{name?, spec?}`, `POST /aegis/api/strategies/{id}/duplicate` `{name}` → 201,
  `DELETE /aegis/api/strategies/{id}` → `{"deleted": id}`; errors 404 unknown, 409
  `strategy <id> is referenced by N runs, M optimizations, K walk-forwards`, 422 built-in
  (`the built-in strategy is read-only; duplicate it`) and invalid specs.
- Produces: backtest, optimization and walk-forward envelopes carry `strategy_id` and
  `strategy_hash`; neither enters a result hash.

- [ ] **Step 1: Write the failing tests.**
  - Library: create overwrites `spec.id`/`spec.name` with the document's; slug collision gets a
    6-hex suffix; unicode-only name → `strategy`; update changes `updated_at` and
    `strategy_hash`; duplicate sets `parent`; the built-in is listed, `get` returns
    `default_strategy()` byte-identical, and update/delete raise `BuiltinRefused`.
  - Usage and Review Focus 1: a run envelope persisted in the Mission 3 shape (no
    `strategy_id`, with `strategy.id` = the document id) counts as one run reference.
  - Review Focus 5: an optimization started with a held runner (`_held_runner`) on the
    document's spec → `DELETE` is 409 while it runs and the detail names one optimization.
  - Routes: each status code above; `PUT` with an invalid rule → 422 naming the operand.
  - Envelopes: backtest response has `strategy_id == spec.id` and a 64-hex `strategy_hash`;
    `result_hash` for the default request is unchanged from the value in
    `test_backtest_hash_stable_across_two_requests`.
  - Repository: `delete_strategy` removes the document and its sidecar; unknown id → `KeyError`.
- [ ] **Step 2: Run** `pytest tests/test_aegis_strategies.py tests/test_aegis_runs.py tests/test_aegis_api.py` → FAIL.
- [ ] **Step 3: Implement** in the listed files. Route dependency: `StrategyLibrary(repository)`
  built from the existing `REPOSITORY` dependency so the test fixture's override applies.
- [ ] **Step 4: Run** → PASS; whole suite `pytest -q -p no:cacheprovider` → PASS.
- [ ] **Step 5: Regenerate contracts, commit** "Aegis: strategy documents, library routes,
  strategy identity on envelopes".

### Task 8: Chart panes, legend and crosshair

**Files:**
- Modify: `ui/src/chart/adapter.ts`, `ui/src/chart/vela.ts`, `ui/src/chart/sync.ts`,
  `ui/src/components/ChartPanel.tsx`, `ui/src/api/client.ts`
- Test: `ui/src/chart/adapter.test.ts`

**Interfaces:**
- Consumes: Task 6's series route shape and `INDICATOR_KINDS`.
- Produces (state, consumed by Task 9): `focusSide: Side` (default `'long'`),
  `latest: Record<string, number | null>`; actions `SET_FOCUS_SIDE {side}`,
  `SET_LATEST {values}`.
- Produces: `Overlay` gains `pane: 'price' | 'own'`, `group: string`, `style: 'line' | 'columns'`;
  `CrosshairPoint` gains `paneKind: 'price' | 'study' | null` and `values: Record<string, number>`
  keyed by overlay id; `overlaysFromSeries(times, series, meta: Record<string, OverlayMeta>)` with
  `OverlayMeta = {title, color, pane, group, style}`; `chartMeta(indicators, outputs, pane):
  Record<string, OverlayMeta>` in `sync.ts` (titles like `DONCHIAN 20 upper`, `RSI 14`; MACD
  `histogram` → `columns`; `ema`/`sma` keep `#2da7ff`/`#39d98a`; other groups take the next
  palette colours, one per output).
- Produces (Vela): native type `aegis-pane` (`paneHint: 'new'`, `overlay: false`, `legend: false`,
  `multiInstance: true`, input `group`) emitting every overlay of its group with
  `kind: 'line' | 'columns'`; one handle per own-pane group; price overlays keep `aegis-line`.
  The adapter keeps a series-id → overlay-id map to translate `CrosshairEvent.values`.

- [ ] **Step 1: Write the failing tests** (mock adapter, no library): `chartMeta` for
  `[ema, sma, donchian, rsi, macd]` gives price panes for ema/sma/donchian outputs, own panes
  grouped by id for rsi and macd, `columns` for `macd.histogram`; `syncChart` passes overlays
  with those fields; the reference strategy's overlays keep ids `ema`/`sma`, titles
  `EMA 9`/`SMA 30` and their colours.
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement.** ChartPanel draws the focused side's indicators (P9), builds the
  legend from the meta (one entry per drawn series, coloured), shows the hovered study pane's
  values when `paneKind === 'study'`, and dispatches the latest value per series for the
  Indicators tab (`SET_LATEST`, Task 9).
- [ ] **Step 4: Run** `npm test` and `npm run build` → PASS. Manually load QQQ 1h with RSI and
  MACD on the long side in the built-in browser against a dev worker; confirm two study panes
  and the histogram render. Record the observation in the ledger.
- [ ] **Step 5: Commit** "Aegis chart: study panes, histogram columns, legend and pane-aware crosshair".

### Task 9: Right panel — Indicators tab, generic inputs, rule editors

**Files:**
- Create: `ui/src/components/IndicatorsTab.tsx`, `ui/src/components/RuleEditor.tsx`
- Modify: `ui/src/state/workspace.tsx`, `ui/src/components/StrategyPanel.tsx`,
  `ui/src/components/SideCard.tsx`
- Test: `ui/src/state/workspace.test.ts`

**Interfaces:**
- Consumes: `rules.ts` (Task 6), `INDICATOR_KINDS`.
- Consumes: Task 8's `focusSide`, `latest`, `SET_FOCUS_SIDE`, `SET_LATEST`.
- Produces (state): `rightTab: 'strategy' | 'indicators'`; actions `SET_RIGHT_TAB {tab}`,
  `ADD_INDICATOR {side, kind}` (id = lowercase
  kind, `_2`, `_3`… when taken; `default_length`; no params; P14 disabled ranges: length
  `max(2, ⌊L/2⌋)`–`2L` step `max(1, round(L/10))`, parameters default/2–default×2 step default/4,
  integer parameters rounded), `REMOVE_INDICATOR {side, id}` (no state change when
  `ruleReferences` names a rule; otherwise drops the indicator and its ranges),
  `SET_RULE {side, which: 'entry' | 'exit', rule: RuleSpec | RuleGroup}`.
- Produces (DOM ids, for acceptance): `#right-tab-indicators`, `#focus-long`, `#focus-short`,
  `#add-indicator-kind` (select), `#add-indicator`, rows `#indicator-<id>` with
  `#remove-<id>`, `#indicator-error`; generic inputs `#<id>-length` and `#<id>-<param>` (long or
  linked) and `#short-<id>-length` (short, unlinked) so `#ema-length`/`#sma-length` stay valid;
  rule editors `#<side>-<which>-left-0`, `-operator-0`, `-right-0`, `-constant-0`, `-left-1`…,
  `#<side>-<which>-add-condition`, `#<side>-<which>-join` (AND/OR), `#<side>-<which>-remove-1`.

- [ ] **Step 1: Write the failing reducer tests**: add RSI twice → ids `rsi`, `rsi_2`, two
  disabled ranges added; remove `ema` from the reference long side is refused (state identical)
  and `ruleReferences` names `entry rule` and `exit rule`; remove an unreferenced indicator
  drops it and its ranges; linked `SET_SIDE_PARAM` on `indicators.rsi.length` changes the short
  side only when it has `rsi` (P11); `SET_RULE` with an `all_of` group round-trips through
  `canonical`.
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement** the reducer, the Indicators tab (focus side, list with kind,
  editable length and parameters, source select, pane, latest values or `—`, add/remove with the
  refusal message in `#indicator-error`), and the same generic inputs component in the Strategy
  tab (only one right tab is mounted at a time, so the input ids never collide), and `RuleEditor` inside each side card
  (operand options: the side's reference spellings, the four price fields and `constant…`;
  band operators offer only bb/donchian ids on the right). Side cards keep describing rules in
  words via `describeRule`.
- [ ] **Step 4: Run** `npm test` and `npm run build` → PASS.
- [ ] **Step 5: Commit** "Aegis UI: Indicators tab, generic indicator inputs, rule editors".

### Task 10: Strategy Lab page and document state

**Files:**
- Create: `ui/src/components/LabPage.tsx`, `ui/src/components/DocumentHeader.tsx`,
  `ui/src/state/documents.ts`
- Modify: `ui/src/App.tsx`, `ui/src/components/SideNav.tsx`, `ui/src/components/StrategyPanel.tsx`,
  `ui/src/state/workspace.tsx`, `ui/src/api/client.ts`
- Test: `ui/src/state/workspace.test.ts`, `ui/src/state/documents.test.ts`

**Interfaces:**
- Consumes: Task 7's routes; `StrategyDocument` from the generated contracts.
- Produces (client): `api.strategies()`, `api.strategyDocument(id)`, `api.createStrategy(name, spec)`,
  `api.updateStrategy(id, patch)`, `api.duplicateStrategy(id, name)`, `api.deleteStrategy(id)`.
- Produces (state): `page: 'charts' | 'lab'`, `document: StrategyDocument | null`; actions
  `SET_PAGE {page}`, `SET_DOCUMENT {document}` (also sets `strategy = document.spec`),
  `ADOPT_DOCUMENT {document | null}` (keeps `strategy`); `unsavedEdits(state): boolean` (P2).
- Produces (`documents.ts`): `useDocumentSync()` — when `strategy.id` differs from
  `document?.id`, fetch that document and adopt it (404 → `null`).
- Produces (DOM ids): `#nav-charts`, `#nav-lab`, `#lab-new`, rows `#doc-<id>` with
  `#use-<id>`, `#duplicate-<id>`, `#rename-<id>`, `#delete-<id>`, `#rename-input`,
  `#lab-error`; right panel `#document-name`, `#unsaved-edits`, `#save-document`,
  `#revert-document`.

- [ ] **Step 1: Write the failing tests**: `unsavedEdits` false after `SET_DOCUMENT`, true after
  a `SET_SIDE_PARAM`, false after `ADOPT_DOCUMENT` with the edited spec; `SET_PAGE` switches
  pages without touching strategy; `useDocumentSync`'s pure decision helper
  `documentToFetch(state): string | null`.
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement.** App loads the built-in document at start (keeping the
  `apiState` messages), renders the Lab page (document table: name, hash prefix, updated or `—`,
  kinds, usage counts; New creates "Untitled strategy" from the built-in spec; Duplicate asks
  for a name inline; Rename edits inline; Delete shows the server's 409/422 detail in
  `#lab-error`; "Use in workspace" sets the document and switches to Charts) beside the right
  panel; the right panel's `DocumentHeader` shows the name, `unsaved edits`, Save (PUT; disabled
  with the read-only title for the built-in) and Revert. SideNav makes Charts and Strategy Lab
  clickable; other items stay "Not yet built".
- [ ] **Step 4: Run** `npm test` and `npm run build` → PASS.
- [ ] **Step 5: Commit** "Aegis UI: Strategy Lab page, document header, document sync".

### Task 11: Acceptance, worker restart and the mission record

**Files:**
- Modify: `tests/products/aegis/browser_workstation.py` (items 37–47, item 22 asserts the
  recorded hash)
- Create: `docs/MISSION5_STRATEGY_LAB.md`, `docs/evidence/aegis-acceptance-<stamp>.json`

**Interfaces:**
- Consumes: everything above, through the browser and HTTP only.

- [ ] **Step 1: Write the items** (spec §1, in order): 37 build the breakout strategy in the
  Lab from a new document (Donchian 20 and RSI 14 on the long side, entry `all_of`, exit on
  `donchian.middle`, ema/sma removed from the long side) and save; 38 use it on QQQ 1h
  2023-01-01 → 2024-12-31 and see three Donchian lines on the price pane, an RSI study pane,
  both in the legend, and a study value in the crosshair readout; 39 run the backtest (trades,
  markers, three metric sets, a hash); 40 optimize Donchian 10–40 step 10 × RSI 7–21 step 7
  (12 cells) and apply the best; 41 walk forward 1000/250 with the structural carry checks of
  spec §1 item 5 (no non-final edge close; `open_at_end[k] == carried_in[k+1]`; rebased window
  net P&L equals the ending-equity difference); 42 duplicate, rename, delete the copy, and
  see the original's delete refused with the 409 detail; 43 item 22's hash equals the recorded
  `cdbc9abd…` (edit item 22 itself); 44 identical rerun → same hash; 45 Indicators tab lists
  kind, parameters, source, pane and latest values, and removing `rsi` is refused naming the
  entry rule; 46 the five HTTP refusals of spec §1 item 10 each return 422 naming the problem;
  47 status `human_directed` / `CLOSED` and
  `git diff --name-only a73f70e HEAD -- app/trading_core app/platform_host app/products/triad`
  is empty.
- [ ] **Step 2: Build and restart.** `npm run build` (ui dir); restart the Aegis worker detached
  (WMI `Win32_Process.Create` of `tools/start_product.ps1 -Product aegis`); poll
  `/aegis/api/status` until the new PID answers.
- [ ] **Step 3: Run** `.venv/Scripts/python.exe tests/products/aegis/browser_workstation.py`
  Expected: 47/47 PASS; copy the JSON to `docs/evidence/`.
- [ ] **Step 4: Full verification.** Whole pytest suite, ruff check and format check,
  `npm test`, `npm run build` → all green; record counts.
- [ ] **Step 5: Write the record** `docs/MISSION5_STRATEGY_LAB.md` (decisions, built table by
  commit, acceptance evidence with hashes including the new walk-forward hash, measurements,
  plan rulings P1–P14, known limits) and commit "Aegis: Strategy Lab acceptance and the
  Mission 5 record".

### After Task 11: stop and ask (operator instruction, 2026-10-11)

Before the milestone QA and the whole-branch review, stop and ask the operator whether to run
them on Fable 5.1 or Opus 5.5. Then: milestone QA (independent agent at the exact commit, the
spec §9 brief), whole-branch review on the chosen model, one fix pass with every fix
test-first, the record completed, and the finishing menu (merge and push only on the
operator's answer).
