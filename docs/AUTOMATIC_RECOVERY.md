# Triad automatic recovery

The three-provider cycle automatically retries recognized stopped read-only failures. This covers proposal authoring/review, implementation QA calls and debrief calls. It keeps the same provider, context, schema and granted paths. It does not replay completed product turns or retry a workspace implementation with an uncertain outcome.

A native runner must confirm it stopped before recovery can begin. Retryable failures are an exhausted time extension with no new progress, native turn interruption, missing final execution evidence, or missing required read evidence. Authentication, executable changes, permission failures, scope violations, paid resource limits and actual reviewer rejection are not retryable infrastructure failures.

There are at most two additional attempts for the same request and six across a cycle, with guarded backoff. Existing bounded response-format correction, citation correction, proposal revisions and debrief corrections remain active. Failure and usage records are retained; retries never refund inference usage, invent approvals or waive acceptance checks. `ProductAutoRecovery` records explain retrying, recovered and needs-attention states on the cycle history page.

Codex now reports completed authorized file reads as deduplicated resource progress. Re-reading identical bytes does not earn another extension. Failed native runs preserve observed tool evidence and measured usage when available. Missing measurements remain unknown.

Only explicit optional improvements create new quality debt. Positive review findings remain evidence without becoming debt. Historical debt is preserved, and debriefs must cite an actual resolution before claiming retirement.

## Existing blocked selection

The trusted host runner accepts `--resume-read-failure --cycle-id ID --operator-authorized` for a stopped time-progress failure during proposal review. It verifies the original authority, canonical failed read and completed proposal, unchanged product baseline, completed turn prefix and absence of unknown writes/merges. It reuses the saved proposal and obtains a fresh independent review. Cross-midnight recovery keeps the original day accounting, requires a cycle younger than 48 hours and refuses recovery once a newer daily cycle exists.

Historical cycles are not automatically dispatched. Process-crash recovery, ambiguous write outcomes, substantive implementation defects and persistent provider failures still require investigation. The daily schedule, authority rules, provider identities and usage policies are unchanged.
