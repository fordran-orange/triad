# Day 4 durable operations

Day 4 introduces a PostgreSQL cycle queue and a provider readiness/review-evidence view. It retains Day 3 policy, budgets, independent review, actual Git isolation and cancellation. Cloud model quality and credentialed inference remain unverified; readiness never substitutes for those tests.

```powershell
Set-Location C:\Triad
.\.venv\Scripts\python.exe tools/day4.py init
.\tools\start_backend.ps1
.\.venv\Scripts\python.exe tools/day4.py readiness
```

The additive `004_jobs` migration installs cycle_jobs; no operational history is deleted. Bootstrap applies it. The dashboard adds Jobs & recovery and Provider readiness. Cycle buttons now persist a QUEUED job before returning HTTP 202. The API process checks scheduling and the queue every five seconds; queued jobs survive its restart. Scheduling is still disabled by default.

Commands: `tools/day4.py jobs` reads the queue; `enqueue --mode REAL` or `--mode SIMULATED` submits; `once` consumes at most one job; `worker` runs a foreground polling loop, terminated with Ctrl+C. The API worker and CLI worker may coexist: a PostgreSQL session advisory lock admits only one at a time. Queuing does not consume an improvement slot; the existing cycle engine reserves budgets at execution. A unique date/mode constraint prevents duplicate submissions. Existing cycle date/mode records prevent replay of already closed cycles.

Running jobs are never automatically retried. If a replacement worker acquires the lock and discovers abandoned RUNNING rows, it pauses autonomy (invalidating old epochs), marks those jobs UNCERTAIN and invokes existing blocked-cycle reconciliation. Inspect job records, CycleSummary, WorkItems and GitCheckpoint before resuming through existing controls. UNCERTAIN is terminal; resuming does not replay it. An old-date queued job or job with invalidated authority becomes CANCELLED. No historical catch-up or automatic budget reset occurs.

Queued jobs can be cancelled in the UI or authenticated `/api/day3/jobs/<id>/cancel`. Running work uses pause/kill/stop controls. Paused jobs remain visible, and queued authority invalidated by pause/kill cannot be resurrected by resume. Provider HTTP calls already in flight may continue upstream; their results cannot grant new authority after cancellation.

The queue covers Day 3 cycle submissions through the dashboard/API and API scheduler. Day 2 legacy background jobs, direct trusted `tools/day3.py demo/real` commands, individual support/review routes and arbitrary task kinds are not migrated. An explicit scheduler `submit` callback provides durable submission; legacy direct tick behavior remains for compatibility. This is one local queue, not a distributed exactly-once executor: a permanently hung worker holds its lock until stopped, and PostgreSQL/Git remain separate transactions. Retained reservations favor safety over maximizing throughput.

Provider readiness reads actual health, pricing configuration, cloud ceiling, observed REAL successes and explicit blockers. Health probes can be refreshed by the existing authenticated health action or CLI readiness. Reports expose no credential values. Illustrative token costs are not reservations. Review evidence separates REAL and SIMULATED, counts distinct identities and repeated checks, and explicitly leaves correctness NOT_MEASURED. Approval percentage is not a model-quality claim.

For real provider evaluation, human account credentials, supported model IDs, verified rates and explicit bounded cloud-spend authorization are still required. Enter them only into local environment configuration; the UI cannot raise limits. A labelled review-quality evaluation remains blocked until real reviewed results and independent ground-truth labels exist.

```powershell
$env:TRIAD_INTEGRATION='1'
.\.venv\Scripts\python.exe -m pytest -q --junitxml=logs/day4-tests.xml
.\.venv\Scripts\python.exe tools/verify_day4.py
```

The live verifier expects the retained Day 3 demo and the recorded Day 4 queue demonstration on this machine. Unit/integration tests reproduce functionality independently in disposable databases and Git repos. No trading authority was added. Day 3 reports remain historical.
