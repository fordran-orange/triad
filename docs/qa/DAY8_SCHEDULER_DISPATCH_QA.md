# Day 8 scheduled failure evidence — independent correction QA

**PASS**, bounded correction at `67e4ee64b09d4444f989c0bfd16b92f20abcff3e`. Reviewer `/root/day6_qa_a`, separate from the builder.

The combined foundation audit identified an evidence gap after the previously accepted scheduler: a due slot stopped by current governance could raise before leaving a CycleRecord, and a runner failure before creation used the legacy ROTATION type. Earlier acceptance reports remain intact; this report accepts the explicit correction, not the earlier gap.

A fresh exact Git archive ran `tests/test_daily_scheduler.py` and `tests/test_day8_scheduler_qa.py` with TRIAD_INTEGRATION=1 and CORE_PROVIDER_MONITOR=0. Result: **15 passed, 2 existing deprecation warnings in 61.07 seconds**, exit 0. Log: `logs/day8-scheduler-dispatch-independent.log`. Ruff passes for both changed implementation files and both tests.

The actual disposable database tests verify global kill, global pause, changed epoch after resume, and product pause produce a BLOCKED, finished, scheduled DAILY_PRODUCT record with the original configuration epoch and a blocked parent WorkItem. No runner executes; precisely one durable date claim is retained, and a second tick returns ALREADY_CLAIMED. Revoked manual acceptance similarly records failure without execution. A concurrent pre-creation runner failure leaves the same honest daily identity and one claim. Existing post-claim revocation races, disabled configuration, trusted-runner requirement, valid/replaced configuration, DST gap/fold handling and date idempotency remain passing.

`CycleHistory.blocked` retains legacy defaults for other callers; only the daily scheduler supplies DAILY_PRODUCT and the original epoch. Evidence-only parent creation and state transitions do not grant execution authority during a stop. No provider inference, production mutation, schedule activation or browser execution occurred. The explicit stopped-date claim is intentional failure accounting, not permission to execute.

The prior independent and builder test bytes are preserved in `logs/day8-scheduler-qa-pre-dispatch.py` and `logs/day8-root-scheduler-test-pre-dispatch.py`. Expectations now reflect the requested retained blocked record; execution denial and no-retry assertions are stronger. Full Day 8 acceptance and the real manual cycle remain separate gates.
