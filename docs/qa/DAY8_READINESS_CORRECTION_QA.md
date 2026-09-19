# Day 8 Core readiness — independent correction QA

Reviewer `/root/day6_qa_a`; builder `/root`.
Exact revision: `372f34c8ed305f89e06bb8f7b01062401414be46`.
Decision: **CHANGES_REQUIRED** for one remaining evidence-validation finding.
Original 460c2c8 findings and failed outputs remain preserved separately.

All four original findings are corrected: normal published parquet reaches READY
with valid exact independent evidence; malformed checks return readable nonready
HTTP results; typed execution time and required outlier details are enforced;
unavailable source status/capability returns BLOCKED. Added exact per-symbol and
session requirements reject missing/wrong sessions, missing symbols/checks and
failed checks. Future/naive times, unresolved outliers and critical findings fail
closed. Changing raw bytes after review invalidates readiness.

## Remaining P1 — empty evidence still counts as completed

A completed independent-reproduction check with `evidence: [""]` in both the
aggregate and session reports passes the contract and the complete evaluator
returns **READY**. The same false READY occurs for whitespace-only normalizer
version, an empty outlier-reference string, and whitespace-only outlier
disposition. Collection length and string length checks do not establish that
required evidence exists. Enforce nonblank values after trimming on required
metadata and every evidence/reference item; retain exact digest/QA binding.
These are four probes of one incomplete-evidence validation defect, not four
separate architectural findings.

## Evidence and limits

Frozen `git archive` at `logs/day8-readiness-372f34c`; only the updated independent
test file was copied into it. The positive fixture now includes actual expected
session dates and complete per-session check maps. No negative assertion was
weakened. Actual Quality.require_pass and file archive code run against offline
fixtures; HTTP uses TestClient and the production evaluator route.

Command (PYTHONPATH selects the frozen application):
`.venv\Scripts\python.exe -m pytest logs/day8-readiness-372f34c/tests/test_readiness.py logs/day8-readiness-372f34c/tests/test_day8_readiness_qa.py -q`

Final result: **4 failed, 30 passed, two dependency warnings in 4.64s**, exit 1.
`logs/day8-readiness-independent-final-372f34c.log` and `.exit` preserve output.
The first correction probe (30 passed, one failed) is retained separately.
All source/evidence hashes are in `DAY8_READINESS_CORRECTION_QA_HASHES.json`.

No implementation edit, production write, inference, data acquisition, database
suite or browser acceptance was performed. Later lifecycle/debrief work remains
outside this verdict. A further correction requires a fresh independent run.
