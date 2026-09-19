# Day 8 engineering foundation — independent QA

Reviewer `/root/day6_qa_b`; builder `/root`.
Exact revision: `4168fd84a76718a32f9efaf2490e62334295f8e9`.
Decision: **CHANGES_REQUIRED**.

The frozen independent run completed **14 passed, 2 failed in 24.23s**.
Evidence: `logs/day8-engineering-independent-4168fd8.log`. Two dependency
deprecation warnings did not affect the run. The implementation tests and the
new `tests/test_day8_engineering_qa.py` were both executed.

## Required corrections

1. **MEDIUM — existing-file staging omits required base-hash evidence.**
   `BoundedTools.changes()` emits a FileChange with original_sha256=None even when
   the broker received the original asset and staged an edit. `GitChanges.apply()`
   requires the actual original hash for an existing file, so that normal exported
   proposal cannot be applied. The Docker reproduction starts with `<h1>Old</h1>`,
   stages `<h1>New</h1>`, and finds the original hash absent. Derive the hash from
   the trusted captured original bytes and carry it through the native result/host
   application boundary; do not depend on the model calculating it. Preserve the
   existing stale-source rejection. Initial creation remains covered and passing.

2. **MEDIUM — final verification omits the grant's aggregate byte ceiling.**
   `EngineeringGit.apply()` checks max_bytes but `verify()` only delegates to the
   parent per-file size/diff checks. In the reproduction a grant permits 10 bytes,
   a 3-byte asset is applied and committed, then an 11-byte candidate is committed.
   `verify()` accepts that candidate. Revalidate aggregate candidate bytes whenever
   the source is verified for QA or merge. This reproduction concerns the Core Git
   primitive; the product workflow is being implemented separately and may add
   exact-snapshot checks, which should not substitute for this grant limit.

## Passing evidence and scope

- Exact feature assets are accepted; unsupported/protected/cross-product paths,
  aliases, traversal, hidden paths and alternate-stream syntax are rejected by
  the repeated implementation tests. Legacy text Git still rejects executable UI
  assets. Native staging rejects an ungranted sibling before execution.
- A missing grant, wrong identity, wrong role, changed exact paths or wrong
  execution permissions cannot use the grant. Product-scoped Records.append and
  Ledger.put cannot forge EngineeringGrant or EngineeringTestRun. Scoped grant
  issuance is denied. Provider disable and a stale kill-switch epoch reject use.
- Hardlinks, stale original hashes and a moved protected baseline are rejected.
- Actual pinned-container staging and checks work. A wrong snapshot fails the
  fixed checks; the test script digest and complete exact-file set are required.
- Container probes observe no OPENAI_API_KEY and no Docker socket. A check trying
  to modify a supplied asset fails under read-only permissions. A stopped guard
  prevents approved checks. Network=none and absent host mounts were inspected in
  the unchanged sandbox implementation; no network-access test was claimed.

Execution used a full archive under `logs/day8-engineering-4168fd8`,
TRIAD_INTEGRATION=1, disposable PostgreSQL/scoped graph cleanup, temporary Git
repositories and actual offline Docker containers. The DB slot was released to
reviewer C afterward. QA-only tests pass Ruff. No vendor call, capability adoption,
production mutation or implementation edit was made. Real Claude verification
and capability adoption remain later gates; this run cannot establish them.
Source and evidence hashes are in `DAY8_ENGINEERING_QA_HASHES.json`.
