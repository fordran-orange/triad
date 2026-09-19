# Operating the extracted platform

This monorepo has three maintained ownership areas on one integration branch:
`app/trading_core`, `app/products/triad`, and `app/products/aegis`. The neutral
`app/platform_host` package assembles HTTP routes without importing product code.
There are no permanently divergent product branches.

From `C:\Triad`:

```powershell
.\tools\start_backend.ps1
```

This starts Core and its local gateway on 8000, Triad on 8101, and Aegis on 8102.
All listeners bind loopback. Each process has separate stdout/stderr logs under
`logs/`. A crashed product returns HTTP 503 through the gateway; Core remains up.
To run only Core, use `start_backend.ps1 -CoreOnly`. This leaves any existing
product workers alone. To restart one product, use `start_product.ps1 -Product triad`
or `-Product aegis`.

Standalone commands are also supported:

```powershell
.\.venv\Scripts\python.exe -m uvicorn trading_core.api:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m uvicorn products.triad.server:app --host 127.0.0.1 --port 8101
.\.venv\Scripts\python.exe -m uvicorn products.aegis.server:app --host 127.0.0.1 --port 8102
```

Use `platform_host.api:app` instead of `trading_core.api:app` for the optional
product gateway. The legacy `triad.api:app` resolves to that gateway. The
in-process `platform_host.legacy` exists only for compatibility tests; it is not
the production launcher.

## Surfaces and compatibility

| Route | Owner and behavior |
|---|---|
| `/`, `/core` | Core operator home: WorkItems, journals, reviews, approvals, diagnostics and global controls |
| `/settings/ai-providers` | Core login, model selection, verification, usage and provider policies |
| `/research` | Core generic data/engine inspection; existing fixture laboratory |
| `/day2` | Retained Core work explorer |
| `/triad` | Product rotation, backlog, proposals, product reviews, journal, jobs and recovery |
| `/aegis` | Sparse human-directed shell; no strategy imports or trading functionality added |
| `/api/core/control` | Authenticated global controls; works without products |
| `/api/day3/control` | Authenticated Triad-local pause/resume/stop only; global actions are rejected |
| `/api/day3/*` | Compatibility gateway to the independent Triad worker |

The local lock still uses the existing `TRIAD_OPERATOR_TOKEN` in ignored `.env`.
Credentials remain in Windows Credential Manager. No credential renaming or
login migration is required. Provider monitoring still runs every five minutes
without inference. Successful verification does not expire solely with time.
CLI/local daily execution caps remain optional and off; usage and Qwen warnings
remain recorded. API budgets, per-run ceilings and the global kill switch remain.

## Configuration and installation

Core configuration is in `config/core/`; scheduling and member sequence are in
`config/triad/product.json`; Aegis's shell settings are in `config/aegis/product.json`.
The former files under `agents/` are retained historical compatibility examples;
new runtime code does not load them. Default package resources mirror the maintained
config and migrations; `test_packaged_defaults_match_maintained_config` detects drift.

Installed deployments set `TRADING_HOME` to their host data/config directory.
Outside a source checkout, the default home is the working directory. Package
resources supply defaults when a host override is absent. They contain no secrets.
Core, product HTML, shared JS/CSS, configuration and SQL ship in the wheel.

## Data ownership and trust boundary

`Store(scope='triad')` and `Store(scope='aegis')` are host-selected service scopes.
Canonical WorkItems and audit/research records carry ownership. Reads filter
before limiting results; foreign IDs, parents, writes, events and research models
are rejected. Shared infrastructure records are readable but cannot be modified
through a product-scoped ledger. Context assembly selects the WorkItem owner even
when invoked by the operator's unscoped Core service.

The unscoped Store is privileged host/operator code. This is a local, single-user
service boundary, not OS isolation between mutually hostile Python applications.
Products are trusted installed code and currently use the same database account.
Untrusted model tools receive bounded snapshots and isolated execution; they cannot
instantiate Store, access host credentials, or run arbitrary host Python. Multi-user
deployment and hostile product plugins would require service identities/database
roles and authenticated internal RPC. Those capabilities are outside this refactor.

Historical output paths retain their original Triad ownership unless registered
otherwise. New generic reports use `research/generated/<owner>/`. Canonical result
artifacts are registered against their record and owner. Graph nodes carry owners;
new filename, mission and evidence identities are product-qualified, while historical
identifiers/edges remain unchanged. Product lineage queries authorize the source
WorkItem and filter neighbors. Operator views can inspect all products deliberately.

## Recovery

`base/day5a-complete` and the private local bundle
`backups/day5a-20260919` preserve the predecessor. SQL 005 moves generic tables
to Core and retains legacy views. 006 adds ownership and product controls; 007
belongs to Triad; 008 registers artifact ownership; 009 classifies relay audit
envelopes as Triad-owned. The `core_baseline_restore`
database proves up/down/up without touching production.

Rollback requires a maintenance window and a fresh backup. The ownership down
migration refuses to discard P2P records; additive owner columns remain because
the old application ignores them and removing them would discard evidence.
Then 005 down restores table names. For complete original storage state, restore
the preserved PostgreSQL, Neo4j and artifact backups together into an isolated
environment first. Never point an old checkout at newly evolved product data
without reviewing the compatibility migration.

## Human notes

Existing generated Markdown stays under `docs/vault/02_Journal/generated` to preserve
links. New projections contain stable record IDs, owner, canonical source and
generation time. Use `docs/vault/operator` for human annotations. Generated files
are projections; human edits cannot approve work or modify database history.
Vault notes are not automatically agent context. Obsidian remains optional.

## Deferred capabilities

P2P strategy libraries, broker adapters, live capital, portfolio/risk products and
expanded autonomous code permissions remain extension points. Exchange has a
typed CLOSED contract and a rejecting import function; there is no transfer API.
The schedule remains disabled as before. Current autonomous Git changes still
require a clean protected `main` checkout; this integration branch intentionally
does not relax that check. Decide when to integrate it into `main` after review.

## Day 7 lineage migration

For an existing Day 6 installation, preserve a tested database/artifact backup,
then deploy with `./tools/start_backend.ps1 -UpgradeDatabase`. The explicit
upgrade runs before any existing listener is stopped and fails the deployment
on error. The equivalent packaged command is
`python -m trading_core.upgrade`. It applies the additive migration transactionally
and verifies the canonical alias. It is safe to repeat after an explicit resume.
Ordinary startup does not migrate: this keeps Core diagnostics startable when
the database is unavailable. A new installation still uses `tools/bootstrap.ps1`.

Migration 012 records p2p as a historical alias of aegis. Historical record owners, payloads, hashes and timestamps remain unchanged. New assignments use aegis. The /p2p route redirects to /aegis. Aegis remains inactive and preserved; exchange is closed. Legacy pause/stop controls transfer conservatively. Keep historical migrations and artifacts intact.
