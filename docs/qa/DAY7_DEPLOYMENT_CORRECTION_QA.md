# Day 7 explicit deployment upgrade — independent QA

**PASS for the deployment correction** at exact implementation revision `1038016b0654559b3203991d46dc3fc10e201fd4` (implementation `2823205`, then subprocess-test lint correction). Reviewer `/root/day6_qa_a`, separate from builder `/root`, 2026-09-19. Initial Phase 1 live CHANGES_REQUIRED remains preserved; this PASS does not imply the production upgrade has been applied.

## Reviewed behavior

`python -m trading_core.upgrade` accepts only an unscoped Core store, acquires a transaction-scoped PostgreSQL advisory lock, requires the Day 6 migration marker, applies additive migration 012 and verifies the canonical alias before committing. Exceptions roll back the transaction. The existing migration retains immutable evidence and preserves explicit resume decisions on repeat application.

`start_backend.ps1 -UpgradeDatabase` runs this command from the workspace and checks its exit status before enumerating or stopping any listeners. Failure raises and prevents the subsequent restart path. Ordinary startup remains independent of migration/database availability, preserving the diagnostics recovery path. This ordering was source-reviewed; the production launcher was not executed by QA.

## Fresh independent verification

`TRIAD_INTEGRATION=1 .venv/Scripts/python.exe -m pytest tests/test_day7_upgrade.py tests/test_day7_upgrade_qa.py tests/test_aegis_lineage_migration.py -q`: **4 passed, 2 existing dependency-deprecation warnings in 9.88s**, exit **0**.

The existing test invokes the actual module entry point in a subprocess against a disposable pre-upgrade database, verifies conservative pause transfer and historical evidence, repeat upgrade after explicit resume, and scoped-product rejection. Independent additional regressions verify missing Day 6 precondition rejects without applying the migration, and an injected late SQL failure rolls back alias-table creation, migration marker, copied Aegis pause and stops while retaining the legacy pause. The injected failure is confined to a temporary resource and disposable database; implementation files are unchanged.

Ruff check for the upgrade module and both upgrade test files: **PASS**, exit **0**. `git diff --check` found no whitespace errors.

Fresh `tools/check_package.py`: **PASS**, exit **0**, installed to `C:/Users/fordr/AppData/Local/Temp/trading-core-package-t7wy7tny/installed`. A separate isolated `python -I` import proves the installed `trading_core.upgrade` module comes from that target and has byte-identical contents to reviewed source. This import did not invoke upgrade or open a production connection. The subprocess database execution test uses the checkout module; it is not misrepresented as installed-package database execution.

Evidence: `logs/day7-upgrade-independent-tests.log`, `logs/day7-upgrade-independent-lint.log`, `logs/day7-upgrade-independent-package.log`, `logs/day7-upgrade-independent-installed-module.log`, each with matching zero `.exit` file.

## Disposition

No blocking findings for this bounded correction. Proceed with explicit backed-up production upgrade, then repeat read-only migration metadata, historical preservation and live service checks before accepting Phase 1. QA added only independent tests/reports/evidence and performed no production writes, restart or inference. Subsequent resource-management work is outside this verdict.

## Raw-file SHA-256 evidence

Implementation hashes correspond to the reviewed revision's checkout bytes; the additional independent test and logs bind this QA run.

| File | SHA-256 |
| --- | --- |
| `app/trading_core/upgrade.py` | `a958b361e82c9c22aeac50bae22a2aa9e2b80baedfbe0ac644255ce02fb5ec7a` |
| `tools/start_backend.ps1` | `5ba742253d284e33bb4702333a811b2bc12d0213424e03612ca0c3f84fd3288f` |
| `infrastructure/postgres/012_aegis_lineage.sql` | `1ec9c60ea64b2b33c22ac872502f836527ca64eb4f13565082add3457e15c4b9` |
| `app/trading_core/resources/sql/012_aegis_lineage.sql` | `1ec9c60ea64b2b33c22ac872502f836527ca64eb4f13565082add3457e15c4b9` |
| `tests/test_day7_upgrade.py` | `657d94ae40c3a5a48b41cdbe7166de805132c8ea12da52d9b531ac969a13d9cd` |
| `tests/test_day7_upgrade_qa.py` | `bbf5b10c3d516ff970dd1d55bcdcff1f8afd4c2db9bc5b688d881fb654777952` |
| `logs/day7-upgrade-independent-tests.log` | `a998f548210c57e0d2133083efdd8f8ebea1fb10fa1e50e933e27681225f0c3c` |
| `logs/day7-upgrade-independent-package.log` | `4d28bd181c640522c0165b8a7079635f6e39a4163b929093683d3c01eccf0357` |
| `logs/day7-upgrade-independent-installed-module.log` | `b080ba92d687a0c68c081f48c11c731cfda7a426b23afb36bd1ecf2ec3b03d6b` |
| `logs/day7-upgrade-independent-lint.log` | `a4443afdcfb6d7363adb285762515ccf7cf50473b1a05c20c1a50f6bed4d26b0` |

