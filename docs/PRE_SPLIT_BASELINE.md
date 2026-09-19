# Preserved Day-5A baseline

Baseline code is the commit referenced by permanent tag `base/day5a-complete`.
The implementation commit hash is recorded below after preservation. Previous
HEAD was `61357f5`; that commit alone did not contain the completed isolated
executors, provider monitoring and readable UI work.

Verified on Windows / Python 3.13, PostgreSQL 17 with TimescaleDB 2.25.2,
Neo4j 5.26 Community, Ollama with qwen3:4b, subscription Codex/Claude/Grok.

- Unit/default suite: 239 passed, 69 integration tests skipped.
- Explicit live integration suite: 69 passed. Uses disposable PostgreSQL databases,
  temporary Git checkouts and bounded graph records. Includes kill-switch,
  authority, provider routing, data, backtesting and persistence checks.
- Backend, PostgreSQL, TimescaleDB, Neo4j, Ollama and Git reported up.
- All four providers ONLINE, existing real acceptance evidence retained, gate PASS,
  no active provider runs at the baseline check.
- All four UI routes and shared JS/CSS assets returned HTTP 200.
- Built and installed a wheel into an isolated target. HTML/JS/CSS resources present.
  Corrected missing JS/CSS package-data declarations before preservation.

## Recovery evidence

Local recovery bundle: `C:/Triad/backups/day5a-20260919/` (excluded from Git).

- PostgreSQL custom dump restored into `core_baseline_restore`; all 19 application
  tables restored, with TimescaleDB pre/post-restore hooks. Counts and dump digest
  are in `manifest.json`.
- 151 artifact files archived, extracted separately and SHA-256 checked. Existing
  dataset/result paths and contents remain unchanged.
- Consistent offline Neo4j volume archive restored into the distinct
  `triad_baseline_graph_restore` volume and started on loopback port 57688.
  Original/restored graph match: 2468 nodes and 1416 relationships, including
  matching per-label counts. Restore container stopped after verification;
  restored volume and original archive retained.
- Production Neo4j was restarted immediately after the archive was taken.
- Credentials are not committed or copied into human-readable reports. Existing
  OS credential entries remain in place. The graph volume archive is private local
  recovery material, not a source-code artifact.

Current architecture documents and inventory describe the authorized extraction;
no product module movement preceded this baseline.
