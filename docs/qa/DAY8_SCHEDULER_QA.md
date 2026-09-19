# Day 8 daily scheduler — independent QA

Reviewer `/root/day6_qa_a`; builder `/root`.
Exact revision: `c47ce8f798ddb0f3c5ea7218a1ee6a03a44b3785`.
Decision: **CHANGES_REQUIRED**. No implementation changes by this reviewer.

Scope: daily_scheduler.py, scheduler API/server integration, existing schedule
UI consumer and scheduler tests. DailyDevelopment.run_daily's entry point and
Daily.create are included only to reproduce the dispatch authority boundary;
separate reviewer `/root/day6_qa_c` owns the larger workflow review.

## Required findings

1. **P1 — A pending claim can execute after its authority is revoked.** After
   the last scheduler guard and durable claim, tick releases its lease and
   calls the runner without its original expected epoch or schedule identity.
   The actual run_daily entry then creates a cycle using the current epoch.
   In a controlled lease-exit interleaving, both (a) kill followed by resume and
   (b) disabling the schedule allow that old claim to reach the actual workflow's
   inspection stage. Tests stop at an injected inspection callback before any
   inference. Carry and revalidate the original dispatch authorization at cycle
   creation, including the exact still-enabled schedule, and synchronize that
   admission with relevant revocations rather than replacing old authority with
   a newly captured epoch.
2. **P2 — Preview and dispatch disagree across nonexistent local times.** For
   America/Chicago at 02:30 on 2026-03-08, next_cycle returns
   `2026-03-08T02:30:00-06:00`, which round-trips through UTC as 03:30 daylight
   time. That local time never occurs, while tick's current wall-clock comparison
   becomes due at 03:00. Define a consistent DST gap/fold policy shared by preview
   and dispatch, retaining the one-date claim rule.
3. **P2 — The new next-cycle value is not displayed.** The API includes
   `next_cycle`, but daily.js's loadSchedule only displays enabled/time/timezone
   and effective_after. No code reads next_cycle, so the requested concrete next
   scheduled run remains absent from the operator UI. Show it readably with its
   timezone/offset and an honest unavailable/disabled state.

## Evidence

Frozen git archive: `logs/day8-scheduler-c47ce8f`; independent test copied into
it. TRIAD_INTEGRATION=1, TRADING_HOME=C:/Triad for existing fixture settings,
PYTHONPATH selecting the frozen archive application. Command:

`.venv\Scripts\python.exe -m pytest logs/day8-scheduler-c47ce8f/tests/test_daily_scheduler.py logs/day8-scheduler-c47ce8f/tests/test_day8_scheduler_qa.py -q`

**3 failed, 8 passed, two dependency warnings in 45.50 seconds**, exit 1.
Failures reproduce both finding 1 interleavings and finding 2. Finding 3 is a
source/API-consumer review. Output and exit are retained at
`logs/day8-scheduler-independent-c47ce8f.log` and `.exit`.

Passing tests independently exercise concurrent tick calls producing one durable
claim and one runner call, no retry after a failed claimed date, manual acceptance
prerequisite, disabled/not-due behavior, existing global pause/kill, product pause,
stale epoch rejection, and missing trusted runner producing no claim. Existing
calendar/day/activation tests also pass. No paid fallback is introduced by the
scheduler; actual provider policy remains the separately reviewed runtime.

DB fixtures create and delete disposable triad_test databases and scoped graph
records. The DB slot was coordinated with the other reviewers. No production
schedule/control change, real provider call or browser action occurred. The
trusted workflow was invoked only far enough to exercise canonical creation and
an offline inspection stop. Fixture control changes affect disposable databases.

Independent test is formatted and Ruff-clean; the preserved tested archive copy
retains its original formatting. Both copies and exact raw Git source hashes
are captured in `DAY8_SCHEDULER_QA_HASHES.json`. Later workflow corrections and
uncommitted work are excluded. Fresh independent QA is required after correction.
