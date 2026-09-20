# Day 8 recovery deployment — independent evidence acceptance

**PASS for deployment only**, exact clean candidate `d0a399c82a153bb647686b3923001bbb23a85953`, compared with deployed main `4b53134743dca86cdd7217414a12c8047ab8fd50`. Reviewer `/root/day6_qa_a`, independent of builder.

All **10** changed app/tool/test paths match their previously accepted exact source hashes. The accompanying JSON binds **all 24 changed files**, including QA and closeout documents, as raw Git SHA-256 values in `git_blob_sha256`; `decision=PASS` and `revision` identify this candidate. All **42** referenced evidence checks pass. The superseded observed-assets test hash matches its preserved Git version; its import-only successor has separate independent PASS at49ae7bc. The accepted closeout document has CRLF on disk and LF in Git; both hashes and their verified identical normalized content are recorded. No unreviewed implementation gap was found, so no redundant tests were run.

Coverage:

- Core native observed-asset reconstruction and probe contract:7c78acb, agent B's63-test PASS plus separate actual repeat-probe acceptance. Exact observed writes, original-read evidence and final authority gates remain required. The failed first product build stays failed.
- Triad actual-file artifact reader, fresh equal inspection context and honest cycle labels:600c5d5, agent C's16 offline and8 integration PASS. This includes the earlier5db63ed reader correction. Generic writable paths are not broadened.
- Transaction-aware concurrency fixture:31dd333, agent C's four-case PASS, retaining exact-one accepted/stale review and rollback assertions.
- Independent observed-assets test import correction:49ae7bc, agent B's separate acceptance.
- HFDataLibrary tool, test and audit document:all three match HFDATALIBRARY_INDEPENDENT_QA exactly. This was a **separately authorized data task**, not an autonomous Day8 improvement. Source manifests remain REAL/FAIL, raw-only and ineligible; the independent audit did not certify them as research-ready.
- Closeout checkpoint document:d0a399c includes agent C's independently reviewed document content and preserves unfinished Day8 gates.

The retained whole regression670PASS is supporting earlier-revision evidence; later corrections are covered by their separate frozen delta runs. This reviewer checked evidence bytes and source ancestry without running providers, tests, database writes, restarts or schedules, and wrote only ignored logs. Working tree remains clean.

This PASS permits the trusted Core deployment gate to consider this exact revision. It is **not Day8 completion**, not approval of the failed feature candidate, and not permission to bypass native independent product QA. The new actual cycle, exact governed product merge, functional browser checks, reviewed real debrief, manual completion, authorized scheduling and final release acceptance remain outstanding.
