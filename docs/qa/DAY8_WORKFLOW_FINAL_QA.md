# Day 8 daily workflow correction — independent QA

Verdict: **PASS for the bounded workflow implementation**.

Reviewer: `/root/day6_qa_c`, independent of the builder. Exact reviewed revision: `add70c29554e3845a244698e0a412224c62f1314`. Source was executed from `logs/day8-workflow-add70c2`, extracted from the preserved Git archive. The accompanying `DAY8_WORKFLOW_FINAL_QA_HASHES.json` binds the reviewed source, independent test, runner, archive, and results. No implementation files were edited by this reviewer.

## Fresh execution

`logs/day8-workflow-correction-tests.log` records **9 passed, 2 warnings in 181.31 seconds**, pytest exit **0**. All six integration cases ran against disposable PostgreSQL and Git state; none were skipped. Three additional cases test the trusted verifier offline. Ruff checks and formatting pass for the independent test file. The two warnings are existing Starlette/AnyIO deprecations.

The tests exercise actual `run_daily`, inspection, selection, grant issuance, build, inherited independent QA, governed Git merge, canonical lifecycle, debrief production/review, and Quality publication gates. Only vendor execution, capability-route selection, readiness catalogue access, sandbox test execution, and final HTTP verification are fixture seams. Thus this proves the orchestration and evidence integration, not live-provider routing or generated UI functionality.

The suite verifies:

- Normal completion retains every fixture provider run ID, all four actual agents, subscription/local billing, WorkItems, and resource extensions in the debrief evidence. Frontier inspectors receive no prior inspector findings. The implementation request retains exact paths, capabilities, and budgets.
- Rejected code QA produces a fresh implementation and QA; only the second passing pair merges. Both implementation attempts and correction history remain in the canonical cycle, with exact checks repeated through build, QA, and merge.
- Provider failure leaves a finished `BLOCKED` cycle and explicit build failure, with no merge or debrief.
- A rejected debrief produces a new draft and independent review before publication. The independent reviewer downgrades the builder's proposed `HIGH` gain to `LOW`, and only that reviewed classification is published.
- Three rejected debriefs exhaust the bounded correction loop, leave `BLOCKED`, and publish nothing.
- Failed post-merge verification preserves the real merge but blocks completion and debrief publication. Generic historical capture cannot infer daily completion from the merge. Evidence refresh preserves lifecycle status, timestamps, parent, and control epoch.
- The verifier reports trusted subprocess failure honestly and rejects source drift occurring during the verification subprocess.

## Findings closed

**D8-WF-001 closed:** refresh now captures authoritative execution records before transitions and debrief context generation. Exact run/agent/billing assertions and correction-history preservation pass; actual resource-extension fixture evidence reaches the debrief call. Refresh preserves lifecycle authority, and generic capture cannot bypass daily completion requirements.

**D8-WF-002 closed:** the verifier checks exact merged HEAD and clean source again after its tests and HTTP checks. The original adversarial drift case now passes.

The initial negative report, exact initial test copy, and logs remain intact: `DAY8_WORKFLOW_QA.md`, `DAY8_WORKFLOW_QA_HASHES.json`, `logs/day8-workflow-qa-initial-test.py`, and the initial unit/DB logs. Initial results were 3 failed and 3 passed across the two runs; they have not been overwritten or relabeled.

## Scope and release boundary

Reviewed implementation includes the workflow and trusted verifier, the new daily evidence-refresh method, and the `CycleHistory.capture` lifecycle boundary, with inherited development/engineering/quality dependencies inspected. Scheduler race and UI acceptance belong to agent A's independent report; engineering and capability-role adoption belong to agent B. Their separate gates still apply.

No real vendor calls, production records, account connections, paid inference, browser execution, or scheduling changes occurred. Mock provider outputs remain explicitly described as fixtures in this report even where the actual pipeline produces its normal execution labels inside the disposable database.

This PASS permits the bounded implementation to proceed to its next authorized acceptance stage. It does **not** declare the first real daily cycle, generated Research Readiness feature, live browser behavior, or all of Day 8 complete. The authorized real cycle still requires native-provider proof, generated feature review and browser acceptance, post-deployment verification, and a reviewed real debrief before any schedule prerequisite is satisfied.
