# AI provider control — Day 5A implementation in progress

Open [Settings → AI Providers](http://127.0.0.1:8000/settings/ai-providers).
The dashboard also shows a Triad Intelligence panel. Operator mutations require the
existing bearer token, kept in page memory. Reloading locks the page.

Each logical agent has separate transports, preference, model selections, fallback
policy, enablement, diagnostics, usage and permission information. Installation,
authentication, reachability, inference verification and WorkItem verification are
separate signals. Successful real proofs do not expire with elapsed time. Installing
a CLI does not make it online. Policy, model and credential changes invalidate proofs;
detected changes to the executable, CLI/local version or endpoint require new verification.

The backend checks selected CLI and local connections on startup and every five
minutes. These checks detect versions, authentication and local reachability without
model inference, paid API requests, login prompts, or replaying failed work. Transient
connection/authentication failures block readiness; a later successful check restores
readiness when the verified setup is unchanged. Runtime authentication and isolation
checks still run before execution. Revoked logins and incompatible software updates
can require operator attention; ordinary idle time does not.

Refresh checks versions and supported authentication metadata. Test requests real
inference; Bounded WorkItem requests acceptance evidence. Qwen uses the existing
SUMMARY capability route. Models lists Ollama models or configured API models;
frontier CLI model discovery is not implemented and is explicitly labeled.

API credentials use Windows Credential Manager. Adding a key does not enable
fallback. Explicit API spending requires both per-agent and global daily ceilings,
configured token prices, and the normal WorkItem authority/budget checks.

**Not complete:** native CLI WorkItem isolation and execution, Grok subscription
authentication verification, CLI model discovery, the frontier acceptance WorkItems,
and the complete relay. Native execution fails closed with
`OuterBoundaryUnavailable`. Login alone will not remove that blocker.
Day 5 strategy discovery remains gated.
