# Mission 4 — Walk-forward validation and Core unthrottle (2026-10-10)

Follow-up to Mission 3 (`docs/MISSION3_AEGIS_WORKSTATION_SLICE.md`). Spec:
`docs/superpowers/specs/2026-10-10-aegis-walk-forward-design.md`; plan:
`docs/superpowers/plans/2026-10-10-aegis-walk-forward.md` (9 tasks, native execution chosen by
the operator). This record fills in task by task; sections marked "pending" are not yet done.

## Operator decisions (chat, 2026-10-10)

| Decision | Choice |
|---|---|
| Mission framing | Unthrottle Core first under governance; rolling walk-forward per side reusing the optimizer; Walk-Forward tab with apply; optimizer hygiene folded in; acceptance and milestone QA as in Mission 3; merge and push on the operator's call |
| Window scheme | Rolling, in bars (fixed in-sample length sliding by the out-of-sample length; contiguous, non-overlapping out-of-sample; chained capital) |
| Runner structure | One job runner, two job kinds, one lock and one 409 rule |
| Core change | One shared helper (`app/trading_core/process_power.py`) called by the gateway, the Triad worker and the Aegis worker; the operator's approval is the explicit Core governance decision; independent QA names the change |
| Execution | Native (inline), one branch `aegis/walk-forward` in the `C:\Triad` checkout |

## Measurements

### Before the restarts (Task 1, 2026-10-10 ≈ 18:50Z; 10 samples each, median / max)

| Route | Median | Max |
|---|---|---|
| `GET http://127.0.0.1:8000/aegis/api/status` (through Core's gateway) | 1,602 ms | 2,151 ms |
| `GET http://127.0.0.1:8000/triad/api/daily-schedule` (through the gateway) | 1,600 ms | 1,863 ms |
| `GET http://127.0.0.1:8000/health/live` (Core itself) | 30 ms | 35 ms |
| `GET http://127.0.0.1:8102/aegis/api/status` (Aegis worker direct) | 76 ms | 93 ms |

Observation: Core answers its own health route in 30 ms, so the 1.6 s is spent on the proxy
hop to a product worker, not on Core's own request handling. Whether the opt-out changes it is
what the "after" table shows.

Triad `DailySchedule` before the restarts: id `c99fa831-0c46-4908-b840-4cbb2d0992b5`,
`enabled: false`, `next_cycle: null`.

### After the restarts (Task 1, 2026-10-10 ≈ 19:00Z; gateway PID 25776 → 37244, Triad 7472 → 37848, Aegis 7840 → 11348)

| Route | Median | Max | Before |
|---|---|---|---|
| `GET http://127.0.0.1:8000/aegis/api/status` (through the gateway) | 359 ms | 538 ms | 1,602 ms |
| `GET http://127.0.0.1:8000/triad/api/daily-schedule` (through the gateway) | 356 ms | 455 ms | 1,600 ms |
| `GET http://127.0.0.1:8000/health/live` (Core itself) | 18 ms | 41 ms | 30 ms |
| `GET http://127.0.0.1:8102/aegis/api/status` (Aegis worker direct) | 63 ms | 107 ms | 76 ms |
| `GET http://127.0.0.1:8101/health/live` (Triad worker direct) | 4 ms | 27 ms | not sampled |

The proxied hop fell from about 1.6 s to about 0.36 s once the gateway opted out of power
throttling; the remaining ≈ 300 ms above the worker's own 63 ms is Core's proxy implementation
and is outside this mission (spec §9). After the restarts: `DailySchedule`
`c99fa831-0c46-4908-b840-4cbb2d0992b5` still `enabled: false`, `next_cycle: null`; the Triad
worker reports `loaded_revision dff1d3a` (it had been serving `9b61ed2`, the Mission 0 revision,
since before Mission 1); `GET /aegis/api/status` still `human_directed` / `CLOSED`. None of the
three stderr logs contains a "refused" line.

## What was built

pending

## Acceptance evidence

pending

## Rulings made during execution

pending (collected from the ledger at the end)

## Known limits

pending
