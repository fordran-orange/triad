# Day 7 lifecycle timestamps — independent QA

Reviewer: `/root/day6_qa_b`; builder: `/root`.

## Revision 1 — CHANGES_REQUIRED

Exact implementation revision: `99dd242c6f9c4d32326ace76440f5d9b4748152e`.
This review uses an ignored `git archive` snapshot of that revision's `app/` at
`logs/day7-timestamps-99dd242/app`, explicitly selected through `PYTHONPATH`.
Runtime and Store import paths were checked. Concurrent resource-policy/runtime
work in the main checkout is not covered by this verdict. The snapshot uses the
existing host configuration for connections; all test writes occur in disposable
PostgreSQL databases and scoped fixture graph records. No production records,
services, settings, or implementation source were changed by this reviewer.

### Required correction: lifecycle evidence can cross an ownership boundary

`Store.add_record` accepts a `HandoffLifecycle` without binding its target handoff,
WorkItem, owner, or assigned receiver. It validates ownership only against the
event's supplied WorkItem. `Store.records` overlays all events naming a returned
handoff ID, without checking those relationships. The actor check in
`handoff_lifecycle` can therefore be bypassed through the public record-ingestion
path.

Two independent disposable-database reproductions fail:

1. The original worker inserts a completion event directly, naming itself as actor;
   the handoff subsequently appears completed although the assigned reviewer did
   not complete it.
2. A Triad-scoped Store writes an event associated with its own WorkItem while
   referencing an Aegis handoff ID. Reading through an Aegis-scoped Store then
   returns the attacker's completion timestamp on the Aegis handoff.

Severity: HIGH for canonical evidence integrity and product separation. This is
not a claim of a demonstrated provider-facing endpoint exploit or an authorized
merge: the reproduced effect is false completion evidence across scoped product
Store boundaries. Validate all lifecycle ingestion paths against the canonical
handoff and constrain projection to valid matching ownership/work/receiver
relationships. Keep duplicate event ingestion idempotent and retain immutable
source handoffs. Fresh independent correction QA is required.

### Repeated checks and evidence

- `logs/day7-timestamps-independent-99dd242.log`: **8 passed, 2 failed in 87.22s**.
  Includes the three builder lifecycle tests, four independent tests, normal
  three-agent rotation, no-change review, and disposable actual Git
  build/independent QA/governed merge regression.
- `logs/day7-timestamps-overlay-proof.log`: **2 failed in 6.70s**. Strengthened
  the two adversarial tests to observe the false completion through the victim's
  read projection, rather than stopping at missing denial. Initial test text is
  preserved in `logs/day7-timestamps-qa-initial.py`.
- `tests/test_day7_timestamps_qa.py` independently checks direct ingestion
  authority, cross-product target binding, normal Review completion with stable
  initial acknowledgment, explicit historical ImplementationRun/QARun times,
  missing starts, and naive-time rejection.
- `logs/day7-timestamps-ui-independent.json`: PASS. A Node DOM stub executed the
  exact frozen shared renderer. An offset timestamp rendered local CDT and the
  correct expandable UTC timestamp; missing values remained “Not recorded.” This
  is a renderer behavior check, not independent browser or visual execution.
- Existing naive-time rejection, UTC normalization, WorkItem retry lifecycle,
  immutable Handoff source preservation and duplicate acknowledgment tests passed.
- The builder's original broader **32 passed / 2 failed** review-parent regression
  and its **2 passed** correction evidence remain preserved in the build report
  and original logs; they are not replaced by this independent result.

The source hashes, QA test hashes and evidence hashes for this reviewed revision
are recorded in `docs/qa/DAY7_TIMESTAMPS_QA_HASHES.json`.
