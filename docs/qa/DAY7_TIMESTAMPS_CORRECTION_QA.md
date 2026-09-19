# Day 7 timestamp correction — independent QA

Reviewer: `/root/day6_qa_b`; builder: `/root`.
Exact source revision: `b10a7ff6e878ea2580b8be369ff91c384c813342`.

Decision: **PASS_WITH_OBSERVATIONS**. The original timestamp authority defect is
resolved on this exact revision; the nonblocking observation concerns disposable
test graph cleanup below.

The original **CHANGES_REQUIRED** report, source manifest and failing logs for
`99dd242` are preserved without edits. This correction was inspected and executed
using a separate `git archive` app snapshot at
`logs/day7-timestamps-b10a7ff/app`, selected through `PYTHONPATH`, with
`TRIAD_INTEGRATION=1`. Concurrent resource-policy/runtime edits in the working
checkout are excluded. Production records, services, configuration and source
were not changed by this reviewer.

The correction rejects direct typed lifecycle-record insertion through
`Store.add_record`. The lifecycle helper inserts only after checking canonical
handoff ownership and its assigned receiver. Deterministic event IDs preserve
the first acknowledgment/completion through duplicate ingestion. The read
projection requires matching handoff kind/ID, row ownership, row WorkItem,
payload WorkItem, receiver and permitted phase.

The new independent regression inserts five historical invalid event variants
using SQL only in a disposable database: foreign owner, foreign row WorkItem,
foreign payload WorkItem, wrong receiver, and forbidden phase. It checks that
the Aegis-scoped handoff projection ignores all five, then checks that ordinary
validated delivery and completion still appear correctly.

Validation evidence:

- `logs/day7-timestamps-independent-b10a7ff.log`: **11 passed in 105.33s**, covering the
  original authority reproductions, historical invalid events, normal Review
  completion, stable repeated lifecycle times, explicit historical quality times,
  UTC normalization/naive rejection, immutable source handoffs, retry lifecycle,
  normal three-agent rotation, no-change review, and disposable actual Git
  build/QA/governed merge.
- Shared renderer source is unchanged from the independently executed Node DOM
  check recorded in `logs/day7-timestamps-ui-independent.json`. That check
  observed local CDT, correct expandable canonical UTC, and missing values as
  “Not recorded.” It was not a browser visual inspection.
- QA test file passes Ruff. No paid/provider requests or production service
  restart were performed by this reviewer.

Test-isolation observation sent to the builder: the common fixture's scoped graph
cleanup should include the new `event_id` field, so disposable lifecycle nodes do
not remain orphaned after their WorkItems are removed. This is separate from the
timestamp implementation source frozen for this review.

Exact source and QA evidence hashes are recorded in the companion correction
manifest. This verdict does not approve concurrent resource runtime changes.

## Fixture-cleanup observation closure — PASS

The observation is closed at exact committed revision
`27cda299418b7145757cf5c262a7e0f360ef7d70`. Commit
`9bd28ade3628f695e924d58331e4cc851f9b8b9c` added `event_id` to the existing
disposable fixture's collected record IDs; that fixture change is unchanged at
the reviewed revision. Store, WorkItem and Quality timestamp source hashes are
unchanged from the accepted `b10a7ff` correction.

Fresh independent repetition passed **11 tests in 110.77s**, including both
authority regressions, historical invalid-event filtering, lifecycle/UTC checks,
rotation, no-change review, and actual disposable build/QA/governed merge.
Source, configuration, SQL and shared fixtures came from a full committed
`27cda29` archive; the earlier independent timestamp QA test extension was copied
into that snapshot. Uncommitted B3 implementation/configuration/tests were excluded.

A read-only teardown observer found 9 lifecycle graph nodes before normal
rotation cleanup, 9 before no-change rotation cleanup, and 1 before product-build
cleanup. All 19 were absent afterward. Other timestamp fixtures likewise left
zero matching lifecycle nodes. Evidence:
`logs/day7-timestamps-independent-27cda29.log` and
`logs/day7-timestamps-cleanup-observations.jsonl`.

The original `b10a7ff` **PASS_WITH_OBSERVATIONS** verdict above remains historical
evidence. Its exact original report and manifest bytes are retained at
`logs/day7-timestamps-correction-report-b10a7ff.md` and
`logs/day7-timestamps-correction-manifest-b10a7ff.json`. The companion manifest
adds this closure separately. No timestamp observation remains open; no B3 or
production deployment acceptance is implied.
