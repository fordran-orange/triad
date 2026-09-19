# Day 8 daily workflow independent QA — initial revision

Verdict: **CHANGES REQUIRED**.

Reviewer: `/root/day6_qa_c`, independent of the implementation builder. Reviewed revision: `c47ce8f798ddb0f3c5ea7218a1ee6a03a44b3785`, executed from the preserved Git archive `logs/day8-workflow-c47ce8f.zip`. Later working-tree corrections are excluded. Exact source, test, and evidence hashes are in `DAY8_WORKFLOW_QA_HASHES.json`.

## Findings

1. **D8-WF-001 — Canonical cycle and debrief omit real execution evidence.** A successful actual workflow reaches `COMPLETED` with empty `work_items`, `provider_runs`, `agents_run`, and `billing_sources`. The correction path also completes with empty `correction_runs`, although the separate build and QA records contain two distinct implementations, a rejected first review, and a correctly merged second implementation. `run_daily` only places the final implementation and QA into the cycle snapshot. In addition, `debrief` filters resource-extension records against that empty WorkItem collection, excluding actual recorded extensions from the reviewer context. The two integration failures reproduce the missing canonical work and correction collections; the additional usage/extension omissions are confirmed by source inspection (those later assertions were not reached). Preserve all actual attempts and authoritative usage, including failure and correction history, before debrief and completion.
2. **D8-WF-002 — Post-merge verifier can certify changed source.** The verifier checks HEAD and clean status before running tests and HTTP checks, but does not check them afterward. An offline adversarial test changes both HEAD and dirty state during the trusted test subprocess; `verify` still returns `PASS`. Revalidate the exact merged revision and clean source after all checks before issuing a passing record.

Scheduler authority handoff is independently owned by agent A. This revision's `run_daily` accepts no inherited scheduler epoch or schedule ID; its race results are covered in that separate review, not counted as an additional test here.

## Executed evidence

- `logs/day8-workflow-qa-db.log`: **2 failed, 1 passed, 3 deselected** in 70.30 seconds; pytest exit 1. Actual pipeline methods, canonical records, disposable PostgreSQL, isolated Git commits, independent QA binding, and merge gates executed. The normal and correction pipelines reached completion before the missing-evidence assertions failed.
- `logs/day8-workflow-qa-unit.log`: **1 failed, 2 passed, 3 deselected** in 2.34 seconds; pytest exit 1. The failed case is the source-drift verifier probe. Honest subprocess success/failure classification passed.
- Both runs emit two existing Starlette/AnyIO deprecation warnings.

The integration fixture mocks vendor execution, capability routing selection, readiness catalogue access, and sandbox check execution. It retains the actual orchestration, exact path/capability request construction, grant issuance, Git application/checkpoints, inherited QA/merge, canonical daily transitions, debrief digest review, and Quality gate. Mocked Usage and extension records are explicitly fixture evidence, not real-provider acceptance. No vendor inference, production mutations, account access, or live trading occurred.

Positive observations: independent frontier inspection contexts do not contain prior frontier findings; one selected bounded profile requests only the two intended UI files and exact capabilities; build/QA/merge repeat exact checks; a rejected code review causes a new implementation and fresh QA, and only that pair merges. An injected provider error preserves `BLOCKED`, finished time, failure records, and prevents merge/debrief. Trusted verifier subprocess failure is reported as failed.

## Remaining acceptance boundary

This is orchestration-seam QA, not first-real-cycle acceptance. Verified live capability routing, native vendor behavior, sandbox execution, generated feature behavior, responsive browser interaction, and post-deployment smoke evidence must come from their separate reviews and the authorized real cycle. The current default post-merge verifier runs framework/readiness tests and route/service checks; these alone do not prove the generated feature's browser behavior. No completed Day 8 or autonomous-schedule readiness claim is made.

Fresh independent QA is required after the corrections; retain these negative results.
