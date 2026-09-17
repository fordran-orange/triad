# Scheduling

`agents/day3.json` supplies scheduler enabled, timezone, time and explicit REAL/SIMULATED mode. Default: disabled, UTC, 14:30, REAL. The API process checks every 30 seconds; `tools/day3.py tick` performs one manual check. Configure a valid IANA timezone and desired local time through a human-reviewed file change. The service must be running for scheduled work.

At or after the configured time, a PostgreSQL advisory lease prevents overlapping cycles. A persistent unique date/mode slot makes repeated ticks idempotent across restarts. Separate REAL/SIMULATED cycle records do not grant separate daily agent improvement allowances. Kill/pause prevents dispatch. The scheduler does not catch up historical missed days, retry failed cycles automatically, or require midnight.

Daily provider reservations currently use UTC dates, while cycle scheduling may use its configured timezone. Keep UTC for aligned accounting boundaries; a different timezone changes the cycle date, not provider accounting's UTC reset. This is documented explicitly rather than presenting a local-midnight budget reset.
