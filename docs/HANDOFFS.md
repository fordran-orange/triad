# Handoffs

Handoff is a frozen validated record with ID, from/to agent, work ID, completed work, changed files, performed tests, evidence, known issues, unresolved questions, assumptions, recommended checks, Git commit and review request. Self-handoffs are rejected. The handoff is committed alongside the result and creation journal before review starts.

The reviewer receives a specific assignment plus Handoff and can retrieve the canonical work, result and journal. The original conversation is unnecessary. A review request explicitly asks it to verify inputs/artifacts independently. Handoffs retain unknowns rather than converting them to facts.

The UI displays handoffs from PostgreSQL, with the current work status. A handoff remains visible when a reviewer integration is unavailable. The next improvement assignment links a completed parent and preserves mission ID. Context assembly includes the matching parent handoff, recent same-mission journals, applicable policy decisions and bounded graph relationships.
