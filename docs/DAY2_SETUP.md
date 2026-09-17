# Day 2 setup and operation

Project: `C:\Triad`. Day 1 verification is recorded in [DAY2_PRECHECK.md](DAY2_PRECHECK.md). Day 2 adds an operator-driven work loop; no unattended scheduler is installed.

## Start

```powershell
Set-Location C:\Triad
docker compose up -d --wait --wait-timeout 240
.venv\Scripts\python tools/init_env.py
.venv\Scripts\python tools/day2.py init
.\tools\start_backend.ps1
```

Open http://127.0.0.1:8000. The frontend is served by FastAPI, with no separate Node service. Ollama must be running for real helper work. The selected model is `qwen3:4b`; its files remain in `C:\AI\Models\Ollama`.

## Exercise the work loop

```powershell
.venv\Scripts\python tools/day2.py demo
.venv\Scripts\python tools/day2.py rotate
.venv\Scripts\python tools/day2.py local
```

`demo` completes a documentation audit and independent deterministic review. `rotate` executes CODEX → CLAUDE → GROK creation assignments, each reviewed by the next member. These names are logical identities; no cloud provider request is made. Reports are in `logs/day2-demo.json` and `research/generated`. `local` calls real Ollama on synthetic input and leaves the result awaiting independent review. It cannot be automatically approved by the documentation reviewer.

The UI's Operator access dialog takes `TRIAD_OPERATOR_TOKEN` from the ignored local `.env`. Open that file privately to use it; never paste it into chat or shared logs. The token is held only in page memory. Read endpoints are loopback-local and unauthenticated; mutation endpoints require the token and reject cross-origin browser requests. This is a single-user development service.

## Verify

```powershell
$env:TRIAD_INTEGRATION='1'
.venv\Scripts\python -m pytest -q --junitxml=logs/day2-tests.xml
.venv\Scripts\ruff check app tests tools
.venv\Scripts\ruff format --check app tests tools
.venv\Scripts\python -m pip check
.venv\Scripts\python tools/audit_foundation.py
```

Integration tests use actual databases and remove only their own synthetic work records and generated files. Without the environment flag these tests are explicitly skipped. Do not run against a shared production database.

## Recovery

Postgres is authoritative. `python tools/day2.py project` retries pending graph/Markdown projections in order. A failed projection leaves a durable outbox row and redacted error type; successful replay is idempotent. `python tools/day2.py recover` marks interrupted execution states BLOCKED under advisory locks. Inspect artifacts and evidence before retrying an assignment through the authenticated run endpoint. Already completed work cannot be rerun in place; create a new work item.

API background tasks are not a durable task queue. A process crash can interrupt a run; there is no automatic unsupervised retry. Files are exclusive-created before the result transaction; a crash can leave an orphan artifact. Review/reconcile it rather than deleting it blindly. Journals, handoffs, state events and the projection outbox commit together with accepted results.

Use `docker compose stop` to stop databases. Never use `down -v` as routine maintenance. Secrets and operational exports remain outside Git. Backup/restore, service accounts, OS-isolated providers and cloud authorizations are later work.
