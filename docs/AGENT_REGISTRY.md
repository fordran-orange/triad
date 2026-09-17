# Agent registry

`agents/registry.json` is host-owned configuration validated as Agent records. It contains identity/name, provider/model, member/helper role, capabilities, allowed tools, default/maximum reasoning budgets, cost class, location, enabled status, review/execution eligibility, authority ceiling and integration status. Models are configuration, not hardcoded decisions in the orchestrator.

| Identity | Role / ceiling | Integration | Review |
|---|---|---|---|
| CODEX | Member / Tier 2 | Unconfigured cloud; deterministic demo | Demo only |
| CLAUDE | Member / Tier 2 | Unconfigured cloud; deterministic demo | Demo only |
| GROK | Member / Tier 2 | Unconfigured cloud; deterministic demo | Demo only |
| LOCAL_QWEN | Helper / Tier 0 | Ollama qwen3:4b | Ineligible |

Rotation is CODEX → CLAUDE → GROK → CODEX. Registry validation rejects duplicates and requires distinct eligible members. Local Qwen is not a fourth decision member. Only allowlisted, low-risk, Tier 0 helper tasks are eligible for automatic local selection. Higher authority does not route locally to save cost. PolicyDecision persists the routed identity and routing reason; explicit operator assignments still undergo policy validation.

The helper allowlist covers journal summarization, log classification, metadata extraction, document tagging, context preparation, history compression, duplicate-note discovery, search keywords and material organization. Day 2's concrete inference adapter performs concise summaries; specialized typed outputs for the other helper capabilities require future adapters. No raw filesystem or shell tools are exposed to Qwen.

To add a provider, implement Provider/Reviewer adapters with validated outputs, update registry configuration as an operator, add contract/security tests, then supply credentials through ignored environment configuration. Merely adding a key does not implement an adapter. Agent code cannot edit its registry or grant authority.
