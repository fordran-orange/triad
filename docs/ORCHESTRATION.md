# Orchestration

`app/triad/orchestrator.py` owns execution. Providers receive a frozen WorkItem, a bounded ContextPacket and a host ToolGateway. They return data in WorkResult; they do not receive database handles, credentials, shell access or state-transition authority.

The successful review-required path is CREATED → VALIDATING → APPROVED → ASSIGNED → IN_PROGRESS → AWAITING_REVIEW → APPROVED_BY_REVIEWER → COMPLETED. DENY ends in REJECTED. Human governance and unavailable integrations end in BLOCKED. Tool/provider failures become FAILED with a structured failure journal. A reviewer can request CHANGES_REQUESTED or REJECTED. Retrying failed/blocked/correction work re-evaluates the immutable assignment.

A PostgreSQL advisory lock serializes each run. Optimistic revision checks prevent stale writes. An atomic transaction stores each state event and associated records plus outbox entries. Neo4j and Markdown are eventually consistent projections, replayed in order under a separate lock. Their outages do not erase accepted operational evidence.

Creation and review are separate journal events. The configurable rotation chooses the next eligible member as reviewer; a completed parent is required before its successor creates an improvement assignment. There is no scheduler, provider billing integration or real cloud execution on Day 2. Provider and Reviewer protocols are integration seams, not evidence of connected cloud models.

The safe demo inspects five architecture documents, writes a report with source hashes and headings, then independently rereads all inputs and the output. This proves the work loop and evidence checking, not comprehensive semantic document consistency or autonomous software engineering.

Review adapter errors leave the work awaiting review; the operator may retry. Completed results are never silently accepted when review is missing. The host process and its Python adapters are trusted code: this is a broker boundary for model output, not a sandbox for hostile Python plugins or other processes running as the same Windows user.
