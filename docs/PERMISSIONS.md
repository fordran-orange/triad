# Permissions

`app/triad/control.py` evaluates every run and persists ALLOW, DENY, REQUIRE_REVIEW or REQUIRE_HUMAN_APPROVAL with reason, rules, version, evaluation time and routing explanation. Any money/trading effect or live tier is denied. Governance requests remain blocked for human action; Day 2 has no elevation approval endpoint.

| Tier | Intent | Day 2 enforcement |
|---|---|---|
| 0 Observe | Read/summarize approved context | Read only; helper ceiling |
| 1 Research | New research notes/evidence | Scoped new files under research/generated |
| 2 Development | Approved development artifacts | Scoped new files under app/extensions; no arbitrary shell |
| 3 Simulation | Future bounded simulations | Permission vocabulary reserved; no simulation engine installed |
| 4 Live | Future money execution | Always disabled |
| 5 Governance | Human policy changes | No agent grants; requests remain pending |

A tier is a ceiling, not a grant of every possible tool. The current broker implements read_file, new artifact writing and the deterministic documentation verification path. General test runners, branch/commit tools, arbitrary code editing, backtesting and paper trading are not exposed to agents.

ToolGateway checks the immutable work envelope on every call: explicit relative paths, allow/deny scopes, protected host files, tool/permission tier, size, call count and elapsed time. It rejects absolute/traversal/alternate-stream/reserved paths, symlinks, Windows reparse points and hardlinks. Writes must be in dedicated generated areas and use exclusive creation; existing files cannot be overwritten. Secrets, Git internals, environment files and host governance configuration are inaccessible.

Frozen models, host-only transitions and a PostgreSQL immutable-envelope trigger provide layered checks. Providers return artifact proposals; the host writes them. Agents cannot approve their own elevation, choose their reviewer after creation, mutate policy or bypass review. Model claims are untrusted data.

Trust boundary: the Windows operator, backend and installed Python adapters are trusted. Database admin credentials belong only to the host. Same-user hostile processes, TOCTOU filesystem races and malicious Python plugins require OS/process isolation before deployment beyond this local development setup. The loopback operator token authorizes actions, not arbitrary governance mutation. Keep the token out of model context.
