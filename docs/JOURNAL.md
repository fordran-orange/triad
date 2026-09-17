# Journal

JournalEntry in `app/triad/work.py` is canonical structured data. Fields include journal ID/time/agent/work/mission, objective, received context, actions, changed files, tests, results, failures, open questions, assumptions, decisions, evidence, next step, handoff recipient and Git commit. Day 2 also records event_kind (creation/review/failure) and execution_mode.

Accepted results and independent review each create a journal. Execution failures create a failure journal; policy decisions and blocked dispatches remain separately auditable in policy records and state events. The journal is stored in `triad.orchestration_records` within the same transaction as the state update before projection.

`app/triad/brain.py` generates `docs/vault/02_Journal/generated/<journal_id>.md` atomically from structured records. Open docs/vault in Obsidian if desired. Markdown is a derived human view; edits there do not change canonical records. Generated pages and artifacts are ignored by Git, while implementation code is committed.

Evidence uses source hashes and file references. git_commit identifies the host implementation used for the run; it does not claim a demo model authored that commit. Creation and review events preserve separate identities. For provenance-sensitive use, retrieve canonical records from the work-detail API alongside state events and lineage.
