# Day 7 B1 resource-policy foundation — independent QA

**CHANGES_REQUIRED** for B1 implementation commit `40da1678ec4ad3ac108615d8f6e78fdbf7f08981`. Reviewer `/root/day6_qa_a`, separate from builder `/root`, 2026-09-19. Scope is the unwired host policy service and protected record kinds; runtime/default/native-executor integration is explicitly not accepted here.

## Blocking finding

**P1 — a product-scoped resource service can mint host-owned progress and grants.** `ResourceSession.__init__` accepts a product-scoped ledger and immediately constructs unscoped `Records(Store(...))`. A caller holding the scoped product service can therefore initialize canonical allocation, submit an arbitrary `authorized_read` fingerprint through `observe()`, and obtain an ALLOW extension. The newly protected `HOST_RECORD_KINDS` reject direct product `Records.append` and `Ledger.put`, but this service path bypasses that same boundary.

The builder confirmed this is intended to be an internal trusted host executor API, not a product-controlled progress writer. Require unscoped Core construction before creating the unscoped host record writer, and keep later runtime wiring responsible for validating the canonical work/request before handing successful host-observed operations to the service. The work's actual product pause/stop controls must still apply through its canonical owner.

Independent disposable-database reproduction in `tests/test_day7_resource_policy_qa.py::test_product_scoped_service_cannot_mint_resource_truth` successfully created canonical progress and granted more tools from the scoped path, causing the expected PermissionError assertion to fail. No production database, provider inference or external cost was involved.

## Independent verification

- Existing suite: `TRIAD_INTEGRATION=1 .venv/Scripts/python.exe -m pytest tests/test_resource_policy.py -q` — **11 passed, 2 dependency warnings in 35.78s**, exit 0. Covers five resource types, append-only states, duplicate progress, terminal denial, API/unknown cost human review, eight-extension bound, concurrent same-threshold deduplication, kill and allocation-reset protection.
- New independent adversarial suite: same environment, `pytest tests/test_day7_resource_policy_qa.py -q` — **1 failed, 3 passed, 2 dependency warnings in 14.65s**, exit 1. Besides the bypass above, confirms an actual existing-budget rejection is durably DENY with zero grant/no extra reservation and remains terminal; an oversized request durably requires human approval; and all five resource truth kinds reject both direct product record-writing paths.
- Source review confirms per-run transaction locks serialize grant decisions and progress deduplication, content is hashed rather than persisted as text, scope digest is checked, denial commits before raising ResourceBlocked, extensions are finite, and API/unknown billing does not gain new cost authority.

Evidence logs: `logs/day7-b1-independent-tests.log` / `.exit` and `logs/day7-b1-independent-adversarial.log` / `.exit`. `DAY7_B1_HASHES.json` binds committed B1 source/test/build-report bytes and raw independent test/results.

## Revision/provenance limits

B1 `resource_policy.py` and the HOST_RECORD_KINDS additions remained unchanged during this review. Root concurrently developed separate, uncommitted lifecycle/timestamp changes in shared work/store/runtime/other files, including timestamp fields elsewhere in contracts.py. Tests ran in that shared checkout; they are not claimed to be a pristine whole-repository replay of commit40da167. The reproduced scoped-constructor bypass is directly in unchanged B1 implementation. Those unrelated lifecycle changes receive no approval here and need their own independent QA.

Preserve this finding and run distinct correction QA after hardening. No production state or implementation was modified by this reviewer; only independent tests/report/evidence were added. Resource runtime integration and overall Phase 2 remain incomplete.
