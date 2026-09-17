# Day 3 preflight

2026-09-17. Checked before implementation against baseline `1f9de1a`. No critical failure found. No AGENTS.md in project or parent. Cloud credentials absent is an external integration limitation, not a foundation failure. No credentials printed.

| Component | Test performed | Expected | Actual | Status | Evidence |
|---|---|---|---|---|---|
| Repository | git fsck / status / branch | Healthy main, clean | main at 1f9de1a; fsck exit 0, one harmless historical dangling blob | PASS | Git command output |
| Python | python --version; pip check | Working venv / dependencies | Python 3.12.10; no broken requirements | PASS | Precheck shell |
| Frontend/backend/UI | GET / and /api/status; Day 2 verifier | Respond with real service and work data | HTTP success; frontend HTML and status available | PASS | logs/day2-verification.json |
| PostgreSQL/Timescale | Authenticated queries / extension | Reachable / extension installed | UP; TimescaleDB 2.25.2 | PASS | Day 2 verifier |
| Neo4j | Authenticated lineage query | Persisted reviewed work links | UP; final demo lineage 11,12,11 links | PASS | Day 2 verifier |
| Ollama | GET /api/tags | Configured qwen3:4b present | UP; qwen3:4b present | PASS | Service probe |
| Work state machine / Control Plane | Full unit/integration suite | Invalid transitions and authority bypass denied | 92 passed, 0 failed, 0 skipped | PASS | logs/day3-precheck-tests.xml |
| Journal/review/handoff persistence | Read final demo records and Markdown | All required records retained | 6 canonical records and 8 state events per demo; journal files exist | PASS | tools/verify_day2.py |
| Docker | docker compose ps | Both databases running healthy | postgres and neo4j healthy | PASS | Precheck shell |
| Secrets | Tracked-file audit / presence-only provider check | No committed secrets | Audit passed; all three cloud key variables absent | PASS | tools/audit_foundation.py |
| Graph projection backlog | Outbox query | Zero pending/errors | 0 pending; 0 errors | PASS | Day 2 verifier |

Day 3 will retain Day 2 records and contracts, add separate cycle/runtime records, and preserve explicit REAL/SIMULATED/UNAVAILABLE labels. No cloud API call will be fabricated. Runtime scheduling support belongs to Triad; this build does not create a Codex reminder automation.
