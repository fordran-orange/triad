# Day 7 C correction 2 — independent QA

**CHANGES_REQUIRED** at exact revision `58546ee620c62e6f0592a6a4c35c52908fd89a7b`. Separate reviewer `/root/day6_qa_a`, 2026-09-19. Previous reports remain intact.

**P2: known terminal completion time is omitted for cancelled/rejected cycles.** Their status now reports correctly, but `CycleHistory.capture` uses WorkItem.completed_at as a finished_at fallback only when final_status is BLOCKED. Two real host-transition probes show CANCELLED and REJECTED records with a canonical UTC completed_at nevertheless returning finished_at=null. Extend the fallback to appropriate terminal outcomes; retain null when historical source time is genuinely absent. This is the remaining part of preserving known terminal times identified in the prior correction report.

The test assertion was extended after source review to compare against the actual persisted WorkItem completion time, without inventing dates. All previous assertions pass, including exact gate result, scheduled flag, creation time, original failure preservation, legacy proposal selection, usage links, billing isolation and read-only API/recovery behavior.

Command: `.venv\Scripts\python.exe logs/day7-c-final-qa-run.py day7-c-final-independent tests/test_cycle_history.py tests/test_day7_cycle_qa.py`.

Result: **9 passed, 2 failed, 2 existing TestClient warnings in 31.90s**, exit 1. Both failures are the terminal timestamp assertion. Ruff PASS. Evidence: `logs/day7-c-final-independent.log` / `.exit`, `logs/day7-c-final-qa-lint.log` / `.exit`.

Fresh archive `logs/day7-c-final-exact-58546ee.zip` and extracted snapshot were tested with snapshot PYTHONPATH/TRADING_HOME, TRIAD_INTEGRATION=1 and provider monitoring off. All app bytes match archive; independent test bytes are separately hashed in `DAY7_C_CORRECTION2_QA_HASHES.json`. Disposable databases/namespaced graph only; no production changes, restart, inference or implementation edits. D/E QA was notified when the DB run finished. Live browser acceptance remains pending. Fresh correction QA is required.
