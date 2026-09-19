# Day 7 A2 — independent QA

## Initial revision: CHANGES_REQUIRED

Reviewer: `/root/day6_qa_a`, separate from builder `/root`. Reviewed commit **f6a6f9cd720da8db155072e23845f1f45d118af1**, diff from `59f53e19c6cd6c5d224ca8d9510f95b731cb9596`, on 2026-09-19. This verdict applies to the initial A2 revision, not subsequent uncommitted corrections.

### Required corrections

1. **P2 — shared records can abort private context construction.** `app/trading_core/context.py` applies `canonical_product()` directly to journal, handoff and decision owners. `shared` is a valid stored/readable owner, but is not a product identity; a same-mission shared journal, matching shared handoff, or shared decision therefore raises `ValueError: Unknown product identity`. The preceding implementation safely excluded these nonmatching records. Restore filtering that recognizes the Aegis/P2P lineage while skipping shared/unknown nonproduct records in these private context fields. Keep the existing explicitly shared graph behavior separate.
2. **P2 — the new Aegis shell violates its declared UTF-8 encoding.** `app/products/aegis/static/index.html` contains byte `0xb7` at offset 838 (the new status separators), despite the HTML and HTTP response declaring UTF-8. Strict decoding fails and browsers show replacement glyphs. Re-encode the complete document as valid UTF-8 and retain readable separators.

Both findings were reproduced against bytes extracted directly with `git show f6a6f9c:<path>` after corrections began, avoiding ambiguity from concurrent shared-workspace edits. Original context raises for all three affected record categories; original HTML fails strict decoding. Evidence: `logs/day7-a2-independent-original-revision-probes.log`.

### Verification and useful coverage

- Independently read the A2 build/progress records, full consumer diff, identity helper, migration and ownership/control code. The changes preserve old stored owner spellings, resolve host scope to Aegis, use parameterized owner-alias reads, keep Triad/Core distinct, enforce canonical pause/stop controls for legacy work and retain immutable historical owners. Aegis remains inactive, human-directed and exchange closed.
- Source review covers current/legacy private artifact paths, graph lineage visibility, specialist ownership comparisons, package assets, launcher replacement of the legacy worker, and GET redirects with query preservation. Runtime migration wiring and broader affected consumers require fresh correction QA and later live acceptance before declaring Phase 1 complete.
- Independently ran `$env:TRIAD_INTEGRATION='1'; .venv/Scripts/python.exe -m pytest tests/test_product_identity.py tests/test_aegis_lineage_migration.py tests/test_architecture.py tests/test_ownership_integration.py -q`: **19 passed, 2 existing dependency-deprecation warnings in 18.37s**, exit 0. Evidence: `logs/day7-a2-independent-tests.log` and `.exit`. These existing tests did not cover the two defects above.
- Added `tests/test_day7_a2_qa.py`: shared nonproduct context regression for journals/handoffs/decisions, positive legacy context with negative foreign-product exclusion, and actual FastAPI HTML response strict-decoding check. The first run was **4 passed, 1 failed** because root's context fix arrived before that test process loaded the module, while HTML remained unfixed. This mixed-workspace run is not represented as the initial revision result. Evidence: `logs/day7-a2-independent-adversarial.log` and `.exit`; original-revision probes preserve both original failures independently.
- Reviewed root's separate additional regression completion: **49 passed, 2 warnings in 175.46s**, exit 0, in `logs/day7-a2-regression.log` and `.exit`. Did not duplicate that concurrent suite.

### Scope and pending acceptance

No implementation was edited by QA. No production services were restarted, production migration applied, live browser acceptance performed, or new provider inference initiated. Root's initial package smoke is supporting evidence; final corrected installed-package/runtime checks remain to be bound to the corrected revision. Preserve this CHANGES_REQUIRED history, then perform a distinct independent review/run for the corrected commit. Do not claim the full rename or Day 7 complete.
