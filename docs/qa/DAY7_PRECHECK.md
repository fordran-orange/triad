# Day 7 — final Day 6 baseline precheck

Date: 2026-09-19. Status: baseline verification complete; independent QA recorded separately before implementation.

## Exact baseline

HEAD and dereferenced `base/day6-complete`: `f1835049aeb4778ec682f0c684d8cec12234a28c`.
Tree: `59c02811df4a3910d39bbefe1967cfacba93e180`.
Git was clean before, throughout and immediately after the fresh regression. No implementation, configuration, migration or test files changed. This report is the first tracked Day 7 change. Independent QA rehashed all 15 final Day 6 acceptance-manifest files: 15/15 identical, including retained log evidence.

## Fresh regression and controls

PowerShell, C:/Triad:

```powershell
$env:TRIAD_INTEGRATION='1'
.venv/Scripts/python.exe -m pytest -q
```

Result: **396 passed, 2 warnings in 714.48s**, exit 0. This fresh run is against final Day 6 bytes, not the earlier 381-test result. Warnings concern Starlette/httpx TestClient and the deprecated AnyIO BlockingPortal alias; neither is a test failure.

Evidence: `logs/day7-precheck-full-regression.log` and `.exit`.
The complete integration suite exercises disposable product-process crashes while Core diagnostics and kill remain available, midrun kill enforcement, merge governance, private ownership/context/graph boundaries, provider isolation and recovery. Production kill was not activated during browser inspection.

## Services, providers, data and package

All three fresh helper checks exited 0:

- `logs/day7-precheck-services.log`: Core/gateway, Triad and P2P routes; PostgreSQL, TimescaleDB, Neo4j and Ollama available; Codex, Claude, Grok and Qwen ONLINE; provider gate PASS; accepted Triad relay; zero active provider runs; P2P human-directed, exchange CLOSED, zero assignments.
- `logs/day7-precheck-data.log`: 151 historical artifacts and 59 record IDs preserved; migration up/down/up passed; two deterministic experiment results retain content hash `92fa86ba7608ba1cee91cca0dfb7e4b9c1df0a5355b525b6d3b51e761921b8e8`. Historical source hashes preserved. Current research fingerprint `f3c0d1f08aa0664cb6dafe4620337f460c7db5fde5a4f286b7ceab1b4b23a293`.
- `logs/day7-precheck-package.log`: clean installed package smoke passed for configuration, SQL, Core/P2P and HTML/JS/CSS. Independent supplemental isolated-interpreter check verified Core intelligence and Triad development HTML/JS routes return 200 with exact source/installed byte equality; installed migrations 010 and 011 match both source mirrors and resolve through packaged resource lookup. Evidence: `logs/day7-precheck-independent-package.log` and `.exit`.

Provider checks inspect live readiness and existing immutable execution proof; they do not claim a new inference through each external provider in this precheck. The fresh suite tests transport behavior in isolated fixtures. Current models: gpt-6-astra, claude-sonnet-5, grok-4.6, qwen3:4b. Live trading and scheduled autonomy remain disabled, paid API ceiling zero, fallback NEVER; daily subscription/local usage caps remain off.

## Fresh browser smoke

Root performed read-only browser checks on the running localhost application (not only HTTP tests). Independent QA reviews root-collected observations; it did not independently drive this browser.

- Core diagnostics: all services UP and four providers ONLINE; readable fields and local timestamps.
- Core intelligence: 13 verified capabilities, four configured agents, zero active temporary agents; transport restrictions shown truthfully.
- Triad development: three frontier inspections, four candidates, independent QA and merged improvement; failed build attempt and successful correction remain visible.
- Triad journal: readable record dialog, model/timestamps/usage/evidence; technical IDs collapsed. Providers and relay PASS.
- Provider settings: signed-in CLIs Ready, distinct unconfigured API connections, automatic monitoring explanation.
- P2P shell: empty, human-directed, exchange closed.
- Research: fixture-only warning, 12 datasets, two experiments and four completed runs. Narrow actual sidebar screenshot showed readable stacked content and scrollable navigation/table. Final browser console query returned no warning/error entries; this is bounded smoke, not exhaustive visual QA of every tab.

Detailed observations: `logs/day7-precheck-browser.md`. A stale accessibility target caused one automation retry; a fresh semantic locator opened the intended journal dialog successfully.

## Projection queue observation

During verification the production graph outbox accumulated 7, then 14, then 21 pending entries, with zero recorded errors. The existing authorized projection-drain path delivered all 21 with no error; final immediate status was pending 0/errors 0 (`logs/day7-precheck-projection-drain.log`). This is a derived-projection operation, not a source/history rewrite. The periodic provider monitor can add later entries; zero is a measured snapshot, not a guarantee of automatic continuous draining. The canonical PostgreSQL data remains authoritative.

## Remaining Day 7 work

No Day 7 implementation is claimed here. The Aegis rename, governed resource extensions, lifecycle timestamps, canonical cycles, external integration contracts/shells/UI, launcher clarity and Day 6 quality-debt resolution remain separate bounded build/independent-QA segments. Historical artifacts, hashes and evidence must remain intact. Do not create `base/day7-complete` until final independent acceptance passes.
