# Day 8 daily lifecycle foundation — independent QA

**CHANGES_REQUIRED** at exact revision
`00dc247c9aab511eded403dc1f19b9d6a9914182`.
Reviewer `/root/day6_qa_c`, independent from builder `/root`, 2026-09-19.

Scope: `products/triad/daily.py`, the six reserved host-record kinds, and the
existing three lifecycle tests. Read the full Day 8 brief and permanent QA rule.
This is the lifecycle/debrief/schedule-configuration foundation, not approval of
a worker, UI, real demonstration cycle or enabled recurring production execution.

## Required corrections

### DAY8-DAILY-001 — completion validates the old snapshot, then replaces its evidence

**High.** `daily.py:235` calls `require_complete` using the previous snapshot;
line 238 subsequently applies supplied updates. The update allowlist includes
`merge_commit`, `implementation_runs` and `qa_runs`. Starting from a legitimately
reviewed debrief and passing verification, three independent regressions each
successfully stamped COMPLETED with a replacement unverified merge, unreviewed
build or unrelated QA list. The cycle is terminal despite the changed provenance.

Validate the exact final snapshot, or prohibit changing reviewed provenance when
completing. The verified merge, build/QA and debrief links must refer to the same
accepted result; a later schedule check is too late to repair an already false
COMPLETED record. Repeat all three replacement reproductions and the valid
completion path after correction.

### DAY8-DAILY-002 — global-only guards ignore product pause and parent stop

**High.** `create`, active `transition`, and `configure` call the unscoped host
ledger guard without product or parent identity (`daily.py:166,220,366`). That
guard checks global control but cannot detect the Triad pause or parent WorkItem
stop. Independent tests reproduce all of the following:

- A paused Triad product accepts a new daily cycle.
- An existing daily cycle advances to INSPECTING while Triad is paused.
- A daily cycle advances after its canonical parent WorkItem is stopped.
- Scheduling can be enabled while Triad is paused, given an otherwise valid
  completed manual prerequisite.

Apply existing product- and parent-aware control checks at these lifecycle
boundaries and before consequential publication/schedule actions. Preserve the
ability to record truthful terminal cancellation/block/failure evidence when
execution has been stopped. This finding concerns existing pause/stop authority;
it does not ask for new operator approvals for ordinary bounded work.

### DAY8-DAILY-003 — same-cycle creation lock starts after parent creation

**Medium.** `create` calls `history.parent` before acquiring the per-cycle advisory
lock (`daily.py:168-170`). Two simultaneous calls for one cycle both pass the
parent lookup and create separate zero-authority parent WorkItems. Only one
CycleRecord is committed; the losing attempt raises duplicate-cycle ValueError
but leaves its extra parent. The deterministic concurrency probe observed exactly
two parent rows for the one cycle.

Serialize the parent lookup/creation and canonical initial append together, and
avoid an orphan parent on rejected/failed creation. Retain one canonical parent
and one initial transition for duplicate concurrent requests. These are evidence
anchors, so this is a provenance/idempotency defect rather than duplicated agent
execution in the current worker-free foundation.

## Evidence and passing boundaries

Used full frozen Git archive `logs/day8-daily-00dc247.zip` extracted under
`logs/day8-daily-00dc247`. `logs/day8-daily-qa-runner.py` selects archived app/tests,
configuration and SQL, sets TRIAD_INTEGRATION=1 and disables monitoring only in
that test process. Test credentials are loaded into memory without printing them.
All writes use disposable database fixtures and scoped graph cleanup. No provider
calls, production writes, restart or implementation edits were performed.

1. Existing three tests plus ten independent cases:
   **6 failed, 7 passed, 2 dependency warnings in 36.03s**; exit **1**.
   `logs/day8-daily-qa-initial.log` / `.exit`.
2. Two added explicit product-pause checks:
   **2 failed, 13 deselected, 2 dependency warnings in 7.14s**; exit **1**.
   `logs/day8-daily-qa-pause.log` / `.exit`.
   These separately test progression and schedule enablement because the earlier
   creation failure stopped its test before reaching the second assertion.
3. Ruff passes for `tests/test_day8_daily_qa.py`.

Passing cases verify legal state order/terminal denial; CREATED canonical identity
and parent with no started/finished timestamps; timestamped lifecycle; rejection
of identity/epoch replacement; independent exact debrief hash and strategic-gain
assessment; missing verification rejection; latest FAILED verification or
CHANGES_REQUIRED QA blocking completion; default disabled schedule; valid manual
completion and next-day configuration with no claim/worker execution; rejection
of another debrief's exact review; and all six reserved daily kinds rejected via
both scoped Records and Ledger paths for Triad, Aegis and scoped Core.

Initial source/test/evidence hashes are in `DAY8_DAILY_QA_INITIAL_HASHES.json`.
The exact initial independent test bytes remain at
`logs/day8-daily-qa-initial-test.py`; two additional tests were subsequently added
to the working and copied archive test file for the supplemental run. The final
companion `DAY8_DAILY_QA_HASHES.json` separately binds both executed test versions,
frozen implementation, logs and this report. No failed evidence was overwritten.

All three findings require correction and fresh independent QA before this
bounded implementation can pass. Other agents' readiness/engineering work and
the complete Day 8 acceptance remain outside this verdict.
