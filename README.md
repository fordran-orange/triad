# Triad

An independent research platform foundation. No trading strategies, indicators,
broker credentials, live execution, or preselected research are included.

## Start on this machine

```powershell
Set-Location C:\Triad
docker desktop start
.\.venv\Scripts\python.exe tools/init_graph.py
.\tools\verify.ps1
.\.venv\Scripts\python.exe -m uvicorn triad.api:app --host 127.0.0.1 --port 8000
```

If containers are stopped, first run `docker compose up -d --wait --wait-timeout 240`.
Open <http://127.0.0.1:8000>. The UI is a read-only foundation shell, not a trading console.
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

- [Architecture](docs/ARCHITECTURE.md)
- [Setup and final verification](docs/DAY1_SETUP.md)
- [Agent Control Plane](docs/AGENT_CONTROL_PLANE.md)
- [Data](docs/DATA_ARCHITECTURE.md)
- [Knowledge](docs/KNOWLEDGE_ARCHITECTURE.md)
- [Local models](docs/LOCAL_MODEL.md)
- [Operator UI](docs/UI.md)

Use `docker compose stop` to stop databases. `docker compose down` preserves named
volumes; `docker compose down -v` destroys retained database state and is not a routine reset.
This is a local development setup; backup, authenticated operator access and runtime
isolation are required before broader deployment.
