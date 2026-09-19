# Core extraction verification

Acceptance is being finalized on branch `codex/core-extraction`. The permanent
`base/trading-core-v1` tag is withheld until the final checks pass.

Verified so far: recoverable Day-5A baseline; generic execution extraction;
scoped record/context/artifact access; separate Core/P2P/Triad processes; product
crash isolation and kill-switch enforcement; installed package resources;
151 unchanged historical artifact files; 59 preserved WorkItems; reversible
SQL up/down/up; identical output from both preserved deterministic experiments.

See `CORE_EXTRACTION_OPERATIONS.md` for launch commands, compatibility mappings,
the local single-user trust boundary, recovery and deferred capabilities.
