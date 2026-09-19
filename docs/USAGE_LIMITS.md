# Triad usage limits

Subscription CLIs and local Qwen track usage without daily token or compute caps
by default. This permanent policy replaces the temporary acceptance-test suspension.
Provider-side quotas still apply; Triad does not reset or bypass them.

Qwen also has an informational high-usage warning on the provider page. Initial
thresholds are 100,000 recorded input/output tokens or 3,600 seconds of elapsed
run time per UTC day. Change them under **Qwen usage alerts**. Crossing either
threshold shows a warning, without pausing work, changing readiness, or enabling
daily caps. The warning is shown in Triad, not sent as an external notification.
It counts all recorded real Qwen runs for the day (including failures), excludes
reservations and simulated runs, and resets with the next UTC day. Elapsed run
time is not a measurement of CPU load or memory consumption.

Open **Settings / AI Providers → Daily usage caps** to enable optional daily token
and compute caps for subscription CLIs or local Qwen. Unlocking settings requires
the local operator token. Saving is audited and replaces any temporary suspension.
The numeric ceilings are the existing autonomy limits. Enabled caps apply per
billing category per UTC day, including usage already reserved earlier that day.

Paid APIs retain the global and per-agent spending ceilings, per-run cost checks,
credential requirements and explicit fallback policy. Their daily token/compute
ceilings remain enforced. API spending is still disabled on this installation.
New subscription/local reservations do not consume API token/compute allowances.
Historical reservations without billing metadata are conservatively treated as
unknown and counted against enabled caps; they are not relabelled retroactively.

The runtime allows one in-flight invocation per agent across workers and provider
tests. Busy invocations are rejected before inference or reservation. All runs
retain timeouts, output limits, isolated tool grants, kill-switch checks and review
requirements. No automatic inference retry loop was added; failures and provider
quota responses remain visible for operator-directed recovery.

Actual token usage remains in Usage records and the provider cards. Reservations
remain in the audit ledger, including failures; optional caps use reservations,
not a claim that estimated tokens equal actual usage. Paid budget accounting stays
conservative. Model responses cannot select billing categories or change caps.

## Verification on 2026-09-18

54 provider/budget/autonomy regression checks passed in
`logs/non-api-budget-tests.xml`; five targeted routing, optional-cap, authorization
and concurrency checks passed in `logs/non-api-routing-tests.xml`. Ruff, JavaScript
syntax and whitespace checks passed. Browser inspection confirmed both optional
caps show **Track usage only** and the banner reports caps off.

Real post-change connection proofs: Codex
`53141c6d-5169-47f6-87b3-cdec147b8286` and Qwen
`df5fab16-4869-4d47-9303-8070437bab61`. Their audited reservations recorded
SUBSCRIPTION/LOCAL billing, daily caps not enforced, no temporary suspension,
and retained usage. The paid API ceiling remains $0.
