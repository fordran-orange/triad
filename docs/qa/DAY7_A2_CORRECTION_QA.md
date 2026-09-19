# Day 7 A2 correction — independent QA

**Decision: CHANGES_REQUIRED** at exact commit `fc104a5e20e10b97b377f80cb310967dd16a7f2a`. Reviewer `/root/day6_qa_a`, independent from builder `/root`, 2026-09-19. This is a fresh review after the original `f6a6f9c` findings preserved in `DAY7_A2_QA.md`.

## Original defects corrected

The new lineage-membership filters safely skip shared/nonproduct journals, handoffs and decisions while retaining legacy P2P context for Aegis and excluding Triad. Shared graph semantics remain explicit. The Aegis shell now strictly decodes as UTF-8 with readable separators. Both corrections pass independent regression and installed-package checks.

## New blocking finding

**P1 — a paused Aegis lineage can promote a historical P2P specialist.** `app/trading_core/intelligence/agents.py:561` queries `core.product_controls` using `old['owner']` directly. A historical specialist retains owner `p2p`, while active controls use canonical `aegis`. The earlier global `ledger.guard(executor_identity)` call receives neither work ID nor product scope and therefore does not enforce this product pause. A valid reviewed promotion can consequently create an ACTIVE persistent specialist for a paused lineage.

Independent reproduction uses the real disposable database, genuine legacy-owner parent/specialist, two independently reviewed usefulness records and reviewed governance evidence. After current Aegis `operate('pause')`, `promote(...)` succeeds; the regression fails **DID NOT RAISE**. No immutable grant was altered to construct this case. Correct the control lookup to canonical identity, retain historical grant/evidence bytes, and make newly issued current identity explicit. Rerun this regression plus promotion governance tests before acceptance.

Evidence: `tests/test_day7_a2_controls_qa.py`; `logs/day7-a2-correction-promotion-probe.log` / `.exit`: **1 failed, 2 dependency warnings in 5.96s**, exit 1.

## Fresh verification

- `TRIAD_INTEGRATION=1 .venv/Scripts/python.exe -m pytest tests/test_product_identity.py tests/test_aegis_lineage_migration.py tests/test_architecture.py tests/test_ownership_integration.py tests/test_day7_a2_qa.py -q`: **24 passed, 2 dependency warnings in 18.90s**, exit 0. Evidence `logs/day7-a2-correction-independent-tests.log` / `.exit`.
- `.venv/Scripts/python.exe tools/check_package.py`: **PASS**, exit 0. Fresh installed destination `C:/Users/fordr/AppData/Local/Temp/trading-core-package-u_3wqlzl/installed`; evidence `logs/day7-a2-correction-independent-package.log` / `.exit`.
- Additional isolated `-I` installed-package check: actual Aegis response is HTTP 200, strict UTF-8, byte-identical to source; legacy route redirects with query preserved; inactive/closed config matches source; migration 012 resolves from the installed resource and matches canonical SQL. Evidence `logs/day7-a2-correction-independent-package-extra.py`, `.log` and `.exit`: **PASS**. No lifespan, provider inference or production database calls.
- Ruff check passed for corrected context and both independent regression files.
- Broader consumer source review includes owner-alias lists/updates, canonical legacy-work pause/stop enforcement, private artifact paths, graph/context filtering, agent ownership and promotion, worker launcher replacement and packaging. Existing historical bytes remain preserved; the newly exposed promotion lookup is the remaining blocking source finding in this review.

## Exact revision and remaining work

`DAY7_A2_CORRECTION_HASHES.json` binds key reviewed files to SHA-256 of exact committed Git blob bytes. Root may correct the shared checkout after this finding; this verdict stays attached to `fc104a5`. QA changed only independent tests/reports/evidence, never implementation.

Production restart/migration, live service/provider and browser checks remain unperformed by this reviewer and must follow a passing corrected-source QA gate. Neither A2, Phase 1 nor Day 7 is complete based on this report.
