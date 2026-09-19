# Day 7 F — final independent correction QA

Reviewer `/root/day6_qa_b`; builder `/root`.
Exact source: `56e4f96cd9ab43a319302edb694897d75143237a`.
Decision: **PASS** for the bounded neutral-data service and adoption corrections.

Both findings from the `308dd76` correction are resolved. Acquisition now binds
the selected integration, implementation ID and commit to the latest actual
adoption decision. The shared validation also rechecks candidate/provider/category,
required implemented capabilities, candidate and definition evidence, Core build
files, and current independent revision-bound QA. REAL-mode acquisition repeats
this validation before each symbol fetch.

Independent regression on the complete frozen revision: **14 passed in 43.08s**.
Evidence: `logs/day7-f-final-56e4f96.log`. Two dependency deprecation warnings did
not affect the results. The suite includes the implementation pipeline test,
all original independent F boundary probes, the two correction reproductions,
and two new final-review tests:

- Exact adopted ingestion remains possible; prior deprecation rejects it.
- A replacement build cannot borrow the candidate's earlier adoption. Each of
  the integration, build, commit and candidate links is individually required.
- Deprecation after the first completed symbol prevents the second fetch.
- A new CHANGES_REQUIRED QA verdict after the first completed symbol prevents
  the second fetch; completed and failed acquisition evidence both remain.
- Registry enabled/configured revocation, global stop between symbols, strict
  license allowlists, raw-source integrity, consistent real/fixture metadata,
  and raw-artifact references on normalization failure still pass.
- The existing positive pipeline, private-owner exclusion, coverage/empty-session
  checks, explicit source selection, canonical corruption checks, paid denial,
  and host-only acquisition boundaries remain covered by the repeated tests.

Tests ran from `logs/day7-f-56e4f96`, a full git archive, using
`TRIAD_INTEGRATION=1`, disposable PostgreSQL and scoped graph cleanup. The added
QA file is `tests/test_day7_f_final_qa.py`; Ruff passes. The D/E DB run finished
before this run; the DB slot was released to reviewer A afterward. Concurrent
working-tree progress documents and D/E QA changes were excluded from execution.
No implementation edit, production upgrade/restart, real account call, paid
access, or production data mutation was performed by this reviewer.

The REAL-mode authority tests deliberately use offline synthetic fixture bytes.
They prove service authorization behavior, not vendor connectivity or real-market
coverage. No new broker/trading authority is inferred. This verdict covers F;
separate D/E metadata, product-cycle, and UI acceptance remain their own scopes.
The initial and first-correction CHANGES_REQUIRED reports and evidence are
preserved unchanged. Exact source and evidence hashes are recorded in
`docs/qa/DAY7_F_FINAL_QA_HASHES.json`. No F blocker remains on this revision.
