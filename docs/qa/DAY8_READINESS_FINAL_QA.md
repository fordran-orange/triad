# Day 8 Core readiness — final independent QA

Reviewer `/root/day6_qa_a`; builder `/root`.
Exact revision: `ef79fce2990cc19ee9dc4d2e9890f4d4eb77bd53`.
Decision: **PASS for the bounded Core readiness service and API**.

The original 460c2c8 and corrections 372f34c/108acfe CHANGES_REQUIRED reports,
revision hashes and failed logs remain preserved. This fresh verdict applies to
the corrected source, not to those earlier revisions.

## Corrections and boundaries verified

- Valid locally published canonical parquet reaches READY when exact request,
  dataset and completed independent evidence match. Known storage metadata is
  excluded from Bar validation; mandatory bar values remain validated.
- Missing, malformed or structurally incomplete check evidence stays nonready.
  The real evaluation route returns a readable response for malformed checks.
- Each requested symbol and expected session requires the complete set of
  completed passing checks. Missing/wrong sessions, missing symbols/checks,
  failed checks, naive/future execution times, unresolved outliers and critical
  findings are rejected.
- Required evidence/reference items and metadata must be nonblank. Nested
  outlier dispositions now use typed resolved findings with nonblank evidence.
  Both the previously failing whitespace case and a positive resolved finding
  with a proper evidence tuple were checked.
- Registry status and historical-bar capability must be usable. Disabled or
  unavailable sources cannot produce readiness. Unsupported acquisition remains
  blocked; paid fallback remains NEVER_AUTOMATIC.
- Exact request/dataset digest, latest independent QA, separate identity,
  reviewed revision and nonfixture execution constraints are enforced. Product
  evidence, tampering, stale or rejected reviews and self-review are rejected.
  Actual scoped Records.append rejects canonical readiness evidence for Triad,
  Aegis and legacy P2P before any database connection.
- Modifying raw bytes after review invalidates eligibility/readiness. Existing
  tests repeat corrupt canonical files, REAL/FIXTURE separation, private/missing
  dataset selection, missing symbols, unsupported years, empty regular-session
  coverage, unknown fields and historical membership unavailability.
- READY still explicitly identifies fixture mode where applicable, and strategy
  status remains NOT_EVALUATED. Core/shared manifest discovery remains unchanged.

## Exact run evidence

Frozen full git archive: `logs/day8-readiness-ef79fce`; unrelated later working
files are excluded. Independent QA test was copied into that archive. Command,
with PYTHONPATH selecting its application:

`.venv\Scripts\python.exe -m pytest logs/day8-readiness-ef79fce/tests/test_readiness.py logs/day8-readiness-ef79fce/tests/test_day8_readiness_qa.py -q`

Final result: **36 passed, two dependency warnings, 4.43 seconds**, exit 0.
Output: `logs/day8-readiness-independent-final-ef79fce.log` and `.exit`.
Independent test Ruff check passes. A 35-case initial passing run and focused
positive-resolution run are also retained; the final run includes both and the
formatted final test file. No behavior assertion was weakened.

Source raw Git blob hashes, actual frozen archive bytes, test and log/report
hashes are recorded in `DAY8_READINESS_FINAL_QA_HASHES.json`. Archive and raw Git
hashes are distinguished because Windows archive line endings can differ.

This reviewer used offline archive files, a controlled canonical-record reader
with the actual Quality validator, and TestClient. No production write, provider
call, external data acquisition, database suite or application source edit was
performed. This does not accept the separate product UI/lifecycle/debrief,
authorize actual readiness attestations, establish real-market coverage, enable
scheduling or constitute Day 8 final acceptance.
