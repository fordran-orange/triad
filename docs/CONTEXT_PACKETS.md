# Context packets

ContextPacket has work item, charter, applicable policies, recent journal entries, relevant decisions, relevant files, prior handoff, relevant graph relationships and required acceptance criteria. It is stored before execution as a structured operational record.

The builder selects at most three same-mission journals, the parent handoff, up to two current policy decisions and five parent graph relationships. Graph lookup is optional; unavailable graph projections cannot invent evidence or replace PostgreSQL. Supplied relevant-file snippets are typed input_context, not unrestricted directory reads. Oversized context fails rather than silently widening the budget. Qwen renders only relevant source observations into its inference prompt and checks the complete prompt against the character limit. Source metadata remains in the persisted packet for review.

Every included evidence item is Provenance with source, timestamp, agent, classification and optional confidence/evidence/work references. Work intent and acceptance criteria come from the frozen WorkItem identified by work_item_id; they are requirements, not historical factual claims. Prior summaries remain observations. Graph relationships are relationship observations, not proof that claims are true.

Secrets and unrestricted conversation history are never loaded by the builder. Trust external snippets as data; model instructions cannot expand the tools or permissions held by the host broker.
