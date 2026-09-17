# Autonomy budget

PostgreSQL transactions serialize reservations with control changes. Defaults: three primary changes/opportunities per day, one per primary member; $0 cloud spend; 160,000 conservatively reserved tokens; 1,800 reserved compute seconds; one repository; zero migrations/high-risk changes. Per change: three files, 180 changed lines, 120 seconds per provider call, 24,000 input characters, 2,048 output tokens, $0.25 maximum estimated run cost. Writable directories are `docs/improvements` and `research/improvements`.

Reservations include maximum configured provider duration and conservatively estimated input/output tokens. Unknown upstream usage after failures remains reserved. Attempts, not just successful changes, consume capacity. An exceeded ceiling raises AUTONOMY_BUDGET_EXHAUSTED and prevents dispatch. Exhausted capacity waits for the next accounting day or separately authorized governance work; there is no agent reset route.

Authenticated UI/API controls may lower limits only. Models cannot change authority tiers, paths, review requirements, budget limits, repositories or trading permissions. More-reasoning requests are recorded but cannot rewrite these limits. Current checks reject policy/governance paths, shell/executable files, traversal, symbolic/reparse links, hard links, stale source hashes and oversized diffs.
