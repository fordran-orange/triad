# Day 7 B2 correction — independent QA

**PASS** for bounded B2 correction at exact implementation revision `27cda299418b7145757cf5c262a7e0f360ef7d70`. Reviewer `/root/day6_qa_a`, separate from builder `/root`, 2026-09-19. The original `DAY7_B2_QA.md` CHANGES_REQUIRED findings remain preserved. No implementation files or production data were modified by this review.

## Findings resolved

- Codex `fs/getMetadata` and `fs/readDirectory` now consume the same run-wide tool counter as process and file-read operations. Independent method probes pass. A new disposable integration test shares one ResourceSession between ToolGateway and CodexExecutor: the initial file read consumes the first call and records progress, metadata consumes the second and receives one extension, and directory listing consumes the third and is denied because the evidence has already justified that resource extension. Allocation remains two; canonical decisions are ALLOW then DENY.
- ToolGateway decodes UTF-8 before appending read evidence or recording authorized progress. The original invalid-UTF8 adversarial probe now raises without creating ResourceProgress. Successful bounded reads still support valid extensions.

The change does not alter authorization, file scope, privacy checks, paid-cost approval, specialist quota review or kill enforcement. No new required corrections were found.

## Exact-source provenance

Tests ran in a fresh `git archive 27cda29` extraction at `logs/day7-b2-qa-exact-27cda29`, using `logs/day7-b2-correction-qa-run.py`. The runner sets TRADING_HOME and PYTHONPATH to that snapshot, TRIAD_INTEGRATION=1 and provider monitoring off. Credentials are forwarded through the child environment without printing or persisting their values. Database and graph fixtures are disposable and namespaced. No live provider inference was used. All archived app bytes were checked against the tested snapshot; concurrent B3 working-tree modifications are excluded.

Only the independent QA test file was augmented outside the archived commit, then copied into the snapshot. Exact executed test, archive, implementation and evidence hashes appear in `DAY7_B2_CORRECTION_HASHES.json`.

## Commands and results

Common command prefix: `.venv\Scripts\python.exe logs/day7-b2-correction-qa-run.py <log-label>`; the runner invokes the same Python executable with `-m pytest <targets> -q` in the exact snapshot.

1. Targets `tests/test_resource_runtime.py tests/test_native_agents.py tests/test_codex_executor.py tests/test_day7_b2_qa.py`: **65 passed, 1 failed in 58.69s**. All three original failure regressions and the new shared-counter integration passed. The one-second real-time test reached required=3 after using its first extension and correctly denied a second grant without fresh progress. This overly tight probe allowed database/host overhead to consume its second second. Log: `logs/day7-b2-correction-independent-tests.log`, exit 1, preserved.
2. Adjusted only the independent real-time test to a three-second initial allocation and a real 3.3-second adapter delay. Assertions still require elapsed time beyond the initial allocation, exactly one adapter invocation, no cancellation, a canonical ALLOW time decision, and unchanged persisted initial budget. Target `tests/test_day7_b2_qa.py -k elapsed_time`: **1 passed, 8 deselected in 9.01s**. Log: `logs/day7-b2-correction-continuation.log`, exit 0.
3. Repeated the four-file suite with that final test: **65 passed, 1 failed in 149.37s**. All nine independent adversarial cases passed. The sole failure was existing offline-tool Docker cleanup (`docker rm --force`, isolation `_docker` bounded operation), during an observed host slowdown that also delayed simple read-only shell commands. This test passed in run 1. Log: `logs/day7-b2-correction-final.log`, exit 1, preserved; this is not represented as an all-green suite run.
4. Repeated only `tests/test_resource_runtime.py::test_offline_tools_extend_then_reject_repeated_reads` and `tests/test_day3_integration.py::test_kill_switch_cancels_inflight_and_blocks_new_requests_merges_and_legacy`: **2 passed in 27.67s**, exit 0. Log: `logs/day7-b2-correction-docker-kill.log`. This resolves the transient Docker failure and freshly verifies cancellation, late output rejection, new-request denial and merge/legacy kill enforcement.
5. Ruff check of final independent tests and the two corrected snapshot implementation files: **PASS**, `logs/day7-b2-correction-final-lint.log`, exit 0.

All pytest runs emitted the same two existing TestClient dependency deprecations. Every bounded test has passing evidence on the final implementation; intermittent failures and their reruns are retained explicitly. No further source correction was necessary.

## Acceptance boundary

PASS covers the two corrected B2 enforcement defects and affected runtime/native regression boundaries. Larger defaults, HTTP generation handling, B3, live subscription inference, whole Phase 2 and whole Day 7 remain outside this verdict. This review does not authorize production changes or scheduled autonomy.
