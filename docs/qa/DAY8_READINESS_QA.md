# Day 8 Core readiness — independent QA

Reviewer `/root/day6_qa_a`; builder `/root`.
Exact reviewed revision: `460c2c8f5f09729d2d701e3fc4c3c08e88b25e42`.
Decision: **CHANGES_REQUIRED**. No implementation changes by this reviewer.

Scope: the four committed readiness/API/host-record-kind/test files, with the
accepted Day 7 readiness definitions and existing archive, registry and Quality
interfaces as dependencies. Later working-tree lifecycle/debrief work is excluded.

## Required corrections

1. **P1 — Published canonical data fails its own readiness validation.**
   `Readiness.evaluate` passes complete `Archive.load` rows into `quality`, whose
   strict Bar contract rejects the normal `bar_end` storage column. A genuinely
   published 60-bar fixture with complete matching independent evidence reports
   PARTIALLY_READY and schema failures for all 60 rows, although the local matcher
   verifies its exact requested coverage. The positive READY regression fails.
   Validate the canonical contract without treating known storage metadata as an
   invalid bar; retain all mandatory financial/time/symbol checks.
2. **P2 — Malformed host evidence crashes the evaluation HTTP endpoint.**
   A digest-bound and independently reviewed record with `outlier_review: null`
   reaches `.get` on a nonmapping check and returns HTTP 500. Typed validation or
   fail-closed parsing should return a readable nonready result for malformed
   retained evidence, without treating it as completed.
3. **P1 — Completion evidence does not enforce the accepted definition.**
   `reviewed_checks` accepts `executed_at: "not-a-timestamp"`; it also accepts an
   outlier method string with no parameters, reference evidence, findings or
   disposition. Both records have exact request/dataset fingerprints, a correct
   digest and a real `Quality.require_pass`-validated separate QA link. The Day 7
   definition explicitly requires execution time and the outlier method,
   parameters, reference evidence, findings and disposition. A valid QA identity
   should not make structurally incomplete completion evidence acceptable.
   These failures are tested directly at the evidence gate because finding 1
   otherwise masks an eventual incorrect READY result.
4. **P2 — Registry unavailability is ignored.**
   A local source with enabled/configured/connected true but status UNAVAILABLE
   and HISTORICAL_BARS UNAVAILABLE proceeds through evaluation and produces
   PARTIALLY_READY instead of BLOCKED. Only the three booleans are enforced.
   Respect the selected source's current usable status and implemented capability
   before returning a readiness claim. The READY consequence is currently masked
   by finding 1; the direct observed result is PARTIALLY_READY, not READY.

## Independent evidence

Added `tests/test_day8_readiness_qa.py`. Frozen full `git archive` of 460c2c8 at
`logs/day8-readiness-460c2c8`, with only the independent test copied into it.
PYTHONPATH selected that archive's application. Command:

`.venv\Scripts\python.exe -m pytest logs/day8-readiness-460c2c8/tests/test_readiness.py logs/day8-readiness-460c2c8/tests/test_day8_readiness_qa.py -q`

Final result: **5 failed, 15 passed, two dependency warnings in 3.60 seconds**;
exit 1. Log: `logs/day8-readiness-independent-review-460c2c8.log` and `.exit`.
The two evidence-shape failures are grouped into finding 3.

Passing cases include the five builder regressions; exact-request/digest
mismatch; product-owned evidence; stale revision; a later rejected QA; self-QA;
TEST_FIXTURE execution; and actual Records.append denial for Triad, Aegis and
legacy P2P scopes. The independent tests use the real Quality validator with
an in-memory canonical-record reader, real locally published parquet/raw files,
and a FastAPI/TestClient evaluation route. There are no production writes,
provider calls, data fetches or database tests.

Initial probe logs remain retained. The first probe had a test import-order
error from importing the integration router before the main API; it was corrected
to the supported application initialization order. An intermediate probe had
three fixture Settings-construction failures in product-scope denial tests; the
final tests use a settings stub because rejection occurs before any connection.
Neither test-harness issue is counted as an implementation finding.

Source review confirms discovery uses only Core/shared manifests, external
adapters are blocked with no fetch, and strategy validation is explicitly
NOT_EVALUATED. Unsupported-year and empty-session behavior are covered by the
passing existing tests. This is not browser acceptance, production evidence
attestation or acceptance of the separate Day 8 product implementation.

Exact raw Git blob hashes (authoritative revision) and frozen test/source/log
byte hashes are preserved in `DAY8_READINESS_QA_HASHES.json`. Git archive line
endings may differ from raw blobs; both are recorded explicitly.
