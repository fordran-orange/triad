# Agent Control Plane

Humans configure intent. The Control Plane compiles intent into validated runtime
policy. Agents may request greater authority but may never grant themselves authority.

Contracts cover model selection, reasoning depth, tool access, data scope, execution
permissions, risk limits, token/time budgets and live-trading authority. Day 1 allows
only documented read tools and isolated scratch-write permissions. All trading risk
limits are zero, live authority is false, and no broker execution exists.

`app/triad/policy.py` supplies immutable intent and policy models, deterministic
intent hashes, authority requests, compiler validation, and Protocol interfaces for
the future policy store, request queue and tool authorizer. Generated JSON schemas
live in `control-plane`. Unknown fields and unsupported tools are rejected. Local
workers have narrower task and compute ceilings.

`compile_policy` rejects agent principals and revalidates even unchecked model copies.
**This pure Python skeleton is not authentication or an OS security boundary.**
`TrustedPrincipal` must eventually be created by an authenticated host adapter;
an agent must never choose its own principal, call the compiler, edit policy files,
or obtain database/admin credentials. No API exposes policy mutation or compilation.
The present tests verify model behavior, not a production security boundary.

Future approval path: agent submits immutable request → human inspects policy diff,
risk and resource impact → authenticated approval → compiler validates against
organizational ceilings → host signs/stores version → isolated runtime consumes it.
Policy changes must be append-only audited, revocable, scoped and time-limited.
Runtime enforcement must validate each tool invocation and resolve filesystem paths
within scoped roots, enforce budgets and reject stale policy. Those adapters are
interfaces only on Day 1. Never run untrusted agents with this development account.
