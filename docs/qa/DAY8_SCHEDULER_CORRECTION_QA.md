# Day 8 scheduler — independent correction QA

Reviewer `/root/day6_qa_a`; builder `/root`.
Revision `6891f07e861e4dca443c94504f2e8b700df85f19`.
Decision: **CHANGES_REQUIRED**, limited to next-run timezone presentation.

All original backend findings are corrected. The scheduler retains original
schedule ID/epoch through dispatch; actual workflow entry rejects a claim after
kill/resume or schedule disable. Configuration and scheduled creation share the
same lease. Missing/replaced grants fail, valid grants preserve the cycle epoch.
DST gaps are skipped by both preview and tick; repeated times use the first
occurrence and the durable date claim prevents a second run.

Frozen archive tests, TRIAD_INTEGRATION=1:
`.venv\Scripts\python.exe -m pytest logs/day8-scheduler-6891f07/tests/test_daily_scheduler.py logs/day8-scheduler-6891f07/tests/test_day8_scheduler_qa.py logs/day8-scheduler-6891f07/tests/test_daily_lifecycle.py -q`

**17 passed, two dependency warnings in 65.24 seconds**, exit 0. Includes the
actual entry-point revocation probes, simultaneous claims, failed-slot no-retry,
current controls, missing runner, authorized creation/replaced grant, DST gap
and autumn fold, plus the three existing lifecycle regressions.
The interleaving fixture was made one-shot because configure now acquires the
same lease; assertions remain unchanged and original test/log bytes are retained.

Remaining **P2**: next_cycle is displayed through Date.toLocaleString() with the
browser's default zone, while adjacent text names the schedule zone. An actual
script probe with UTC browser time and a 09:00 America/Chicago schedule displays
an unqualified next run of 3:00 PM. Format in the configured zone and include its
zone abbreviation/offset, or explicitly label the different displayed zone.
`logs/day8-scheduler-ui-6891f07.log` preserves this failed assertion. Existing
filter/render/partial-outage checks pass in the same Node fixture.

No production scheduling, inference or app edits. DB tests used disposable
fixtures and a coordinated slot; UI tests are Node DOM fixtures, not browser QA.
Hashes: `DAY8_SCHEDULER_CORRECTION_QA_HASHES.json`. Larger workflow evidence
refresh changes after this revision remain assigned to the separate reviewer.
