# Day 8 daily lifecycle correction — independent QA

**CHANGES_REQUIRED** at exact revision
`6dba1093d07ef303c3203b64756b2ff8f43992bd`.
Reviewer `/root/day6_qa_c`, independent from builder `/root`, 2026-09-19.
The initial `DAY8_DAILY_QA.md` findings and failed evidence remain unchanged.

Fresh frozen-source run: **18 passed, 3 failed, 2 dependency warnings in 64.52s**,
exit **1**. Evidence: `logs/day8-daily-qa-correction.log` and `.exit`.

## Verified corrections

- DAY8-DAILY-001 is resolved: all three completion snapshot replacement attempts
  reject, leaving the reviewed snapshot unchanged. Ordinary reviewed completion
  still works.
- The original product-pause checks pass for new creation, existing progression
  and schedule enablement. A stopped canonical parent now blocks progression.
- DAY8-DAILY-003 is resolved: duplicate concurrent creation leaves exactly one
  parent and one canonical cycle. The concurrency probe now tolerates the expected
  serialized path by handling a one-second barrier timeout; its original unsafe
  path still synchronizes both pre-lock creations. This is an independent-test
  adaptation for the corrected locking behavior, not weakened uniqueness checks.
- Injected failure when appending the initial DailyCycleTransition rolls back
  parent WorkItem, work event, projection outbox and CycleRecord together.
- Existing-parent Store.create with a caller transaction retains ownership
  protection and rolls back correctly. Ordinary create still works. A killed
  cycle may append truthful CANCELLED terminal evidence.
- All previous passing debrief/hash/QA supersession/manual prerequisite/reserved
  record checks still pass.

## Remaining required changes

### DAY8-DAILY-002 remains open for publication

**High.** `Daily.publish` now checks the product pause, but does not supply the
draft cycle's parent WorkItem or control epoch. Given an independently reviewed
draft, publication succeeds after that parent is stopped. It also succeeds after
a global pause/resume has invalidated the cycle's original epoch. Both independent
reproductions expected the existing guard to reject and failed with DID NOT RAISE.

Resolve the canonical cycle from the draft and apply its current parent/epoch
guard before publication, as the corrected draft/transition paths already do.
Completion's later guard does not prevent publishing stale/stopped work now.

### DAY8-DAILY-004 — Store.create does not use its transaction for parent lookup

**Medium.** The new generic `Store.create(..., conn=...)` performs the parent read
through `self.get`, opening a separate connection. Creating a valid same-product
parent then child in one supplied transaction fails with KeyError because that
second connection cannot see the uncommitted parent. This breaks the new API's
atomic composition despite valid ownership and prevents committing both rows.

Use the caller transaction for parent lookup while retaining scope and canonical
product ownership validation. Repeat positive atomic parent/child creation,
cross-product rejection, rollback and the ordinary no-conn path.

## Provenance

The complete `6dba109` Git archive is retained at
`logs/day8-daily-6dba109.zip` and extracted under the matching directory. Independently
compared all **195** app/configuration/SQL snapshot files to the archive: unchanged.
The runner sets archived import paths/TRADING_HOME, TRIAD_INTEGRATION=1 and test
monitoring off. It copies only the two independent QA test files into the snapshot.
Original builder tests plus both QA files make 21 cases.

`tests/test_day8_daily_correction_qa.py` adds rollback, ordinary/new transactional
Store.create, publication controls and terminal evidence probes. Both QA test files
pass Ruff. Exact implementation/test/archive/log hashes are in the companion
manifest. DB runs were staggered with reviewer A; only disposable fixtures and
scoped graph cleanup were used. No implementation changes, production mutations,
provider calls or restart were performed. Worker/UI/engineering and full Day 8
acceptance are outside this correction verdict. Fresh QA is required after fixes.
