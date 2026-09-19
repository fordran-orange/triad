# Day 7 B1 correction — independent QA

**PASS for the unwired host resource-policy foundation.** Exact B1 correction revision: `289c79787fe9181a07d0c29b98c51ffc06fce60d`. Reviewer `/root/day6_qa_a`, separate from builder `/root`, 2026-09-19. The original CHANGES_REQUIRED finding and failing evidence remain in `DAY7_B1_QA.md`.

## Boundary correction verified

`ResourceSession` now rejects every scoped ledger before constructing unscoped Records, loading work, or recording allocation/progress/grants. Only the trusted host executor can create the service. Expanded the independent regression across `triad`, `aegis`, legacy `p2p`, and scoped `core`; each rejects with the trusted-host error and leaves canonical allocation records unchanged. Unscoped host operation remains functional.

Direct scoped forgery also remains blocked through both `Records.append` and `Ledger.put` for all five canonical resource kinds. This closes the original service-constructor bypass without increasing product authority. Runtime wiring must still validate canonical assignment/policy and call `observe()` only after successful authorized host operations; no model-controlled progress endpoint is accepted here.

## Fresh independent run

```text
TRIAD_INTEGRATION=1
.venv/Scripts/python.exe -m pytest tests/test_resource_policy.py tests/test_day7_resource_policy_qa.py -q
```

**18 passed, 2 existing dependency-deprecation warnings in 52.98s**, exit **0**. Evidence: `logs/day7-b1-correction-independent-tests.log` and `.exit`.

The combined suite covers all five resource extensions; immutable assignment preservation; durable request/decision/state evidence; duplicate-progress rejection; terminal denial; actual existing-budget rejection without additional reservation; oversized/API/unknown-cost human review; finite eight-grant envelope; concurrent same-threshold deduplication; kill; run-ID allocation reset prevention; all scoped constructors; and both direct canonical-record forgery paths.

Ruff check of the resource-policy module and both test files: **PASS**, exit **0**, evidence `logs/day7-b1-correction-independent-lint.log` and `.exit`.

## Revision and scope limits

B1's resource-policy module remained unchanged during verification. An AST comparison confirms HOST_RECORD_KINDS equals the reviewed committed set, including all resource kinds. `DAY7_B1_CORRECTION_HASHES.json` binds committed B1 source/tests and raw independent regression/results.

The shared checkout also contained root's separate uncommitted lifecycle/timestamp work in dependencies and UI files. This is a bounded B1 source/API verdict with transparent shared-checkout test provenance, not a pristine whole-tree replay or approval of those unrelated edits. QA changed only its independent scope regression and reports/evidence; no production writes, inference or restart occurred.

No blocking B1 findings remain. Runtime/native-executor wiring, actual default-envelope adoption, completion behavior at live thresholds, and lifecycle timestamps remain future independently reviewed segments. Phase 2 and Day 7 are not declared complete.
