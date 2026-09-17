# Disagreement and evidence

Reviews record reviewer/worker, decision, actual change SHA, findings, repeated checks, assumptions and execution mode. A rejection or conflicting decisions on the same work/commit create a Disagreement with agents, conflicting claims, evidence, severity, status, resolution method and human-review requirement. The host does not count votes or silently discard dissent.

PostgreSQL preserves the canonical records. Neo4j projects review DISAGREES_WITH review and claim CONTRADICTS claim relationships plus work/commit lineage. Open disagreement blocks merge/continuation; the operator must resolve the underlying work through separately reviewed changes. There is no convenient majority-vote override endpoint.

Model statements remain assertions/assumptions, separate from host-verified Git/file/test evidence. Journal, proposal, review and outcome histories support future context retrieval without self-training. Successful output alone is not treated as proof of good judgment.
