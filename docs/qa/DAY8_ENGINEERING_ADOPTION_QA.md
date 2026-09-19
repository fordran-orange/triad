# Day 8 capability adoption verification

Verdict: **PASS**. Independent reviewer: `/root/day6_qa_b`. This follow-up was read-only against production; no vendor calls or work transitions were performed.

The adopted proposal `e5b68940-e51d-49f8-86a4-a904a9dafc7b` and current capability version `b837ff38-b331-4c4d-acd7-8ac75ccd4877` match the independently accepted normalized digest `ed98a219b9256fbedb3e0402d7c43caf1349815188f846ef430c3c1b49fab924` exactly. Implementation `e02ad6fc-8fdf-4650-89b4-e6f54417213d` and latest passing QA `a83f27f9-d510-40c0-8854-12c40d6fd2f7` bind that digest. Canonical QA correctly names `/root/day6_qa_b`.

Role adoption `f6b2e4b6-e375-46ce-ac16-5ff79ac2f78c` binds the same QA and capability version, with `engineering-role:CLAUDE:isolated_product_ui_edit` present in both implementation and QA evidence. Raw CLAUDE definition fingerprint remains `b3e9ac4e351ce61d320260fae47530466853605565a39a42412c6d53aec0cfbb`. Effective permissions add only `write_code`; effective capabilities add only `isolated_product_ui_edit`. Tier, tools, allowed/forbidden paths, provider/model/transport and eligibility match the base. Existing separately governed resource-policy overlays are not attributed to this role adoption.

Probe work `b66984e4-73ad-40d9-b26d-26f1e0997faf` remains AWAITING_REVIEW with immutable CLAUDE builder / CODEX reviewer assignment at this audit. The actual independent reviewer was the Codex desktop QA agent, not a native CODEX CLI provider invocation.

The existing Review record accepts explicit execution provenance. Recommended completion: preserve `reviewer=CODEX` as the assigned role; set `execution_mode=codex_desktop_independent_host_qa`; explicitly identify actual reviewer `/root/day6_qa_b`, canonical QA and report hashes in findings/evidence; state that no native CODEX provider call or host asset merge occurred. Ingest through the normal `Orchestrator.apply_review` guard and reviewer checks, which transitions APPROVED_BY_REVIEWER then COMPLETED. Any handoff lifecycle action should likewise be described as host-recorded assigned-role processing. Do not synthesize Usage, native execution evidence or an AgentRunResult. This capability-experiment closure does not replace native provider QA required by the real product cycle.

Read-only snapshot: `logs/day8-adoption-independent.json`. Earlier real-probe acceptance and its frozen hash manifest remain unchanged. Completion itself remains to be performed and verified by the parent operator agent.
