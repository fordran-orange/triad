# Mission 1 — Quiet Green Baseline (2026-10-08/09)

Follow-up to Mission 0 (`CORE_STATE_AUDIT.md`, audited at `9b61ed2`). Scope: restore a quiet,
verifiable, backed-up Core baseline before any Aegis work. No redesign, no gate relaxation,
no product code, no schema change. Operator decisions were taken in chat on 2026-10-08
(America/Chicago) and are recorded here so the repository no longer disagrees with the
live state.

## Operator decisions

| Topic | Decision | Effect |
|---|---|---|
| Codex re-verification loop (`provider-recovery-codex_cli` BLOCKED, retry every 30 min) | **Leave the loop running.** No change to the CODEX agent or `CORE_PROVIDER_MONITOR`. | The ~33-minute failing "Day 5A explicit provider verification" work items continue until the operator decides otherwise. |
| Scheduled daily autonomy (`DailySchedule.enabled=true` since 2026-10-01, contrary to `AGENTS.md:18`) | **Disable the schedule record.** | A new `DailySchedule` record `c99fa831-0c46-4908-b840-4cbb2d0992b5` with `enabled=false` was appended at 2026-10-09T03:31:33Z through `Daily.configure` (the same code path as `POST /triad/api/daily-schedule`), host-side because the Triad worker was down. `AGENTS.md:18` is now consistent with the database. Re-enabling requires the operator route and a completed manual REAL cycle, as before. |
| 207 unpushed commits on `main` | **Push `main` and the unmerged local branches** (no force-push). | See "Push" below. |

## Changes (fixtures, tooling, no production behaviour change)

| File | Change | Why |
|---|---|---|
| `tests/test_application_plan.py` → `tests/test_application_plan_validator.py` | renamed (git mv, content unchanged) | Shared basename with `tests/products/triad/test_application_plan.py` interrupted default `pytest` collection ("import file mismatch"), so the 11 Core governance tests in this file never ran. The product-owned copy keeps its name because Triad journal evidence references it by path. |
| `tests/test_proposal_recovery.py` | `cycle()` helper gives the bare `SequentialCycle` an `s` stub with `rows(kind, mission) -> []`; the REJECT/REQUEST_CHANGES cases now expect two attempts and the "made no progress" refusal | `SequentialCycle.propose()` began consulting prior reviews/proposals via `self.s.rows` on 2026-10-03/04, and `f568122` (2026-10-03) added the rule that an identical resubmission is refused after attempt 2; the 09-30 fixture predates both and expected three attempts. 5 tests. |
| `tests/test_day8_readiness_qa.py` | records stub now exposes `store.connect()` and a `list(kind, *, shared, matching, conn)` that filters like `Records.list` | `Quality.require_pass` gained a transaction and a `matching=` filter on 2026-10-01; the 09-19 stub swallowed the resulting `TypeError` into `PARTIALLY_READY`. 3 tests. |
| `tests/test_day8_daily_ui_qa.py` | daily service stub gains `host.store` with a silent `connect()` | `daily_api.configure` now calls `notify(service.host.store)` (2026-10-02/03); the stub lacked `host`, producing a 500. 1 test. |
| `tools/ensure_triad_worker.py` | `occupied(port=8101, timeout=10)` (was a fixed 2 s probe of 8101) | On this host a closed loopback port is refused only after ~2.04 s, so the 2 s probe raised `TimeoutError` and the supervisor aborted before relaunching the worker: 1,112 consecutive `NEEDS_ATTENTION` passes from 2026-10-05 06:52Z to 2026-10-09 03:27Z (the Mission 0 audit counted 1,069 at ~2026-10-08 23:50Z; the loop ran a further ~3.6 h before the fix landed). The commit message of cc20922 carries the stale 1,069 figure. Semantics unchanged: timeouts remain "uncertainty", only `ConnectionRefusedError` means free. |
| `tests/test_triad_worker_supervisor.py` | two real-socket tests: closed ephemeral port → `False`; listening ephemeral port → `True` | Written first and watched fail (`TypeError`, then `TimeoutError` with the old 2 s value); pass with the fix. Existing tests still monkeypatch `occupied` and are unchanged. |
| `tools/health_check.py` | import `trading_core.settings`; assert hypertable `core.candles_1m` (was `triad.candles_1m`) | The Core extraction moved the hypertable; the script asserted a schema that no longer holds it and imported the legacy shim package. |

Line endings: the six edited files were normalised back to LF (`.gitattributes` requires it).

## Runtime evidence

- Supervisor log: last `NEEDS_ATTENTION TimeoutError` at 2026-10-09T03:27:10Z; first `RECOVERED` at 03:32:10Z, the first pass after the probe fix landed on disk.
- `GET http://127.0.0.1:8101/health/live` → `{"status":"ok","product":"triad","loaded_revision":"9b61ed2…"}`; `GET /triad/product-api/health` via Core → 200.
- `GET /triad/api/daily-schedule` via Core → `enabled: false`, `id: c99fa831-…`, `next_cycle: null`.
- `tools/health_check.py` → exit 0 (postgres, timescaledb 2.25.2, hypertable, read/write, neo4j constraints, ollama qwen3:4b all passed). Before the fix: exit 1 (`postgres_stack` AssertionError).
- Probe proof on a closed ephemeral port: `occupied(port, timeout=2)` → `TimeoutError` after 2.01 s; `occupied(port, timeout=10)` → `False` after 2.03 s.
- Codex loop deliberately untouched: `provider-recovery-codex_cli` still BLOCKED with a 30-minute `retry_at`.

## Verification

- Default `pytest` (no flags, `testpaths=["tests"]`): **964 passed, 596 skipped, 0 failed, 0 errors, exit 0** in 136.5 s (before Mission 1: interrupted at collection; with `--continue-on-collection-errors`: 941 passed, 9 failed, 597 skipped, 1 error).
- `ruff check` on the seven touched files: clean. `ruff format --check`: 5 of 7 clean; `tools/ensure_triad_worker.py` (subprocess.run argument layout) and the renamed `tests/test_application_plan_validator.py` (content-identical rename) carry pre-existing formatting that `ruff format` would rewrite. Deliberately not reformatted so the diff stays limited to the fix.
- Integration tier (`TRIAD_INTEGRATION=1`): not run in this mission (it creates disposable databases; the operator did not ask for it). Remains opt-in.

## Housekeeping

- The uncommitted change found in `data/temp/reconcile-stabilization-20260929` (`app/products/triad/sequential_correction_plan.py`, +23 lines, "baseline_approved_file_snapshot") was committed verbatim to a new branch `wip/correction-plan-baseline-snapshot-20261004` (`bc15866`, parent `28eb45a`) and the worktree returned to `codex/provider-object-schema-completeness`, now clean. Not reviewed or merged.
- Stale PID files under `logs/` were left in place: `start_product.ps1` overwrites them on launch and nothing reads them.
- The 14 unmerged `codex/triad/*` candidate branches and 3 diverged `codex/*` branches are listed in `CORE_STATE_AUDIT.md` §2.3 for operator disposition; none were deleted.

## Push

Recorded after the push step completes.

## Independent QA

- Reviewed revision: `cc20922e7e5260e45b90a6142673a2616b53b73d` (parent `9b61ed2`), tree clean before and after.
- Reviewer: separate QA agent (not the builder), read-only plus test execution, 2026-10-09 ~03:40–04:05Z.
- Verdict: **PASS_WITH_OBSERVATIONS**.
- Evidence it produced: bare `pytest` → 964 passed, 596 skipped, 0 failed, exit 0 (131 s); collision reproduced from parent-revision copies in a scratch dir (`Interrupted: 1 error during collection`); each pre-change fixture re-run against current code failed for exactly the documented reason (`500 == 200`, `'PARTIALLY_READY' == 'READY'` ×3, `no attribute 's'` ×3); rename byte-identical (`git diff 9b61ed2:… cc20922:…` empty); `ruff check` clean; `health_check.py` exit 0; probe timings reproduced (2.01 s TimeoutError at 2 s, 2.03 s False at 10 s); `app/` untouched; worker HEALTHY; schedule `enabled: false`.
- Findings (none blocking): (1) stale 1,069 count — corrected above to 1,112; (2) push requires integrating remote-only `e9dc503` first (done below, no force); (3) format-check wording — corrected above; (4) theoretical worst-case `ensure()` ≈97 s against the supervisor's 100 s budget, raised ≤8 s by the longer probe, realistic ≈85 s here; (5) the closed-port test depends on the host answering loopback SYNs within 10 s; (6) the live worker reports `loaded_revision 9b61ed2` because it was relaunched 7 minutes before the commit and `app/` is byte-identical; (7) the readiness stub mirrors containment for scalar keys only, same as before.
