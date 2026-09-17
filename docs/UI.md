# Operator dashboard

The Day 2 dashboard is served at http://127.0.0.1:8000. Overview combines real service probes, workload counts, agent identities/authority/integration status, work queue and chronological journal. Navigation provides dedicated queue, journal, reviews, handoffs and control-plane views. Work rows open lifecycle events, permission envelope, structured records and graph lineage.

Health includes PostgreSQL, TimescaleDB, Neo4j, Ollama, Git and backend. Demo-only cloud agents are labeled. Missing data is not replaced with fabricated activity. Read data refreshes every eight seconds. Live-execution-disabled status remains visible.

The Operator access dialog accepts the ignored local bearer token into page memory. Run safe demo creates an actual persisted work item through the authenticated API, then the normal host lifecycle. No trading or permission approval button exists. The frontend uses textContent for dynamic data, with no external scripts/assets or analytics.

Browser verification includes the live overview, completed-work detail, review list, handoff list and control-plane view. API integration tests cover dashboard data, authenticated mutation, unavailable stores, forged Origin/Host handling and absent governance endpoints. See DAY2_VERIFICATION.md for results.
