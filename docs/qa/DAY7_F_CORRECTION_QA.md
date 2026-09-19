# Day 7 F correction — independent QA

Reviewer `/root/day6_qa_b`; builder `/root`.
Exact source: `308dd766657019acc42a82598ca70e90834b77a9`.
Decision: **CHANGES_REQUIRED** for the new REAL-source adoption guard.

All six original findings/seven failing probes are resolved on this revision:
current registry enabled/configured revocation, pre-fetch kill checks, strict
license allowlists, retained raw-source integrity, consistent fixture/real modes,
and failed-normalization raw-artifact links. The original report and hashes for
`fd7f8d0` remain unchanged. An additional positive fixture verifies exact adopted
REAL-mode ingestion and denial when the candidate is deprecated before ingestion.

Two required fixes remain:

1. **HIGH — acquisition does not bind to the actual adoption decision.** The new
   guard checks an IMPLEMENTED candidate and a Core build with matching definition
   digest and passing QA, but does not match that candidate's canonical adoption
   record to the selected integration, implementation ID and commit. Definition
   fingerprints deliberately omit implementation-link fields. The reproduction
   first adopts a valid adapter, then creates a separate QA-covered Core build
   with only an unrelated documentation file and the definition digest. A new
   definition points to that unadopted build while retaining the old candidate.
   Ingestion succeeds although no adoption decision approved the replacement.
   Require the exact current adoption chain, including its integration/build/
   revision and relevant candidate/definition evidence.
2. **HIGH — mid-request deprecation does not stop another fetch.** REAL adoption
   is checked once before the symbol loop. A candidate deprecated immediately
   after symbol 1 completes still authorizes symbol 2 because per-symbol checks
   inspect definition metadata but not current adoption status. Revalidate the
   exact active adoption and its current QA before every external fetch, along
   with the existing registry and global-control checks.

These are host-service validation reproductions with disposable canonical Core
records, not product ownership escalation or demonstrated external account
access. The REAL-mode fixtures use synthetic local bytes solely to exercise the
new authority path; no real-market coverage or vendor connectivity is claimed.

## Evidence

- `logs/day7-f-independent-308dd76.log`: **10 passed, 2 failed in 35.87s**. The
  unadopted-build failure is a direct implementation failure. The initial
  deprecation failure was a QA hook error: recursive append interception attempted
  the deprecation twice. The initial fixture is preserved in
  `logs/day7-f-correction-qa-initial.py`.
- After limiting the hook to one actual deprecation,
  `logs/day7-f-deprecation-proof.log`: **1 failed in 6.70s**, confirming that
  acquisition completes instead of rejecting the next fetch.
- Tests: `test_integration_data.py`, `test_day7_f_qa.py`, and new independent
  `test_day7_f_correction_qa.py`. QA-only tests pass Ruff.

Execution used a full frozen `308dd76` archive at `logs/day7-f-308dd76`, with the
new independent test copied into it, `TRIAD_INTEGRATION=1`, disposable PostgreSQL
and scoped graph cleanup. D/E DB tests finished before this run. No production
change, restart, account call, paid data access or implementation edit occurred.
Source/evidence hashes are in `docs/qa/DAY7_F_CORRECTION_QA_HASHES.json`.
Fresh independent correction QA is required before F acceptance.
