# Aegis Mission 13: the strategy builder — design (2026-10-22)

## 1. Intent

The operator: "can we work on the strategy builder. i'm thinking an AI assisted text based
interface. so i say buy when 9 ema crosses 30 sma and price is above 200 sma and it builds the
nodal model. i can then edit the nodal model, adding and deleting blocks as i see fit."

Success: typing that sentence in the Strategy Lab builds the long side as blocks on a canvas: two
moving averages crossing, price above a third, both joined by AND into Entry, and a default exit.
The operator drags blocks in, wires and deletes them, saves, and runs the backtest. Every strategy
saved before this mission opens on the canvas and keeps its identity, and every result without
stops is byte-identical to today's.

## 2. Decisions (the operator, 2026-10-22)

1. **Text is read in two steps ("A").** This mission builds a deterministic phrase reader inside
   Aegis. The real AI comes later through Core, as its own separately governed mission (Core owns
   providers; Aegis holds no provider credential).
2. **The blocks form a logic tree ("1").** Indicator, price, condition, AND / OR and Entry / Exit
   blocks. AND / OR take any number of inputs and nest. Indicators read price only: no indicator of
   an indicator and no arithmetic between blocks in this mission.
3. **Exits.** Mirroring the entry was rejected ("1 will not work for every strategy"). When the text
   names no exit, the default is a **2% stop loss and a 5% take profit**, badged as the default.
   Stop loss and Take profit are blocks, dragged in and wired into Exit ("in the nodes. we can
   build stop conditions. drag and drop").
4. **Stops fill on the close ("2").** A stop or target fires when a bar closes past its level and
   fills at the next bar's open, the timing of every rule today. Assumed and not objected to:
   percentages are measured from the entry fill; the short side mirrors the long; stop and target
   percentages can be optimized.
5. **The Strategy Lab becomes the builder ("1").** The narrow Strategy panel beside the chart shows a
   plain-text summary and "Edit in builder"; its two-condition dropdown editors retire.
6. **The canvas uses React Flow ("1").** `@xyflow/react` 12.12.0 (MIT, released 2026-09-24), pinned
   exactly. This is the operator's approval for the new UI package and its dependencies (zustand,
   classcat, `@xyflow/system`, d3-drag, d3-zoom, d3-selection, d3-interpolate and their types).
   Assumed and not objected to: block positions are saved with the strategy document, outside the
   strategy's identity; older and text-built strategies are laid out automatically.
7. Sections 1–6 of the design were each approved "yes" in chat.

## 3. Today

- `strategy.RuleGroup` holds exactly two conditions (`all_of` or `any_of`), refused past two ("at
  most two conditions in this slice"). A side has one `entry` and one `exit`, each a `RuleSpec` or a
  `RuleGroup`.
- `backtest.evaluate` turns a rule into a boolean series over the bars; `_side_frame` stores
  `entry_signal` and `exit_signal`. The reference engine (`_simulate_side`) and the numba kernel
  (`kernel.py`) read only those two arrays: on each evaluated, warm bar an exit signal sets a
  pending exit, filled at the next bar's open. On the last bar with `close_at_end` off, the exit
  signal travels with the open position.
- `strategy_hash(spec)` is the SHA-256 of the spec's canonical JSON. `StrategyDocument` holds the
  spec, its hash and metadata; the hash covers the spec only.
- There are no stops or targets. Every exit is a rule.
- The Strategy Lab page lists saved strategy documents (New, Use in workspace, Duplicate, Rename,
  Delete). The Strategy panel (`StrategyPanel`, `SideCard`, `RuleEditor`) edits one or two
  conditions per rule with dropdowns, beside the chart and on the Lab page.

## 4. Design

### 4.1 The rule tree

- `RuleGroup` keeps `all_of` / `any_of` (exactly one set). Each member is a `RuleSpec` or another
  `RuleGroup`. A group needs at least two members; there is no cap on members. Nesting deeper than
  32 levels is refused by name, a guard against pathological input, not a design limit.
- Everything that reads rules walks the tree: `conditions()` (all leaf conditions),
  `referenced_columns`, operand checks, `evaluate` (AND / OR over the members' series), and the
  UI's descriptions (members in brackets where needed: "A AND (B OR C)").
- Serialization is unchanged for every rule expressible today, so every saved strategy dumps
  byte-identically and keeps its hash.

### 4.2 Exits, stops and targets

- `StrategySide` gains `stop_loss_pct: float | None` and `take_profit_pct: float | None`: percentages
  of the entry fill price (2 means 2%). `stop_loss_pct` is above 0 and below 100;
  `take_profit_pct` is above 0 and finite. Unset fields are left out of the dump.
- `exit` becomes optional. A side needs at least one exit: a rule, a stop or a target; otherwise
  it is refused by name ("long side has no exit: add a rule, a stop or a target"). An absent
  `exit` is left out of the dump.
- The trade closes on whichever fires first.

### 4.3 The engine

- On each bar where the exit rule is checked today (evaluated, warm, in position), the engines also
  check the trade's levels against the bar's close:
  - long: stop when `close <= entry_price * (1 - stop_loss_pct / 100)`, target when
    `close >= entry_price * (1 + take_profit_pct / 100)`;
  - short: stop when `close >= entry_price * (1 + stop_loss_pct / 100)`, target when
    `close <= entry_price * (1 - take_profit_pct / 100)`.
- A fired stop or target sets the pending exit exactly as an exit signal does: the fill is the next
  bar's open with the usual slippage and commission. On the last bar with `close_at_end` off it
  travels with the open position like an exit signal.
- Carried positions (walk-forward, studies) already carry their entry price, so levels hold across
  window joins.
- A trade closed by a stop or target gains `exit_reason: "stop_loss"` or `"take_profit"`; a stop
  and a rule on the same bar report `"stop_loss"`. Rule exits gain no field. A side without stops
  takes exactly today's path, so its trades, curves, metrics and result hashes are byte-identical.
- The reference engine and the kernel make the same change; the existing engine-agreement tests
  cover stops.

### 4.4 Experiments and optimization

- Side-relative parameter paths gain `stop_loss_pct` and `take_profit_pct` (surface paths
  `long_side.stop_loss_pct`, …), with ranges like any parameter (for example 1–5 step 0.5).
  `apply_parameters` sets them; warm-up is unaffected.
- A stop or target range changes only the kernel's settings, not the signals, so those cells reuse
  the cached indicator and signal work.

### 4.5 The canvas document

- `StrategyDocument` gains an optional `canvas`: per side, the blocks (id, type, settings), wires
  and positions, including loose blocks. It is outside the spec and its hash; moving a block never
  changes the strategy's identity. It is left out of the document when absent and bounded in size
  (256 KB).
- On open, the saved canvas is used when it still reads as the document's strategy; otherwise
  (an older document, a strategy changed elsewhere, a text-built side) the strategy is laid out
  automatically, left to right: price and indicators, conditions, groups, Entry and Exit.
- The built-in reference strategy stays read-only; it opens laid out automatically.

### 4.6 The builder (Strategy Lab)

- Layout: the text line across the top; Long / Short tabs over the canvas; the palette on the left;
  the saved-strategy list on the right (collapsible; clicking a row opens that strategy in the
  builder; Duplicate, Rename, Delete as today). The builder edits the workspace's current strategy,
  the one the chart runs, and saves through today's document path.
- Palette: Price (close, open, high, low); EMA, SMA, RSI, ATR, Bollinger, Donchian, MACD; Condition
  (the six comparisons); AND; OR; Stop loss; Take profit. Each side's canvas always has one Entry
  and one Exit block, which cannot be deleted. A side has at most one Stop loss and one Take profit.
- Blocks: an indicator shows its kind, length and settings, editable on the block, with one output
  per series (Bollinger: upper, middle, lower). A condition has a left and a right input and a
  comparison dropdown; a number can be typed into an unwired input. AND and OR grow an input as one
  is wired. Stop loss and Take profit take their percentage on the block. Blocks the phrase reader
  added as defaults carry a "default" badge (kept in the canvas) until they are edited.
- Wiring: drag from an output to an input. Series go into condition inputs; conditions and groups
  go into AND, OR, Entry or Exit; Stop loss and Take profit go into Exit only; a band comparison
  needs a band on the right. A wire that breaks a rule is refused on drop with a short reason.
- Delete (key or right-click) removes a block and its wires; Ctrl+Z / Ctrl+Y undo and redo canvas
  edits, including an applied sentence.
- A status line reads "Ready" or names the first problem ("Exit has nothing wired in"; a server
  refusal's message). Run backtest and Save wait for Ready. Blocks not wired to Entry or Exit are
  greyed and ignored by backtests. A group with one input counts as that input.
- The Strategy panel beside the chart shows each side's rules and stops as text with "Edit in
  builder". Its optimization ranges stay as they are and gain the stop and target percentages.

### 4.7 The phrase reader

- `POST /aegis/api/strategies/read` with `{"text": ...}` answers `{"sides": {...}, "reading": ...,
  "defaults": [...]}`: the proposed parts per side, a one-line reading back, and which parts are
  defaults. Text it cannot read answers 422 with the message and the unread spans
  (`[{"start", "end", "text"}]`). The later AI step answers the same request with the same shape.
- The builder previews the proposal and its reading ("Long entry: EMA 9 crosses above SMA 30 AND
  close above SMA 200. Exit: stop loss 2%, take profit 5% (default)"). Nothing changes until
  **Apply**; Ctrl+Z undoes it.
- What it reads (case-insensitive):
  - sides: "buy", "go long", "long when" → long entry; "short", "sell short", "go short" → short
    entry; "sell", "exit", "close when" → long exit; "cover when" → short exit. Clauses are
    separated by ";" or ".";
  - indicators: "9 ema", "ema 9", "ema(9)", "200 sma", "rsi 14", "atr 14", "bollinger 20 2",
    "bb 20", "donchian 20", "macd 12 26 9" with "macd line", "macd signal", "macd histogram"; a
    band's "upper", "middle", "lower" band; kinds keep their default length when none is given;
  - price: "price" (close), "close", "open", "high", "low";
  - comparisons: "crosses above" / "crosses over", "crosses below" / "crosses under", "is above" /
    "greater than" / ">", "is below" / "less than" / "<", "inside" / "outside" a band, and plain
    numbers ("rsi above 70");
  - logic: "and", "or", brackets; without brackets AND binds before OR;
  - exits: "stop at 2%", "2% stop", "stop loss 2%", "take profit at 5%", "target 5%".
- The same indicator named twice is one block; the same kind at two lengths is two (ids `sma30`,
  `sma200`). An entry clause replaces its side (entry, exit, stops); a side whose entry is named and
  whose exit is not gets the default 2% stop and 5% target. An exit clause alone replaces only its
  side's exit. A replaced side starts with no optimization ranges.
- Nothing is guessed. Unknown words, a comparison with a missing side, or two exits of one kind
  refuse the whole text, naming the words.
- The reader builds exactly the strategy the same blocks built by hand would.

### 4.8 Not changed

Indicator kinds and their computation, fill timing, the temporal context, walk-forward and study
logic beyond carrying levels, saved runs and documents, Core, the platform host, Triad.

## 5. Verification

- **Identity first.** Before any change, goldens are captured from today's code: a backtest, an
  experiment, a walk-forward and a study without stops, in the test suite on synthetic bars, and a
  real-archive identity script (capture before, compare after). All are byte-identical afterwards.
  A read-only check recomputes every saved strategy document's hash in the operator's store and
  finds them unchanged.
- **Tests:**
  - model: trees, nesting, the depth guard, the no-exit refusal, unset stops and an absent exit
    left out of dumps;
  - `evaluate` over trees against worked truth tables;
  - stops in both engines: a stop, a target, a gap past the stop (it fills at the next open), a stop
    and a rule exit on one bar (`stop_loss`), the short mirror, a level travelling on the last bar,
    a stop carried across a window join; engine agreement with stops; stop and target ranges in
    an experiment;
  - the phrase reader: a table of sentences and the side each builds, and the refusals with their
    spans;
  - the canvas: canvas ↔ strategy round trips, wiring rules, single-input groups, automatic layout;
    UI tests, type check and build.
- **Browser acceptance, items 91 onward:**
  - type "buy when 9 ema crosses 30 sma and price is above 200 sma", preview, Apply: the blocks
    appear, the backtest runs, and trades show "stop loss" / "take profit";
  - drag in RSI, a condition and an AND; wire them; delete a block; undo;
  - save and reopen with positions kept; an older strategy opens laid out automatically with its
    hash unchanged;
  - an experiment over the stop percentage;
  - the panel's text summary and "Edit in builder";
  - governance: nothing under `app/trading_core`, `app/platform_host` or `app/products/triad`
    changed; exchange CLOSED; DailySchedule `c99fa831` disabled; items 1–90 pass.
- **Milestone:** `tools\verify.ps1`, the frontend tests, the browser acceptance and the lint/build
  checks; milestone QA and the whole-branch review at the end (the operator picks the model).

## 6. Boundaries

Product work only: `app/products/aegis/` (including the UI and its package files), tests and docs.
No Core change, no model call, no provider or credential, no environment change. The new UI package
is pinned exactly in `package.json` and its lock. Exchange stays CLOSED; live trading disabled.

## 7. Out of scope

The AI through Core; indicators of indicators and arithmetic between blocks; stops that fill inside
a bar; trailing stops; NOT blocks; multi-symbol rules.

## 8. Risks

- React Flow under the worker's content security policy: the first UI task loads the canvas in the
  served build and confirms no policy errors before building on it.
- The kernel's arithmetic order: the level check is placed so that a side without stops compiles to
  the same operations in the same order; the goldens are the proof.

## 9. Amendments from planning (2026-10-22)

Found while writing the plan; each is shown to the operator with the plan.

1. **The reader sees the current strategy.** The request is `{"text", "strategy"}`, so an exit
   clause alone can keep its side's entry and indicators; `sides` in the answer are whole
   replacement sides.
2. **Indicator ids from text.** An indicator alone of its kind on its side takes the kind's name
   (`ema`, `donchian`, `rsi`), as an indicator added by hand does; two of a kind take kind and
   length (`sma30`, `sma200`), and a further clash takes `_2`. An exit clause reuses a side's
   indicator with the same kind, length and settings.
3. **Ranges.** A side applied from text gets the default (disabled) ranges of each new indicator,
   as an indicator added by hand gets them; a reused indicator keeps its ranges. This replaces "a
   replaced side starts with no optimization ranges".
4. **A bare "crosses".** The operator's sentence says "9 ema crosses 30 sma". A bare "crosses" means
   "crosses above" in a long entry or a short exit, and "crosses below" in a short entry or a long
   exit; the reading back says which.
5. **Entry and Exit inputs.** Entry takes one rule input; Exit takes one rule input plus one Stop
   loss and one Take profit input. Several conditions are joined with AND or OR first; a second
   wire into a one-wire input is refused with that reason.
6. **Walk item 37.** It built the Donchian / RSI breakout with the retired dropdowns. It now types
   it ("buy when close crosses above donchian upper and rsi below 70; sell when close crosses below
   donchian middle"), and asserts the same strategy, so items 38–90 run unchanged.
