# Explicit API fallback

Default: CLI preferred, `NEVER`, per-agent API budget zero. No API key is read
from `.env` or inherited environment by the new production transports.

- NEVER: deny fallback unless the operator authorizes a single active WorkItem.
- ASK_EACH_TIME: deny pending an explicit one-time operator grant.
- ALLOW_WITHIN_BUDGET: allow configured API fallback within the operator's budgets.

A one-time grant binds agent and active WorkItem, expires in 15 minutes, and is
consumed transactionally with the transport reservation. It does not override
disabled agents, kill/pause, assignment/policy validation, model configuration,
provider health, prices, per-run limits or global/per-agent budgets.

The provider UI can explicitly authorize the global daily API ceiling (0–25 USD)
and each agent's policy. This action is audited and advances the authority epoch.
The previous lower-only control remains lower-only. Existing assignments may need
a fresh host policy envelope after operator changes; no agent can raise a budget.

Explicitly selecting an API preference or its Test button is an API request,
not hidden fallback. Tests still require prices, stored credentials and budget.
Failed/unknown attempts retain conservative reservations. Optional API transports
may remain NOT_CONFIGURED and do not block a fully verified subscription gate.
