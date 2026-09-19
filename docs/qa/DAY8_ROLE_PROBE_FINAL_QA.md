# Day 8 role overlay / probe — final independent preexecution QA

Reviewer `/root/day6_qa_b`; builder `/root`.
Exact revision: `5faaec90492d8fe0d1994f14942901184e1b1f92`.
Decision: **PASS** for this bounded correction and preexecution gate.

The rollout now appends a reviewed adoption instead of updating the immutable
agent definition. Agents.get resolves the narrow effective extension against the
base-definition digest, exact latest QA and current adopted capability version.
The production probe consults current capabilities before creating work and
retains substrate version IDs and current comparison evidence in its plan.
Engineering grant issuance now uses the WorkItem's original recorded authority
epoch instead of obtaining a fresh epoch after revocation.

Independent frozen execution: **9 passed in 16.98s**, recorded in
`logs/day8-role-correction-5faaec9.log`. A preliminary no-DB precheck run also
passed four cases in 3.25s. Two dependency deprecation warnings did not affect
results. Passing checks include:

- Exact reviewed rollout succeeds without changing the raw definition or its
  AgentDefinition history. Effective permission/capability additions are narrow;
  tools, paths, forbidden paths, authority and budget remain equal to the base.
- Missing QA, missing rollout marker, unverified/restricted/wrong-model capability,
  wrong commit and product-scoped rollout/record ingestion are rejected.
- A later blocking QA, a superseding QA, capability downgrade or replacement
  version removes the effective extension. A fresh valid adoption is needed to
  restore it. A different base-definition digest cannot inherit the extension.
- The immutable-definition database trigger still rejects direct modification.
- Missing original RunAuthority prevents grant issuance. Kill/resume cannot
  refresh an existing WorkItem's stale epoch. The legitimate started-assignment
  path succeeds; wrong identity/path/role/permissions, scoped writes, provider
  disable and stale grant-use epoch still fail closed.
- Missing, wrong-model, restricted or unverified Claude text substrate stops the
  probe before a capability proposal or work dispatch. These prechecks use mocks
  only and make no provider or production calls.

The parent requested two existing positive QA fixtures be aligned with the new
contract: engineering grant setup now starts the WorkItem; role rollout asserts
unchanged stored definition and inspects effective Agents.get. Both were rerun.
Their prechange bytes are preserved as `logs/day8-engineering-qa-pre-authority.py`
and `logs/day8-role-qa-pre-overlay.py`, matching the earlier manifests' test hashes.
Initial CHANGES_REQUIRED reports and logs remain unchanged; the existing negative
immutability assertion was retained. The new independent fixture is
`tests/test_day8_role_correction_qa.py`; all three QA files pass Ruff.

Tests used the full frozen archive `logs/day8-role-5faaec9`,
TRIAD_INTEGRATION=1, disposable PostgreSQL and scoped graph cleanup. Reviewer A
finished before this run and reviewer C received the released DB slot afterward.
Later scheduler/workflow source changes were excluded. No implementation edit,
production call, real provider inference, capability adoption or role rollout
was performed by this reviewer.

This PASS permits the separately authorized bounded real probe to proceed; it
does not itself verify the provider's new capability. Actual probe evidence still
requires independent review before capability adoption and role rollout. The
product workflow and final Day 8 acceptance remain separate gates. Exact hashes
are recorded in `DAY8_ROLE_PROBE_FINAL_QA_HASHES.json`.
