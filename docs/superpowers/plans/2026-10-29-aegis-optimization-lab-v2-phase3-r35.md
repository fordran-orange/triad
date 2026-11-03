# Aegis Optimization Lab v2, Phase 3: R3.5 hand-off note (linked analytics)

Branch `claude/zen-thompson-50e9bb`, 2026-11-03. Plan:
`docs/superpowers/plans/2026-10-29-aegis-optimization-lab-v2-phase3.md`, Task 13. Spec:
`docs/AEGIS_OPTIMIZATION_LAB_V2_IMPLEMENTATION_PLAN.md`. Nothing was pushed or merged into `main`;
merging stays Randall's answer.

Task 13 was run in steps by different seats: the checks (Step 1), the benchmarks and the walk
(Steps 2 and 3) and this note (Steps 5a and 5) by a Sonnet implementer; the independent statistical QA
(Step 4, mandatory at R3.5) by a Fable 5.1 reviewer with no history on the branch, in its own detached
worktree. The sources named in this note are the Task 13 reports and the ledger kept beside the work
(`.superpowers/sdd/2026-10-29-aegis-optimization-lab-v2-phase3/`: `progress.md`, `task-13-step1-report.md`,
`task-13-step23-report.md`, `task-13-qa.md`, `task-12-review.md`, `task-0-report.md`); the ledger directory
is not under version control, so the QA's text, the rulings and the record figures this note relies on are
quoted or tabulated here.

## 1. Checkpoint R3.5: what Phase 3 is

**Scope.** Phase 3 is the §11 Phase 3 row of the spec, built as Tasks 0 to 13 of the plan. Tasks 1 and 2
add screening blocks (a block is a scored span of the experiment's range; indicators warm up on all prior
history, the kernel starts flat at the block) to the pool, the job, the planner and the readers. Tasks 3, 4,
5 and 6 add the Lab task executor (one task at a time, beside the job), the importance task on the fine
grid with its three uncertainties (bootstrap intervals, permutation floors, coverage and aliasing), the
coarse pair and triple decomposition with its residual veto and candidate-only triple intervals, the
sixteen recommended-status cases of §20 and the staged importance and interaction views. Tasks 7 and 8 add
neighbourhoods and the four robustness categories (A to D) with the candidate card, Pareto fronts, the
exact-mode parallel sample and the convergence view. Tasks 9, 10 and 11 add the data layer, Screen B's
analytic tabs and the candidate card, and Screen E, Parameter Families (family tree, trellis with n per
square, drill-down, parallel coordinates, convergence). Task 12 adds walk items 111, 112 and 124 and
`lab_benchmark.py analytics`; Task 13 is this checkpoint. Task 0 is the R3 carry-over: the per-snapshot
index and the column-set cache that bring Phase 2's Track A misses inside their budgets.

**The branch.** `claude/zen-thompson-50e9bb`, head `d4bd1ba` (the R3.5 records) plus the Step 5a commit
**`dcf9894`**. The range from Phase 2's R3 head (`8c522bb`, the last row of the R3 note's table) to
`dcf9894` is **38 commits**; `git rev-list --count main..HEAD` at `dcf9894` is **92**. The merge base with
`main` is `1737ea0` (Mission 14's merge; `main` has not moved). Never pushed. This note is not committed
(Step 6 follows the executor's go), so the count above excludes it.

| Commits | What |
|---|---|
| `d611b94` | the R3 note's last update (O1 and O2 fixed and verified) |
| `2b32aa5`, `720d526` | the Phase 3 task plan; Randall's answers (decisions 18 to 20 accepted, walk 112 on 10 parameters, subagent-driven) |
| `ca443ff`, `ff6b7bc` | Task 0: the R3 carry-over (per-snapshot index, one cache entry per column set, released Arrow memory) and its review fixes |
| `5ae0c7c` | Task 1: the analytics constants and `evaluate_from` on the metrics path |
| `333d877`, `a814417` | Task 2: screening blocks in the pool, the job, the planner and the readers; review fixes |
| `dece1a8`, `56df175` | Task 3: Lab tasks, one at a time beside the job; polish |
| `942c89e`, `5a1db7d` | Task 4: importance on the fine grid with intervals, floors, coverage, aliasing; review fixes |
| `63670f3`, `07ba184` | Task 5: coarse decomposition, availability and the recommended statuses; review fixes (leave-one-out floors, `lab/rule.py`) |
| `218c44d`, `b857427`, `f648da9` | Task 6: the staged importance task and the importance, interactions and triples views; review fixes and an addendum |
| `794bc7f`, `3049f16`, `799fb0a` | Task 7: neighbourhoods, the four robustness categories and the card; review fixes and an addendum |
| `9703fa6`, `b267c0f` | Task 8: Pareto, the exact parallel sample, convergence; review fixes |
| `6cd3d49` | Task 9: the data layer for the analytics views and Lab tasks |
| `6a09edd`, `a54f5b5`, `caa55af` | Task 10: Screen B's analytics tabs and the card; two fix rounds |
| `c3fb8ef`, `cd85c7e`, `9de71ab`, `4278af3` | Task 11: Screen E, Parameter Families; three fix rounds |
| `2fc6422`, `fc575a7`, `5edabf8`, `6bfd40c`, `71af8ba`, `7a63a52` | Task 12: walk items 111, 112, 124 and `lab_benchmark.py analytics`; fix rounds 1 and 2 and the record |
| `d4bd1ba` | Task 13 Steps 2 and 3: the two R3.5 benchmark records (the trailer amended by the executor; tree unchanged) |
| `dcf9894` | Task 13 Step 5a: the case 1 companion test renamed for what it asserts |

**The pass conditions of §16 for R3.5** (spec line 1431: builder plus independent QA on the statistical
fixtures), each against this head:

| Pass condition | Verdict | Where |
|---|---|---|
| The sixteen §20 cases green with their reasons | **Met.** 51 case tests (16 cases at seeds 1 to 3, plus the 5,000-row companion), no xfail; the QA re-derived each case from the spec before reading a test and found them in agreement on what §20 names, with the case 5 mismatch (F1) and the decision 20 premise (F2) for Randall | sections 3 and 8 |
| `lab_benchmark.py analytics` within 180 s beside a running job, the job's throughput loss recorded | **Met on the fixture it can run.** The importance task read 10.86 s against 180 s beside a running Case A job; the loss is recorded (headline -22.7 %, not comparable; chunk-aligned matched 6.8 %). The fixture has 10 parameters and no blocks, so the budget is unmeasured at d = 20 with blocks | sections 4 and 6 |
| The four robustness categories' tests green | **Met.** `tests/test_lab_robustness.py` 132 passed in the QA's re-run; 1273 passed in the whole Aegis scope | sections 2 and 8 |
| Block parity tests green | **Met.** `tests/test_lab_blocks.py` 27 passed (QA); the same tests are in the 1273 | sections 2 and 8 |
| Independent QA of the statistics (mandatory) | **PASS WITH FINDINGS** (Fable 5.1): a fault injected into the own-direction triple increment failed ten tests; the design interval's coverage was confirmed by an independent simulation; F1 to F8 are for Randall | section 8 |
| Track A and the Lab walk | **Every judged Track A row True; the walk 16/16 with page errors 0** (not a stated R3.5 condition; Task 13's Steps 2 and 3) | sections 5 and 7 |

## 2. The checks and their counts

Task 13 Step 1, run from the worktree on `7a63a52` with the worktree `PYTHONPATH` (`task-13-step1-report.md`).
The commits after it (`d4bd1ba`: two JSON records; `dcf9894`: one test name and its docstring) change no
file under `app/`; `git diff --stat 7a63a52 HEAD` lists the two records and `tests/test_lab_analytics.py`.

| Check | Result |
|---|---|
| The whole Aegis scope, `pytest -q -p no:cacheprovider tests` | **`1273 passed, 1 skipped, 1661 deselected, 6 warnings`** in 719.98 s (`scope aegis: 1274 run of 1274 owned here`; the 1661 are core 603 and triad 1058). The skip is `tests/test_aegis_lineage_migration.py:12` (needs `TRIAD_INTEGRATION=1`). R3 at `8c522bb`: 696 passed, 1 skipped. The run shared the machine with the QA seat (2.2x R3's 329 to 357 s) |
| Core scope: `test_architecture.py::test_dependency_directions`, `test_pytest_scope.py::test_every_module_in_this_repository_declares_one_owner` | **`2 passed`**, with `trading_core` and `products.aegis.lab` imported from the worktree |
| The whole of `test_architecture.py` beside them | **`6 passed, 2 failed`** (the file holds 8 tests at this head). The two failures recurred and are worktree-only, see below. The R3 note's "33 passed, 2 failed" for this file was not this file alone |
| `npm test -- --run` | `Test Files 48 passed (48)`, **`Tests 715 passed (715)`** (R3: 32 files, 372 tests) |
| `npm run build` | `tsc --noEmit` clean; `vite v5.4.21`, 460 modules, built in 7.04 s; `index-DDH0Tl65.css` 58.87 kB, `index-_8t04GXK.js` 716.35 kB, `vela-CThRMBD9.js` 998.98 kB. The bundle is byte-identical in name and size to the one built at the previous head; `ui/dist` is gitignored (`.gitignore:35`) |
| `tools\aegis_contracts.py --check` | `contracts.ts is current` |
| `bash tools/lint_aegis.sh` | `All checks passed!`, `110 files already formatted`, ok. Run through Git Bash: the PowerShell `bash` is WSL's and fails with `execvpe(/bin/bash) failed` |
| `builder_identity.py compare identity-before.json` | `17,533 bars in 15.8 s: identical` |
| `study_identity.py compare study-identity-before.json` | `8 windows in 23.8 s: identical` |
| The engine guard set (`test_aegis_experiments`, `_pool`, `_engine_golden`, `_api`, `_kernel`, `_results`, `_stops`, `test_lab_sharpe`) | **`157 passed, 5 warnings`** in 135.95 s |
| The R3 note's named tests (`test_legacy_read_equals_cells`, `test_legacy_report_reproduced_identically`, `test_legacy_resume_unchanged`, `test_legacy_job_never_compacts`, `test_materialize_matches_lab_page_row`, `test_materialize_refuses_vintage_drift`, `test_aegis_engine_golden.py`, `test_lab_sharpe.py`) | **`35 passed`**, the R3 note's 35 |
| The 14 golden keys | exactly 14 in `tests/fixtures/aegis_engine_golden.json`; the fixture, its test and `tests/products/aegis/engine_golden.py` have an empty `git diff 9cd6c26 HEAD` (last changed in `87071a1`) |
| `git status --short` | clean |
| Step 5a (after the rename, at `dcf9894`) | the case 1 tests (`-k case01`): `6 passed`, printing `case 1 at 5,000 rows, seed 1: 3 of 7 noise proposable`, `seed 2: 7 of 7`, `seed 3: 1 of 7`; the whole of `tests/test_lab_analytics.py`: `101 passed` in 94.78 s; lint ok |

**The two `test_architecture.py` failures** (reported, not fixed; reasons re-checked at this head). Both fail on
any worktree and are not about the code:
1. `test_core_startup_with_product_imports_blocked` asserts the kill-switch POST answers 401. A direct probe returns
   **409** `Record validation failed ... postgres_password missing, neo4j_password missing`: the worktree has no `.env`
   (`C:\Triad\.env` exists).
2. `test_product_libraries_absent_from_core_and_triad`: `AssertionError: missing .venv-triad: run tools/bootstrap.ps1`;
   the worktree has no Triad environment.

`git diff --name-only main -- tests/test_architecture.py app/trading_core app/platform_host app/triad` lists no file.

**Warnings** (pre-existing; the ledger parked them for this step). The scope printed 6 and the guard set 5, among them
`app/products/aegis/analysis.py:295: RuntimeWarning: Mean of empty slice` (`np.nanmean`, Task 1's M4 and Task 8's M10), and the
third-party `StarletteDeprecationWarning` (httpx) and `anyio.abc.BlockingPortal` deprecations. None is new in Phase 3.

## 3. The sixteen cases

The sixteen cases of §20 run at seeds 1, 2 and 3 on the fixtures in `tests/lab_stat_fixtures.py` (sigma 0.5, 8 values per
parameter, d = 8, 5,000 rows; d = 20 for case 7; 20,000 rows for cases 1 and 13 by decision 20). No flip is registered (Ruling
P9's `xfail(strict=True)` mechanism is unused) and the run produced no xfail. The table is read from the product's own
`assess` and `statuses` on the tests' own cases at seeds 1, 2, 3 (a read-only dump in process, 51 results; it uses no worker
and no store), and the right-hand column is the QA's finding.

| # | Availability and veto | Statuses at seeds 1 / 2 / 3, with the reason | QA |
|---|---|---|---|
| 1 strong first order (20,000 rows) | available; no veto | x1 `Active · detected` (`not proposable: condition 1 (fine S upper 0.7982 / 0.7973 / 0.7978 ≥ θ_min 0.01)`); the 7 noise parameters `Deprioritized · proposable` at every seed | agrees; row count departs from §20 (decision 20) |
| 1 at §20's 5,000 rows (companion) | available; no veto | x1 `Active · detected`; noise `Deprioritized · proposable` **3 / 7 / 1 of 7**, the rest `Active · not detected` blocked by condition 2 or 3 | **F2** |
| 2 XOR | available; no veto | x1, x2 `Investigate · interaction not ruled out`, `not proposable: condition 2 (Δ beyond <other> upper 0.815 / 0.804 / 0.809 ≥ θ_min 0.01)` | agrees |
| 3 three-way only | available; no veto | x1 to x3 `Investigate · three-way effect not ruled out`, not proposable (conditions 2 or 3) | agrees |
| 4 aliased | **unavailable: `aliased inputs`** | x1, x2 `Active · detected`, `failing` = `aliased inputs`; nothing proposable | agrees; status gap **F4** |
| 5 uneven sampling | **unavailable: `aliased inputs`** (the fixture's x3 = x1 ± 1) | x1 `Active · detected`, `failing` = `aliased inputs`; 3 / 3 / 4 parameters `Active · detected` | **F1** |
| 6 sparse coverage | unavailable: `inputs are not a product design (80 % of the grid is invalid)` | x1 `Insufficient coverage · unresolved`, listed last; the other 7 `Active · not detected`; label reason `coverage: 8 of 40 values hold ≥ 20 rows; n = 5,000 (needs 1,200)` | agrees |
| 7 pure noise (d = 20) | available; **veto raised** (`structure not captured by mains, pairs and triples: deprioritization unsafe`) | 20 × `Active · not detected`; nothing proposable | agrees under decision 18; spec text **F3** |
| 8 one-block regime | available; no veto | x1 `Investigate · period-dependent`, `not proposable: condition 1 (fine S upper 0.8065 / 0.7968 / 0.8057 ≥ θ_min 0.01)` | agrees |
| 9 range change | parent: available, veto raised | parent x1 `Active · detected`, rest `Active · not detected`; `compare_scope(parent, child) == "stale: ranges changed"`; child: veto raised, 8 × `Active · not detected` at seeds 1 and 2, x1 `Investigate · three-way effect not ruled out` at seed 3 | agrees on what Phase 3 builds ("not reused" is Phase 4) |
| 10 correlated inputs | **unavailable: `aliased inputs`**; veto raised | x1, x2 `Insufficient coverage · unresolved`, `failing` = `aliased inputs`; nothing proposable | agrees; V numbers **F5** |
| 11 coarse-bin cancellation | available; veto raised (not pinned) | x1 `Active · detected` (coarse S1 near 0, condition 1 on the fine grid); the rest `Active · not detected` | agrees |
| 12 higher-order structure | available; **veto raised** | 8 × `Active · not detected`; nothing proposable | agrees |
| 13 own-direction triple | (the case 1 experiment) | x2 `Deprioritized · proposable` at every seed with Δ1\|23 above 0.5 and Δ2\|13 below θ_min | agrees; the test the injected fault broke |
| 14 pairwise independent, jointly dependent | **unavailable: `inputs are not a product design (50 % of the grid is invalid)`**; not aliased | 3 × `Investigate · three-way effect not ruled out`, x4 `Active · detected`, 4 × `Active · not detected` | agrees |
| 15 weak constraint | **unavailable: `inputs are not a product design (2 % of the grid is invalid)`**; not aliased | 2 × `Active · detected`, 6 × `Active · not detected` | agrees; the spec's V ≈ 0.2 is wrong (**F5**) |
| 16 outcome-dependent missingness | under `profit_factor`: unavailable, `1,189 of 5,000 configurations have no finite profit_factor (0 invalid, 0 failed, 1,189 undefined)` at seed 1 (the string is built from the fixture's own count at each seed); under `net_pnl`: available, no note | with `net_pnl`: x1 `Active · detected`, proposable 3 / 7 / 1 of 7 (the case 1 data at 5,000 rows) | agrees (Ruling P8) |

**Disagreements the QA found, verbatim** (F1, F2, F4 and F5 in full in section 11; the QA's own table in section 8):
- *Case 5:* "**Disagreement → F1 (Medium).** Measured: V(x₁,x₃) = 0.546 → the experiment is `aliased inputs`; every parameter's `failing` is `aliased inputs`, x₁'s status `Active · detected` (S₁ = 0.008–0.013); balance TVD(x₁,x₂) = 0.223–0.231 < 0.25 (my arithmetic confirmed); Δ₁\|₂ upper = 0.0163 / 0.0203 / 0.0166. The intended quantity is checked, but the status-level "not proposable" rides on aliasing, and the `confounded?` flags on a dependence the spec never states."
- *Case 1:* "the companion's printout shows **3 of 7, 7 of 7, 1 of 7** noise parameters proposable at seeds 1–3, which contradicts decision 20's premise: **F2**."
- *Case 4:* "The status gap against §8.4 is **F4** (Low)."
- *Cases 10 and 15:* "the case clears 0.3 by 0.010–0.017 and only because B = 8 ... **F5** (Low)"; "the spec's 'V ≈ 0.2' is wrong: **F5**."

**Observations from the dump that the QA's table does not state** (mine; measured, not pinned by §20 or the tests, and not raised as defects):
a fourth parameter reads `Active · detected` in case 3 at seed 3 (the noise parameter p7, `failing` = condition 2); case 5 at seed 3 reads
four parameters `Active · detected` (p0, p1, p2 and the noise parameter p6) beside the `aliased inputs` unavailability; case 15 reads
both p0 and p1 `Active · detected` at every seed (the skipped cell makes x2 weakly informative about x1; the QA measured V = 0.057 to 0.063);
the case 9 child at seed 3 reads x1 `Investigate · three-way effect not ruled out` with the veto raised. Each sits beside a case whose
pinned outcome (the statuses §20 names) is unaffected. The QA's out-of-sample check (pure noise, seeds 11 to 20) found no false
detection in any family (section 8).

## 4. The importance task beside a running job

`lab_benchmark.py analytics`, a freshly restarted scratch worker (`-Workers 10`), the 1M-trial fixture
`demo-synthetic-1m` (10 parameters, no blocks), the task on 50,000 rows (`IMPORTANCE_ROWS`) at seed 1, started while a Case A experiment
(10,000 trials on 2,603 bars) was running; polled every 0.5 s. The record is
`docs/superpowers/plans/2026-10-29-aegis-optimization-lab-v2-phase3-benchmark-analytics-r35.json` (`git_head` `7a63a5233fbc`).
`job_coverage` was 1.0 (minimum 0.9) so the task ran beside the job for its whole window (`beside_job` true); the status at the end
read `sharing_cpu: false`.

| Measure | R3.5 (`7a63a52`) | Task 12 committed record (`6bfd40c`) | Line |
|---|---|---|---|
| Stage 1, the fine grid (`fine_stage_s`) | **6.273 s, an upper bound**: stage 1 finished before a poll read it, so stage 2's `elapsed_s` is the first stage read | 6.936 s, measured | <= 30 s |
| Stage 2 delivered (server `elapsed_s`, wall) | 6.273 (6.709) | 7.059 (7.932) | none |
| Stage 3, the whole task (`task_s`, wall) | **10.86 s** (11.34), 18 polls | 11.832 (12.52) | <= 180 s |
| 20 values per parameter, 10 parameters (`demo-synthetic-1m-20v`): stage 1 / 2 / 3 | **6.474** (7.114) measured / 6.586 (7.709) / 11.201 (12.293) | stage 1 not read; stage 2 6.882 (7.543), a bound / stage 3 12.639 (13.107) | <= 30 s (stage 1) |

`elapsed_s` is the server clock when the stage was delivered (cumulative), `wall` the client's. Across all nine analytics records in
`logs/` the task read **10.86 to 11.88 s** (180 s met by a factor of 15 to 17) and the fine stage **6.27 to 7.42 s** (30 s met by a factor of
4 to 5; the bound flag is absent from the first four records). **These factors are on a fixture that exercises neither d = 20 nor
blocks (K = 4 by default, up to 8; "K = 20" is Q6's shortlist size, not a block count).** §9.4's budgets are unmeasured at their stated
scale until Phase 4's 20-parameter fixture. The task's cost model there is Task 4's, in process: 24 to 41 s for the fine stage alone at
20 values and d = 20, against the 30 s line (`progress.md`, Task 4), not measured beside a job.

**The throughput loss.** The brief's formula, `1 - loaded.trials_per_s / quiet.trials_per_s`, divides a short window's rate by a whole-run rate that
includes the start-up gap and a compaction pause; it is not comparable, and the record's own basis says so ("the loaded window sits clear of the
pauses, so this figure reads as the job speeding up"). The figure R3.5 reads is the chunk-aligned matched one: the quiet run read at the same chunk
positions as the loaded window, 1,400 rows over 6.764 s against 1,400 rows over 7.258 s.

| Run (log stamp, UTC) | git head | Headline (brief's formula) | Matched loss | Alignment | Quiet / loaded trials per s |
|---|---|---|---|---|---|
| Task 12, `230745Z` | `4278af30` | -17.1 % | none | none | 150.4 / 176.2 |
| Task 12 run 1, `231912Z` | `4278af30` | -21.9 % | 6.9 % | by time | 151.0 / 184.2 |
| Task 12 repeat 2, `232311Z` | `4278af30` | -19.2 % | 10.4 % | by time | 149.2 / 177.8 |
| Task 12 repeat 3, `232703Z` | `4278af30` | -21.8 % | 9.7 % | by time | 143.4 / 174.6 |
| Fix round 1, `002527Z` | `2fc6422b` | -24.1 % | 7.6 % | by time | 146.0 / 181.2 |
| Fix round 1, `004705Z` | `fc575a71` | -24.2 % | **-16.3 %** | by time (straddled the start-up gap) | 141.4 / 175.6 |
| Fix round 1, `010240Z` | `5edabf80` | -18.7 % | 7.9 % | by chunk position | 142.2 / 168.8 |
| Fix round 1, `011814Z` (the committed Task 12 record) | `6bfd40ca` | -20.1 % | 7.2 % (8.4 % against the after-run) | by chunk position | 149.5 / 179.5 |
| **R3.5, `152504Z`** | `7a63a523` | -22.7 % | **6.8 %** (4.0 % against the after-run) | by chunk position | 157.3 / 192.9 |

Read as a range, the matched loss is **6.8 to 10.4 %** across the eight runs that carry it, outside the one run (-16.3 %) that the
time alignment broke and that `5edabf8` replaced with chunk alignment. The three chunk-aligned runs read 7.9, 7.2 and 6.8 %.
`quiet_run_to_run`, how far the two quiet runs differ over those very chunks, is the noise the loss has to be read against: **2.96 %** here
(-1.34 % in the committed Task 12 record). The second quiet run (after the loaded one, `quiet_after`) read 159.2 trials per s against 157.3,
and 200.9 matched against 207.0, so the order of the runs does not explain the loss. The window is short (8 chunks, 7.3 s) and a single
window: a range, not a point. The task's own window sat 10.0 to 21.3 s from the loaded run's creation.

**The committed Task 12 record's headline tail is stale.** Its `throughput_loss_basis` ends "read throughput_loss_matched, the window against the
quiet run at the same offsets", where the figure is chunk-aligned (found after the last run, reported not edited; Task 12's re-review N-3). The
R3.5 record's `throughput_loss_basis` ends "at the same chunk positions" and supersedes it. The two repeats keep "at the same offsets" as
measured (time alignment).

## 5. Track A before and after

`lab_benchmark.py explore --trials 1000000`, a freshly restarted scratch worker (`-Workers 10`), `demo-synthetic-1m` (1,000,000 trials, 10 parameters),
20 runs per row over HTTP, the cache empty before the first open (`cache_entries_before` 0). Record
`docs/superpowers/plans/2026-10-29-aegis-optimization-lab-v2-phase3-benchmark-explore.json` (`git_head` `7a63a5233fbc`, engine build
`f416bb177cdb`, 4.07 GB free at start, 52.9 s wall). Phase 2's record is `...phase2-benchmark-explore.json` (`b3ffc92`, engine build
`8bef56cd6730`, 2.70 GB free). The Task 0 columns are `task-0-report.md`'s tables for its first record (`logs/lab-benchmark-explore-20261029T161350Z.json`)
and its fix-round record (`...T165712Z.json`, `ff6b7bc`). Latencies are in ms; the budget is §9.6a's p95.

| Row | Phase 2 p50 / p95 | Task 0 p95 | Task 0 fix p95 | R3.5 p50 | R3.5 p95 | Budget | `evaluate()` |
|---|---|---|---|---|---|---|---|
| `open_cold` (one cold open) | 3,273 / 3,273 | 2,075.8 | 1,748.8 | 1,914.8 | 1,914.8 | 4,000 | True |
| `open` | 2,100.6 / **2,202.1** | 122.8 | 105.3 | 78.3 | 81.6 | 1,500 | True (Phase 2 False) |
| `filter_heatmap` (cold first 355.6) | 664.3 / **794.9** | 57.3 | 48.2 | 40.6 | 43.5 | 400 | True (Phase 2 False) |
| `stat_change` | 813.2 / **851.3** | 24.6 | 25.2 | 22.0 | 23.7 | 300 | True (Phase 2 False) |
| `page` | 301.5 / 326.5 | 72.5 | 55.3 | 51.7 | 53.4 | 600 | True |
| `exact_slice` (cold first 136.3) | 99.0 / 118.4 | 24.8 | 24.4 | 20.3 | 23.0 | 300 | True |
| `parallel` (cold first 670.7) | 559.0 / 665.3 | 603.9 | 650.1 | 539.2 | 588.3 | 800 | True |
| `progress_poll` (cold first 12.75) | 3.7 / 4.9 | 5.1 | 4.9 | 4.0 | 8.0 | 100 | True |
| `pareto`, two objectives (cold first 308.3) | not in Phase 2 | not measured | not measured | 231.2 | 294.1 | 800 | True |
| `neighbourhood` (cold first 440.3) | not in Phase 2 | not measured | not measured | 12.9 | 15.0 | 150 | True |
| `worker_rss_delta_mb` | **828.4** (342.7 to 1,171.0) | 375.8 | 372.0 (343.0 to 715.0) | 398.5 (342.6 to 741.2) | | 450 | True (Phase 2 False) |
| `disk_mb` | 333.3 | 333.3 | 333.3 | 333.3 | | 350 | True |
| `compaction_1m_s` (in-process proxy) | 2.491 | 2.517 | 2.381 | 2.258 | | 10 | True |

Recorded beside them, with no §9.6a line: `rankings` p50 66.4 / p95 69.0; `convergence` p50 17.5 / p95 18.6 (cold first 306.8); `pareto_3` p50 645.5 /
p95 674.7 (cold first 781.3); the worker growth after those three rows 387.2 MB (729.9); the 10,000-trial storage proxy (compact 1.707 s; a
7-column read 87.9 ms, 39.0 ms after reclaim). `retest_due`: `engine_build_changed` true (the engine build moved since Phase 2's record); the
other six flags false.

**Misses: none.** All thirteen `evaluate()` keys are True or `absent` (`browser_heap_mb`, absent by construction: HTTP only; the walk's heap is in
section 7). The four rows that missed in Phase 2 (open 2,202, filter and heatmap 795, stat change 851, worker growth 828) now meet their
budgets, by the per-snapshot index and the column-set cache of Task 0. Against Task 0's fix-round record the figures agree within run noise; the
one row that moved the wrong way is `progress_poll` p95 (8.0 ms against 4.9), 8 % of its 100 ms line. The worker growth, 398.5 MB, is above
Task 0's projected 200 to 250 MB and inside the 450 MB line. `pareto_3` read p95 674.7 in this run and 937.7 in the analytics run (section 6);
the two sessions differ in what the cache and the importance result hold, and the record does not say which explains the gap.

**Track B was not re-run in Task 13** (the plan's Step 2 names Track A and analytics only). Task 0's records stand as the last measurement
(`task-0-report.md`): case A at **142.1 trials per s** against 150 (R3 144.7; an engine finding, no engine work in this phase); host growth
for case A 11.5 MB at the fix round but from a 602 MB starting working set against 345 MB in the earlier run (122.0 MB), so it is not
settled; the query p95 ratio under load **7.66 against 2.5** (R3 9.49; each chunk is a new snapshot, so every query during a run is a
cold read under ten busy pool processes); the query throughput ratio 1.016.

## 6. The analytics rows

Judged and recorded rows of the R3.5 analytics record, beside Task 12's committed record (`6bfd40c`) and its two repeats (`4278af30`; they
predate the later record fields, so a dash means the field does not exist there). Latencies are in ms.

| Measure | R3.5 | Task 12 | Repeat 2 | Repeat 3 | Line |
|---|---|---|---|---|---|
| importance `task_s` | **10.86 s** | 11.83 | 11.56 | 11.47 | <= 180 s (True) |
| `fine_stage_s`, 1M value counts | **6.273 s (a bound)** | 6.936 (measured) | 6.851 | 6.838 | <= 30 s (True) |
| `fine_stage_20_s`, 20 values per parameter | **6.474 s, measured** | 6.882 (a bound) | - | - | <= 30 s (True) |
| `pareto`, two objectives, p50 / p95 / max | 231.2 / **266.6** / 322.9 | 250.3 / 266.4 / 335.6 | 225.6 / 275.4 / 1,365.5 | 245.9 / **912.8** / 1,626.4 | <= 800 (True; repeat 3 False) |
| `neighbourhood` p50 / p95 / max | 13.3 / **15.3** / 602.6 | 15.4 / 23.6 / 1,182.7 | 12.8 / 16.1 / 436.4 | 13.6 / 16.7 / 432.8 | <= 150 (True) |
| `candidate` (A plus B's region read, importance live) p50 / p95 / max | 72.4 / **79.1** / 93.9 | 81.3 / 89.1 / 94.8 | - | - | <= 150 (True) |
| `rankings` (B not run) p50 / p95 | 65.3 / 68.1 (cold 251.8) | 72.0 / 86.5 | - | - | none |
| `rankings_importance` (B on the top 20) p50 / p95 | 240.3 / 253.6 | 244.2 / 255.8 | - | - | none |
| `convergence` p50 / p95 (cold first) | 17.3 / 43.5 (312.7) | 17.7 / 51.6 (335.7) | - | - | none |
| `pareto_3` (three objectives) p50 / p95 / max | 710.5 / **937.7** / 957.8 (cold first 817.6) | 724.1 / 870.8 / 899.9 | - | - | none; 800 is the two-objective line |
| `pareto_widest` p50 / p95; front | 217.4 / 250.7; 57 (expectancy x trade_count, 55 pairs probed) | 232.9 / 286.5; 57 | - | - | none |
| importance poll beside the job p50 / p95 | 158.9 / 258.8 (0.5 s cadence) | 159.3 / 189.3 | - | - | none (the 100 ms row is the progress poll) |
| `opt_frame_rebuild` at 99,856 cells (in process) p50 / p95 | 1,269.5 / 1,364.1 | 1,308.6 / 1,465.5 | - | - | none |
| K = 4 plan / actual / ratio | 175.9 s / 219.0 s / **1.245x** | 194.5 / 265.5 / 1.365x | - | - | none |
| K = 0 ratio, actual to plan | 1.394x | 1.436x | - | - | none |
| K4 / K0, planned vs actual | 3.41x vs 3.05x | 3.66x vs 3.48x | - | - | none |
| Case A host growth during the run (not judged) | K = 0: 118.6 (working set 715.2 to 833.7); after-run 57.8; K = 4: 124.2 | K = 0: 93.3; K = 4: 113.4 | - | - | the Track B line is 100 MB |
| Pool-child peak (K = 0 / K = 4) | 154.8 / 157.4 MB | 154.8 / 157.5 | - | - | 160 MB + 400 B per bar |

`evaluate()` for the R3.5 record: `{"importance_task_s": true, "fine_stage_s": true, "fine_stage_20_s": true, "pareto": true, "neighbourhood": true, "candidate": true}`.
Task 12's committed record evaluates the same six True; repeat 2 had its four keys True; repeat 3 had `pareto` False (912.8). **`fine_stage_s` is again an
upper bound, not a measurement, in the R3.5 record** (stage 1 finished before the first poll that read a stage; the first stage read was stage 2 at
6.273 s, so a pass is sound and a fail would have been conservative); the 20-value row is measured (stage 1's own `elapsed_s`).

**The Pareto p95 of every analytics record** (20 HTTP samples per row, the cold first sample included, the p95 therefore the 19th of 20, so two slow
samples fail it): Task 12's runs **268.4 / 275.4 / 912.8** (and 248.9 in the first, uncommitted run before them); fix round 1's **265.9, 346.3, 245.3 and 266.4**
(the last the committed record); **R3.5: 266.6**. Nine records, one over the 800 line (repeat 3); the R3.5 run is not that one. Report the spread,
not a single pass.

**`pareto_3` p95 across the five records that carry it:** 827.7, 840.1, 798.5, 870.8 and **937.7** (R3.5, the highest; p50 710.5 is in line, and the
p95 is the 19th of 20 samples, two of them 937.7 and 957.8). It is recorded against no line: §9.6a's 800 ms row is for two objectives.

**`candidate_b`:** `{"cards": 20, "b_resolved": 20, "b_ran": 20, "b_reasons": {}}`; `ranking_pool`: `{"pool": 300, "k": 20, "candidates_drawn_from": 300, "b_max": 20}`.
So the 79.1 ms candidate p95 times A plus B's region read on cards where B resolved and ran in all 20; the harness stops the run if the importance
result is live and no card's B ran.

**The memory rows** (fix round 2's additions). `first_call_memory` per row, taken around each row's first (cold) call;
`working_set_delta_mb` is a post-call working-set reading and noisy (Windows trims it between calls: the same code read +231 and +7 MB for one
call in Task 12's round); `peak_working_set_mb` is the process's `PeakWorkingSet64` high-water mark; `cache_delta_mb` is deterministic (decimal MB of
`GET /api/lab/build`'s `cache.bytes`).

| Row (cold first call) | Working-set delta (noisy) | Peak working set | Cache before to after | Cache delta |
|---|---|---|---|---|
| `neighbourhood` | +237.2 MB | 687.2 MB | 0 to 194.0 MB (0 to 4 entries) | +194.0 MB |
| `convergence` | +0.75 | 735.5 | 194.0 to 194.2 (4 to 5) | +0.242 |
| `rankings` | +4.05 | 735.5 | 194.2 to 194.2 (5 to 5) | 0.0 |
| `rankings_importance` | +2.69 | 1,147.1 | 372.0 to 372.0 (6 to 6) | 0.0 |
| `candidate` | +0.34 | 1,147.1 | 372.0 to 372.0 (6 to 6) | 0.0 |

The worker's working set read 341.3 MB before the views and 715.1 MB after them (a growth of 374 MB, to be read against the 450 MB row). Its **peak working
set** read **619.4 MB before the first view, 909.0 MB after the views (and the 55-pair Pareto scan) and 1,147.1 MB after the candidate rows.**
The peak is a process-lifetime high-water mark, so these are cumulative. The 619.4 MB was set before the benchmark's first view, by the worker's
start-up and the benchmark's setup calls (the benchmark runs the views first and the job cases after them, so the job cases cannot have set it; Task 0's
fix round saw a fresh `-Workers 10` start with a 602 MB working set before its job, and Task 12's smoke saw 508 MB with a 549 MB peak on a fresh
worker). By the 1,147.1 MB reading, the three Case A runs, the importance task beside the loaded run, the K = 4 and 20-value passes and the k = 300
ranking had also run in the same process. **So the Task 8 "460 MB peak" row (the in-process peak beyond the frame, at d = 20) has no like-for-like figure
yet.** The remedy for Randall is a fresh worker per view in the benchmark (a restart before each view, or a peak reset).

**The Lab cache** (`lab_cache`, from `GET /api/lab/build`): before the views 0 bytes, 0 entries; after the views **367,629,196 bytes, 9 entries**; after the
candidate rows **372,004,220 bytes, 6 entries**. Entries fall 9 to 6 while bytes rise 4.4 MB. **Read from `app/products/aegis/lab/cache.py`
(read only): it was LRU eviction, not replacement.** The only code that lowers the entry count is the insert loop in `LabCache.get`, which pops the
oldest entry while the byte total exceeds `max_bytes` (`LAB_CACHE_BYTES` = 400 MiB = 419,430,400 bytes); a same-key insert pops and re-inserts
that key, so the count does not fall; and `LabCache.evict(prefix)`, the other remover, has no caller under `app/`. Between the two readings the
benchmark ran the quiet, loaded (the importance task, which loads its own table under its own key, Ruling P1) and after Case A runs, then the
k = 300 robustness request: loads that took the total over the bound while 367.6 MB was held, so the least recently used entries left. What the record
cannot say is which three entries, or how many insertions happened in between (the two readings are not adjacent). By construction the held total cannot exceed 419.4 MB (the two
readings are 367.6 and 372.0 MB). After the views the working set had grown 374 MB against 367.6 MB held, so the worker holds about what the cache holds,
as `cache.py`'s release of Arrow memory intends (Phase 2's R3 note found the growth, 828 MB, far above the 400 MB bound); the 1,147 MB peak is a transient
above that.

**`not_measured`, verbatim, with owners** (seven rows; Task 12's record has five, rows 6 and 7 are new):

| # | Row | Why | Owner |
|---|---|---|---|
| 1 | the importance task at d = 20 with blocks (K = 4 by default, up to 8) (§9.4's 180 s budget at its stated scale) | the 1M fixtures have 10 parameters and no blocks, so the per-block mains (stage 2's K x 200 cheap passes) and the d = 20 cost are not measured here; the task is a 10-parameter, 50,000-row one | Phase 4's 20-parameter fixture (the Task 13 R3.5 note states the budget unmeasured at its scale until then) |
| 2 | the robustness ranking and a candidate's view at d = 20 (the cache entry, the 840 probes at m = 2) | the fixtures have 10 parameters | Phase 4's 20-parameter fixture |
| 3 | the Pareto all-on-front worst case | not constructible over HTTP: a metric cannot be named twice (the view refuses `an objective is named twice`) and no pair of the fixture's metrics is anti-correlated; the widest front among all pairs is recorded as `pareto_widest` instead | R3.5 (a synthetic anti-correlated fixture) or the Pareto unit tests |
| 4 | the `opt:` source's importance poll at MAX_CELLS over HTTP | needs a finished 100,000-cell grid job in the store; `opt_frame_rebuild` is an in-process proxy for the per-poll frame rebuild, without the view on top of it | R3.5 |
| 5 | plan against actual at d = 20 with blocks (K = 4 by default, up to 8) | the blocked run is K = 4 at d = 10 | Task 2's price model; an R3.5 finding |
| 6 | the fine stage at d = 20 with 20 values per parameter beside a job | Task 4 measured 24-41 s alone against the 30 s line; `fine_stage_20_s` is the 10-parameter, 20-value row, which at d = 10 reads as it does at 12-19 values | Phase 4's 20-parameter fixture |
| 7 | a candidate's card on a blocked experiment | `trial_blocks` reads the trial's block rows only when K > 0 and no K = 0 fixture exercises it; the card's C finding is not timed | R3.5 or the blocked fixture |

**Not in `not_measured` and not measured by Task 13**, named so they do not disappear: the convergence view beside a **running** job (the ledger's ruling after Task 8:
"a new chunk is a cache miss costing up to 1.8 s and 460 MB; R3.5 measures it beside a running job"; the record's convergence rows are on a finished fixture, cold 312.7 ms and
warm 17.3 ms, cached); `memory_probe.py` on a blocked plan (Ruling after Task 2's fix round: "Task 13 runs `memory_probe.py` on a blocked plan beside the
benchmarks"; it was not run; the pool-child peak at K = 4 reads 157.4 MB against 154.8 at K = 0, inside the 160 MB + 400 B per bar budget, which is the nearest
evidence the benchmarks give); and Track B (section 5).

## 7. The walk

`C:\Triad\.venv\Scripts\python.exe tests\products\aegis\browser_workstation.py --base http://127.0.0.1:8103/aegis/ --only lab --data-root C:\Triad\data\temp\lab-scratch --pid-file logs\aegis-scratch.pid`,
from the worktree on `7a63a52`, against a freshly restarted scratch worker (`-Workers 10`). Record
`logs/aegis-acceptance-20261103T152633Z.json` (not committed; `logs/` is ignored): **`16/16 PASS, 0 FAIL, page errors 0`**, 278.2 s (wall 280.8 s),
`lab_only` true, first item 103, `lab_longtask_supported` true. The worker served `app` of the worktree on the scratch root and `/lab/build` agreed
(engine `f416bb177cdb`). No re-run was needed.

Items 103 to 118 (ms): 103 Expand Lab (4,840), 104 sub-nav keeps filter, selection and pins (1,486), 105 every unavailable control says why (2,162),
**106 both widths (182,037)**, 107 (the walk's 126) Variable Intelligence's workflow strip (371), 108 (106b) the keyboard model (765), 109 (RF2/3) a
running experiment (4,910), 110 (107) exact slice with no match (899), 111 (108) an aggregate square (660), 112 (109) counts identical across the heatmap,
table and header (673), 113 (110) a brush on the real 12k experiment (1,116), 114 (104b) sub-nav on the real 12,000-trial experiment (1,991), 115 (111) a spike and a
plateau are labelled (6,493), 116 (112) Parameter Families on the 10-parameter bench (52,199), 117 (124) a candidate card shows four categories (1,067),
118 governance (835): aegis `human_directed` and exchange CLOSED, `DailySchedule` `c99fa831` enabled False, no change under Core, the platform host or Triad
since `1882c81` but Mission 14's four fix-pass files merged from `main`.

`lab_timings_ms` (12,000 trials; Playwright to browser to scratch worker; zero long tasks over 50 ms on every label):

| Label | ms | Budget | R3's final-code walk (`b3ffc92`) | R2.5's figures (kept by the R3 note) |
|---|---|---|---|---|
| `exact_slice` | 87.1 | 300 | 75.5 | 99.8 |
| `stat_change` | 57.0 | 300 | 52.6 | 180.5 |
| `filter_heatmap` | 193.0 | 400 | 78.6 | 225.6 |
| `page` | 218.3 | 600 | 96.8 | 315.9 |
| `brush` (the `parallel` budget) | 305.7 | 800 | 351.9 | 494.9 |

Every label is inside its budget (the brush at 38 % of 800). `lab_heap_mb`: **29.9** after the walk's items labelled (109) and **42.1** after (110), against 300
(R3's final-code walk 12.7 and 17.7; Task 12's walk 16.4 and 14.6; its fix round's 16.1 and 28.6). `lab_scratch_size_bytes` 1,080,250,863.

**Item 106, both widths.** At 1672 x 941 and 1440 x 900: no primary Lab control clipped (20 controls inside and on top on the Lab page; the bench by
the keyboard with 31; the Robustness tab with a card open 28; Parameter Families 13 and maximized 11), 4,954 texts checked, every text >= 11 px, 24 catalog inputs
brought into view by scrolling the catalog list alone before they were measured. Lowest contrast outside disabled controls 5.50 (`.sub`,
`.trial-table th[aria-sort=none]`); the eight disabled controls under 4.5:1 (2.61 to 4.30, inactive components being exempt under WCAG 1.4.3) are item 116, deferred and unchanged.

**Screenshots** (all in `logs/`, prefix `aegis-acceptance-20261103T152633Z-`): item 106 at 1672 x 941: `lab-1672x941`, `robustness-1672x941`, `families-1672x941`,
`families-max-1672x941`; at 1440 x 900: `lab-1440x900`, `robustness-1440x900`, `families-1440x900`, `families-max-1440x900`; items 111 and 112 at 1600 x 1000:
`robustness-1600x1000`, `families-1600x1000`; also `dock-1600x1000` and `final`: 12 PNGs (170 to 312 KB each) and the JSON.

**The fixtures the walk makes** (`lab_fixtures`): a 9-cell optimization job `f2f2fd39` (item 103); the experiment `lab-walk-20261103t152633z` (2 reports); the bench
`lab-walk-20261103t152633z-bench` (12,000 trials, 10 parameters, sampler `lhs+refine`, 2,603 bars, built in 118.1 s, its report in 29.8 s; trials #7933 and #7169 materialized on
the pinned bytes, each equal to its page row on the 4 of 30 metric pairs the page projects); `...-running` (9 cells, posted and opened at once); `...-blocks` (4 blocks, an exhaustive 3 x 3 grid for item 124's
resolved A and unresolved C); `...-leave` (9 cells, for item 112's second case). Item 124 asserts C on both fixtures: `no blocks or folds` on the bench and
`unresolved · selection-period only` with its informational finding on the 4-block grid.

**Item 112, step 10: the two cases and what they cover.** (1) Leaving Screen E on a *finished* source asked for no task view and no task status in 4.5 s.
(2) Leaving it on the *running* experiment `...-leave` with its importance task queued asked for no importance, interactions or triples view in the 40 s after (one 30 s
ask cadence and two 2 s ticks; a real wait on the clock), and exactly **1 status poll** of the one handed task, `(2.1, 'done')`, the last answering its end and nothing for the 38 s
after it. Covered: a leaked task watch and a leaked task-view re-ask now fail. **Not covered** (N-6): the 30 s ask timers of Screen E's own views (matrices, map,
sampled parallel, chart) cannot be told from Trial Lab's asks for the same views, the 9-cell fixture keeps its task active for 1 to 2 s on this host, and the walk types the UI's
30 s cadence (`LAB_ASK_CADENCE_S`). The item says to give `LAB_RUNNING_SURFACE` more cells on a faster host; here it reached the wait.

## 8. The QA verdict

Verbatim from `task-13-qa.md` (Fable 5.1, independent of Tasks 4 to 6, a detached worktree at `7a63a52`, removed after). The QA quotes the case 1
companion by its old name, `test_case01_at_5000_rows_proposes_nothing_honestly`; it was renamed `test_case01_at_5000_rows_reports_what_is_proposable`
in `dcf9894` (Step 5a), with no other change.

**Reviewer:** Claude Fable 5.1, independent of Tasks 4–6 (no history with the branch). **Date:** 2026-11-03.
**Implementation reviewed:** `7a63a52` on `claude/zen-thompson-50e9bb`, in a throwaway detached worktree `Q = C:\Triad\data\temp\r35-qa` (created by `git worktree add --detach`, removed at the end, §9).
**Interpreter:** `C:\Triad\.venv-aegis\Scripts\python.exe`, `TRIAD_PYTEST_SCOPE=aegis`, `PYTHONPATH=Q\app;Q\tests`, `-p no:cacheprovider`, `PYTEST_ADDOPTS` cleared, `TRADING_HOME` unset (it then resolves to `Q`, `app/trading_core/settings.py:7-12`, so no test touched `C:\Triad\data\aegis`).
**Not done, by the brief:** no worker, pool process, benchmark or browser walk; no subagent; nothing written outside `Q` but this file. A Phase 3 checks run was in progress beside me in the Lab worktree.

**Verdict: PASS WITH FINDINGS** for R3.5's statistical pass condition (§8). Two findings go to Randall as spec/plan corrections (F1, F2); none changes a number the rule computes.

### The sixteen §20 cases: expectation, the test's, agreement (QA §1)

My expectations were written from §7.3–7.4a, §8.4 and §20 alone before any test or implementation file was opened (scratchpad `r35-derivation.md`, kept). Then `tests\test_lab_analytics.py` (cases at lines 699–954), `tests\lab_stat_fixtures.py` and the rule were compared case by case; every case is parametrized over seeds 1, 2, 3 (`at_seeds()`, line 639; no flip is registered, and the run produced no xfail).

Fixture constants that the spec leaves open and the fixture fixes (`lab_stat_fixtures.py`): σ = 0.5 (:33), 8 values per parameter (:39; 17 for case 11, 40 for case 6, 2 for case 14's binaries, 5 for case 9's child), d = 8 (20 for case 7), 5,000 rows (20,000 for cases 1 and 13, decision 20).

| # | My expectation (spec alone) | What the test pins (`test_lab_analytics.py`) | Agreement |
|---|---|---|---|
| 1 strong first-order | x₁ `Active · detected`, S₁ upper ≫ θ_min; every noise parameter has a `Deprioritized` proposal with conditions 1–5 holding; rule available, no veto. Two things to verify: the noise share must keep R's lower bound < 0.3, and a noise variable's condition 3 needs bias-adjusted coarse terms (unadjusted η² for 64 cells at N = 5,000 is 0.0128 > θ_min). | :700–711 on **20,000 rows**: `available`, `veto is None`, x₁ `Active · detected` and not proposable, S₁ upper > 10·θ_min, every noise parameter `Deprioritized · proposable` with `failing is None`. Companion :715–732 on §20's 5,000 rows accepts either `Active · not detected` or `Deprioritized · proposable` for a noise parameter and requires a non-proposable one's `failing` to name condition 2 or 3; prints the proposable counts. | Agrees on the 20,000-row test. Both verifications hold (coarse terms adjusted and unclamped, `coarse.py:139`; `test_coarse_bins_and_terms_match_the_definition` :1078 checks the formula by brute force; R = 0.187–0.203 in the first-order shape). The row count departs from §20 (decision 20, accepted 2026-10-29); the companion's printout shows **3 of 7, 7 of 7, 1 of 7** noise parameters proposable at seeds 1–3, which contradicts decision 20's premise: **F2**. |
| 2 XOR | S₁, S₂ below the floor; pair (1,2) Measured; Δ₁\|₂ upper ≫ θ_min; both `Investigate · interaction not ruled out`; not proposable (condition 2). | :736–751: mains ≤ family floor; both the status; not proposable; `failing` starts `not proposable: condition 2 (Δ beyond <other> upper`. Fine half :184–189 pins Δ₁\|₂ upper > 0.2. | Agrees. |
| 3 three-way only | mains and pairs below the floor; each own-direction coarse Δ^c upper > θ_min; all three `Investigate · three-way effect not ruled out`. | :755–763: the status for x₁..x₃; not proposable. `test_triples_top_ranks_by_the_largest_own_increment` :1337 pins (0,1,2) at the top. | Agrees (mains/pairs below the floor is implied by the status order, rule 6 after rules 4–5). |
| 4 aliased | V > 0.3 → both `aliased · credit shared with <other>`; neither proposable; rule unavailable for the whole experiment. §8.4 lists `aliased` as Investigate evidence, so I expected `Investigate`. | :767–777: `availability.reason == "aliased inputs"`, both flags, neither proposable, `failing == "aliased inputs"`. Measured V(x₁,x₂) = 0.549. Status not pinned; the implementation gives `Active · detected`. | Agrees on everything §20 names. The status gap against §8.4 is **F4** (Low). |
| 5 uneven sampling | x₁ not proposable because Δ₁\|₂ upper > θ_min (and x₁ carries a main effect unless x₂ is centred). **Spec arithmetic:** with P(x₁ = v) ∝ v the §7.4 pair-balance TVD is 0.222 at B = 8 and tends to 0.25 from below, and the §7.2 per-square TVD is ≈ 0 because the skew is global — "TVD > 0.25" is not reachable from §20's generator. | :781–794: the (x₁,x₂) aggregate squares are flagged `confounded` **by x₃**, x₁ not proposable, fine Δ₁\|₂ upper > θ_min, condition 2 present in `conditions(result, 0)`. The fixture (`uneven_rows`, :84–91) adds **x₃ = x₁ ± 1**, which §20 does not have. | **Disagreement → F1 (Medium).** Measured: V(x₁,x₃) = 0.546 → the experiment is `aliased inputs`; every parameter's `failing` is `aliased inputs`, x₁'s status `Active · detected` (S₁ = 0.008–0.013); balance TVD(x₁,x₂) = 0.223–0.231 < 0.25 (my arithmetic confirmed); Δ₁\|₂ upper = 0.0163 / 0.0203 / 0.0166. The intended quantity is checked, but the status-level "not proposable" rides on aliasing, and the `confounded?` flags on a dependence the spec never states. |
| 6 sparse coverage | x₁ `Insufficient coverage · unresolved`, coverage "8 of 40" printed, listed last, excluded from ranking, never proposable; the label must count the lattice's 40 values, not the 8 observed (else 5,000 ≥ 30·8 and 625 rows/value make it `Measured`). | :798–808: last in `statuses`, the status, label `Insufficient coverage`, not proposable, reason `coverage: 8 of 40 values hold ≥ 20 rows; n = 5,000 (needs 1,200)`, every other parameter `Measured`. `coverage_label` (`analytics.py:406–419`) counts the lattice's B. | Agrees. Not pinned by §20 nor the test: the fixture models the 32 absent values as a validity rule, so the rule is also `not a product design (80 % …)` (set aside). |
| 7 pure noise | every status `Active · not detected`; veto raised; no proposal; the warning text. **Statistics:** under §7.3's per-share 95th-percentile floor, "every share below the floor" has probability 0.95²⁰ = 0.36 per seed for the mains alone. | :812–826 at d = 20: 20 statuses all `Active · not detected`, `veto == VETO_TEXT`, warning present, `coarse.lo > 0.3`, nothing proposable, every `failing` the veto text. Holds because "detected" uses the **family-wise max-T floor** (decision 18, `analytics.py:305–353`). | Agrees under decision 18; the spec text was not amended: **F3** (Low). My out-of-sample check (seeds 11–20, §6 F7): 0/10 false detections in any family, veto 10/10. |
| 8 one-block regime | x₁ `Investigate · period-dependent`, block range [≈0, high], never proposable (condition 1 fails in block 2). The spec gives no threshold for "large" / "near zero". | :830–836: the status, not proposable. Fine half :237–251: block 2's S₁ lower > 0.5, blocks 1, 3, 4 upper < θ_min. Rule 3 (`rule.py:642–655`): a block detected with upper > θ_min and another block with upper < θ_min. | Agrees; the operationalization is decision 21's, documented. Set aside. |
| 9 range change | wide: x₁ detected; after the re-screen on [0, 0.7·range]: old evidence `stale`, not reused; fresh S₁ below the floor; scoped to its range. | :840–852: parent x₁ `Active · detected`; `compare_scope(parent, child) == "stale: ranges changed"`; child S₁ ≤ family floor (the child's Y is 0 on its whole range, `child_hinge` :309–314). `test_stale_then_rescreen_refreshes_evidence` :988. | Agrees on what Phase 3 builds; "not reused" (parent rows in a child cohort) is Phase 4 (`analytics.cohort` reads one experiment). Set aside. |
| 10 correlated inputs | V > 0.3 → both aliased; `unavailable: aliased inputs`; no proposal for anyone. Both "aliased" and "not a product design" apply; §20 pins "aliased inputs", so aliasing must be checked first. | :856–866: reason `aliased inputs`, both flags, nothing proposable. `availability` orders aliasing before the product design (`rule.py:127–159`; `test_availability_reasons_in_order_and_their_strings` :1178). | Agrees. Measured V(x₁,x₂) = 0.317 / 0.310 / 0.314: the case clears 0.3 by 0.010–0.017 and only because B = 8 (fixture comment: B = 10 gives 0.27): **F5** (Low). Also 67 % of the grid is invalid (second reason, as expected). |
| 11 coarse-bin cancellation | fine S₁ detected and upper ≥ θ_min → condition 1 fails on the fine grid; `Active · detected`; coarse S₁^c ≈ 0. | :870–878: `abs(coarse.S[0]) < θ_min`, fine S₁ > 0.5, `Active · detected`, `conditions(result, 0)[0]` starts `condition 1 (fine S upper`. Bins at B = 17, q = 4 are 5/4/4/4 values and sin(πv/2) sums to 0 in each (checked by hand). | Agrees. |
| 12 higher-order structure | mains, pairs, triples ≈ 0; R lower bound > 0.3 → veto; no proposal; the warning. | :882–888: `coarse.lo > 0.3`, veto text and warning, nothing proposable. | Agrees ("terms ≈ 0" is implied, not asserted; set aside). |
| 13 own-direction triple | x₂ proposable although Δ₁\|₂₃^c ≈ 1 (≈ S₁^c, 0.76 at B = 8) and Δ₂\|₁₃^c ≈ 0. | :892–900 (case 1's 20,000-row experiment): `Delta3[0,1,2] > 0.5`, `abs(Delta3[1,0,2]) < θ_min`, x₂ `Deprioritized · proposable`. | Agrees. This is the test my fault injection broke (§4). |
| 14 pairwise-independent, jointly dependent | `unavailable: inputs are not a product design (50 % of the grid is invalid)`; not aliased (pairwise V ≈ 0); fine lists still present. | :904–916: `aliased_pairs == []`, the exact reason string, `hint == PRODUCT_HINT`, S finite for all 8, x₄ `Active · detected`. Measured V ≤ 0.015. | Agrees. |
| 15 weak constraint | not aliased; `unavailable: inputs are not a product design (2 % of the grid is invalid)` with the freeze/narrow hint. "V ≈ 0.2" from a 2 % deletion is implausible (I expected ≈ 0.05). | :920–928: `aliased_pairs == []`, the exact string (1 cell of 64 = 1.6 %, printed `2 %`), the hint. Measured V(x₁,x₂) = 0.057–0.063. | Agrees; the spec's "V ≈ 0.2" is wrong: **F5**. |
| 16 outcome-dependent missingness | `unavailable: n of N configurations have no finite profit_factor (0 invalid, 0 failed, n undefined)`; note "on N−n of N; missingness may bias"; `net_pnl` → available. The 1,240 / 3,760 are illustrative. | :932–954: the string from the fixture's own count at every seed (1,189 / 3,811 pinned at seed 1), `hint == METRIC_HINT`, the note, and `net_pnl` available with no note. `cramers_v` reads every uniform configuration (`X_uniform`), so the missingness never shows as aliasing (`test_aliasing_reads_every_uniform_configuration` :562). | Agrees (Ruling P8). |

The §20 "plus" tests: `test_refinement_rows_excluded` :268, `test_stale_then_rescreen_refreshes_evidence` :988, `test_rule_unavailable_when_aliased_or_adaptive` :971, `test_interval_coverage_known_variance` :282 (§3), `test_permutation_floor_scales_with_bins` :298 — all present and green.

**What the tests pin that the spec does not say:** 20,000 rows for cases 1 and 13; case 5's x₃ dependence; the max-T family floor (case 7); the period-dependent thresholds (case 8); the availability order (case 10); the exact reason/format strings everywhere (fine: they are the plan's). **What the spec says that the tests do not pin:** §8.4's `Investigate` on `aliased` / unresolved pair (F4); case 7's "every share below the floor" for pairs (only the mains are status-visible; an increment detected with upper < θ_min would still read `Active · not detected`); case 9's "not reused" (Phase 4); case 12's "terms ≈ 0" (implied).

### Re-run counts (QA §2)

| Set | Result |
|---|---|
| `tests\test_lab_analytics.py tests\test_lab_blocks.py tests\test_lab_robustness.py tests\test_lab_pareto.py` | **455 passed, 0 failed, 0 xfail/xpass**, 214.2 s (collected: analytics 101, blocks 27, robustness 132, pareto 195; the sixteen cases × 3 seeds = 51 case tests, incl. the 5,000-row companion). Printed by the companion: `case 1 at 5,000 rows, seed 1: 3 of 7 noise proposable`, `seed 2: 7 of 7`, `seed 3: 1 of 7`. |
| Engine guard set (R3 note :59): `tests\test_aegis_engine_golden.py` (14 golden keys), `tests\test_lab_sharpe.py`, `test_legacy_read_equals_cells`, `test_legacy_report_reproduced_identically`, `test_legacy_resume_unchanged`, `test_legacy_job_never_compacts`, `test_materialize_refuses_vintage_drift`, `test_materialize_matches_lab_page_row` | **35 passed**, 33.3 s (the R3 note's 35). |
| The four files again after the fault was reverted (§4) | **455 passed, 0 failed, 0 xfail**, 216.5 s, `git status --short` empty at `7a63a52`; the companion printed the same 3 / 7 / 1 of 7. |

### `test_interval_coverage_known_variance` by the QA's own simulation (QA §3)

**The test** (`:282–295`): Y = a·x₁ + ε with a = 1, 8-value lattice, σ = 0.5, n = 5,000, d = 2; true share S₁ = a²·Var(u)/(a²·Var(u) + σ²) with Var(u) = (B+1)/(12(B−1)) = 9/84 → **S₁ = 0.300**; asserts the implementation's 90 % interval covers it in ≥ 85 of seeds 1..100.

**My simulation** (scratchpad `coverage_sim.py`, nothing from the repo in the main pass): my own data (streams `(99991, seed)`), my own count-weighted adjusted η² (`S − (k−1)/(n−k)·(1−S)`, clamped), my own 200-draw multinomial bootstrap, both the re-centred interval `[θ̂ + q₀.₀₅ − mean, θ̂ + q₀.₉₅ − mean]` and the plain percentile interval; **1,000 seeds**. A second pass fed the same 1,000 datasets to the implementation's `intervals(FineTerms(B, pairs=False), …)`.

| Interval | Covered the true share |
|---|---|
| my re-centred 90 % | **899 of 1,000 = 0.899** (SE 0.010) |
| my plain percentile 90 % | 896 of 1,000 = 0.896 |
| the implementation's `intervals` on the same data | **902 of 1,000 = 0.902** (SE 0.009) |

Point estimates: mean 0.30014, SD 0.0103, bias +0.00014 (the adjustment works). The coverage is the nominal 0.90 at this share; the test's ≥ 85/100 would fail on a random 100-seed set with probability 0.043 at p = 0.899 (0.040 at exactly 0.90), but its seeds are fixed 1..100, so it is deterministic and it passed in both runs. Set aside (§7). Verdict on this test: the interval's coverage claim is confirmed independently.

### The injected fault (QA §4)

**Fault:** the own-direction triple increments swapped between i and k in `app/products/aegis/lab/coarse.py:146`: `np.stack([T - J[b, c], T - J[a, c], T - J[a, b]])` → `np.stack([T - J[a, b], T - J[a, c], T - J[b, c]])`, so Δ_{i|jk} read Δ_{k|ij} and vice-versa (the §7.4a own-direction rule, condition 3). Chosen over the brief's off-by-one because it is a semantic error a brute-force formula test would not catch alone, and it is what case 13 exists to pin.

**Run** `tests\test_lab_analytics.py` with the fault: **10 failed, 91 passed** in 133 s:
`test_case13_own_direction_triple[seed1|2|3]`, `test_case01_strong_first_order[seed1|2|3]`, `test_case01_at_5000_rows_proposes_nothing_honestly[seed1|2|3]`, `test_coarse_bins_and_terms_match_the_definition`.

Quoted failure (case 13, seed 1):
```
tests\test_lab_analytics.py:897: in test_case13_own_direction_triple
    assert result.coarse.Delta3[0, 1, 2] > 0.5
E   assert np.float64(-1.3679539236255422e-05) > 0.5
```
and the definition test: `Obtained: 0.46108426282261816  Expected: 0.06003201563572602 ± 1.0e-12` (`:1122`). Case 1 fails because x₃'s "own" increment now carries x₁'s share, so condition 3 blocks the noise parameters.

**Revert:** `git -C Q checkout -- app/products/aegis/lab/coarse.py`; `git status --short` and `git diff --stat` empty at `7a63a52`; the original line confirmed on disk; then the four files re-run green (§2, last row).

### The carried statistical questions (QA §5)

**Q1. The pooled mean on merged trellis squares** (`ui/src/lab/familiesModel.ts:37–57, 110–131, 194–198`). The merge is statistically exact for the mean: each part is weighted by its trials with a value (`stats.n − histogram.nulls`, the server's `m`), so the pooled mean equals the mean over the union. The median is withheld with a visible note, which is right (a median is not a function of its parts' medians). Three costs remain: (i) the trellis's statistic **switches from median to mean whenever an axis exceeds 16 values** (`trellisStat`), so wide-lattice pairs are drawn on a more outlier-sensitive statistic than narrow ones in the same screen — heavy-tailed `net_pnl` spikes will colour them differently; the legend says so, but an operator comparing two pairs will not read it; (ii) p25/p75 and the `confounded?` flag cannot be pooled, so a merged square carries neither; (iii) a merged square is labelled by its group's low lattice value (`rows: rows.map((g) => g.lo)`), i.e. a square spanning values 17–18 is labelled 17. A **server-side binned matrix** (groups chosen server-side, every statistic computed over the union's rows) removes all three and keeps "the UI never aggregates" (§7.8). I support it for Phase 4; until then the median-to-mean switch deserves a line on the pair itself, not only the legend.

**Q2. `inputs.valid_basis = "frame"`** (`neighbours.py:18–22, 55, 132–134`). `valid` = on-lattice positions less those the pool refused (`invalid` rows), and once an exhaustive grid is complete, less positions without a row; a sampled surface's constraint cells count as valid and untested. The bias is one-directional (coverage understated → `unresolved`, never a false `stable` or `peak`), which is the right direction. Its cost: on a sampled surface with a validity table (MACD `slow > fast` removes about half the (fast, slow) neighbours), coverage near the constraint is capped near 0.5, so A is unresolved for exactly the candidates that sit against the boundary, where overfit often lives; and on a running grid, skipped cells read untested until the run ends (Task 7 report, concern 5). Finding: acceptable for Phase 3 and honest; when Phase 4 brings validity tables, `valid` should read them and `valid_basis` should say which basis was used. The card prints the bare token `frame` (`candidateModel.ts:144`); a sentence would be clearer.

**Q3. `RANK_POOL = 300` ahead of k = 20** (`robustness.py:17–25, 741–805`). `robust` is a re-ordering of the top 300 trials **by peak**, A read for all 300, B only for the top `min(k, RANK_B_MAX) = 20` whose A is unresolved; rows 21..300 with A unresolved sort as unresolved. Statistically: (i) on a sparse sampled surface (the 12,000-trial bench, where every top-300 candidate has coverage ≈ 0) `robust` reduces to `peak` with B as a tiebreak among the top 20; (ii) a plateau none of whose trials ranks in the top 300 by peak cannot appear, so `stable: null` means "none among the top 300 by peak", which the basis line does print; (iii) within the pool the lexicographic rule puts every `stable local` above every `mixed`, so low-value stable cells outrank high-value mixed ones (Task 7 report, concern 2; §7.6's design, not the pool's). The bound is honest and visible. Suggestions: make the pool depend on n (e.g. top 1 % capped at 300, floor 20), and let B run for every A-unresolved pool row when the request's axes ≤ 6 and n is small, since B is cheap there; neither is an R3.5 blocker.

**Q4. `isolated peak` unreachable on real engine surfaces** (`robustness.py:270–323`; `policy.py:73–77`). I measured category A on a fully tested 11 × 11 grid (scratchpad `peak_probe.py`, τ = 0.15·(P90−P10), r = 1, m = 1, so four neighbours): a smooth bump 100·exp(−r²/8) plus N(0, s²): at s = 0 / 2 / 5 the true optimum reads **`isolated peak`** (P75 88–92, IQR 0–2.9, fence 88–100 below the value 100–104), at s = 10 / 20 it reads **`mixed`** (IQR 5.7 / 11.5, fence 112 / 137 above the value 108 / 117); the cell counts move from 80 stable / 40 mixed / 1 peak to 48 / 70 / 3. A planted spike (+20 to +140 over a flat field at 10 ± 2; +100 to +180 over the bump's shoulder) reads `isolated peak` at every height tried. So the rule is sound on a flat field and "every tried grid reads `mixed`" is what it does on rough surfaces: the peak fence is 3 × **the neighbourhood's own IQR**, which inflates exactly when the surface is rough, while the stable band τ is 0.15 × **the experiment's** P90−P10; the two named states live on different scales and `mixed` is the residual class. Two consequences worth a ruling: (a) a smooth symmetric optimum reads `isolated peak` at IQR ≈ 0 (the fence degenerates to P75), which is the opposite of what the label means; (b) a genuine spike on a rough surface reads `mixed`. Options: floor the fence at `max(3·IQR, k·τ)`; or print a prominence number `(t − P75)/τ` on the card beside the trichotomy, so the operator sees the magnitude whatever the label. The §7.6 thresholds are policy constants (Q6); the labels are explained with their inputs on the card, so this is not a Phase 3 blocker.

### Verdict (QA §8)

**PASS WITH FINDINGS** for R3.5's statistical pass condition.

Reasoning: the sixteen §20 cases are green with their reasons at seeds 1, 2 and 3 (51 case tests, no xfail), the four robustness categories' and the block tests are green (455 passed across the four files), the engine guard set is green (35), the design interval's 90 % coverage is confirmed by an independent simulation (0.899 mine / 0.902 the implementation's over 1,000 datasets at the nominal 0.90), a fault in the own-direction increment is caught by ten tests including the case that exists for it, and the detection floors control false detections out of sample (0/10 in every family, veto 10/10). The estimators I read (`adjusted_shares`, `intervals`, `floors` with leave-one-out max-T, `CoarseTerms`, `cramers_v`, `pair_quality`, `coverage_label`, the five availability reasons and the seven status rules) implement §7.3–7.4a as amended by the accepted decisions 15–21. The findings are a spec/test mismatch on case 5 (F1), a false premise recorded under decision 20 (F2), stale spec text and numbers (F3, F5), a status-vocabulary gap left to Phase 4 (F4), a calibration note on §7.2 (F6) and a sensitivity note on §7.6's A rule (F8). None affects a number the rule computes or a status the sixteen cases pin; F1 and F2 belong in the R3.5 note for Randall.

## 9. The product store and the scratch root

**The product store `C:\Triad\data\aegis` was in use by the product worker on 8102 during Task 13**, and no Task 13 process had its root: the scratch worker, the
benchmarks and the walk used `C:\Triad\data\temp\lab-scratch`; the Aegis tests and both identity scripts resolve their data root to the worktree's `data/aegis`
(`DATA_ROOT` is `parents[3]` of `app/products/aegis/data.py`; `AEGIS_DATA_ROOT` unset). Step 1 saw writes it did not make, UI-shaped (run documents and sidecars, a
strategy, an optimization), so the condition for Steps 2 and 3 became "no diff entry attributable to Task 13's processes" with a fresh before-manifest taken
immediately before the explore run (the executor's ruling). The R3 script (`product-store-manifest.ps1`, read only) wrote the files below into the scratch root.

| File | Taken (local) | Entries | Files | Bytes | Newest write |
|---|---|---|---|---|---|
| `product-store-after-r3.txt` (Phase 2's) | 2026-10-29 | 9,222 | 8,490 | 1,681,094,516 | 11:45:36Z, an optimization sidecar |
| `product-store-before-r35-step1.txt` | 08:49:45 | 9,238 | 8,506 | 1,681,504,521 | 14:49:42Z, `runs` |
| `product-store-before-r35.txt` (fresh, before the explore run) | 09:11:02 | 9,246 | 8,514 | 1,683,572,263 | 15:04:27.629Z, `optimizations` |
| `product-store-after-r35.txt` (after the walk, worker stopped) | 09:31:31 | 9,246 | 8,514 | 1,683,572,263 | 15:04:27.629Z, `optimizations` |

**Fresh before against after: empty.** Both files hash to SHA-256 `E654A8E8D50434FD1FE2ED6C0E55AB797DFB06C9585DF0411B4267F64037BC68`; the comparison returns 0
entries. The newest write in the store (15:04:27Z, 09:04:27 local) is about 6 minutes before the first Step 2 process (the scratch worker, about 09:10), and nothing was written
in the 21 minutes of Steps 2 and 3. **No entry is attributable to Task 13's processes.**

**Step 1's file against the fresh before** (+8 entries, +2,067,742 bytes), every entry timestamped before any Step 2 or 3 process existed and so the 8102 worker's
(UI saves and its own summary-cache refresh), listed from a read-only listing of everything modified after 14:49:00Z:

| Time (UTC) | Path under `C:\Triad\data\aegis` | What |
|---|---|---|
| 14:49:41.205, 14:49:42.581 | `runs\163ed89d-...json.gz`, `runs\b2482e57-...json.gz` (50.6 KB each) | two run documents (in Step 1's file already) |
| 14:50:12.046 to .277 | `runs\*.summary.json` for `b2482e57`, `163ed89d`, `ecfa8b9d`, `cb4f795c`, `8b817233`, `c949428f`, `e0594605`, `a1d3b260` | eight sidecars rewritten in one 0.23 s sweep, about +310 bytes each (3,589 to 3,901) |
| 14:50:12.374 to .424 | `optimizations\e882d0f4-...`, `1f6efdb1-...`, `dc4bc3db-....summary.json` | three optimization sidecars rewritten in the same sweep (about 4.0 KB each) |
| 14:59:00.679 to .682 | `strategies\untitled-strategy-1cbeca.json.gz` (1.4 KB) and `.summary.json` | a strategy saved from the UI |
| 14:59:05.895 to .897 | `runs\6c7a5e09-...json.gz` (78.1 KB) and `.summary.json` (4.0 KB) | a run saved |
| 14:59:47.400 | `optimizations\590d874c-...json.gz` (35.8 KB) and `.summary.json` (4.1 KB) | an optimization saved |
| 15:04:27.624 to .629 | `optimizations\4f9715a5-...json.gz` (1.94 MB) and `.summary.json` (4.1 KB) | an optimization saved (the last write in the store) |

Phase 2's after-manifest against Step 1's (+16 entries, +410,005 bytes) is the same kind of change: runs from 2026-10-30 and 2026-11-03 and the optimization `e882d0f4`
(created 14:46:48Z, 271 cells, done 14:47:14Z).

**The scratch root** `C:\Triad\data\temp\lab-scratch` measures **1,080,410,210 bytes** (3,687 files) after Task 13: `experiments\` 1,078,171,786 (the
`demo-synthetic*` fixtures 736,308,471), `optimizations\` 173,195, `runs\` 837,524, `strategies\` 30,532 and the eight manifest files about 1.2 MB. R3 measured
434,563,217 bytes and Task 12 about 515 MB; the growth is this session's analytics cases (the quiet, loaded, K = 4, 20-value and after-run experiments, each with its curves and reports) and the
walk's fixtures. Nothing was deleted (its deletion after the milestone is the R3 note's open question 11, still Randall's). **The scratch worker was stopped** after the walk
(`tools\start_aegis_scratch.ps1 -Stop`; no listener on 8103, the pid file removed). The product worker on 8102 was never used.

## 10. Decisions this phase made that the spec left open

**The plan's decisions** (`2026-10-29-aegis-optimization-lab-v2-phase3.md`; Randall answered 2026-10-29 "Accept all three": decisions 18 to 20 stand, decision 11 accepted, subagent-driven execution).

1. **Blocks subdivide the experiment's whole range** in Phase 3 (partitions arrive in Phase 5). A block runs on the bars from the range's start to the block's end and is scored from its start; indicators warm up on all prior history and the kernel starts flat at the block, so block 1 warms up as block 0 does. A configuration costs `bars + Σ end_b` bar evaluations (about 3.5 x bars at K = 4), priced exactly by the planner.
2. **`blocks` is an optional request field, default 0**, accepting 0 or 2 to 8; the planner's checkbox offers `SCREEN_BLOCKS = 4`. Existing clients, walk fixtures and benchmarks are unchanged.
3. **A block too short for a configuration's warm-up is an `invalid: insufficient bars` block row**; block 0 decides the configuration's status.
4. **Without blocks** the period uncertainty reads `not measured: no screening blocks` and condition 1 applies to block 0 only, so case 1 is proposable without blocks.
5. **Phase 3 computes recommended statuses and reasons**; persisting them, confirming them and staleness of persisted statuses are Phase 4. Case 9's `stale` is `compare_scope` over the evidence scope.
6. **Lab task results live in memory**, at most 32, least recently used, recomputed after a restart; `opt:` sources are keyed by `(job_id, cells_done)`.
7. **Importance always runs unfiltered** (§7.3) and says so; the fast views (Pareto, robustness, convergence) honour the filter.
8. **Exact-mode parallel is `parallel_mode`, not `mode`**, since `QueryRequest.mode` defaults to `"exact"` for the matrix.
9. **Neighbourhoods hash positions** (`pos.<k>` in layout 2, value indices for legacy and `opt:` sources); nothing is O(n²).
10. **`ConvergenceChart` sits in Trial Lab's rail, compact**; the Run Monitor (Phase 5) adopts the component.
11. **Walk 112 runs on the 10-parameter bench**; the 20-parameter version follows Phase 4. *Accepted.*
12. **The candidate card's C and D classifiers are pure functions over evidence**, tested on fixtures now and fed folds (Phase 6) and replays (Phase 5) later; in Phase 3 C is `unresolved · selection-period only` with the blocks' diagnostic and D is `no replay yet (stage 2)`.
13. **The centre tab moves into the Lab store**, so a mini view's click opens its tab.
14. **The rail's deterministic findings** combine the report statement with the importance and robustness findings the views already fetched; `summary.findings` stays unbuilt.
15. **Ordering rules the spec leaves implicit:** the availability reasons run aliasing before the product design (cases 10, 14, 15); the status precedence is decision 21.
16. **The veto shows both texts**: `structure not captured by mains, pairs and triples: deprioritization unsafe` and the warning `unexplained share high: noise or higher-order structure`, so cases 7 and 12 each find theirs.
17. **The statistical fixtures' generator constants are fixed once** in `tests/lab_stat_fixtures.py`, a comment each; the sixteen cases run at three seeds; a flip is reported at R3.5, never tuned away. No flip occurred.
18. **"Detected" uses family-wise floors (max-T), not per-share floors**: with 20 mains and 190 pairs about ten noise shares cross a per-share 95 % floor by chance, so §20 case 7 could never hold. The per-share floor stays on the panel as a tick. *Changes a spec definition; accepted.* (QA F3: the spec text is not amended.)
19. **Intervals are bootstrap distributions re-centred on the point estimate; the coarse terms are adjusted and unclamped**: plain percentile intervals of an adjusted share are biased upward by about df/n; on pure noise at d = 20 the residual's bootstrap mean was -5.5 against a point estimate of 1.00. *Changes §7.3's "90 % percentile interval"; accepted.* The QA confirmed the coverage independently (0.899 and 0.902 at the nominal 0.90).
20. **Cases 1 and 13 run on 20,000 uniform rows**, with a companion at 5,000 rows. *Changes §20's 5,000 rows; accepted.* The plan's stated product consequence ("deprioritization needs roughly 20,000 uniform trials at d ≈ 8 before it can propose anything") is **false as measured**: at 5,000 rows 3, 7 and 1 of 7 noise parameters are proposable at seeds 1 to 3 (the QA's F2; the rule working, a truly irrelevant parameter being proposable). The 20,000 rows buy test determinism, not product necessity.
21. **Status precedence:** coverage, then proposable, then period-dependent, then detected, then interaction, then three-way, then not detected. "Not ruled out" requires both a family-wise detection and an upper bound above `THETA_MIN`.

**Rulings during execution that changed a design** (`progress.md`; the reasoning in one or two sentences each):

- **P1.** The Lab cache key carries the row selection: ordinary views cache the block-0 table, the importance task loads every block under its own key, so Task 0's column-set key and Task 2's block-0 filter do not collide.
- **P2.** `LabTasks.result(key, snapshot)` returns the newest finished result for a key; Task 7's category B needs the importance axes and Task 3 defined no read accessor.
- **P3.** Screen E's element ids are `lab-families-<part>`, listed in Task 11's report, because the plan names none for walk item 112.
- **P5.** `evaluations_done` stays the spec §6.4 snapshot count (distinct `(trial_no, block)` with status ok over every block), computed from the full table before the block-0 filter.
- **P7.** Case 5 uses §20's own generator `Y = 3·x₂ + x₁·x₂ + ε` (uncentred, Δ1|2 about 0.0165) with the plan's dependent x3 draw; the plan's centred form leaves an increment below θ_min at any sigma. (QA F1 asks whether §20 case 5 should be redesigned.)
- **P8.** Case 16 asserts the reason string built from the fixture's own undefined count (1,189 at seed 1, not the plan author's 1,240); the spec pins the format, not the RNG outcome.
- **P9.** A flip at seeds 2 or 3 would be marked `xfail(strict=True, reason="R3.5 finding: ...")` in the parametrization, visible in every run, never deleted, loosened or re-seeded; none occurred.
- **P10.** The permutation floors standardize each permutation's shares by the leave-one-out null mean and SD, because in-sample standardization shrinks the extremes that set the per-permutation maximum (a z of about 5 inflates its own member's variance by about z²/P). At d = 20 pure noise this moved the false detections from 10/10 to 0/10 (t 4.38 to 5.72); at d = 8 the triple family reads 1/10. A correction to decision 18's estimator.
- **P11 (amended).** Case 1's 5,000-row companion asserts x1 detected and not proposable, no noise parameter detected, and every non-proposable noise parameter's `failing` naming condition 2 or 3; the proposable counts are printed. The original premise (nothing proposable) was a coin flip (null SD about 0.002, upper about 0.0097 against 0.01). Renamed in `dcf9894`.
- **P12.** `importance_stages` lives in `lab/importance.py`, not `analytics.py`: the rule split made `analytics -> rule` a cycle.
- **P13 (superseded by the keep-stopped mechanism).** The importance view never re-requests a task it last saw failed or cancelled for that key; `QueryRequest.rerun` is the only re-request, and the decision is made atomically under the executor's lock, since a route reading a task's status under `LOCKS.read` could deadlock with finalize-to-compact and undo a cancel. `latest` was removed.
- **P14.** While a newer snapshot computes, the importance view answers the newest `done` result, labelled `snapshot X · current Y`; a partial stage is shown only when no done result exists.
- **P15.** Task 7 reads position codes through `index.codes_for(frame, path)` and B's axes from `LabTasks.result` at the frame's snapshot, so a running experiment's B reads `importance not computed for this snapshot` until a matching done result exists.
- **P16.** §7.6 binds for C: with no blocks or folds it reads `no blocks or folds`; with blocks `unresolved · selection-period only` plus the `selection-period consistency` finding. Walk item 124 now runs on both fixtures (P-5), which supersedes P16's single-fixture form.
- **P17.** When A's coverage passes but n falls short the reason reads `untested surroundings (n 7 of 8)`, keeping §7.6's prefix.
- **P18.** `RANK_POOL = 300`: the robust ranking reads A for the 300 top rows by peak (about 2 ms each at 1M), B only for the top `RANK_B_MAX = 20`; a pool of best points alone defeats "candidates by robust rank, never by best point alone". The response states the pool and `stable: null` reads "none among the top 300 by peak".
- **P19.** `stable` names the first robust-ranked candidate that is `stable local` (or `stable region` with A unresolved), untied, and on a signed metric with a value above its break-even (`BREAK_EVEN`: net_pnl, net_return, cagr, mar, expectancy, sharpe_trade at 0, profit_factor at 1). At τ <= 0, A and B read unresolved `no spread in the metric (τ = 0)`, matching `analysis.py:533`.
- **P20.** Task 9 keeps the hand-offs in the data layer (`canRerun`, `displayShare`, `rerun?`, `k?`, a discriminated type for robustness's two shapes); `optBody` prefixes axes only, since prefixing `objectives` would 422.
- **P21.** `GET /lab/{src}/tasks/{task_id}` is a read-only status route that never requests a task: a poll of the view can queue work, so a watch that must not create work cannot use it. A small Aegis route; no Core change.
- **Cancel acts on the key** under the lock (drop the key's waiting task, set cancel on the running one): the operator cancels "this analysis", not a task id they cannot see.
- **A snapshot is its `chunk_watermark`** for the task cache, coalescing, the label and `compare_scope`: compaction bumps the generation without changing canonical rows, so recomputing and labelling `g0 cN · current g1 cN` would be false movement.
- **The pair adjustment uses k = occupied cells** (ratified): it is the between-group sum of squares' degrees of freedom and equals B_i·B_j when every cell is tested.
- **The convergence payload is cached** (snapshot, canonical filter, scope, metric) with `provisional` kept out of the cached dict, so polls do not recompute; convergence stays computed in full (median under about 2 s at 1M).
- **TRELLIS constants:** `TRELLIS_MIN_N = 30`, `TRELLIS_MAX_SIDE = 16`, `TRELLIS_PAIRS = 6` live in `lab/policy.py` and in the matrix and interactions responses; the UI reads them from the answers with no literal fallback.
- **The ask cadence:** a view asks again on mount, on a new key, at most every 30 s while the source runs, and once more when the run ends (`refreshRule.ts`), shared by the trellis pairs, the map's matrix and robustness asks, the sampled parallel and the chart; each is a cache miss on a new chunk.
- **§7.11's assumptions line** is one shared `AssumptionsLine` (static text in Phase 3, since partitions arrive in Phase 5) on every analytic panel: no task owned it.
- **The chunk-aligned matching:** the matched throughput baseline aligns by chunk position (`5edabf8`), after two identical quiet runs read the same chunks 21 % apart by time and 1.3 % by position.
- **Item 124 on two fixtures** (the bench and a 4-block exhaustive grid), P-5; **walk 112 step 10** on a running fixture with POST task views and GET task polls observed for one full ask cadence plus two ticks.
- **Lint lists:** each Lab test module added by a task is added to `tools/lint_aegis.sh` and `tools/verify.ps1`, as Phase 2 did.

## 11. Findings for R3.5

**Measurements** (none re-baselined):
1. **`opt_frame` rebuild per poll:** 1,269.5 ms p50 / 1,364.1 p95 at 99,856 cells (MAX_CELLS 100,000), in process (Task 12's record 1,308.6 / 1,465.5); the Lab polls every 2 s. The `opt:` source over HTTP is unmeasured (`not_measured` 4).
2. **`pareto_3`** p95 827.7, 840.1, 798.5, 870.8, 937.7 across the five records that carry it, against no line (the 800 ms row is for two objectives).
3. **The K = 4 plan** reads 1.245x its estimate (175.9 s planned, 219.0 s actual; Task 12 1.365x); the K = 0 run is itself 1.394x (1.436x), so the K = 4 gap is not the blocks; K4/K0 is 3.41x planned against 3.05x actual (3.66x and 3.48x). Task 2's price model stays an R3.5 judgement (Task 2: warm K = 4 costs about 4.4x against decision 1's 3.5x, from a per-evaluation fixed cost the bar-linear model omits).
4. **First cold calls:** neighbourhood 602.6 ms (analytics), 440.3 (explore), 1,182.7 (Task 12); convergence 312.7 / 306.8; filter_heatmap 355.6 and exact_slice 136.3 on the first sample. These are inside the cold-first convention (the p95 includes them) and outside the warm lines; if the 150 ms row is meant for a first click, warm the `pos.*` columns when the Lab opens.
5. **The importance poll beside a job** costs p50 158.9 / p95 258.8 ms (no line; the 100 ms row is the progress poll).
6. **The fine stage at d = 20** with 20 values is unmeasured beside a job (Task 4: 24 to 41 s alone against 30 s); the 10-parameter 20-value row is 6.47 s.
7. **The peak working set (a)** is a process-lifetime high-water mark: 619.4 MB before the first view (start-up and setup, not the job cases), 909.0 after the views, 1,147.1 after the candidate rows, so **the Task 8 "460 MB peak" row has no like-for-like figure yet**. The remedy for Randall is a fresh worker per view in the benchmark.
8. **The Lab cache (b)** went from 9 entries / 367.6 MB after the views to 6 entries / 372.0 MB after the candidate rows: **LRU eviction at the 400 MiB bound** (`cache.py`'s insert loop; no replacement path lowers the count and `evict(prefix)` has no caller), section 6.
9. **`pareto_3`'s p95 of 937.7 ms (c)** is the highest of the five records that carry it (828, 840, 799, 871, 938), recorded against no line.
10. **`fine_stage_s` is again a bound** in the R3.5 record (6.273 s, stage 2's), while the 20-value row is measured (6.474 s). **The Pareto p95** of every analytics record: 268 / 275 / 913 (Task 12), 346 / 245 / 266 (round 1), 267 (R3.5); one of nine over 800.
11. **Not measured by Task 13:** the convergence view beside a running job; `memory_probe.py` on a blocked plan; Track B at R3.5 (section 6, section 5). Task 0's Track B findings stand: case A 142.1 trials per s against 150 (engine), the query p95 ratio 7.66 against 2.5 under load (contention), case A host growth unsettled (11.5 against 122.0 MB from different starting working sets).
12. **The §9.4 budgets** (180 s task, 30 s fine stage) are met by a factor of 15 to 17 and 4 to 5 on a fixture that exercises neither d = 20 nor blocks; unmeasured at their stated scale until Phase 4's 20-parameter fixture (P-3).

**Plan amendments** (carried to Randall, not made):
- **Task 11's P1.** The plan's "<= 16 x 16" trellis assumed a binned matrix the server does not offer: the matrix view returns the whole lattice, so past 16 values the UI merges neighbours (n sums, a range filter, the mean pooled, the merged median withheld). **P2.** The trellis floor and side are not among the §7 constants; `TRELLIS_*` now live in `lab/policy.py` and the responses and should be added to §7.
- **Task 12's P-1.** The brief's throughput formula is ill-posed for a short window; the chunk-aligned matched figure is the one R3.5 reads; a longer task or a start after N steady chunks, and a second quiet run. **P-2.** §9.6a's candidate row is now measured (79.1 ms p95 at the 150 ms line); item 111's spike: `isolated peak` is never on screen on real data, so either a planted-outlier exhaustive grid through `lab_fixture` or a reworded item title and spec scenario 111 (Randall's call). **P-3.** §9.4's budgets are unmeasured at their stated scale (d = 20 with blocks, K = 4 by default, up to 8; the Task 12 review's "K = 20" was Q6's shortlist size, not a block count). **P-4.** Task 13 carries the dropped rows: this note does. **P-5.** Item 124 asserts C on both fixtures, superseding P16's single-fixture form.
- **§5.10's route table lists neither task route:** `GET /lab/{src}/tasks/{task_id}` (P21) and `POST /lab/{src}/tasks/{task_id}/cancel` are additions.
- **§7.11's owner:** no task owned the assumptions line; it is the shared `AssumptionsLine`, static in Phase 3 and server-side when Phase 5 adds partitions.
- **F6's calibration note (QA):** the §7.2 `confounded?` threshold has no finite-sample calibration (text under Statistics (QA), F6).
- **Three-objective Pareto** has no plan line (p95 798 to 938 ms here), and **a candidate's card on a blocked experiment** has no plan line and is unmeasured (`trial_blocks` is read only when K > 0).

**Residuals:**
- **Step 10's N-6.** Screen E's 30 s ask timers cannot be told from Trial Lab's own asks for the same views, the 9-cell running fixture keeps its task active for 1 to 2 s, and the walk types the UI's 30 s cadence. Two remedies: a heavier running surface (a longer window, several chunks) or a request signature only Screen E carries (its trellis matrices, its `parallel_mode`, its neighbourhood `trial`).
- **The Robustness screenshot's rail fold:** the open card sits below the rail's fold, which the item 106 sweep covers and the picture does not.
- **`isolated peak` is never on screen on real data:** the bench's peaks all read `untested surroundings`, smooth grids read `mixed`; it is unit-tested only (`test_lab_robustness`). See F8.
- **An open Importance tab queues an importance task per chunk beside a job**, on Screen B and on Screen E (Tasks 10 and 11); the status-route watch no longer chains tasks after a tab is left.
- **Accepted drill-check residuals (Task 11):** a click's pick is up to 30 s old until the next pair refresh; a compaction between two settled reads; a wrapped parallel note still moves the plot by its extra lines; the held drill total sits beside a new n uncompared until the new read lands.
- Smaller Task 8 minors parked: a new chunk is a cache miss, so a running 1M d = 20 experiment pays 1.3 to 1.8 s and the 460 MB peak about once per chunk (unmeasured beside a job).

**Environment:**
- The scratch worker's `GET /aegis/api/status` answers 500 without Core's postgres/neo4j variables (a console error, never a page error; the walk records page errors only and read 0).
- The two worktree-only `test_architecture.py` failures (section 2); the PowerShell `bash` is WSL's, so the lint is run through Git Bash.
- The product store was in use by the 8102 worker (section 9). The benchmarks need `-Workers 10`; the walk needs it only for the bench fixture build. The machine was quiet for Steps 2 and 3 (3.9 to 4.1 GB free at each start; Task 12's runs started at 2.2 to 2.9 GB).

**Labelling:** the KPI strip's BEST (the report's best cell, $7,240) sits beside the Robustness tab's top peak ($37,691): two measures under one word (a Phase 2 labelling question for Randall).

**QA leftovers and items parked for the final whole-branch review** (no whole-branch review record exists in the ledger at this head):
`experiment_unique` recomputes `scope_counts` without the index once per snapshot (`sources.py:429-441`); a task pinning a deleted experiment's snapshot (a queued pin is released when the task runs or the executor stops); the repeating slow deterministic failure beside a running job; `analysis.analyse`'s "fragile peak" on a flat surface against the card's unresolved; `rankings_basis` gate and the tie wording; Task 8's minors (`_bins` NaN on adjacent subnormals, `_with_bests` at a cap <= 3, `_basis` over-claiming "spans more", the `opt:` key missing per new cell); Task 9's `results.ts` (1,553 lines) splitting at the whole-branch review or Phase 4; Task 10's pointer-only Pareto points; stale comments `workflow.ts:26`; and the pre-existing warnings (section 2).

**Statistics (QA)**, verbatim from `task-13-qa.md` §6:

- **F1 (Medium, spec ↔ test; case 5).** §20 case 5 is not testable as written: under P(x₁ = v) ∝ v the §7.4 pair balance TVD is 0.222 at B = 8 (measured 0.223–0.231) and tends to 0.25 from below, and the §7.2 per-square TVD is ≈ 0 because the skew is global. The fixture makes the case hold by adding x₃ = x₁ ± 1, which aliases (x₁, x₃) at V = 0.546 and makes the experiment `aliased inputs`: x₁'s `failing` is `aliased inputs`, not condition 2, and the `confounded?` squares are confounded by x₃. The test still checks the intended quantity (Δ₁\|₂ upper = 0.016–0.020 > θ_min; condition 2 listed), and Ruling P7 records the choice. For Randall: amend §20 case 5 to name the dependent draw and drop "TVD > 0.25" (or state it as the `confounded?` flag by x₃), or redesign the case so the rule stays available and `failing` names condition 2.
- **F2 (Medium, plan record; decision 20 / Ruling P11).** Decision 20 was accepted on the premise that "at 5,000 rows the rule honestly proposes nothing" and that "real experiments need roughly 20,000 uniform trials before deprioritization can propose anything". The companion test's own printout shows 3 / 7 / 1 of 7 noise parameters proposable at 5,000 rows (seeds 1–3), and Ruling P11 (amended) loosened the assertion to accept either state (test name still says `proposes_nothing_honestly`). The code is right (a truly irrelevant parameter being proposable is the rule working; the 20,000 rows buy test determinism, not product necessity). The R3.5 note should state the actual behaviour at 5,000 rows and correct decision 20's product consequence, and the test should be renamed.
- **F3 (Low, spec text stale).** The spec at `7a63a52` still defines the design interval as a "90 % percentile interval" and the floor as "the 95th percentile of each share"; the implementation (decisions 18–19, accepted) uses re-centred intervals, family-wise max-T floors with leave-one-out standardization (Ruling P10) and unclamped coarse terms. None of "max-T", "family-wise", "re-centred", "unclamped" appears in `docs/AEGIS_OPTIMIZATION_LAB_V2_IMPLEMENTATION_PLAN.md`. §20 case 7 holds only under the family-wise floor. Amend §7.3–7.4 and §20.
- **F4 (Low, spec ↔ statuses).** §8.4 names `aliased` and `unresolved pair / triple` as evidence for `Investigate`; decision 21's precedence has no such rule, so cases 4 and 10 read `Active · detected` with the aliased flag and `failing = aliased inputs`, and an unresolved pair surfaces only in `failing`. The tests pin the flag and the availability reason, not a status. Phase 4 (persisted statuses) should decide which §8.4 reading stands.
- **F5 (Low, spec numbers).** §20 case 15's "Cramér's V ≈ 0.2" cannot follow from 2 % skipped cells (measured 0.057–0.063; the test rightly asserts only `not aliased`). §20 case 10's "V > 0.3" is a property of the lattice size, not of the constraint: 0.310–0.317 at B = 8, 0.27 at B = 10 per the fixture's comment. Amend both numbers; keep the fixture.
- **F6 (Low, §7.2 calibration; Phase 2 code that case 5 leans on).** The `confounded?` rule (`query.py:558–601`; TVD > 0.25 with n ≥ 8) has no finite-sample calibration: with no dependence anywhere it flagged 1 of 64 (x₁, x₂) squares at ≈ 78 rows per square in 4 of 6 probes (d = 8 and d = 20). Near n = AGG_MIN_N = 8 the sampling TVD of an 8-valued parameter alone exceeds 0.25 routinely. Suggest a permutation-calibrated or n-scaled threshold when §7.2 is next touched.
- **F7 (Info, measurement Ruling P10 asked for).** Out of sample (pure noise, d = 20, 5,000 rows, seeds 11–20, none used by the suite): fine mains over their family floor 0/10 seeds, fine increments 0/10, coarse own-direction triple increments 0/10 (3,420 members, t = 5.39–6.32 from P = 50 maxima), every status `Active · not detected` 10/10, veto raised 10/10 with R = 0.90–1.10 and lower bounds 0.44–0.71. The coarse t from 50 maxima is noisy but conservative. No action.
- **F8 (Low, §7.6 A rule).** Q4 above: the peak fence on the neighbourhood's own IQR makes `isolated peak` unreachable on rough surfaces and mislabels a smooth symmetric optimum at IQR ≈ 0. For Randall with Q4's options.

## 12. Open questions for Randall

1. **The pooled mean on merged trellis squares** (Task 11's P1; QA Q1). Accept the pooled mean for merged squares in Phase 3, or put a server-side binned matrix with exact medians on Phase 4's list? The QA supports the binned matrix for Phase 4 and, meanwhile, a per-pair line when the statistic switches from median to mean (past 16 values).
2. **Pin brush.** The plan defines no behaviour for the §5.5 row and it is not built: define what it pins, or strike the row.
3. **12 importance-ordered axes** on the parallel coordinates (10 axes are drawn now): with Phase 4's 20-parameter work, or declined.
4. **R2's stepper** (still open since R2): the workstation top bar against the design's stepper.
5. **Item 111's spike** (P-2): a planted-outlier exhaustive grid through `lab_fixture` so the browser shows `isolated peak`, or reword the item title and spec scenario 111.
6. **Three-objective Pareto:** p95 798 to 938 ms in five records, no line (the 800 ms row is for two objectives). Give it a line (which?), or keep it recorded.
7. **A candidate's card on a blocked experiment:** unmeasured, no plan line. Give it one with the blocked fixture, or accept it unmeasured.
8. **The throughput formula** (P-1): amend the plan to name the chunk-aligned matched figure (6.8 to 10.4 %, 6.8 % at R3.5), a longer task or a start after N steady chunks, and a second quiet run.
9. **Step 10's remedy** (N-6): a heavier running surface, or a request signature only Screen E carries; neither is built.
10. **`RANK_POOL = 300`** (P18): keep it, or take the QA's suggestion (Q3: the pool as the top 1 % capped at 300 with a floor of 20; B for every A-unresolved pool row when the request's axes are <= 6 and n is small, since B is cheap there).
11. **The peak working-set row:** accept a fresh worker per view in the benchmark so the Task 8 "460 MB peak" row has a like-for-like figure, or retire the row (finding 7).
12. **§9.4's budgets at d = 20 with blocks:** confirm that Phase 4's 20-parameter fixture owns the measurement and that the 180 s and 30 s lines stand (spec §19: "B_c and P reduced first if missed").
13. **Task 2's price model:** the K = 4 plan is 1.245x low (K = 0 1.394x low). Fix the model, or accept it as a documented error.
14. **QA F1, §20 case 5:** amend §20 case 5 to name the dependent draw and drop "TVD > 0.25" (or state it as the `confounded?` flag by x3), or redesign the case so the rule stays available and `failing` names condition 2.
15. **QA F2, decision 20's product consequence:** record the corrected statement (at 5,000 rows 3 / 7 / 1 of 7 noise parameters are proposable; 20,000 rows buy test determinism, not product necessity). The test is renamed in `dcf9894`.
16. **QA F3, the spec text:** amend §7.3 to §7.4 and §20 to say re-centred intervals, family-wise max-T floors with leave-one-out standardization (P10) and unclamped coarse terms.
17. **QA F4, §8.4's `Investigate`** on an aliased or unresolved pair: not in decision 21's precedence; Phase 4 (persisted statuses) decides which reading stands.
18. **QA F5, §20 cases 10 and 15's V numbers:** amend "V ≈ 0.2" (measured 0.057 to 0.063) and "V > 0.3" (a lattice-size artefact: 0.31 at B = 8, 0.27 at B = 10); keep the fixture.
19. **QA F8 and Q4, §7.6's peak fence:** floor the fence at `max(3·IQR, k·τ)`, or print a prominence number `(t - P75)/τ` on the card beside the trichotomy.
20. **QA Q2, `valid_basis`:** read validity tables in Phase 4 and print a sentence instead of the bare token `frame`.
21. **The KPI BEST label** (the report's best cell) against the Robustness tab's top peak (the best trial): rename one, or keep both. (The QA's Q1 and Q3 are questions 1 and 10.)
22. **`opt_frame` caching** (1.27 s per poll at MAX_CELLS) and whether `opt:` sources need a cheaper importance poll: a design call for Phase 4.

## 13. Hand-off

**R3.5's approval unlocks Phase 4**: persisted variable statuses, proposals, apply, focus and re-screen children, and budgets (§8); the 20-parameter fixture and `MAX_PARAMETERS = 20`
(which gives `not_measured` rows 1, 2 and 6, and §9.4's budgets at their stated scale, their measurement; row 5 is Task 2's price model); the server-side binned matrix if question 1 says so; and the §8.4 reading of question 17.
Phases 5 and 6 (partitions, stage-2 replays, folds, the Run Monitor) follow.

**What stays closed.** Exchange stays CLOSED and live trading disabled until separately and explicitly authorized; Aegis remains human-directed; Triad stays suspended (the
autonomous improvement game does not run; `DailySchedule` `c99fa831`, 2026-10-09, remains disabled, which walk item 118 asserted on this branch: `enabled=False`). Phase 3 changed
no file under `app/trading_core`, `app/platform_host` or `app/products/triad` (walk item 118: none since `1882c81` but Mission 14's four fix-pass files merged from `main`)
and added two Aegis routes (P21's status route and the task cancel route) without a Core change.

**Nothing is pushed or merged** until Randall says so. The branch is 92 commits ahead of `main` at `dcf9894`; this note's commit makes 93. One seat remains before the
merge decision: the whole-branch review (Fable 5.1, as the ledger's models table assigns it) over the range from `8c522bb` to this note, with the items parked for it in
section 11; its record and any fix round it opens are committed on this branch after this note, and the R3.5 decision is Randall's on both together.
