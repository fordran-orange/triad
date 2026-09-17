# Provenance

Meaningful claims are typed FACT, OBSERVATION, HYPOTHESIS, DECISION, EXTERNAL_CLAIM, TEST_RESULT, ASSUMPTION or RECOMMENDATION. Provenance attaches source, timestamp, agent, optional confidence, evidence and work reference. FACT and TEST_RESULT validation requires evidence references.

At the provider-result boundary, FACT and TEST_RESULT claims are rejected even if the provider supplies a reference. A model cannot promote itself to a verifier. Host deterministic checks and independently recomputed hashes supply operational evidence; helper summaries remain unverified until reviewed. No automatic hypothesis-to-fact conversion exists.

PostgreSQL retains operational records and their original classifications. Neo4j projects identities, useful links and minimal descriptive attributes. Its label/relationship vocabulary includes agents, missions, work, journals, claims/evidence, policy decisions, reviews, files, commits and future dataset/experiment relationships. Day 2 instantiates only relationships justified by actual work. It does not fabricate experiments, datasets or agent-authored commits.

An outbox commits with canonical state so graph failure is visible and retryable. Replay uses stable IDs and MERGE; PostgreSQL remains authoritative. Query work detail for canonical events, records, lineage and explicit graph_error. Inspect projection backlog in the dashboard; graph absence during an outage is not evidence that no work occurred.
