# Day 7 A2 correction 2 — independent QA

**PASS for corrected A2 source; ready for controlled live acceptance.** Exact implementation revision: `07453222c8f892bc8fc4d9a7093e87ee0b510183`. Reviewer `/root/day6_qa_a`, independent from builder `/root`, 2026-09-19. The original and correction-1 CHANGES_REQUIRED reports remain preserved.

## Correction verified

Agent promotion now resolves the historical owner to its current canonical identity before looking up product pause controls. New persistent grant and promotion evidence use `aegis`; the old immutable `p2p` grant is preserved. This closes the P1 pause bypass reproduced at `fc104a5`.

Extended the independent disposable-database regression to verify both rejection and successful recovery: a genuine historical P2P specialist with valid independently reviewed usefulness/governance evidence cannot promote while current Aegis controls are paused. After explicit Aegis resume, promotion succeeds with a distinct persistent agent owned by `aegis`, current scoped access works, promotion evidence is owned by `aegis` and links the original agent, the budget is preserved, and the entire original agent row remains exactly equal with owner `p2p`. The rejected attempt produces no extra promotion record.

## Fresh independent checks

PowerShell environment `TRIAD_INTEGRATION=1`:

```text
.venv/Scripts/python.exe -m pytest tests/test_day7_a2_controls_qa.py tests/test_ownership_integration.py tests/test_day6_qa_b.py -k "promotion or product_controls or owner_column or aegis_reads" -q
```

**11 passed, 13 deselected, 2 existing dependency-deprecation warnings in 30.32s**, exit **0**. Covers the new legacy pause/resume case, ordinary positive promotion, duplicate/invalid evidence rejection, current product pause, disabled provider, global kill, active-agent ceiling, foreign evidence, legacy work controls, ownership immutability and product inability to relax global governance. Evidence: `logs/day7-a2-correction2-independent-tests.log` and `.exit`.

Ruff check for `app/trading_core/intelligence/agents.py` and the extended independent regression: **PASS**, exit **0**, evidence `logs/day7-a2-correction2-independent-lint.log` and `.exit`. `git diff --check` found no whitespace errors (only Git's informational Windows line-ending normalization warning for the test).

This correction changes only promotion identity/control handling in implementation. The preceding independent 24-test ownership/architecture/context/encoding run and fresh installed-package checks remain relevant to unchanged files, as documented in `DAY7_A2_CORRECTION_QA.md`; they are not represented as newly repeated here. Earlier failure-isolation/intelligence/product regression also remains supporting evidence, not a new full-suite claim.

## Scope and disposition

No blocking source findings remain from this bounded A2 review. The two initial defects (shared-context failure and malformed HTML encoding) and subsequent legacy-promotion control defect now have passing independent regressions. Exact committed hashes for changed A2 implementation/configuration/launcher files and raw hashes of the extended independent test/results are recorded in `DAY7_A2_CORRECTION2_HASHES.json`.

QA edited only the independent regression and this report/evidence. No production migration, restart, live provider inference or browser run occurred in this review. This PASS allows the next controlled acceptance step; it does not assert that production is already on Aegis, that live migration/browser/service checks have passed, or that Phase 1/Day 7 is complete. Preserve backups, historical hashes and authority restrictions during the separately verified activation.
