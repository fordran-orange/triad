# Agent transports

Logical assignments remain CODEX, CLAUDE, GROK and LOCAL_QWEN. Transport IDs:

| Agent | Default | Optional |
|---|---|---|
| CODEX | codex_cli | openai_api |
| CLAUDE | claude_code_cli | anthropic_api |
| GROK | grok_build_cli | xai_api |
| LOCAL_QWEN | ollama | none |

`AgentTransport` describes detection, installation, authentication, health, models,
execution, cancellation, usage, billing and capabilities. HTTP adapters preserve
the existing schema-validated data-only runtime. CLI adapters currently implement
installation/auth controls and diagnostics, but deny native WorkItem execution.

Runtime validates immutable assignments and persisted policy decisions before
selecting a transport. The router records selection or denial; API grants and
per-agent reservations serialize on the global control row. Existing runtime
reservations independently enforce the total daily cost/token/compute budget.
Reservations remain conservatively charged after unknown failures. Policy changes
advance the authority epoch, invalidating already-built run envelopes.

ManagedProcess launches fixed argument vectors with no shell interpolation,
an environment allowlist, bounded pipes and a deadline. On Windows it creates a
suspended process, assigns a kill-on-close Job Object, then resumes it. Cancellation,
timeout, parent exit and setup failure terminate the process tree. A Job Object
controls lifecycle; it does **not** isolate file access, credentials or network.
That missing outer security boundary is why native WorkItems remain disabled.

`TransportDecision`, `TransportRun`, `TransportVerification`, provider policy,
status and audit records use PostgreSQL and the existing Neo4j outbox. No fabricated
native command/file/Git evidence is emitted. Full native output parsers, isolated
worktrees and frontier relay integration still need implementation and verification.
