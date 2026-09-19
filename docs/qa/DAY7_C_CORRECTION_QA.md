# Day 7 C correction — independent QA

**CHANGES_REQUIRED** at exact revision `08865f43358cdd1244d6dd72693f736c96129cd3`. Independent reviewer `/root/day6_qa_a`, builder `/root`, 2026-09-19. Original `DAY7_C_QA.md` findings and evidence are preserved.

## Remaining findings

1. **P2 — recapture still changes known lifecycle and gate facts.** The earlier BLOCKED status/code/time assertions now pass. However a blocked record with scheduled=true and an explicit gate result `{status: BLOCKED, failed_provider: CLAUDE, reason: Verification expired}` becomes scheduled=null, receives the later anchor WorkItem creation timestamp, and substitutes a generic historical FAILED gate object. Preserve the existing canonical creation time, scheduling fact and actual gate result when no new source supersedes them; do not synthesize historical details over known live facts. The expanded original recapture test demonstrates all three differences in one assertion. Its original source record remains immutable, but the selected latest snapshot loses required provenance.
2. **P2 — other terminal work outcomes remain incorrectly active.** Corrected status inference recognizes FAILED/BLOCKED but ignores CANCELLED and REJECTED. Two independent probes transition genuine WorkItems through valid host lifecycle paths and capture their ProductCycle; both rollups report IN_PROGRESS. The rejection case additionally includes ProductQA decision FAIL. Include terminal cancellation/rejection in cycle reporting, preserving their reasons and known times without marking genuinely active correction work complete or successful. No merge evidence exists in these probes.

## Corrections independently confirmed

The original failed-inspection status probe passes; blocked status/code/blocked_at survive recapture; early Development.run failure retains PRODUCT_BUILD/REAL; and Runtime-style Usage retains its SQL WorkItem relationship. Product billing isolation still passes. A newly added legacy schema test verifies unselected Proposal evidence is retained without fabricating selection, then creates the actual Change-to-proposal link and verifies correct selection plus stable repeated capture. Existing build/QA/merge and recovery/read-only tests continue passing.

## Exact evidence and command

Fresh git archive `logs/day7-c-correction-exact-08865f4.zip` was extracted to `logs/day7-c-correction-exact-08865f4`. Tests run there through `logs/day7-c-correction-qa-run.py`, using snapshot app/config, TRIAD_INTEGRATION=1, snapshot TRADING_HOME/PYTHONPATH, and provider monitoring disabled. Credentials pass only in the child environment. All app bytes match the committed archive. The independent regression file was expanded and separately copied/hashed. Concurrent F/B3 or other edits are excluded.

Command: `.venv\Scripts\python.exe logs/day7-c-correction-qa-run.py day7-c-correction-independent tests/test_cycle_history.py tests/test_day7_cycle_qa.py`.

Result: **8 passed, 3 failed, 2 existing TestClient dependency warnings in 29.01s**, exit 1. The three failures are the expanded gate preservation test and two terminal-state parametrizations. Logs: `logs/day7-c-correction-independent.log` / `.exit`. Ruff check of the final independent test file: PASS (`logs/day7-c-correction-qa-lint.log` / `.exit`). Exact archive, implementation, test and evidence hashes are in `DAY7_C_CORRECTION_QA_HASHES.json`.

The run waited for B3 database QA to finish; D/E QA was notified after completion. All data mutations were confined to disposable test databases and their namespaced graph evidence. No implementation edits, production backfill, restart or live inference were performed. Browser/live UI acceptance remains deferred until the correction gate passes. Further correction requires fresh independent QA.
