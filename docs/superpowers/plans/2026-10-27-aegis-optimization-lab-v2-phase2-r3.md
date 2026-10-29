# Aegis Optimization Lab v2, Phase 2: R3 hand-off note (the trial store and the query layer)

Branch `claude/zen-thompson-50e9bb`, 2026-10-29. Plan:
`docs/superpowers/plans/2026-10-27-aegis-optimization-lab-v2-phase2.md`, Task 13. Spec:
`docs/AEGIS_OPTIMIZATION_LAB_V2_IMPLEMENTATION_PLAN.md`. Nothing was pushed or merged into `main`;
merging stays Randall's answer.

Task 13 was run on Opus 5.5 after a `/model` switch; the mandatory independent QA ran on Fable 5.1
(Randall's choice, 2026-10-29).

## Since R2.5

| Commit | What |
|---|---|
| `e8fc3ec` | R2.5's fix round 1 and the revised note, committed as the note said; **R2.5 passed by Randall** ("Pass R2.5, go"), the five findings read |
| `9cd6c26` | `main` merged in: Mission 14's acceptance, its milestone QA and review fix pass and its record (`760baf7`, `a6ba93b`, `066bf5a`, `1737ea0`). One conflict, the walk's docstring, both sides kept. The walk holds 102 base items and the 13 Lab items numbered after them, **103 to 115**. The Lab's governance item allows exactly the four Core files of Mission 14's fix pass (`LAB_MAIN_CORE_FILES`, attributed to `a6ba93b`); the Lab changes no Core file |
| `b3ffc92` | The R3 QA's fix: a move to or from Recently deleted, and a hard delete, is whole or nothing (below) |
| (this note) | The R3 note and the two benchmark records |

## Verdict

**Phase 2 is complete and its checks are green; the R3 pass is Randall's.** At the hand-off commit:

- **Checks:** the whole Aegis scope **690 passed, 1 skipped**. The core-scope architecture and ownership tests
  pass, as do vitest (372), the build and the contracts check. Lint is ok, both identity scripts read
  `identical`, the 14 golden keys are unchanged and the legacy reads are identical.
- **Independent QA (mandatory, Fable 5.1):** FAIL at `9cd6c26` on one High defect in the trash path.
  It was fixed test-first in `b3ffc92`, and the same reviewer then verified the fix:
  **PASS_WITH_OBSERVATIONS**, two Low observations older than the fix.
- **Track A (1M trials over HTTP):** 7 of 11 rows True. Warm open, filter + heatmap, stat change and
  the worker's memory growth miss.
- **Track B (real engine):** cases B and C meet their rates. Case A misses 150 trials / s by 3.5 %.
  Host memory growth misses on A and B, and the query p95 ratio under load misses.
- **The Lab walk on the final code:** **13/13**, page errors 0, items 103–115.
- **The product store:** untouched by Task 13 (the manifest diff is empty).

R3's pass criteria put every Track A and Track B row at True. **They are not all True on this laptop.**
The misses are recorded below as findings with their numbers, never as re-baselines (open question 3).

## Checks (Task 13 Step 1)

Run from the worktree with the plan's commands (worktree `PYTHONPATH`, `TRADING_HOME` unset).

| Check | Result |
|---|---|
| The whole Aegis scope, no paths | at `9cd6c26`: `685 passed, 1 skipped` (356.9 s); at `b3ffc92`: **`690 passed, 1 skipped`** (333.4 s), the five new tests included; the skip is `test_aegis_lineage_migration` (integration) |
| Core scope: `test_architecture.py::test_dependency_directions`, `test_pytest_scope.py::test_every_module_in_this_repository_declares_one_owner` | **`2 passed`**, with `trading_core` and `products.aegis.lab` imported from the worktree |
| The whole of `test_architecture.py` beside them | `33 passed, 2 failed`: `test_core_startup_with_product_imports_blocked` and `test_product_libraries_absent_from_core_and_triad`. Both fail on any worktree: its root has no `.env` (Core cannot open its store, so the kill-switch request is not the expected 401) and no `.venv-triad`. The branch's Core, platform host, Triad and `test_architecture.py` are byte-identical to `main` (`git diff --name-only main` empty), where both passed in `tools\verify.ps1` the same morning |
| `npm test` | `Test Files 32 passed (32)`, `Tests 372 passed (372)` |
| `npm run build` | `tsc --noEmit` clean; `vite build` in 9.0 s, `index-CILHbmFT.js` (unchanged since R2.5) |
| `tools\aegis_contracts.py --check` | `contracts.ts is current` |
| `bash tools/lint_aegis.sh` | `All checks passed!`, ok |
| `builder_identity.py compare identity-before.json` (Task 2's baseline) | `17,533 bars in 16.4 s: identical` |
| `study_identity.py compare study-identity-before.json` | `8 windows in 23.7 s: identical` |
| The named tests | `test_legacy_read_equals_cells`, `test_legacy_report_reproduced_identically`, `test_legacy_resume_unchanged`, `test_legacy_job_never_compacts`, `test_materialize_matches_lab_page_row`, `test_materialize_refuses_vintage_drift`, `tests/test_aegis_engine_golden.py` (14 golden keys, the file unchanged since R2.5) and `tests/test_lab_sharpe.py` (the fourteen §7.12 cases, `test_sharpe_scopes_low_n_boundary` and the DSR worked example): **`35 passed`** |
| Product-store manifest diff (`product-store-before-r3.txt` → `product-store-after-r3.txt`) | **empty** (9,222 entries, 1,681,094,516 bytes before and after) |
| `git status --short` | clean |

## Independent QA (Task 13 Step 4): FAIL, fixed, then PASS_WITH_OBSERVATIONS

The mandatory review, by a Fable 5.1 reviewer that wrote none of Tasks 5 and 6, read-only, never on
the product store or a worker. Scope: `lab/store.py`'s `compact`, `reclaim` (its per-file
`PermissionError` handling), `file_set`, `read_trials`; `tools/aegis_decompact.py`; `runs.py`'s
`ITEM_FOLDERS`, `_item_paths`, `delete_experiment`; beyond it the `LOCKS.read` wrapping,
`tests/test_lab_store.py` and `api.py`'s `_pinned_bars` on resume and materialize.

**At `9cd6c26`: FAIL.** It re-ran `tests\test_lab_store.py tests\test_aegis_runs.py` (52 passed) and the
engine guard set (156 passed), and injected crash points by a fault-injecting wrapper over the real
functions on temporary roots (no tracked file edited):

- **Its own crash point:** `reclaim` dying between a chunk's unlink and its record. The reader stayed
  whole (12 rows, no duplicates), an older snapshot answered `SnapshotExpired` (never partial), and the
  re-run reclaimed exactly the remaining chunks and recorded all three; a third pass was a no-op.
- Also: `reclaim` dying before the manifest swap; `decompact` dying at three points; `compact` dying
  with its part written but not swapped; a pinned snapshot across reclamation; a layout-1 folder (never
  compacted, reclaimed or rewritten; tree identical); an unreadable chunk (never overwritten, decompact
  refused with the folder unchanged); a part failing its sha256; a held chunk during `reclaim` (skipped,
  retried next pass); `tools/aegis_decompact.py` round trips and refusals; hard delete, trash, restore
  and erase across namesakes (`abc`, `abc-refined`, `abc.1`, `ab`). **All held.**

- **D1, High: a trash move under a held file tore the live folder on Windows.** `move_to_trash`,
  `restore_from_trash` and `_bring_back` used `shutil.move`, which falls back to copy-then-delete when
  Windows refuses to rename a folder while a reader holds a file inside (a Lab read of a part,
  `recompute_report`, `materialize`). The delete half removed the live folder's other files and the
  retry nested a second copy. A finished experiment was left live without its manifest, reading
  **0 trials**, and every later delete was refused as a clash. Reached from `DELETE /experiments/{id}`.
  Reproduced by the builder before the fix.
- **D2, Low: the hard delete removed the document first and its folders with
  `rmtree(ignore_errors=True)`**: a held file stayed behind a removed document, and a new experiment
  taking the id read the old trials. No route calls it today.

**The fix, `b3ffc92`** (tests first: four errors on the missing settings and one failure on the lock
wait, then green):

- `runs._move` renames only, under `_retry` for about 5 s (`MOVE_ATTEMPTS` 200 × `MOVE_DELAY`
  0.025 s); within one volume a rename moves the whole piece or nothing. Another volume falls back to
  `shutil.move`.
- `_move_all` renames the pieces in order; when one is refused, every piece already moved goes back
  and `ItemBusy` is raised ("… is in use (a file inside it is open); nothing was moved, try again in a
  moment"). Trash (document last) and restore (document first) use it.
- The Library maps `ItemBusy` to `Refused`, which the routes answer as 409, and moves an experiment
  under `lab_store.LOCKS.write`, so this worker's own Lab reads finish first; `ExperimentStore.delete`
  takes the lock too.
- The hard delete renames every piece into a private `<root>/.erasing/` folder (the document last)
  and erases it only after all moved; `heal_trash` erases staging leftovers.
- Tests: `test_trash_under_a_held_part_moves_nothing_and_says_so`,
  `test_restore_under_a_held_file_in_the_trash_moves_nothing`,
  `test_a_refused_piece_puts_back_every_piece_already_moved` (portable),
  `test_a_trash_move_waits_for_an_in_process_lab_read`,
  `test_a_hard_delete_under_a_held_part_deletes_nothing_and_says_so`.

**At `b3ffc92`: PASS_WITH_OBSERVATIONS** (the same reviewer). `tests\test_lab_store.py
tests\test_aegis_runs.py tests\test_aegis_library.py`: 80 passed; 13 probes of its own passed. Held
files in the cells folder, another attachment folder and the document: trash, restore and hard delete
each moved nothing and answered 409 / `ItemBusy`; **through the route with the real retry, 409 in
5.38 s** with the experiment intact, then 200 after release. The rollback itself refused, a staging
leftover, `heal_trash` with both, the lock (a waiting delete never blocks another experiment; a thread
holding a read that deletes gets a loud `RuntimeError`, no deadlock), and the other kinds (a backtest
and a study round-trip by rename) all behaved. No new defect.

Its observations, both Low and older than the fix (Mission 9's I4 rule), left for Randall:
- **O1:** after a stranding (a put-back refused, or a crash mid-move), a listing regenerates the live
  `<id>.summary.json`; `heal_trash` then counts the stale trashed sidecar as a clash and keeps a trash
  folder holding only `trash.json` and that sidecar, so the next delete is refused until the folder is
  removed by hand. Data whole and live throughout. Suggested: a trashed `*.summary.json` with a live
  twin is derived data, discarded, never a clash.
- **O2:** a refused put-back raises `PermissionError` out of the Library (the route answers 500, not
  409). The item is stranded, never torn, and `heal_trash` repairs it.
- A refused move holds the experiment's write lock for its whole retry (about 5 s), so new Lab reads
  of that experiment wait that long; other experiments are unaffected.
- `curves()`, `read_report` and a layout-1 read run outside the lock by design; a delete during one
  meets the 409 "try again", loud and whole.

**The DSR worked example:** `not reproduced: paper unavailable; the case is the pinned formula check`
(Randall, 2026-10-29). The QA recomputed the pinned case (`sr0 = 0.050612`, DSR `0.494618`) and found
it internally consistent; its 1e-9 tolerance catches the plausible mutants (`sqrt(T)`, excess
kurtosis, a sign flip).

## Track A: the 1M record (Task 13 Step 2)

Record: `docs/superpowers/plans/2026-10-27-aegis-optimization-lab-v2-phase2-benchmark-explore.json`
(copied from `logs/lab-benchmark-explore-20261029T124732Z.json`; sha256
`f78a0347eec8c2c38730b42d5c3ddb667abca519e9a3c399094640b91d42591a`, 7,578 bytes).

The scratch worker was restarted first; `/lab/build` reported `cache.entries == 0`, so the first open
is cold. The fixture is `demo-synthetic-1m`: 1,000,000 trials, ten parameters (the surface cap),
written through `lab_fixture.py` in 60.0 s. Each interaction was run 20 times over HTTP through the
scratch worker; git head `b3ffc92`, engine build `8bef56cd6730…`, 2.7 GB free at start.

| §9.6a row | p95 (max) | Budget | `evaluate()` |
|---|---|---|---|
| `open_cold` (summary + two queries) | 3,273 ms (one run) | 4,000 | True |
| `open` (warm) | **2,202 ms** (2,221) | 1,500 | **False** |
| `filter_heatmap` | **795 ms** (1,003) | 400 | **False** |
| `stat_change` | **851 ms** (987) | 300 | **False** |
| `page` | 327 ms (494) | 600 | True |
| `exact_slice` | 118 ms (248) | 300 | True |
| `parallel` | 665 ms (698) | 800 | True |
| `progress_poll` | 4.9 ms (5.1) | 100 | True |
| `worker_rss_delta_mb` | **828 MB** (343 → 1,171) | 450 | **False** |
| `disk_mb` | 333 MB | 350 | True |
| `compaction_1m_s` (in-process proxy) | 2.5 s | 10 | True |
| `browser_heap_mb` | absent by construction (HTTP only) | 300 | the walk's 12.2 / 12.9 MB on 12,000 trials |

Beside them: `compact_10k_s` 1.83 s and `read_7cols_10k_ms` 108.5 (33.7 after reclaim); the 1M
compaction merged 50 chunks into generation 11 with 1,009,996 unique trials. `retest_due`: none.

**Findings (for Phase 3; none re-baselined).**
- Three interaction rows and the worker's memory miss at 1M on this laptop. The same benchmark at
  100,000 trials (Task 9's trial record, `logs/lab-benchmark-explore-20261028T183842Z.json`) passed
  every row: open 464 ms, filter + heatmap 156, stat change 179, memory growth 115 MB.
- The three slow rows grow about 5× for 10× the trials (open 4.7×, filter 5.1×, stat change 4.8×),
  so they re-read or re-scan per request at a cost that scales with the trial count. The memory growth
  (828 MB against `LAB_CACHE_BYTES = 400 MB`) says the cache's own bound is not what limits the
  worker's resident set at 1M.
- Page, exact slice, parallel and the poll keep their headroom at 1M.

## Track B: execution on the real engine (Task 13 Step 3)

Record: `docs/superpowers/plans/2026-10-27-aegis-optimization-lab-v2-phase2-benchmark-execute.json`
(copied from `logs/lab-benchmark-execute-20261029T125617Z.json`; sha256
`03f48d59ec126fec18ceb5666d964ab14ed806f03fa5a09c7f9bd93998899029`, 17,179 bytes).

The scratch worker restarted with `-Workers 10`; 10 pool children were observed in every case. Each
case is an experiment created through the worker's API (`lab-bench-10p`, LHS over the 2.87 × 10¹¹-cell
surface, seed 1, QQQ on the §9.1b ranges); git head `b3ffc92`, 3.1 GB free at start; the whole run
took 457 s.

| §9.6b row | A (1h) | B (15m) | C (1m) | Limit |
|---|---|---|---|---|
| trials | 10,000 | 10,000 | 2,000 | |
| bars (drift) | 2,603 (0) | 9,669 (0) | 46,034 (0) | drift ≤ 2 % |
| **trials / s** | **144.7 False** | 104.2 True | 37.1 True | ≥ 150 / 65 / 19 |
| first chunk | 13.6 s | 10.5 s | 13.8 s | ≤ 20 s (≤ 10k bars), ≤ 35 s (50k) |
| chunk write p95 | 12.3 ms | 11.6 ms | 12.1 ms | ≤ 100 ms |
| **host growth** | **920 MB False** | **506 MB False** | 37 MB True | ≤ 100 MB |
| compaction | 0.36 s | 0.32 s | 0.15 s | ≤ 10 s |
| pool-child peak | 155 MB | 159 MB | 173 MB | ≤ 160 MB + 400 B / bar |
| progress poll p95 | 53 ms | 62 ms | 49 ms | ≤ 100 ms |
| invalid / failed | 0 / 0 | 0 / 0 | 0 / 0 | 0 |
| `resume_read_s` (before / after finalize) | 0.31 / 0.01 | 0.31 / 0.02 | 0.07 / 0.004 | |

**§9.1b: measured against the affine model** (≈ 27 ms + 0.0079 ms per bar per trial):

| Case | Model ms / trial | Measured worker ms / trial | Measured ÷ model |
|---|---|---|---|
| A, 2,603 bars | 47.6 | 69.1 | 1.45 |
| B, 9,669 bars | 103.4 | 95.9 | 0.93 |
| C, 46,034 bars | 390.7 | 269.2 | 0.69 |

**Queries during a run** (case A again, one §9.1b query set per second against the running
experiment): throughput ratio 0.81 (True, ≥ 0.75); **p95 ratio 9.49 (False, ≤ 2.5)**: 476 ms during
the run against 50 ms quiet (summary p95 612 ms, counts 327 ms during); no errors. The case's own rate
under that load was 116.7 trials / s.

`retest_due`: `rate_drift_over_15pct` is true against Task 9's trial record (which ran a smaller
pool), so this record is the new baseline; no other trigger.

**Findings (for Phase 3 and the milestone; none re-baselined).**
- **Case A misses 150 trials / s by 3.5 %** (144.7). At 2,603 bars the fixed per-trial cost dominates:
  69 ms against the model's 48 (1.45×), while B and C beat the model.
- **The host process grows with the trial count during a run:** 920 MB at A, 506 MB at B (10,000
  trials each) and 37 MB at C (2,000), against 100 MB. At the milestone's `A100k` this would exhaust
  this laptop's memory; it should be explained (what the host holds per trial until finalize) before
  that run.
- **Lab queries slow ninefold while trials run**, though their throughput holds: the query and the
  pool share the CPU.
- **R2.5's finding 1 depended on the pool size.** The R2.5 bench ran with the four pool workers that fit
  its free memory then (12,000 trials in 424 s, about 28 / s, during the walk). With ten workers and
  3.1 GB free, case A ran 10,000 trials in 81 s, and the walk's own bench took 123.8 s.

## The walk on the final code

`C:\Triad\.venv\Scripts\python.exe tests\products\aegis\browser_workstation.py --base http://127.0.0.1:8103/aegis/ --only lab --data-root C:\Triad\data\temp\lab-scratch --pid-file logs\aegis-scratch.pid`,
from the worktree on `b3ffc92`, against the scratch worker started with `-Workers 10`:
**`13/13 PASS, 0 FAIL, page errors 0`**, in 197 s (`logs\aegis-acceptance-20261029T125708Z.json`,
`lab_only: true`, `lab_first_item: 103`, `lab_longtask_supported: true`).

- **Governance (item 115):** no change under Core, the platform host or Triad since `1882c81` but the
  four fix-pass files merged from `main`; aegis `human_directed` / exchange `CLOSED`; `DailySchedule`
  `c99fa831` disabled; Lab items 103–114 PASS.
- **The bench:** `lab-walk-20261029t125708z-bench`, 12,000 trials on 2,603 bars, done in 123.8 s
  (R2.5: 424 s on four pool workers). The report took 32.5 s.
- **`lab_timings_ms`:** exact slice 75.5 ms of 300; stat change 52.6 of 300; filter + heatmap 78.6 of
  400; page 96.8 of 600; brush 351.9 of 800 (parallel). Zero long tasks on every label.
- **`lab_heap_mb`:** 12.7 after item 109 and 17.7 after 110, against 300.
- **`lab_bench_materialized`** (Gate 3 parity): trials #7933 and #7169 materialized on the pinned
  bytes, results `66cb3ab9e162…` and `6e286de3cfb0…`, each equal to its page row on the 4 of 30 metric
  pairs the page projects.
- **Item 106:** 11 catalog inputs revealed by scrolling the catalog list alone. The eight disabled
  controls under 4.5:1 (2.61–4.30) are item 116, deferred.

The Task 12 walk's figures stay R2.5's evidence on the 12,000-trial slice
(`logs\aegis-acceptance-20261028T232955Z.json`, 13/13, page errors 0): `lab_timings_ms` exact slice
99.8 ms of 300, stat change 180.5 of 300, filter and heatmap 225.6 of 400, page 315.9 of 600, brush
494.9 of 800 (parallel), zero long tasks on every label (`lab_longtask_supported: true`); `lab_heap_mb`
12.2 after item 109 and 12.9 after 110, against 300; `lab_bench_materialized` trials #7933 and #7169,
each on the pinned bytes, 4 of 30 metric pairs compared per trial (the page row's projection), equal.

## Product store and scratch root

- **The product store** `C:\Triad\data\aegis` was never a data root here. Its manifest was taken at
  2026-10-29 07:05 local, before Task 13's runs (`product-store-before-r3.txt`), and again after the
  walk (`product-store-after-r3.txt`, both in the scratch root): **identical**, with 9,222 entries,
  8,490 files and 1,681,094,516 bytes, the newest write at 11:45:36 UTC before the baseline. The
  product worker on 8102 was never used.
- **Task 1's manifest** (`product-store-before.txt`, 7,242 entries) differs from today's by Mission 14's
  walks on the product worker and that worker's own summary caches, all outside this work (ruling 2).
- **The scratch root** `C:\Triad\data\temp\lab-scratch` measures **434,563,217 bytes** after R3 (the walk reported 434,404,982 before the after-manifest was written). It
  holds R2.5's contents (69.6 MB), the 1M fixture `demo-synthetic-1m` (333 MB), Track B's four
  experiments and this walk's fixtures and bench. Nothing was deleted; its deletion after the milestone
  is Q11.
- **The scratch worker** was stopped after the walk (`tools\start_aegis_scratch.ps1 -Stop`).

## Rulings in Task 13

1. **The Core allowance after merging `main`.** The plan's constraint was an empty Core diff since
   `LAB_BASE`; after the merge it holds Mission 14's four fix-pass files, governed on `main`. The item
   allows exactly those, named and attributed, as Mission 14's own items allow main's fixes. Cost: an
   allowance wider than the plan wrote; exact and attributed.
2. **The product-store baseline re-taken.** Mission 14's walks ran on the product worker after Task 1's
   manifest (and the product worker writes its own summary caches), so a diff against Task 1 could not
   be empty. A fresh manifest was taken at 2026-10-29 07:05 local, before Task 13's runs. Cost: the
   R3 diff covers Task 13 only; Tasks 1–12's runs are covered by their own walk-time checks.
3. **The two worktree-only architecture failures** are recorded, not fixed: they test the checkout's
   environment, not the code, and the code is identical to `main`'s, where they pass. Cost: none.
4. **QA observations O1 and O2 deferred to Randall** rather than widening R3: both are older than the
   fix, Low, and leave data whole. Cost: a rare refused delete until the stale sidecar is removed.
5. **The Lab walk re-run on `b3ffc92`**, since the merge and the fix changed the walk file and the
   trash path after R2.5's evidence. Cost: one more 12,000-trial bench experiment in the scratch root.
6. **A miss is a finding, never a re-baseline** (the plan): Track A's and Track B's misses are listed
   for Phase 3 and Randall, with the measured numbers.

## Deferred

- 116: the disabled `#lab-refine` look (WCAG exempts inactive components).
- The 20-parameter fixture, after Phase 4 lifts `MAX_PARAMETERS`.
- `A100k`, the 100,000-trial execution case: at the milestone (`not run at R3`).
- The 1M DOM-row / response-size / long-task / browser-heap walk: the milestone's (§15 row 11).
- The Phase 3 §9.6a rows (Pareto, neighbourhood / robustness, importance): `lab_benchmark.py analytics`
  at R3.5.
- Track A's and Track B's misses (above), for Phase 3's planning.
- QA observations O1 and O2.

## Decisions this plan made where the spec left a choice

From the plan's Self-review; each held through Phase 2.

1. **`AEGIS_DATA_ROOT` moves the run store only.** The scratch launcher gives a worktree worker the
   archives through a junction to `-ArchiveRoot`'s `data/raw/HFDataLibrary`. The `relative_path` strings
   are identical, so pins stay portable, and there is no second product override.
2. **`filter_hash` is the client's FNV-1a value, echoed verbatim.** The server computes none in
   Phase 2; Phase 3's task cache will hash its own canonical form.
3. **`pos.<k>` names a parameter by its index in the surface's path order.**
4. **Compaction runs at the start of the unit after the fiftieth unmerged chunk**, outside the runner
   lock. The remainder runs at finalize under it (the "one unit" pause).
5. **`counts.unique` on the document is recomputed per compaction generation** (`unique_generation`
   says which); the summary route computes it exactly from the snapshot.
6. **The spec's loose `<id>.views.json` became the folder `<id>.views/`**, because `runs._list` treats
   every `experiments/*.json` as a document.
7. **Trial numbers derive from the schedule the document already persists** (`first_pass_cells` +
   `refinement_cells`, saved before the rows that use them), not from a new schedule file or a manifest
   field. The document is the schedule's one record.
8. **The `opt:` importance placeholder names Phase 3**, where importance lives.
9. **`A100k` runs at the milestone** (§11's milestone row, §16's R3 row); `evaluate()` says
   `not run at R3` rather than staying silent.
10. **The Phase 2 synthetic fixture has ten parameters** (the `Surface` cap); the 20-parameter record is
    re-taken after Phase 4 lifts `MAX_PARAMETERS`.
11. **The DSR worked-example test is a pinned formula check** until the paper's Appendix literals are
    transcribed (Randall, 2026-10-29: it stays so; see the QA's DSR line).
12. **Trial ids carry the source prefix, `exp:<id>#<n>`** (the spec writes `<experiment_id>#<trial_no>`):
    one id grammar for both source kinds, since `opt:<job>#<k>` needs the prefix and `parse_source`
    re-checks it on the trials route.
13. **`elapsed_ms` is float64 in layout 2** (the spec says float32): layout 1 already stores float64, so
    one type serves both layouts and a promoted legacy value never casts.
14. **`snapshot` and `provisional` live on the envelope, not inside `scope`.** `scope` stays a pure
    function of (frame, filter, metric), so the cross-view equality tests compare it whole.
15. **The Lab routes live on `api.router` under `/lab/...`** (served at `/aegis/api/lab/...`), not a
    separately included router: one router keeps the existing dependency providers and the test
    fixture's overrides.
16. **The `opt:` adapter reads `runner.status(job_id, kind="optimization")`**, which takes the runner's
    lock briefly (the spec says views run outside it). The alternative is a second copy of the job's
    cells; the lock is held only for the status snapshot, never for a view.
17. **The §11 "data root override" test lives in `tests/test_aegis_lab_harness.py`** (the spec lists it
    under `test_lab_store.py`): it tests `runs.py`, `preferences.py` and the launcher, beside the walk
    refusal it belongs with.
18. **`reserved = 0` and `reused = 0` on every Phase 2 frame**: no reservation or reuse by value exists
    before Phase 4, and `scope_counts` needs the keys.
19. **Items 51, 63 and 87 are edited inside the 1–97 range** for the `require_scratch_root()` guard, the
    scratch restart and item 87's trash path (§9.8 wins over §11.1's "stay unchanged"); their numbers,
    titles and assertions stay.
20. **`engine_build` is computed in `server.py`'s lifespan at worker start** and cached for the worker's
    life; a test replaces the name through the module attribute. (R3's two worker starts reported the
    same build, `8bef56cd6730…`, as R2.5's: the engine did not change.)

## Open questions for Randall

1. **R2's question 1:** the shell keeps the workstation's top bar rather than the design's stage
   stepper. Randall said he answers it at R3.
2. **The DSR worked example** stays the pinned formula check unless the paper's Appendix literals
   (Bailey & López de Prado 2014, SSRN 2460551) are supplied.
3. **The benchmark misses:** accept them as findings at R3, or a fix task before Phase 3?
4. **QA observations O1 and O2:** fix now, or with Phase 3?

## R3 checkpoint

Randall is asked to:

1. **Accept the phase's checks and the QA's verdict:** the fix `b3ffc92` and its verification, with
   O1 and O2 open (question 4).
2. **Rule on the benchmark misses** (question 3). R3's pass criterion puts every Track A and Track B
   row at True, and four Track A rows and four Track B rows are False on this laptop:
   - Track A: warm open, filter + heatmap, stat change and memory growth at 1M;
   - Track B: case A's rate by 3.5 %, host growth on A and B, and the query p95 ratio under load.
   R3 can pass with them recorded as findings for Phase 3, or a fix task can come first. They are
   performance and memory findings, not correctness ones: every count, read and parity check held.
3. **Answer R2's question 1** (question 1).

Nothing was pushed or merged. The branch `claude/zen-thompson-50e9bb` is 52 commits ahead of `main` (Phases 0–2,
the R2.5 fix round, the two merges of `main` and the R3 fix), with nothing of `main` missing.
