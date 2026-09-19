# Day 7 deployment correction

Builder /root. Independent live QA at e2b44d4 found migration012 absent in production despite source and route checks passing. Preserve DAY7_PHASE1_ACCEPTANCE.md as CHANGES_REQUIRED. The earlier root live note incorrectly inferred migration from startup; the production database probe disproved that inference.

Added packaged `python -m trading_core.upgrade` and explicit launcher `-UpgradeDatabase`. The transaction takes an advisory lock, requires the Day6 schema, applies012 and verifies the alias. Upgrade runs before stopping listeners; ordinary startup stays independent of database availability. No product policy/authority expansion. Fresh bootstrap already calls Ledger.initialize.

Root validation: real disposable-database entry-point test plus lineage preservation test:2passed/6.82s. The test removes012/alias table, invokes the actual module in a subprocess, verifies conservative pause transfer and immutable records, then verifies repeated upgrade preserves explicit resume. Independent QA and controlled production application remain required.
