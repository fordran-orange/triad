# Human controls and kill switch

All mutations require the local operator bearer token. Controls include pause/resume, stop WorkItem, disable/enable agent, deny/approve within-policy proposal, require human review, lower limits and kill. Reads remain available. No operation activates live trading or raises a permission tier.

Pause/kill increments a persisted cancellation epoch. Dispatch and merge acquire the same database control lock and recheck policy; running provider waits poll control every 0.2 seconds. Late results are discarded when the original epoch is invalid, even after resume. Subsequent writes/commits/merges are rechecked. Scheduler ticks respect the controls. Stopping a WorkItem is persistent.

This is software cancellation. An already dispatched HTTP request can continue computing or billing upstream until it finishes/times out; Triad cannot promise server-side cancellation. A merge already admitted under the control lock completes before a concurrent kill transaction takes effect. No new merge is admitted after that transaction commits. Conservative reservations are retained.

Integration tests cover an in-flight slow provider, kill, blocked new calls/merge, resume epoch invalidation and retained Day 2 entry points. Inspect records after stopping; use documented recovery for interrupted work. Resume does not revive cancelled authority or reset budgets.
