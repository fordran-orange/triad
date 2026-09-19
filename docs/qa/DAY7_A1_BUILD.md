# Day 7 A1 — staged Aegis lineage foundation

This is a bounded foundation segment, not completion of the Aegis rename. The application still uses the Day 6 P2P routes and scope logic until A2 integrates the rename across every consumer.

Adds a fixed canonical identity helper (p2p aliases aegis, never Triad/Core) and additive migration 012. The migration retains immutable historical owner/payload/ID/time bytes, records the canonical alias with a UTC timestamp, allows new Aegis spelling in intelligence/agent constraints, creates the Aegis namespace, copies stop controls and combines pause state conservatively on first application. Reruns preserve later explicit resume decisions. Old schemas and artifacts stay intact.

The migration is staged and packaged but intentionally not registered in runtime initialization or applied to production yet. Activate it only with the complete A2 consumer integration: ownership checks and parameterized list queries, work/contracts, intelligence, graph/context/files, product controls including legacy stopped work, package/config, routing/redirects, UI labels, launch scripts, and architecture/service/package tests. Do not interpret the helper alone as an enforced data boundary.

Build checks: `TRIAD_INTEGRATION=1 .venv/Scripts/python.exe -m pytest tests/test_product_identity.py tests/test_aegis_lineage_migration.py tests/test_architecture.py -q`: **13 passed**, two existing TestClient deprecation warnings, 6.87s. Tests use a disposable database, retain old evidence/grants byte-for-byte, verify protection triggers, new-owner inserts and repeat migration behavior. Evidence: logs/day7-a1-build-tests.log and .exit. Separate independent QA required before accepting this segment.
