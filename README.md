# Trading Core, Triad and Aegis

Day 5A provider acceptance **passed on 2026-09-18**: real isolated frontier
WorkItems, local Qwen, and the independently reviewed four-agent documentation relay.
Open [Settings → AI Providers](http://127.0.0.1:8000/settings/ai-providers) for current
readiness; successful verification has no time-only expiry. Paid API fallback remains disabled.
See [verification evidence and tested scope](docs/DAY5A_VERIFICATION.md).

A bounded research and development work system. Day 4 adds portable market data and deterministic backtesting. Only trivial engine-test fixtures are included; no broker credentials or live execution.

The post-5A extraction separates shared infrastructure from both product lineages.
Use [Core](http://127.0.0.1:8000/core), [Triad](http://127.0.0.1:8000/triad), and
[Aegis](http://127.0.0.1:8000/aegis). See the [operations and ownership guide](docs/CORE_EXTRACTION_OPERATIONS.md)
and [extraction verification](docs/CORE_EXTRACTION_VERIFICATION.md).

## Start on this machine

```powershell
Set-Location C:\Triad
docker desktop start
.\.venv\Scripts\python.exe tools/day4.py init
.\tools\start_backend.ps1
```

If containers are stopped, first run `docker compose up -d --wait --wait-timeout 240`.
Open <http://127.0.0.1:8000>. The UI shows real work, journals, independent reviews and lineage. Day 3 adds provider adapters, daily cycles, proposal policy, reviewed Git changes, budgets and a kill switch. Cloud providers without credentials are UNAVAILABLE; explicit demo cycles are SIMULATED. Local Qwen uses real Ollama inference.
Day 4 adds the research laboratory at http://127.0.0.1:8000/research: datasets, experiments, directional results, ledgers, quality and provenance. Its initial source is explicitly FIXTURE. Supporting durable queues and provider-readiness views remain available.
Open `docs/vault` as an Obsidian vault; installing Obsidian is optional.

## Reproduce from a clean checkout

Prerequisites: Git, Python 3.12 or 3.13, Docker Desktop with a working Linux engine.

```powershell
.\tools\bootstrap.ps1 -Python 'C:\path\to\python.exe'
```

The bootstrap installs locked dependencies into `.venv`, generates local secrets,
starts persistent services, initializes graph constraints, runs tests and authenticated checks.
Credentials live only in ignored `.env`. Never run `docker compose config` without
`--quiet` in shared logs because it renders interpolated secrets.

## Orientation

- [Day 4 research laboratory](docs/DAY4_SETUP.md)
- [Supporting durable operations](docs/DAY4_DURABILITY_SETUP.md)
- [Day 4 verification and review corrections](docs/DAY4_REVIEW_FIXES.md)
- [Original Day 4 evidence](docs/DAY4_VERIFICATION.md)
- [Day 3 operation](docs/DAY3_SETUP.md)
- [Day 3 verification](docs/DAY3_VERIFICATION.md)
- [Providers](docs/PROVIDERS.md)
- [Day 2 operation](docs/DAY2_SETUP.md)
- [Day 2 verification](docs/DAY2_VERIFICATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Setup and final verification](docs/DAY1_SETUP.md)
- [Agent Control Plane](docs/AGENT_CONTROL_PLANE.md)
- [Data](docs/DATA_ARCHITECTURE.md)
- [Knowledge](docs/KNOWLEDGE_ARCHITECTURE.md)
- [Local models](docs/LOCAL_MODEL.md)
- [Operator UI](docs/UI.md)

Use `docker compose stop` to stop databases. `docker compose down` preserves named
volumes; `docker compose down -v` destroys retained database state and is not a routine reset.
This is a local single-user setup with verified backups and separate product processes.
Multi-user identity and service-level database identities remain future deployment work.
Mutations require a local operator token.
