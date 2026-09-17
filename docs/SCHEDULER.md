# Scheduling

`agents/day3.json` supplies scheduler enabled, timezone, time and explicit REAL/SIMULATED mode. Default: disabled, UTC, 14:30, REAL. The API process checks every 30 seconds; `tools/day3.py tick` performs one manual check. Configure a valid IANA timezone and desired local time through a human-reviewed file change. The service must be running for scheduled work.

At or after the configured time, a PostgreSQL advisory lease prevents overlapping cycles. A persistent unique date/mode slot makes repeated ticks idempotent across restarts. Separate REAL/SIMULATED cycle records do not grant separate daily agent improvement allowances. Kill/pause prevents dispatch. The scheduler does not catch up historical missed days, retry failed cycles automatically, or require midnight.

Cycle and support execution pass the configured cycle date to daily reservations. Direct Ledger calls without a supplied date default to UTC. The dashboard currently groups usage timestamps by UTC day; use UTC scheduling for aligned display and reservation boundaries.
