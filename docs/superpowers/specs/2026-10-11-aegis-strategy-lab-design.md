# Aegis Mission 5 — Strategy Lab and walk-forward carry-over (design)

Date: 2026-10-11. Builds on the merged Mission 4 slice (`main` at `ac811c1`,
`docs/MISSION4_WALK_FORWARD.md`). Operator framing approved in chat on 2026-10-11: carry
positions across walk-forward windows first (the operator's yes to the semantics change); an
indicator library beyond the EMA/SMA cross; a per-side rule builder; a Strategy Lab page for
strategy documents; the Indicators tab lit; regenerated contracts; acceptance through backtest,
optimization and walk-forward for a non-crossover strategy; milestone QA and whole-branch
review; merge and push on the operator's call.

Standing constraints carry over unchanged: honesty rule (nothing fabricated is shown), pinned
raw-archive provenance, one job at a time, Core imports neither product, no Core change in this
mission, exchange CLOSED, no broker path, Triad suspended with its scheduled autonomy disabled.

## 1. Intent and definition of done

The operator can study strategies beyond one moving-average cross without writing code, with
every number still real, pinned and reproducible, and the walk-forward record no longer cut at
window edges.

Definition of done (the acceptance script walks these in order):

1. Build "LONG: enter when `price.close` crosses above `donchian.upper` AND `rsi` is less than
   70; exit when `price.close` crosses below `donchian.middle`" in the Strategy Lab from a new
   document, with Donchian 20 and RSI 14 as the side's indicators, and save it.
2. Use it in the workspace on QQQ 1h 2023-01-01 → 2024-12-31: see Donchian's three outputs on
   the price pane and RSI in its own pane, both in the legend; the crosshair reads the RSI pane.
3. Run the backtest: real trades, markers, long/short/combined metrics, a `result_hash`.
4. Optimize the long side over Donchian 10–40 step 5 × RSI 7–21 step 7 and apply the best cell.
5. Walk the long side forward (in-sample 500 / out-of-sample 125 bars): a trade entered in one
   window and closed in the next is shown as carried, the stitched equity is continuous across
   the join, and only the final window may show an edge close.
6. Duplicate the document, rename the copy, delete the copy; deleting the original is refused
   while the run from item 3 references it, with the reason shown.
7. Reload the built-in 9 EMA / 30 SMA strategy and rerun QQQ 1h 2023–2024: the Mission 3 hash
   `c9b6f8f821c0…` is returned unchanged.
8. Rerun the new strategy's backtest with nothing changed: the same `result_hash`.
9. The Indicators tab lists the side's indicators with kind, parameters, source, pane and the
   latest value per output; removing an indicator a rule references is refused with the rule
   named.
10. Every validation refusal is honest: an unknown operand, a bare id of a multi-output kind, a
    band operator with a non-band operand, a group of one or three conditions, a parameter the
    kind does not have, each answered with a 422 naming the problem.
11. `GET /aegis/api/status` still reports `human_directed` / `CLOSED`; no file under
    `app/trading_core/`, `app/platform_host/` or `app/products/triad/` changed.

## 2. Operator decisions recorded in this design

| Decision | Choice (chat, 2026-10-11) |
|---|---|
| Mission shape | Carry-over fix first, then the Strategy Lab |
| Chart panes | **Add pane support now**: price-scale kinds overlay the price pane, oscillators get one pane each (Vela native indicator with `paneHint: 'new'`) |
| Contract growth | **Extend in place (A)**: `IndicatorSpec.params`, string operands with validated references, `entry`/`exit` as one rule or a two-condition group; the default strategy's JSON stays byte-identical so every Mission 3 and 4 hash reproduces |
| Rule breadth | Six operators, two conditions with AND/OR, constants and price fields as operands |
| Non-goals held | No expression language, no stops or sizing, no joint-side walk-forward, no Core change |

## 3. Architecture

Everything lives under `app/products/aegis/`. Dependencies still point one way: browser →
worker HTTP → `data`, `indicators`, `backtest`, `optimize`, `walkforward`, `jobs`, `runs`.
Core is imported only for `local_headers`, `Store` and `process_power`
(`tests/test_architecture.py` enforces).

| Unit | Location | Responsibility |
|---|---|---|
| Engine carry-over | `backtest.py` (revised) | `OpenPosition`, `BacktestSettings.initial_position`, `close_at_end`; `open_position`, `ending_cash`, `ending_equity` in side results; `carried_from_window` on closing trades |
| Indicator library | `indicators.py` (revised) | registry of kinds (compute, outputs, pane, params, warm-up); multi-output frames; cache keyed with params |
| Contracts | `strategy.py` (revised) | `IndicatorSpec.params`, operand references, operators, `RuleGroup`, side validation, parameter paths |
| Rule evaluation | `backtest.py` (revised) | operand → series, operator → boolean series, groups, warm-up over referenced columns |
| Walk-forward | `walkforward.py` (revised) | carry-over plumbing, window flags, kind-based warm-up and lead |
| Strategy documents | `runs.py` (revised), `strategies.py` (new) | repository kind `strategies` with sidecars; document shape, ids, hash, usage counts, delete refusal |
| API | `api.py` (revised) | `/strategies` routes; `pane`/`outputs` in the series route; `strategy_id`/`strategy_hash` on envelopes |
| Chart | `ui/src/chart/` (revised) | `Overlay.pane`/`group`; Vela pane native type; sync mapping |
| UI | `ui/src/` (revised) | Strategy Lab page, Indicators tab, rule editors, generic indicator inputs, workspace document state |
| Acceptance | `tests/products/aegis/browser_workstation.py` (extended) | items 1–11 above appended to the Mission 3 and 4 walks |

## 4. Walk-forward carry-over

### 4.1 Engine

`OpenPosition` (Pydantic, `extra="forbid"`): `side: "LONG" | "SHORT"`, `entry_time`,
`signal_time` (ISO, timezone-aware), `entry_price: float`, `quantity: int`, `entry_fee: float`,
`capital_at_entry: float`, `entry_tags: list[str]`, `origin_window: int | None`.

`BacktestSettings` gains `initial_position: OpenPosition | None = None` and
`close_at_end: bool = True`. Serialization keeps both out of the dump when at their defaults so
the backtest envelope, canonical payload and hashes of plain runs are unchanged.

`_simulate_side` starts holding `initial_position` when its `side` matches the simulated side
(a mismatch raises `ValueError("initial_position side LONG does not match the short side")`);
`cash` starts at `initial_capital`; marked-to-market equity includes the position from the first
evaluated bar; exits follow the side's exit rule as for any position; the closing trade carries
`carried_from_window = initial_position.origin_window`. With `close_at_end` false, an open
position at the last bar is not closed: the side result reports `open_position` (an
`OpenPosition` dump with `origin_window` set by the caller) or `null`, plus `ending_cash` (the
cash balance) and `ending_equity` (the last marked value). With `close_at_end` true (default)
the end-of-data close behaves as today and `open_position` is `null`. The canonical backtest
payload (`results.canonical_payload`) is unchanged for plain runs: `open_position`,
`ending_cash` and `ending_equity` are not part of `SIDE_KEYS` and never enter a backtest hash.

### 4.2 Walk-forward

Window k's out-of-sample run uses `initial_capital = window k−1's ending_cash` (the request's
capital for window 0), `initial_position = window k−1's open_position` with `origin_window =
k−1`, and `close_at_end = (k is the last window)`. Window records gain `carried_in: bool`,
`open_at_end: bool`, `ending_cash`, `ending_equity`; out-of-sample trades keep
`window_edge_exit` (now only possible on the final window) and gain `carried_from_window`.
Stitched equity is the concatenation as today (continuous because marked equity includes the
open position); stitched metrics, efficiency and stability are unchanged in definition. The
payload includes the new fields, so walk-forward hashes change once more (recorded). The tab's
windows table shows "carried in" and "open at end"; the stitched row counts carried trades.

## 5. Indicator library

### 5.1 Kinds

| Kind | Inputs | Parameters (defaults) | Outputs | Pane | Warm-up bars |
|---|---|---|---|---|---|
| `EMA` | `source` | — | single | price | `length` |
| `SMA` | `source` | — | single | price | `length` |
| `RSI` | `source` | — | single (0–100) | own | `length + 1` |
| `ATR` | high, low, close | — | single | own | `length + 1` |
| `BB` | `source` | `multiplier` (2.0) | `upper`, `middle`, `lower` | price | `length` |
| `DONCHIAN` | high, low | — | `upper`, `lower`, `middle` | price | `length + 1` |
| `MACD` | `source` | `slow` (26), `signal` (9); `length` is the fast period | `line`, `signal`, `histogram` | own | `slow + signal` |

Definitions: EMA `ewm(span=length, adjust=False, min_periods=length)`; SMA rolling mean;
RSI with Wilder smoothing of average gains and losses over `length` (`100 − 100/(1+RS)`, 100
when the average loss is zero); ATR Wilder-smoothed true range over `length`; BB middle = SMA,
upper/lower = middle ± `multiplier` × population standard deviation over `length`; DONCHIAN upper
= highest high and lower = lowest low of the **previous** `length` bars (the current bar
excluded, so a breakout rule on the close can fire), middle = their mean; MACD line = EMA(fast)
− EMA(slow), signal = EMA(signal) of the line, histogram = line − signal. Every output is NaN
until its warm-up is complete.

### 5.2 Registry and cache

`INDICATORS[kind] = IndicatorKind(compute(spec, frame) -> pd.DataFrame, outputs: tuple[str, ...],
pane: "price" | "own", params: dict[str, float], requires: tuple[str, ...], warmup(spec) -> int)`.
`compute(spec, frame)` returns one column per output (single-output kinds: one column named by
the id); `IndicatorCache.get` returns that frame, keyed by (data identity, kind, source, length,
sorted params). `warmup(side)` = max over the side's indicators of `kind.warmup(spec)` and over
enabled ranges' upper ends (replacing `longest_length`), used by the engine's warm-up check,
the walk-forward floor and the lead.

### 5.3 Contract

`IndicatorSpec`: `id`, `kind` (registry key, case-insensitive), `length: int > 0`,
`source: "close" | "open" | "high" | "low"` (ignored by kinds that use high/low/close
directly), `params: dict[str, float]` (keys must be the kind's parameters; missing keys take the
defaults; `params` is omitted from dumps when empty, which keeps the default strategy's JSON and
every existing hash byte-identical; a test pins the default strategy's canonical JSON),
`overlay: bool` (kept for compatibility, derived from the kind's pane on validation).

Optimizer paths: `indicators.<id>.length` and `indicators.<id>.params.<name>`; `_resolve_path`
and `apply_parameters` accept both; the range validator requires integer start/stop/step for
`.length`; parameter ranges may be fractional.

### 5.4 Series route

`POST /aegis/api/indicators` returns `times`, `series` (keys: `id` for single-output kinds,
`id.output` for multi-output), `outputs: {id: [output, …]}`, `pane: {id: "price" | "own"}`,
`data`. The chart draws from this; nothing is computed in the browser.

## 6. Rule model and evaluation

- **Operand grammar** (strings in `RuleSpec.left/right`): an indicator id (single-output kind),
  `id.output` (multi-output kind), `price.close|open|high|low`, or a decimal constant
  (`30`, `0.5`, `-1`). A bare id of a multi-output kind is refused naming its outputs; an unknown
  id or output is refused naming it; two constants compared with each other are refused.
- **Operators**: `crosses_above`, `crosses_below` (as today, on the two series' previous and
  current bars), `greater_than`, `less_than`, `inside_band`, `outside_band`. Band operators
  take `left` as a series operand and `right` as the bare id of a kind with `upper` and `lower`
  outputs (`bb`, `donchian`): inside is `lower ≤ left ≤ upper`, outside is `left < lower or left
  > upper`. Any other `right` for a band operator is refused.
- **Groups**: `entry` and `exit` are a `RuleSpec` or `RuleGroup { all_of: [RuleSpec, RuleSpec] }`
  / `{ any_of: [...] }` with exactly two conditions (one is refused as "a group needs two
  conditions", three or more as "at most two conditions in this slice"). `timing` stays
  `bar_close`.
- **Evaluation** (`backtest.py`): operand → `pd.Series` (indicator column, price column, or a
  constant broadcast), operator → boolean series, groups combine with `&` / `|`; the side's
  `warm` flag is true where every referenced indicator column is non-null. The simulation loop,
  temporal precedence, fills, markers, exposure and chaining are unchanged.
- **Description**: `describe(rule, side)` renders "price.close crosses above DONCHIAN(20).upper
  AND RSI(14) < 70" for side cards, trades and the lab; the TypeScript side has the same helper.

## 7. Chart panes and the Indicators tab

- `Overlay` gains `pane: 'price' | 'own'`, `group: string` (the indicator id) and `style:
  'line' | 'columns'` (histograms as columns). The Vela backend registers a second native type
  with `paneHint: 'new'`; all overlays of one `group` with `pane: 'own'` are emitted by one
  instance so they share a pane; price-pane overlays behave as today. `sync.ts` maps the series
  route's `outputs` and `pane` onto overlays (one per output, colours per group), library-free
  and unit-tested with the mock adapter.
- Chart legend lists every drawn series; the crosshair readout shows the hovered pane's value
  (`e.paneKind === 'study'` carries the study values).
- Indicators tab (right panel, lit): the current side's indicators with kind, parameters,
  source, pane and the latest value per output from the fetched series; add (kind picker with
  parameter fields, id derived from the kind and made unique), remove (refused when a rule
  references the indicator, naming the rule), edit lengths and parameters; the link toggle
  mirrors indicator edits across sides as today. The Strategy tab's inputs become generic per
  indicator; nothing is hard-coded to the crossover.

## 8. Strategy Lab and documents

- **Document**: `{id, name, spec: StrategySpec, created_at, updated_at, strategy_hash, parent}`;
  `strategy_hash` = SHA-256 of the spec's canonical JSON. The built-in document
  `ema9-sma30-cross-v1` (the default strategy) is always listed, cannot be deleted or renamed,
  and its spec is byte-identical to today's `default_strategy()`.
- **Repository** (`runs.py` kind `strategies`, folder `data/aegis/strategies/`, sidecar
  summaries): `save_strategy`, `get_strategy`, `list_strategies`, `delete_strategy`. Usage
  counts come from the persisted run, optimization and walk-forward summaries' `strategy_id`.
- **Envelopes**: runs, optimizations and walk-forwards gain `strategy_id` and `strategy_hash`
  (the document loaded when the request was made, or the built-in; the hash of the spec that
  actually ran, which differs from the document's when it ran with unsaved edits). Neither
  enters a result hash.
- **Routes** (`/aegis/api/strategies`): `GET` list (summaries with usage counts), `GET /{id}`,
  `POST` create (`{name, spec}` → id from a slug of the name plus a 6-character hash suffix when
  taken), `PUT /{id}` update (`{name?, spec?}`), `POST /{id}/duplicate` (`{name}`), `DELETE /{id}`
  (409 `{"detail": "strategy <id> is referenced by N runs, M optimizations, K walk-forwards"}`;
  404 unknown; 422 for the built-in). Every spec goes through the side validation of §6.
- **Page** (sidebar "Strategy Lab", lit): list with name, hash prefix, updated, kinds used,
  usage counts; New (from the built-in), Duplicate, Rename, Delete, "Use in workspace". The right
  panel shows the loaded document's name, "unsaved edits" when the workspace spec's hash differs
  from the document's, Save (PUT) and Revert; the side cards gain entry/exit editors (operand
  pickers from the side's outputs, price fields and a constant box; operator picker; optional
  second condition with AND/OR). Apply flows (optimizer, walk-forward) mark the document edited.
- **Workspace state**: `document: {id, name, hash} | null`; `LOAD_RUN` restores the run's
  embedded spec and records its `strategy_id`; `SET_STRATEGY` from the lab sets the document.

## 9. Verification and QA

- Test first for every behaviour in §4–§8 (pytest, DB-free; vitest for the adapter grouping, the
  reducer's document and indicator edits, the rule description helper).
- Contracts regenerated (`OpenPosition`, `RuleGroup`, `IndicatorSpec.params`, the strategy
  document) with the staleness test.
- Acceptance: the Mission 3 and 4 walks plus items 1–11 of §1 against the restarted worker;
  evidence copied under `docs/evidence/`.
- Milestone QA: an independent agent at the exact commit reruns the suite and the acceptance,
  re-derives one indicator (RSI 14) by hand against the series route, checks the carry-over
  arithmetic across a window join to the cent, probes every validation refusal over HTTP,
  confirms the default strategy's Mission 3 hash and that no file under `app/trading_core/`,
  `app/platform_host/` or `app/products/triad/` changed, and reads the lab's honesty rules.
  Whole-branch review by a fresh reviewer, then one fix pass with every fix test-first.
- Record: `docs/MISSION5_STRATEGY_LAB.md`; merge and push on the operator's call.

## 10. Non-goals

No indicators beyond the six named; no Pine or expression language; no more than two
conditions per rule; no stops, targets or sizing beyond the allocation fraction; no multi-symbol
strategies; no joint long × short walk-forward; no Core change; no event feed; no broker path;
nothing re-enabling Triad's autonomy; no migration of persisted envelopes (older ones simply
lack `strategy_id`).

## 11. Build order

1. Engine carry-over (`OpenPosition`, `close_at_end`, side results) and the walk-forward
   plumbing; hashes re-recorded.
2. Indicator library and cache; `IndicatorSpec.params`; warm-up by kind; default strategy JSON
   pinned.
3. Operands, operators, groups, validation, evaluation, description.
4. Series route additions; chart adapter panes; Indicators tab and generic indicator inputs.
5. Strategy documents: repository kind, `strategies.py`, routes, envelope fields.
6. Strategy Lab page, rule editors, workspace document state.
7. Acceptance items, worker restart, mission record.
8. Milestone QA, whole-branch review, fix pass, merge and push.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Contract growth changes the default strategy's JSON | `params` omitted when empty; a test pins the canonical JSON and the Mission 3 hash |
| Carry-over changes out-of-sample semantics in a way that surprises | operator-approved; every carried trade and open-at-end window is labelled; the final window's edge close stays labelled |
| Pane support in the chart adapter | the spike already proved native indicators and Vela documents `paneHint: 'new'`; the mock adapter keeps panels library-free |
| Rule validation gaps let a bad rule reach the engine | validation at the side level with named messages, tested per case; the engine still raises on anything unexpected |
| Document deletion orphaning references | delete refuses while referenced; envelopes embed the full spec regardless |
