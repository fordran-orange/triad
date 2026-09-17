# Day 3 operation

Day 3 adds a bounded engineering loop, provider adapters, independent review, Git isolation, budgets and operator controls. Read DAY3_VERIFICATION.md for measured results and remaining credential blockers. DAY3_PRECHECK.md records the passing Day 2 baseline before implementation.

From PowerShell in `C:\Triad`:

```powershell
.\.venv\Scripts\python.exe tools/day3.py init
.\tools\start_backend.ps1
.\.venv\Scripts\python.exe tools/day3.py health
```

Open http://127.0.0.1:8000. The retained Day 2 explorer is at `/day2`. Mutations require the existing local operator token from ignored `.env`; the browser holds it only in memory. Never paste credentials into a journal or model prompt.

`tools/day3.py demo` runs explicitly SIMULATED primary providers through real PostgreSQL, policy, Git worktrees, checks, reviews, merges and Neo4j projections. `tools/day3.py real` uses configured real providers, reporting unavailable members without substituting fixtures. Both require a clean main checkout for changes. Repeating a date/mode returns the existing cycle; it does not grant new daily slots. `tools/day3.py support` invokes real local Qwen on a small synthetic summary under an eligible completed CODEX parent.

Defaults allow nonexecuting `.md`, `.txt` and `.json` improvements only under `docs/improvements` and `research/improvements`. General application-code edits, migrations, governance edits and trading are outside this initial autonomous write policy. Expanding those boundaries is separate human-reviewed development, not a provider permission request.

After a process interruption, inspect GitCheckpoint, Change, Event and WorkItem records, then run `tools/day3.py recover`. Recovery marks interrupted cycles/work blocked, retaining budget reservations and Git branches. It does not replay provider calls or automatically merge partially completed work. Background tasks are not a durable job queue; PostgreSQL is authoritative and graph/Markdown projections are retryable.

Reproduce checks:

```powershell
$env:TRIAD_INTEGRATION='1'
.\.venv\Scripts\python.exe -m pytest -q --junitxml=logs/day3-tests.xml
.\.venv\Scripts\python.exe -m ruff check app tests tools
.\.venv\Scripts\python.exe tools/audit_foundation.py
.\.venv\Scripts\python.exe tools/verify_day3.py
```

Integration tests use disposable, explicitly named test databases and temporary Git repositories. The rollback and destructive-path tests do not revert the production demo.
