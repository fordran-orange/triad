# Independent review

The Reviewer protocol accepts WorkItem, Handoff and a bounded ToolGateway and returns a structured Review. Review includes ID, reviewer, work ID, decision, findings, severity, required changes, optional improvements, evidence checked, repeated tests, timestamp and execution mode.

Allowed decisions: APPROVE, REJECT, REQUEST_CHANGES. Host validation requires the assigned eligible reviewer, a different identity from the worker, the correct work ID and AWAITING_REVIEW state. The same transaction stores the review and review journal before the final completed transition.

The documentation demo uses two separate deterministic implementations. The worker constructs a report; the reviewer reads that report, independently rereads each original, recomputes SHA-256 and checks headings and exact input coverage. Tests alter source contents after work and verify REQUEST_CHANGES. Other tests exercise rejection, self-review denial and mandatory review bypass denial.

These checks demonstrate independent evidence verification under separate logical identities. They are not calls to Claude, Codex or Grok APIs and are not general code-diff/security review. Genuine cross-model review is BLOCKED — REQUIRES HUMAN/EXTERNAL PROVIDER ACTION plus adapter implementation. The actual Qwen result stays pending rather than receiving a fabricated cloud approval.

No automatic self-approval, reviewer-role promotion or human override endpoint exists. An unavailable adapter preserves the pending work/handoff. A thrown review exception also leaves pending state so an operator can diagnose and retry.
