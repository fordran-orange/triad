# Day 1 setup and verification

Project root: `C:\Triad`. Final verification date: 2026-09-17 (America/Chicago),
2026-09-17 UTC. Machine-generated current evidence lives in ignored `logs/`.

## Installed and configured

- Reused Git 2.53.0, Python 3.12.10 and Docker Desktop 4.63.0 / Engine 29.2.1.
- Created all 15 requested top-level/staged directories, project virtual environment,
  Python package configuration, fully pinned Python dependency lock and Git `main`.
- Installed pandas/PyArrow, psycopg binary, Neo4j driver, Pydantic/settings/dotenv,
  FastAPI/Uvicorn, pytest/httpx and Ruff. No trading libraries or strategies installed.
- Configured PostgreSQL 17 with TimescaleDB 2.25.2 and Neo4j 5.26 Community.
  Both container references include immutable image digests in Compose.
- Created three named persistent volumes, SQL working-data/operational schemas,
  one-minute hypertable, seven graph ID constraints and idempotent graph initialization.
- Created the policy interfaces, generated JSON schemas, exact-decimal Parquet candle
  contract, provenance manifest example, architecture docs and nine-section Obsidian vault.
- Started the read-only operator UI and provided repeatable bootstrap/health/audit tools.

## Verification evidence

| Check | Result / evidence |
|---|---|
| Files and folders | Written and read back; `tools/audit_foundation.py` verifies required paths |
| Virtual environment | Python 3.12.10; installed project imports; `pip check` passes |
| Automated tests | 30 passed; `logs/tests.xml`; policy denial, immutable limits, Parquet round trip, validation and read-only API |
| Lint / formatting | Ruff checks and formatting verification pass |
| Docker engine | Linux engine reports 29.2.1 after runtime-socket repair |
| Compose | Configuration validates; both containers become healthy |
| PostgreSQL from Python | Authenticated SELECT and transaction-scoped write/read pass |
| TimescaleDB | Extension 2.25.2 active; `triad.candles_1m` registered as hypertable |
| Neo4j from Python | Authenticated connectivity, query, rolled-back write and all seven constraints pass |
| Persistence | Synthetic records survive forced recreation of both containers, then are removed; `logs/persistence-probe.json` |
| UI | Live HTTP response and browser visual inspection pass; disabled execution and six areas visible |
| Credentials | Unique random passwords; ignored `.env`; local file ACL limited to owner/system/admins; tracked-file scan excludes secret values |
| Git | Initial verified commit on `main`; final commit ID and clean status reported in `logs/git-final.txt` |
| Ollama | Not found in PATH, standard install/model locations or uninstall inventory; endpoint unavailable; optional configuration provided |

The tests emit two upstream deprecation warnings for Starlette/httpx and an AnyIO
alias. They are warnings, not failures. No local-model inference was verified because
Ollama is unavailable. No strategies, large market datasets or live trades were introduced.

## Resolved failures

Docker initially failed before starting its engine because Windows could not access
stale AF_UNIX socket entries at `Docker/run/dockerInference` and
`docker-secrets-engine/engine.sock`. Backing up both affected socket-only directories
while Docker was stopped allowed startup. Images, volumes and settings were preserved;
no factory reset or WSL unregister operation was performed. Backup directories remain
under the original AppData parent locations with `.backup.triad.<timestamp>` names.
A direct rename of the socket itself failed; backing up the containing directory worked.

Ruff found initial formatting/style issues; these were corrected before commit.
The machine's inherited root-directory ACL exposed `.env` to other local users;
`tools/init_env.py` now restricts that credential file on every run.

## Running services and security limits

| Service | Loopback address |
|---|---|
| Triad operator API/UI | http://127.0.0.1:8000 |
| PostgreSQL / TimescaleDB | 127.0.0.1:15432 |
| Neo4j browser / HTTP | http://127.0.0.1:17474 |
| Neo4j Bolt | bolt://127.0.0.1:17687 |

Containers: `triad-postgres-1`, `triad-neo4j-1`. Volumes:
`triad_postgres_data`, `triad_neo4j_data`, `triad_neo4j_logs`.
The UI process runs in the background; its launcher PID is in `logs/api.pid`, and
stdout/stderr are in `logs/api.*.log`. It is not configured as a Windows startup service.

This remains a local development foundation. Database credentials are privileged
bootstrap credentials and must never be given to future agents. Docker administrators
can inspect container environment credentials. `.env` is plaintext with restricted
local access; no secret manager, remote TLS, operator authentication, production
backup/restore workflow or runtime agent sandbox is claimed. Named volumes provide
persistence, not backups. No brokerage execution or live authority exists. Policy
contracts alone do not authenticate humans or isolate code; see the Control Plane doc.

## Human action and exact resume commands

No human action is required for the verified Day 1 foundation. Optional: install/configure
Ollama later if local inference is wanted, select a Qwen size appropriate for hardware,
and open `C:\Triad\docs\vault` in Obsidian. Neither is needed for database/API checks.

```powershell
Set-Location C:\Triad
docker desktop start
docker compose up -d --wait --wait-timeout 240
.\.venv\Scripts\python.exe tools/init_graph.py
.\tools\verify.ps1
git status --short --branch
```

If the UI is not already running:

```powershell
Set-Location C:\Triad
.\.venv\Scripts\python.exe -m uvicorn triad.api:app --host 127.0.0.1 --port 8000
```

Reproduce dependencies and services on this machine from a clean checkout:

```powershell
.\tools\bootstrap.ps1 -Python 'C:\Users\fordr\AppData\Local\Programs\Python\Python312\python.exe'
```

Stop with `docker compose stop`; resume with `docker compose up -d --wait`.
Never use `down -v` as a routine restart. Initial SQL runs only on an empty PostgreSQL
volume; future schema changes need migrations. Editing `.env` does not rotate existing
database passwords. Preserve credentials with the volumes and use database-native
password rotation when needed.

## Reference documentation

Follow-up on 2026-09-17: the earlier unavailable result records the initial check.
Ollama 0.34.1 is now installed and its local API responds. The operator subsequently
selected `qwen3:4b`; it is downloaded, checksum-verified and selected in Triad configuration.
Application: `%LOCALAPPDATA%\Programs\Ollama`; model storage: `C:\AI\Models\Ollama`.
See `LOCAL_MODEL.md` for verified installation details.

- [TimescaleDB Docker image](https://hub.docker.com/r/timescale/timescaledb)
- [Neo4j Docker configuration](https://neo4j.com/docs/operations-manual/current/docker/configuration/)
- [Docker stale-socket startup issue](https://github.com/docker/desktop-feedback/issues/448)
