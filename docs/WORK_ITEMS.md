# Work items

The canonical Pydantic contracts are in `app/triad/work.py`; generated JSON schemas are in `control-plane/day2`. Unknown fields are rejected. Records are frozen; collection fields are tuples. WorkItem contains identity/parent/mission, title/description/creator/time, assignment/status/priority/type, tools/path scopes, reasoning and compute budgets, permissions/risk, inputs, expected outputs, acceptance criteria, review assignment, run timestamps, structured result and failure reason. Day 2 adds authority tier, money/trading/governance flags and optimistic revision.

`triad.work_items` stores the validated JSONB document with indexed identity, mission, status and revision. `triad.work_events` stores the ordered lifecycle. PostgreSQL triggers reject changes to the assignment and authority envelope, including reviewer, allowed paths, budgets, criteria and inputs. Assignments are chosen before insertion. Create a new item when intent changes.

`transition()` contains the explicit allowed edges. Only the host actor can transition. An IN_PROGRESS item requiring review cannot go straight to COMPLETED. APPROVED_BY_REVIEWER requires the matching independently assigned review. Terminal states cannot restart; correction, blocked and failed work reenter validation. See tests for invalid edges and stale revisions.

Default budgets are 12,000 input characters, 512 output tokens, 90 seconds and 30 tool calls. Schema ceilings are 32,000 characters, 2,048 output tokens, 120 seconds and 100 calls; agent-specific reasoning limits may be narrower. Qwen uses an explicit output/context ceiling and HTTP timeout. Timed-out inference may continue at the upstream server until its output limit; no process-level cancellation is claimed.
