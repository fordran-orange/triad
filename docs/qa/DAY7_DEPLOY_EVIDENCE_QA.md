# Day 7 deployment evidence helper — independent QA

**PASS** for corrected helper revision `120f3289f6a9425f624d027c69397aef25dd4bf5`, with the explicit preflight condition below. Reviewer `/root/day6_qa_a`, separate from builder `/root`, 2026-09-19. This scoped review did not execute production mutations or authorize unrelated integration implementations.

## Preserved initial finding

**CHANGES_REQUIRED** at `58ef0992b4d790fab66621e336c899eec3748761`: helper checked the original artifact and PASS report marker/revision but recorded whatever current definitions-v2 bytes were on disk under the old reviewed commit. An unreviewed edit reached Records and appended a definitions-only resolution. Independent isolated reproduction: **1 failed, 3 passed in 3.90s**, `logs/day7-deploy-original-qa.log`, exit 1. The failing preflight test changes only the temporary definitions file; all database dependencies are strict in-memory stubs.

## Corrected behavior

The helper retrieves the definitions raw Git blob from exact reviewed commit `56e4f96cd9ab43a319302edb694897d75143237a` and requires matching current SHA before constructing Records. The corrected exact helper passes **4 tests in 3.18s**, `logs/day7-deploy-correction-qa.log`, exit 0:

- Changed definitions fail before any database object construction or append.
- Changed original artifact and a missing/failed QA marker fail before database access.
- Valid evidence appends only QualityDebtResolution, retains the original OPEN debt and reviewed artifact/commit metadata, uses only the intended recovery link and avoids duplicate resolution on repeat.

Commands set DAY7_HELPER_QA_SOURCE to the respective exact raw script exported under logs, then run `.venv\Scripts\python.exe -m pytest tests/test_day7_deploy_qa.py -q`. The raw helper bytes are compared to their committed Git blobs. Only subprocess git-show retrieval is stubbed with exact reviewed bytes and checked arguments; actual raw blob retrieval and current-file comparison were also inspected separately. No actual database, registry seed, backfill, recovery link, provider or network action was executed. Ruff passes for the independent test file.

## Required preflight before production execution

Read-only inspection found the working definitions document contains CRLF bytes, SHA `3e9f1136a565f7ff0d0e22191cda419c4a626724212ec2c204b5638df0902ce0`. The reviewed raw Git blob uses LF, SHA `9542a822398e252302dc3a79358732675d30f24c15429cc9e1611c9cc8d32fba`. Text matches after LF normalization. The corrected helper therefore correctly refuses the present working bytes. The builder must restore the exact reviewed blob bytes for that document before execution; do not relax the guard or bless an arbitrary new hash. QA has not changed the working document. Evidence: `logs/day7-deploy-definitions-preflight.json`.

The final G/H/I PASS report exists and binds the reviewed definition hash. The original Day6 artifact must still pass the helper's existing strict check. Production execution remains contingent on those current-byte checks, required sibling integration QA gates and the builder's backup/deployment procedure. Actual production records and post-deployment service/browser behavior require separate acceptance; stub tests do not prove those outcomes.

Exact script, test, report and run hashes are retained in `DAY7_DEPLOY_EVIDENCE_QA_HASHES.json`. Previous GHI and cycle failure reports remain unchanged.
