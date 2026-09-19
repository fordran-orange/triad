# Day 7 B2 runtime/native resources — independent QA

**CHANGES_REQUIRED** at exact implementation revision `9bd28ade3628f695e924d58331e4cc851f9b8b9c`. Reviewer `/root/day6_qa_a`, independent from builder `/root`, 2026-09-19. Resource defaults and HTTP changes in the later B3 segment are excluded.

## Required corrections

1. **P2 — Codex filesystem operations bypass shared tool accounting.** `app/trading_core/providers/codex_executor.py`, `CodexExecutor.mediate`, calls `resources.consume_tool()` only for `process/start` and `fs/readFile`. Allowed `fs/getMetadata` and `fs/readDirectory` operations do not consume the run-wide tool allocation. Repeated workspace operations therefore bypass the WorkItem tool threshold until the separate protocol-frame safety ceiling. Count allowed filesystem operations against the shared tool allocation while keeping pure protocol initialization distinct. Independent mediation tests reproduce zero consumed calls for each operation when one is expected.
2. **P2 — a failed text read is recorded as successful progress.** `app/trading_core/gateway.py`, `ToolGateway.read`, calls `resources.observe('authorized_read', ...)` before decoding bytes as UTF-8. An invalid UTF-8 file raises `UnicodeDecodeError` to the caller but leaves canonical ResourceProgress that can justify extensions. Record successful progress only after the complete read/validation/decode operation succeeds. A disposable real-resource-session test reproduces the false progress entry.

No implementation was modified by QA. Preserve these findings and repeat independent QA after correction.

## Exact-source test provenance

Before B3 edits began, archived committed source with `git archive 9bd28ad` into ignored `logs/day7-b2-qa-exact-9bd28ad.zip` and extracted it. Tests execute inside that frozen snapshot, using its app/config/tests and `TRADING_HOME`, through `logs/day7-b2-qa-run.py`. Database credentials are passed in the child environment without logging or writing credential values. PostgreSQL tests use the existing disposable database/namespaced graph fixture. No production data writes or live provider inference were initiated; offline container tools run against fixture files.

This avoids the shared-checkout revision ambiguity from the previous segment. The independent test file is copied into the snapshot separately and hashed below. Later B3 working-tree modifications cannot affect these results.

## Independent tests and observations

- `tests/test_resource_runtime.py tests/test_native_agents.py tests/test_codex_executor.py`: **57 passed, 2 existing dependency warnings in 28.93s**, exit 0. Covers native protocols, command/path/privacy boundaries, shared resource plumbing, repeated-read thrashing and native cancellation.
- New `tests/test_day7_b2_qa.py`, first five cases: **3 passed, 2 failed in 15.54s**. Actual elapsed-time continuation beyond a one-second initial allocation completes the same adapter invocation without cancellation or immutable budget mutation. Real authorized fixture-file progress supports output expansion; bounded input context expands before execution. The two failures expose uncounted Codex filesystem operations.
- Three further new boundary cases: **2 passed, 1 failed in 12.03s**. Unapproved API context extension blocks before the provider executes; a specialist output extension requires a separately reviewed lifetime grant and retains its reserved token quota. The failure exposes progress recorded for an undecodable text read.
- Existing inflight kill/late-output/new-request/merge/legacy enforcement test, independently repeated in the same frozen source: **1 passed in 7.67s**, exit 0.

All runs report the same two known TestClient dependency deprecations. Root's separate 38-test broader resource/Day 3 run passed 218.38s and was reviewed as supporting evidence, not duplicated here. Overall new adversarial coverage has **5 passing and 3 failing cases** at this revision.

Logs: `logs/day7-b2-independent-tests.log`, `logs/day7-b2-independent-adversarial.log`, `logs/day7-b2-independent-boundaries.log`, `logs/day7-b2-independent-kill.log`, with matching `.exit` files. Exact implementation/archive/runner/test/results hashes are in `DAY7_B2_HASHES.json`.

## Scope and remaining acceptance

Source review confirms runtime validates canonical work identity/permissions/persisted policy before trusted ResourceSession construction; cost/specialist review restrictions remain; no provider gains a shell, host credentials, broader file scope or paid fallback. Time extensions reach the running adapter rather than restarting it. Resource denial retains BLOCKED_RESOURCE_LIMIT usage/product evidence. Shared tool accounting and progress freshness need the two corrections above.

This review does not assert larger defaults, HTTP generation handling, live subscription inference, overall Phase 2 or Day 7 completion. The B2 correction gate must pass before accepting this implementation segment.

Independent regression Ruff check passes after an import-order-only cleanup. No assertions changed; the hash manifest separately retains the exact executed snapshot test bytes.
