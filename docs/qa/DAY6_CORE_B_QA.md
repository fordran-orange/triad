# Day 6 Core B independent QA

Current final decision: **PASS_WITH_OBSERVATIONS** after correction 2; see the final section for the approved snapshot and retained Core C gate.

Initial decision: **CHANGES_REQUIRED**. The original failed review and correction history are preserved below. No implementation files were edited by this reviewer.

- QA run: `day6-core-b-independent-qa-20260919`
- Builder: root Day 6 implementation agent.
- Independent reviewer: `/root/day6_qa_b`.
- Baseline: `091874ac1939dbca60dc651b6d90c48fa80a5130`; uncommitted B implementation identified by SHA-256 below.
- Capabilities used: source review, adversarial Python tests, disposable PostgreSQL integration, Neo4j lineage verification, concurrency interleaving.
- Scope: agent creation/definitions/lifecycle/promotion; reservation and runtime enforcement; reserved intelligence writes; graph projection. Routing/UI are later segments and are not approved by this report.

## Required corrections

1. **High: runtime accepts authority beyond a read-only specialist's grant.** `app/trading_core/runtime.py:455-488` checks the request against its caller-selected role, but does not compare requested tools or execution permissions to the canonical assignment and configured specialist grant. A specialist created with only `read_file` and a read-only child WorkItem successfully ran a `PROPOSE` envelope containing `propose_file_change` and `write_docs`. Reproduced by `test_runtime_cannot_add_tools_to_read_only_specialist`. Validate the effective bound specialist tools, execution authority, inherited exclusions and canonical assignment before invoking an adapter; preserve intentionally governed static compatibility without treating a caller's chosen role as authorization.

2. **High: release can undo an operator disable.** `app/trading_core/intelligence/agents.py:460-480` reads status, then writes a stale computed status without serializing against lifecycle operations. A deterministic two-thread interleaving disables a specialist after release reads ACTIVE; release restores ACTIVE. Reproduced by `test_releasing_a_run_cannot_undo_concurrent_operator_disable`. Preserve terminal/operator states with an atomic update or common locking strategy; test concurrent disable and terminate against release and reservation.

3. **High: persistent adoption can bypass usefulness evidence validation.** `app/trading_core/intelligence/agents.py:517-532` trusts a proposal's evidence list, although product-scoped `Records.append` intentionally permits proposals. A product can directly append an empty `AgentPromotionRequest`; after a separately QA-approved Core governance build referencing that request, promotion succeeds with zero usefulness records. Reproduced by `test_forged_empty_promotion_proposal_cannot_skip_value_evidence`. Revalidate the proposal at adoption, including at least two distinct qualifying runs, correct specialist/product ownership and independent passing QA for each. Calling `propose_promotion` must not be the only validator.

4. **High: promotion ignores active global controls.** `Agents.promote` does not consult the control plane. A valid two-evidence promotion still creates an ACTIVE persistent specialist after global kill. Reproduced by `test_promotion_cannot_ignore_global_kill`. Recheck global/product controls, provider eligibility and active-agent ceilings under adoption serialization before creating the new identity.

5. **Medium: dynamic runtime does not honor the granted timeout.** `app/trading_core/runtime.py:522,552,575` uses only global timeout. A child granted one second (and a canonical one-second WorkItem) accepted a 1.4-second adapter result. Reproduced by `test_runtime_honors_child_timeout_not_global_timeout`, using a valid read-only SUPPORT envelope. Enforce the minimum applicable global, WorkItem and specialist deadline and preserve that effective reservation/provenance value.

6. **Medium: a disabled provider identity can create specialists.** `app/trading_core/intelligence/agents.py:218` calls guard with only WorkItem, so `disabled_agents` is not checked. After disabling CODEX in Core, its active parent request is still ALLOW. Reproduced by `test_disabled_provider_cannot_create_specialist`. Include the parent's effective executor identity in current control validation, including dynamically bound parents.

## Test evidence

All commands used `C:\Triad\.venv\Scripts\python.exe`, with `TRIAD_INTEGRATION=1` for integration runs. PostgreSQL fixtures were disposable; no paid or real inference was used by these QA tests.

- `tests/test_intelligence_agents.py` plus `tests/test_architecture.py`: **14 passed**, as part of `logs/day6-core-b-independent-qa.log`. Covers allowed creation, path/tool/authority ceilings, delegation depth, expiration, parent terminal state, independent static configuration, Core import boundaries and owned graph lineage.
- `tests/test_day3_integration.py`: **16 passed**, 123.41 seconds. Log: `logs/day6-core-b-independent-static.log`. Static execution and its existing governance/regression paths remain compatible.
- Final six-test adversarial run before race addition: **1 passed, 5 failed**, 23.48 seconds. Log: `logs/day6-core-b-independent-adversarial.log`. Atomic simultaneous reservation passed: one reservation is granted and the other denied by either quota or advisory-lock conflict; active count remains one.
- Dedicated concurrent release/disable test: **1 failed**, 5.80 seconds. Log: `logs/day6-core-b-independent-race.log`; actual final status ACTIVE, expected DISABLED.
- New independent regression file: `tests/test_day6_qa_b.py`, seven tests total. Initial harness mistakes (the fake adapter omitted metadata attributes and the concurrency test failed to accept the documented ConcurrentUpdate denial) were corrected before the final adversarial run. Original failure output is preserved; those harness failures are not implementation findings.
- Browser checks: not applicable to this bounded backend-only segment; UI changes require separate later QA.
- Packaged SQL copy is byte-identical to canonical migration 011.

## Production graph safety

Read-only canonical link verification against production PostgreSQL and shared Neo4j after the QA runs found **87 assigned works, 23 reviews, 47 handoffs, zero missing links**. No Agent-node cleanup recurrence was observed. Evidence: `logs/day6-core-b-independent-graph.json`; verifier: `logs/qa_b_graph_check.py`. Test static AgentDefinition records use UUID record IDs; shared Agent nodes are not included in fixture cleanup IDs. No recovery or production mutation was performed by this reviewer.

## Architecture and limitations

Core owns the new mechanics and no Core-to-product import was added. Product-scoped specialist reads and records remain private under the current tests. Lineage creation is persisted in PostgreSQL and Neo4j. Budget/reservation counts are monotonic. The ownership boundary is trusted local host/service scoping, not hostile arbitrary Python code isolation. No P2P behavior, exchange setting, live trading authority or scheduled autonomy was changed during QA.

Separate correction implementation and a new independent QA run are required. This revision must not merge as passing Day 6 B. The six findings above are required changes, not deferred QualityDebt.

## Exact implementation hashes (SHA-256)

| File | SHA-256 |
| --- | --- |
| app/trading_core/intelligence/agents.py | FE6F4E9AC5C8BA69BD02B87C58E225CD6381EEA4A88351D0D1C4FD6CDF682419 |
| app/trading_core/intelligence/records.py | 2D55DB70758C55E0FCC23A846FE80353E38D71FCB18AC1E78343DE2B04FAADC4 |
| app/trading_core/ledger.py | F7B18E0C83AB4C93E86F9E38DCAF10D0944750C8E5DBBE776E6D21132549AA44 |
| app/trading_core/runtime.py | 7392539937F565FF41A0CDF4F7E02C404E6CA50B68E1CBC44DDEC8602664FC95 |
| app/trading_core/brain.py | 8CDF4D181A2A824B156A14F054648C24AB3D3B2680A9D8FA24450AF5CD4308D5 |
| infrastructure/postgres/011_agent_lifecycle.sql | 44B51F857FF3CAB9E5FE14C4796E47CDB5BCFCB36A3DF8939B7C8EE8E9A8810E |
| app/trading_core/resources/sql/011_agent_lifecycle.sql | 44B51F857FF3CAB9E5FE14C4796E47CDB5BCFCB36A3DF8939B7C8EE8E9A8810E |
| tests/test_intelligence_agents.py | 4AFCF73A0DC9FAB3C2A6AD33599C5E0398548B69ADE5857CA0149BFA413AE8F6 |

## Correction 1 independent QA

Decision: **CHANGES_REQUIRED**. The original six findings are fixed and their regression tests pass. Two additional authority/projection seams are reproduced below. Initial findings and hashes above remain preserved.

Reviewed correction hashes (unchanged files retain the initial table's hashes):

| File | SHA-256 |
| --- | --- |
| app/trading_core/intelligence/agents.py | 314BA390EF6548F3CDF89C5193D82750F498C1F994F4DF38FCFC1C9182988E0A |
| app/trading_core/runtime.py | 588E4AD07805E771EFD0218082C4B2E3E2D2CF1187817F84F3B1ED1C3BF12336 |
| app/trading_core/ledger.py | E85B2CE0EE55B4C6C402147E3A901BCB1723A2A54905E0293FCB0CF8DA36C5DB |
| tests/test_provider_integration.py (corrected admission fixture) | ADC255B5451CAEB354E245056D56F23403C7F01616F421DB72A01EC56DB5F35A |

Repeated the original seven independent tests plus agent tests, provider integration, static Day 3 integration, relay and architecture: **55 passed, one incomplete-fixture failure**, 249.84 seconds, in `logs/day6-core-b-correction-independent.log`. The admission-lock test used an object containing only agent_id; new reservation requires WorkItem ID and token budget even on its unlocked paths. Builder corrected only those fixture fields, preserving real reservation and concurrency assertions; independent rerun **passed** in `logs/day6-core-b-correction-cost.log`. Runtime validation was not weakened.

New promotion checks independently passed valid persistent adoption with retained owner/budget/tools, duplicate adoption rejection, foreign-product evidence denial, product pause, provider disable, and active-agent ceiling. Initial ceiling test tried to mutate a frozen policy; the corrected fixture substitutes a lower immutable policy and passes. These are harness corrections, not product fixes.

Additional required changes:

7. **High: zero-dollar specialist grant is not enforced by runtime.** Runtime cost validation uses request/global budgets but not the AgentDefinition's max_cost_usd. With the disposable test database's host day budget set to $1, a specialist explicitly granted $0 completed through a fake adapter estimating $0.01. `test_runtime_honors_zero_cost_specialist_grant` fails with DID NOT RAISE PermissionError. `logs/day6-core-b-correction-cost.log`: **1 failed, 2 passed**, 11.50 seconds. The production day budget remains zero and no paid provider was called; that existing global protection initially masked the missing child ceiling. Enforce the bound configured-agent cost grant independently of broader host policy.

8. **High: legacy product ledger writes can forge canonical graph intelligence.** Product-scoped Records.append protects AgentDefinition and other host-only evidence kinds, but product-scoped Ledger.put accepts the same kinds. A synthetic P2P AgentDefinition targeting a disposable Triad specialist projected successfully and changed its ConfiguredAgent owner to p2p and provider to forged. `test_legacy_product_records_cannot_forge_configured_agent_truth` reproduces this; `logs/day6-core-b-correction-records.log`: **1 failed**, 7.93 seconds. Reserve host-only evidence consistently at both entry points, or reject noncanonical intelligence in projection. Check all reserved kinds, including lifecycle and QA evidence. The test targeted only its own random specialist ID, never shared static Agent IDs, and fixture cleanup removed it.

The expanded independent test file now contains fourteen tests including parametrized cases. Production graph check after correction QA remains **87 works / 23 reviews / 47 handoffs / zero missing links**, read-only. No implementation or production data was modified by this reviewer. Correction 2 and another independent QA are required.

## Correction 2 independent QA — final B decision

Decision: **PASS_WITH_OBSERVATIONS** for the bounded Core B implementation. All eight reproduced implementation findings above are fixed and their independent regression checks pass. This approves progression to Core C; it is not approval of the entire Day 6 implementation or production autonomous operation.

Fresh independent execution:

- `tests/test_day6_qa_b.py`, `tests/test_intelligence_agents.py`, `tests/test_provider_integration.py`, `tests/test_day3_integration.py`, `tests/test_provider_relay.py`, `tests/test_architecture.py`, `tests/test_intelligence_capabilities.py`, and `tests/test_day6_qa_a.py`: **75 passed**, 298.76 seconds. Evidence: `logs/day6-core-b-correction2-independent.log`.
- Expanded independent B adversarial/seam tests: **18 passed**, 70.37 seconds. Evidence: `logs/day6-core-b-correction2-seams.log`. This adds all protected intelligence kinds through both write APIs, canonical intelligence projection despite legacy mirror tampering, successful runtime configured-agent Usage identity, correct child-to-parent lineage with no reverse edge, and owning-product pause enforcement during unscoped host dispatch.
- Ruff formatting/checks pass for the independent test file. Production read-only canonical graph check after the suites: **87 works, 23 reviews, 47 handoffs, zero missing links**.
- No paid inference, production permission changes, P2P behavior changes, exchange opening, live trading, scheduled autonomy, or browser/UI changes occurred during this QA. The zero-cost test raises only its disposable fixture database's host budget to verify that the stricter specialist ceiling is independently enforced.

The runtime now enforces configured-agent cost/time constraints as well as canonical WorkItem authority, and retains the configured identity in Usage. Reservations remain atomic and operator-disabled state survives concurrent release. Promotion revalidates distinct owned usefulness records and current controls; positive adoption preserves the grant. Product-originated writes cannot publish protected intelligence through either append API or the legacy ledger, and graph projection uses matching canonical immutable evidence.

### Retained observation / Core C acceptance gate

Quality debt `DAY6-B-QD-001` (medium): shared Neo4j `ConfiguredAgent` static keys still use CODEX/CLAUDE/GROK/LOCAL_QWEN across PostgreSQL databases. Disposable fixtures seed test model metadata into those graph keys. UUID intelligence-record IDs prevent destructive Agent cleanup, but do not isolate static ConfiguredAgent metadata across databases. Canonical runtime/registry authority remains in PostgreSQL, production configured identities have not yet been seeded, and the tested random specialist IDs are isolated. This is non-blocking for the current B segment only. Core C must namespace configured graph identities consistently across nodes, edges and lifecycle updates, retain the canonical agent_id separately, and independently test cross-database isolation **before production static seeding or overall Day 6 acceptance**. Owner: Core C builder. Status: OPEN, explicitly accepted for the next bounded segment. No other B required changes remain.

### Final verified B hashes (SHA-256)

Baseline remains `091874ac1939dbca60dc651b6d90c48fa80a5130`; this table identifies the uncommitted implementation and test snapshot approved here. Earlier failed revision hashes and evidence remain above.

| File | SHA-256 |
| --- | --- |
| app/trading_core/intelligence/agents.py | 314BA390EF6548F3CDF89C5193D82750F498C1F994F4DF38FCFC1C9182988E0A |
| app/trading_core/intelligence/contracts.py | FFFFFE4C37CE4CA673851796F5D2F34E77FEE4564F91FE26AA55F2AD72FC39C4 |
| app/trading_core/intelligence/records.py | 2B3F81243B2906A01CB89000428B09157E4340FF791F74FDF41EA39CBDB5CDF8 |
| app/trading_core/runtime.py | FDB9F386483EC276243BAAD7FCBC0D4D03C9CA707FFDA87FC559042619904335 |
| app/trading_core/ledger.py | 3BCF2FD17F6276F79C640F9BCAD6C19F202E58572A19D3BBC968122E5B6948A4 |
| app/trading_core/brain.py | 60350466655BC048A4297563BE6E9E7B656F53291C46F74803D41382D7FCCFE5 |
| infrastructure/postgres/011_agent_lifecycle.sql | 44B51F857FF3CAB9E5FE14C4796E47CDB5BCFCB36A3DF8939B7C8EE8E9A8810E |
| app/trading_core/resources/sql/011_agent_lifecycle.sql | 44B51F857FF3CAB9E5FE14C4796E47CDB5BCFCB36A3DF8939B7C8EE8E9A8810E |
| tests/test_intelligence_agents.py | 4AFCF73A0DC9FAB3C2A6AD33599C5E0398548B69ADE5857CA0149BFA413AE8F6 |
| tests/test_provider_integration.py | ADC255B5451CAEB354E245056D56F23403C7F01616F421DB72A01EC56DB5F35A |
| tests/test_day6_qa_b.py | D52B3B64E503CCE70F6BCF07E035C1F099BF2FC7312DE66785C3CA077B36373A |
