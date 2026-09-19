# Day 8 research-review fixture correction — independent QA

Verdict: **PASS** at exact revision `31dd333b64381247da840e5d3bdcc9f35fff4c58`.

Reviewer `/root/day6_qa_c`, independent of builder `/root`. This commit changes only `tests/test_lab_failure_integration.py`: the monkeypatched `concurrent_get` accepts the optional keyword-only transaction connection and forwards that inner call directly. No application implementation changes are present in this commit.

The full regression's original failure is preserved in `logs/day8-full-regression.log`: **1 failed, 653 passed, 5 warnings in 1521.86 seconds**. Its traceback shows the fixture's old signature rejecting `conn` when the real `Store.get` delegates to itself inside an opened transaction; the concurrency behavior was not reached.

Independent frozen execution from `logs/day8-lab-fixture-31dd333`, with `TRIAD_INTEGRATION=1`, ran the entire four-test file against disposable PostgreSQL, temporary research artifacts, and scoped graph cleanup. Result: **4 passed, 2 existing dependency warnings in 26.94 seconds**, exit **0**. Evidence: `logs/day8-lab-fixture-qa.log` and `.exit`; exact source/test/archive/log hashes accompany this report.

The concurrency test remains substantive. Each of the two top-level calls reads its WorkItem before waiting at the same two-party barrier. The connection-bearing recursive call performs the actual read but does not wait again, so there is no second barrier or deadlock. Both submissions then act on the captured revision. The original assertions still require exactly one `ACCEPT_RESULT`, one `STALE`, exactly one persisted ResearchReview, and final `COMPLETED` status.

The rollback half remains unchanged: it raises after inserting ResearchReview inside the same review transaction, then asserts no review survived and the WorkItem remains `AWAITING_REVIEW`. The other three cases still verify late failure reconciliation across files/database/work, failed sweep attempt retention, and rejected parameter variants without phantom runs.

No assertions, competing threads, failure injection, or stale-update check were removed or weakened. No production writes, inference, migrations, or application edits were performed by this reviewer. This closes the identified test-fixture incompatibility; it does not relabel the earlier full regression as wholly passing or replace separate acceptance of subsequent application changes.
