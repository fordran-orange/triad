# Day 7 regression correction — independent QA

Reviewer `/root/day6_qa_b`; builder `/root`.
Exact revision: `335a8f4dd3148c20eb4131800918b7ac1a0479dd`.
Decision: **CHANGES_REQUIRED** for one remaining Qwen test-fixture incompatibility.

The independent frozen six-case run finished **5 passed, 1 failed in 43.85s**.
Evidence: `logs/day7-regression-independent-335a8f4.log`.

The Qwen compact-SUPPORT fixture still replaces `transport` with a function that
requires a third positional timeout and accepts only `/api/generate`. Current
HttpProvider first invokes `/api/show` with its default timeout to verify the
model's context capacity. Consequently the test fails with TypeError before
generation, even after the generation-timeout expectation was changed to 480.
Correct the mock to support the real transport signature and a bounded declared
context window for `/api/show`; retain its generation timeout, compact schema,
256 output, disabled thinking and malformed-response rejection assertions.
This is a fixture correction, not evidence to bypass context validation.

The three other affected cases pass: raised runtime budget/wrong identity
rejection; an explicitly enabled local daily cap exhausting without cycle reset;
and specialist TIME=1 blocking with zero extension and no successful Usage.
Two additional independent cases verify legacy grants of 512 and 8192. Negative
requests are denied; zero and requests within the grant are allowed; above-grant
requests, including 1,000,000, require human approval. Wrong-agent requests are
rejected without recording a request. Every request leaves the complete WorkItem
unchanged and produces neither a ResourceExtensionDecision nor Usage.

Source review confirms the only implementation change removes the legacy
hardcoded 2048 decision threshold. Runtime authority and ResourceSession code are
unchanged. The new QA-only file `tests/test_day7_regression_qa.py` passes Ruff.

Execution used the complete frozen archive `logs/day7-regression-335a8f4`,
TRIAD_INTEGRATION=1, disposable PostgreSQL and scoped graph cleanup. It began only
after the root full regression released the DB slot; that slot is now released.
The original full-run evidence is preserved at `logs/day7-full-regression.log`
(5 failed, 524 passed in 1208.59s), including the separately investigated provider
fallback failure, which is outside this correction verdict. No production or
implementation changes were performed. Fresh independent QA is required for the
fixture correction; exact source and evidence hashes accompany this report.
