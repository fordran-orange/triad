# Billing and usage

Run usage records now include logical agent, provider, transport, requested model,
actual model when returned, billing source, tokens, duration, result and timestamp.
Billing values are SUBSCRIPTION, API, LOCAL or UNKNOWN. UNKNOWN is visible in UI.
The main intelligence panel shows each agent's current preference and billing.

Only API transport usage is included in estimated API dollars. Subscription
transports reserve zero API dollars; this is not a claim that subscription usage
has a known monetary value. Local usage is tracked separately. The UI does not
invent subscription token prices.

The HTTP adapter records the model returned by the provider independently from
the requested model. Native CLI token/model extraction still needs implementation.
Legacy runs retain UNKNOWN/legacy provenance rather than being relabeled as CLI.

API estimates require explicit input/output prices per million tokens. The router
reserves the conservative request ceiling. Daily accounting uses UTC. Reservations
are not refunded merely because output or billing evidence is missing.

Displayed retained usage is currently bounded to 2,000 recent records; the hard
budget checks use transactional reservations rather than trusting UI totals.
