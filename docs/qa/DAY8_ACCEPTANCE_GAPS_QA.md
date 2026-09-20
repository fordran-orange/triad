# Day 8 acceptance-gap corrections — independent QA

**PASS for the bounded corrections at `600c5d53c70d430f81c0b6e3570f7d71203ce585`.** Independent reviewer: `/root/day6_qa_c`; builder: `/root`.

Candidate `49ae7bc06ee69c0141d6e6ff436c47a0f06bb188` has identical app/config/tool/infrastructure/package source to this tested revision. Its only subsequent diff is an import-format correction in `tests/test_day8_observed_assets_qa.py`, independently reviewed by agent B. The later evidence-only descendant `ca03028662cdc11b8add3b801e74b16fa66e5eb0` also has unchanged application source. This report accepts the artifact reader, fresh inspection snapshot, and cycles copy/type corrections; it does not independently re-adjudicate unrelated changes or declare Day 8 complete.

## Fresh independent execution

Tests ran from the full preserved Git archive `logs/day8-acceptance-gaps-600c5d5.zip`. No tracked file was changed. Added test files, runners, and this report remain under ignored logs; copies used for collection are inside the ignored archive extraction.

- **16 passed in 0.59 seconds**, exit 0: `logs/day8-acceptance-gaps-offline.log`. These invoke actual artifact and inspection methods and execute actual `cycles.js` using a Node DOM harness.
- **8 passed, 3 deselected, 2 existing dependency warnings in 180.67 seconds**, exit 0: `logs/day8-acceptance-gaps-integration.log`. `TRIAD_INTEGRATION=1`; six full disposable workflow cases, one new product-private inspection test, and the existing scoped dashboard/artifact test. The three deselected cases are offline verifier tests from the workflow file, already passed in the earlier workflow correction run; no integration case was skipped.

The database run began only after the parent released the full-regression slot. All vendor execution and worker-health HTTP are mocked for these tests. Actual PostgreSQL transactions, scoped record selection, temporary Git commits/merges, grant/QA gates, lifecycle/debrief methods, ownership checks and evidence rollups run in disposable state. No production inference, provider mutation, schedule change, service startup, migration or deployment occurred.

## Findings closed

**D8-GAP-001 — Reviewed feature artifact viewer: closed.** Original direct-method reproduction is preserved at `logs/day8-artifact-seam-gap.json`. The read-only reader now admits the exact reviewed bounded HTML/JS/CSS feature path while retaining the merged-content hash and ownership gates. Tests prove:

- Exact reviewed HTML, JavaScript and CSS read successfully with their merge identity; legacy reviewed Markdown still works.
- Generic Git's writable path method still rejects executable UI suffixes even under the feature directory. The correction has not broadened that writer.
- Missing merge evidence, changed bytes, the newest reviewed hash differing, foreign ownership, foreign product paths, traversal and Python suffixes fail closed.
- Assets over 32,000 bytes, a real filesystem hardlink, and a simulated Windows reparse-point attribute are rejected. The reparse test exercises the actual reader with a patched filesystem attribute, not a claim that a real junction was created.
- Real database scoped ownership behavior is repeated by the existing product fixture.

**D8-GAP-002 — Cycles accuracy: closed.** Actual JavaScript renders `DAILY_PRODUCT` as “Daily product cycle,” keeps `PRODUCT_BUILD` and rotation labels correct, and the HTML no longer asserts that scheduling is permanently disabled. It directs the operator to the current governed schedule. This is actual DOM-harness execution, not a fresh interactive-browser walkthrough; final deployed browser acceptance remains separate.

**D8-GAP-003 — Current inspection evidence: closed.** Actual `inspect` now supplies prior product-map areas, capability inventory, candidate backlog, independent QA findings, current control projection and truthful worker liveness. Tests prove:

- All three frontier inspectors receive the same snapshot captured before any current inspection result is appended; local Qwen alone receives the three new summaries.
- Current-mission inspection and candidate rows are excluded from the historical snapshot.
- Only projected QA/control fields are supplied; injected unrelated secret fields are absent.
- The health request is made once, read-only, without proxy environment use. Correct Triad health yields UP, an unrecognized response yields UNKNOWN, and connection failure yields UNAVAILABLE. Liveness is explicitly not task-success evidence.
- A disposable database with both Triad and Aegis historical inspection/candidate records proves actual scoped Records selection passes Triad history and excludes the Aegis private sentinel from all frontier contexts.

## Workflow regression and boundaries

The six existing full workflow cases still pass: normal execution with exact usage/agent/billing and extension evidence; fresh build/QA correction before the correct merge; provider failure with blocked records; debrief rejection followed by a new reviewed draft and independent gain downgrade; exhausted debrief QA with no publication; and failed post-merge verification with no completion. Generic historical capture still cannot infer daily completion from a merge.

The parent's full suite started against `32bb237`; its completed log independently reads **670 passed, 5 warnings in 1409.91 seconds**. Its hash is retained as supporting parent-run evidence; subsequent source differences are covered by the exact independent correction runs. This reviewer did not rerun or claim that full suite. The exact frozen targeted runs above cover the later three corrections.

Source/evidence hashes are in `logs/DAY8_ACCEPTANCE_GAPS_QA_HASHES.json`. Every executed source file matches its preserved archive member. Eight inspected Python files match Git bytes exactly; the two static files in the archive use CRLF while the Git blobs use LF. The manifest preserves both hashes. Source blobs are identical between the tested revision and candidate `49ae7bc`; current checkout content also matches after CRLF normalization. No content mismatch was excused.

Earlier gap evidence remains preserved. The unrelated task's untracked files were neither read for implementation nor edited, staged, removed or included in this acceptance. New real-market manifests from that task must remain separately attributed; their existence does not establish research readiness or belong to the Day 8 autonomous cycle.

No additional structural blocker was found within these corrections. The new real cycle, native independent QA, governed merge, deployed feature/browser checks, reviewed real debrief, scheduler activation and verification, package smoke and final exact release acceptance remain the outstanding Day 8 gates. Scheduled runs use the trusted framework/service verifier; this report makes no claim of unattended browser execution on future scheduled cycles.
