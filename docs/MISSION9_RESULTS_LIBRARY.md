# Mission 9 — The Results library: every saved result in one place (2026-10-19/20)

Branch `aegis/results-library`, cut from `main` at `d56485a` (the plan commit; the spec at
`dbf8ee0`). Spec: `docs/superpowers/specs/2026-10-19-aegis-results-library-design.md`.
Plan: `docs/superpowers/plans/2026-10-19-aegis-results-library.md` (6 tasks, rulings P1–P11).
Executed natively on Opus 5.5 in one session; the ledger carried the state across a compaction.
The milestone QA and the whole-branch review ran on Fable 5.1 (the operator's choice) as
independent read-only agents at `df0d74b`; one fix pass followed (`2fad968`). The operator stepped
away during the review with the instruction to continue and save questions for the end, so the
branch waits, ready, for the merge decision.

Product work only: nothing under `app/trading_core/`, `app/platform_host/` or `app/products/triad/`
changed (acceptance item 76 checks it with git against `d56485a`). Exchange stays CLOSED; no broker
path; Triad suspended; the `DailySchedule` record `c99fa831` stays disabled (item 76).

## Intent

Eight missions produced five kinds of saved result: backtests, optimizations, walk-forwards,
experiments and studies. Each was reachable only from the place that made it (the Runs drawer,
the results tabs, the Experiments page), and opening a run meant loading it over the workspace.
The Library puts every saved result in one list. It opens any of them read-only without
disturbing the workspace, compares two backtests side by side, and gives every item a label,
notes, a star and a delete that can be undone.

## Operator decisions (chat, 2026-10-19)

| Decision | Choice |
|---|---|
| Next mission | 9, the Results library |
| What compares | Two backtests |
| Where it lives | A Library page in the side navigation |
| Opening a backtest | View it read-only; Load into the workspace only on request |
| Comparison axis | The same dates, as % return |
| Housekeeping | Label, star, delete |
| Approach | A: one index route over every saved kind |
| Delete | Restorable: Recently deleted, Restore, and an explicit Empty |
| Execution | Native |

## What was built

| Commit | Task | What |
|---|---|---|
| `155540e` | 1 | `library.py`: one index over the five kinds; each item's headline cached in its summary sidecar (`library` block, version 1) and backfilled incrementally within a time budget per query ("preparing" until done); filters, search, sort and paging; `GET /aegis/api/library` |
| `afbd796` | 2 | Annotations (`library/annotations.json`, atomic); the restorable delete into `trash/<kind>/<id>/` with each item's own folders; the refusals (unfinished jobs, an experiment with studies, a study whose experiment is gone); Restore; Empty; trashed ids stay reserved; the existing experiment and study deletes now go to Recently deleted |
| `59575e1` | 3 | `compare.py`: identity notes, strategy differences by path, A / B / B − A metrics with direction marks, both equity curves on one calendar axis (% and $, with drawdown), per-side trade summaries; `GET /aegis/api/library/compare` |
| `bfc63c7` | 4 | The Library page: filters, the list, the read-only views (a backtest with its own chart, Summary, Trades and Equity; an optimization's matrix and table; a walk-forward's windows, stitched equity and stability), Load buttons, deep links to the Experiments page, "Open in Library" in the Runs drawer |
| `b49b564` | 5 | The comparison view; label and notes, stars, Delete, "Delete selected" naming each refusal, Recently deleted with Restore, Empty behind a confirmation naming the count; a losing headline in red |
| `c54cd45` | 6 | An annotation keeps the fields a request leaves out (found by the acceptance trial) |
| `f7ee759` | 6 | Acceptance items 70–76 |

## Acceptance evidence

`docs/evidence/aegis-acceptance-20261020T032955Z.json`: **76/76 PASS, no page errors**, 618 s in
total. Items 1–69 are the Mission 3–8 walk, unchanged and passing. Items 70–76 walk spec §3:

- **70:** all five kinds listed with their headlines, 50 rows per page: backtest 380, optimization
  105, walk-forward 107, experiment 21, study 9. The walk's own items are indexed.
- **71:** the filters narrow 622 → 380 (backtest) → 333 (QQQ) → 273 (1h) → 85 (default strategy).
  The label "identical pair B 20261020T032955Z" set on item 22's second run is found by search
  alone, and its star by the Starred filter. Accepted lists the walk's experiment and study.
  Sorting by MAR orders the list descending.
- **72:** item 22's run (`114b1942`) opens read-only: 3,493 bars and its 220 markers, Net P&L
  $18,211, 5 temporal rows, 110 trades. The workspace (run, instrument, range, both side cards,
  the unsaved-edits flag) is equal before and after; Load then loads it. In this walk the
  workspace had no unsaved edits, so Load did not ask. The asking path ran in the standalone
  trial: with unsaved edits made as item 54 makes them, a dismissed question changed nothing and
  an accepted one loaded the run.
- **73:** item 21's optimization (`eaf0ff25`) shows 40 matrix cells and 40 table rows, and a pick
  enables Load. Item 28's walk-forward (`cc5c9303`) shows its 6 windows, stitched equity and
  stability. The experiment and the study each open selected on the Experiments page.
- **74:** item 22's pair reads "identical result · same data · same strategy". Item 39's run
  (`424aff04`) against item 54's (`7fb5e38c`) lists exactly `long_side.indicators.rsi.length
  14 → 21` and `short_side.indicators.ema.length 9 → 10`, matching both envelopes. Eight of ten
  combined metrics carry a mark, and two curves share one axis in % return.
- **75:** a throwaway backtest (`4f54a9cc`) is deleted, listed in Recently deleted and restored
  with the same result hash. Three refusals answer 409: the item-63 study's parent experiment, a
  running study, and a restore of a study whose experiment is in the trash. The throwaway pair is
  then restored in order (experiment, then study).
- **76:** governance unchanged since `d56485a`; items 1–69 pass; Recently deleted holds 9 items
  and was never emptied.

## The acceptance trial and the bug it found

Before the full walk, items 70–76 ran on their own against the store, using the ids of the
previous walk (`20261019T170035Z`). Five passed. Item 71 failed for a real reason: the row's star
sent the whole annotation, built from the list's copy of the entry. Starring a result just after
saving its label therefore wrote the old, empty label back, and saving a label could likewise
undo a star just set. `PUT .../annotation` now changes only the fields it is sent; the star sends
`starred`, the editor sends `label` and `notes` (`c54cd45`, test-first). After the fix both items
passed, item 72 on the asking path.

## Measurements (this laptop)

| What | Value |
|---|---|
| One-time headline backfill of 593 saved results | about 25 list queries at a 1.5 s budget each (≈ 40 s), polled by the page every 2 s |
| The list route afterwards (about 620 items) | 105–120 ms for a page of 50 when warm; 250 ms for the first request; 115–180 ms with a kind, a search and the MAR sort |
| Items 70–76 in the walk | 58.7 s, of which item 75 took 33.4 s (a running study started and cancelled, and a 9-cell experiment and its study run to the end) |

## Verification

- Aegis tests for the library, the API and the comparison: 73 passed after the annotation fix.
- UI: 14 vitest files, 88 cases; `tsc` clean; the build succeeds; lint passes through the scope
  script.
- `tools\verify.ps1` on the branch (2026-10-20, after the walk): lint and format passed. The
  inventory was core 557, triad 1,058 and aegis 380. All three scopes ran in full and passed
  (core 386 passed / 171 skipped; triad 634 / 424 with 209 subtests; aegis 379 / 1). It stopped
  at the foundation audit's "Wrong Git branch" check, by design; it runs on `main` after the
  merge.

## Milestone QA (Fable 5.1, read-only, at `df0d74b`)

**PASS_WITH_OBSERVATIONS.** QA recomputed the following independently:

- The index: all 625 entries paged; 51 sampled documents across the five kinds recomputed from
  their own routes (headlines, symbols, range, strategy, status, decision, links all equal); every
  filter, search, sort and page recomputed over the full set.
- Annotations: full and partial PUTs, limits, 24 concurrent writes, a delete racing an annotate.
- The restorable delete on disk, by SHA-256 of every file, for each kind (a study with 34 files,
  an experiment with cells, curves and reports): exactly the item's files moved, restore
  byte-identical, result hashes unchanged; every refusal; ids reserved; old routes into the trash.
- The comparison on six pairs, reimplemented from the envelopes: all 30 metric rows, marks,
  notes, curves and trade summaries to 1e-9.
- The page in Chromium, including Load asking over unsaved edits, Empty's confirmations dismissed
  with no request sent, and the colour rule over 50 rows (5 losing headlines red, 0 green).
- Tests: Aegis 119, vitest 88, tsc clean. Nothing was erased; governance unchanged.

**Defects:** D1 the comparison's drawdown drawn upside down with "deepest 0.00%" (also found by
the review); D2 an opened item not on the current list page fell back to a bare "Backtest" view
without housekeeping (most Runs-drawer links, a new label under a search, unstarring under
Starred); D3 (low) a trashed job still answered by id from the runner's memory until restart.
QA's throwaway items are all in Recently deleted.

## Whole-branch review (Fable 5.1, `d56485a..df0d74b`) and fix pass

**"With fixes"**: 0 Critical, 5 Important, 8 Minor. The review confirmed the path safety, the
explicit per-item folders, the comparison maths and the read-only promise (only the three Loads
and the page switch write the workspace). After re-grading by effect, seven findings entered the
one fix pass (`2fad968`), each test-first:

1. **The drawdown panel** (review I1, QA D1): the worker sends drawdown at or below zero and the
   page negated it again. It now draws as sent and reads "deepest 30.22%" on the run checked.
2. **The headline cache could overwrite a concurrent save** (review I2). A lost final save could
   later have relabelled a finished job "lost" at startup. Every sidecar write takes one lock; the
   cache writes only while the sidecar is still the copy it read, and never for a queued or
   running job.
3. **Unreadable items read "preparing…" forever** (review I3; ruling 3 had not shipped as stated).
   Entries carry `ready`; a computed empty headline reads "—".
4. **An interrupted delete or restore had no exit but Empty** (review I4, with the torn trash
   record folded in). The document's place now decides where an item is: a delete moves it last,
   a restore first. The next delete or restore of the item, and a startup check, finish a move
   that stopped; Empty never erases a live item's stranded pieces.
5. **Annotations on a busy file** (review I5). Fixing it found a worse case: a refused read made a
   save write back only its own note, erasing every other annotation. Reads and swaps retry, and a
   write never starts from an unreadable file.
6. **An opened item off the list page** (QA D2): `GET /library/{kind}/{id}` answers for one item,
   live or deleted, and the page keeps the full view.
7. **A deep-linked study stayed open under another experiment** (review minor, re-graded: it
   showed one experiment's study under another's report). A study shows only while it belongs to
   the open experiment.

After the pass: Aegis scope 389 passed / 1 skipped; architecture and isolation tests on all three
interpreters; vitest 15 files, 90 cases; `tsc` clean; the build; lint. The fixes were checked in
the browser against the restarted worker: the drawdown reads "deepest 30.22%" and dips; a Runs
drawer link 200 rows down opens with its label editor, Delete and Compare with…; a new label
saved under the old label's search keeps the view; a deep-linked study is gone after switching
experiments. **The walk after the pass passed 76/76 with no page errors**
(`docs/evidence/aegis-acceptance-20261020T115945Z.json`, 618 s).

### Deferred minors

- Empty with a malformed id answers 500 rather than 404/422.
- Recently deleted is ordered by creation, not deletion time.
- The star on a Recently deleted row answers 404; it should be disabled there.
- The Library chart leaks an adapter created after a fast unmount.
- `test_compare_handles_a_run_without_trades` asserts the null-MAR case only conditionally.
- The star toggles on the row only; the view's head shows it without toggling.
- A trashed optimization or walk-forward still answers by id from the runner's memory until a
  restart (QA D3).
- Recently deleted shows trashed experiments as "no report".
- A legacy run without a strategy hash: the notes omit "same strategy" while the differences
  table says "Same strategy and settings."
- The first list query after a large backfill pays a cold file-open cost (up to about 18 s on a
  fully stripped copy of the store); the budget covers computation only.

## Rulings

Plan rulings P1–P11 are in the plan. Rulings made during execution (the ledger holds each with
its cost if wrong):

1. The sidecar caches a `library` block (headline, symbols, timeframe, range, strategy name), not
   a headline alone: experiment and study summaries carry neither data nor the strategy.
2. Kind chips count what each kind would give under the other filters.
3. A document the index cannot read is cached with an empty headline; it lists with "—".
4. An item's own folders move to the trash by an explicit list, never by a glob: ids may contain
   dots.
5. Recently deleted computes headlines from the trashed documents on each query.
6. `POST /studies` still erases its own just-created document directly after a 409.
7. Each comparison curve is extended to the run's first and last evaluated bars, so both start at
   0%.
8. Settings differences are listed only when both runs carry settings; a legacy run's capital is
   shown as assumed.
9. A zero difference carries no mark.
10. Experiments and studies open a compact Library view with housekeeping; its main button opens
    them on the Experiments page selected.
11. Load writes strategy and selection and switches to Charts without running a backtest.
12. Optimization and walk-forward Loads apply the pick onto the job's own strategy and data.
13. The temporal breakdown appears inside Summary, as on the Charts page.
14. The Library chart recomputes indicators for the run's archive selection and draws the long
    side's (the short side's when long is off); a vintage that moved shows the source-unavailable
    notice instead of a chart.
15. A deep-linked backtest not on the current list page still opens.
16. The Library page keeps no state across visits.
17. The Library's Delete, "Delete selected" and Empty ask first; the Experiments page's Delete
    buttons keep no confirmation and say where the item goes.
18. "Delete selected" deletes studies before experiments.
19. Empty with nothing ticked erases the whole trash and names its unfiltered count.
20. "Compare with…" ticks the open backtest.
21. Percentage differences read in percentage points.
22. A losing headline is red; nothing else in the Library is.
23. An annotation merges the fields it is sent (the trial's bug).
24. Item 75's running-study refusal uses a QQQ-only study of the 252-cell experiment, which runs
    long enough not to race the delete.
25. The walk leaves its throwaway items in Recently deleted and never calls Empty.
26. Ruling 16 stands although the reviewer disagreed: the read-only Library keeps its own state,
    apart from the workspace; filters reset after a Load round trip.
27. The reviewer's declined-to-judge lines stand as set aside: other comparison kinds, two tabs
    writing at once, dangling parent links between experiments, the Experiments page's deletes
    without a confirmation, the sidecar reads per list, the trash growth per walk, green positive
    P&L in the optimization table, and a restored run whose strategy was deleted. Each is outside
    the spec's single-operator model or a choice already made; a trashed job answering by id is
    deferred above.

## Left in the store

Nothing was erased. Recently deleted holds the walks' and trials' throwaway items (experiment and
study pairs, cancelled "running" studies, and the backtest labelled "throwaway check"); the
restored throwaway backtests stay in the library. Emptying the trash is the operator's call.
