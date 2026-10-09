# CORE_STATE_AUDIT

**Mission 0 — Establish Core ground truth.** Inspection only. No source, config, data, git refs, or running processes were changed. Read-only git, read-only SQL (`default_transaction_read_only=on`), read-only HTTP GETs, imports, ruff, pytest, `pip wheel` into a scratch directory, and the repo's own health/audit scripts were the only actions.

| Field | Value |
|---|---|
| Repository | `C:\Triad` (origin `github.com/fordran-orange/triad`) |
| Branch / HEAD | `main` @ `9b61ed2c0e5bde99c78234caf777c3e4eccf6de9` ("Resume only exact closed review maintenance checkpoints", 2026-10-04 07:52 -0500) |
| Audit performed | 2026-10-08, 18:30–19:10 America/Chicago (23:30–00:10 UTC) |
| Python | 3.12.10 in `.venv`; ruff 0.16.8; pytest 9.1.1 |
| Method | 7 parallel read-only inspection agents (Core backend, product layers, memory, providers, governance, runtime, research/backtest) plus coordinator verification of every load-bearing claim |

Classification vocabulary used throughout: **VERIFIED WORKING** (observed live, by test execution, or by read-only runtime check), **PRESENT BUT UNVERIFIED** (code exists; nothing in this audit confirmed it runs), **PARTIAL**, **DOCUMENTED ONLY**, **BROKEN**, **UNKNOWN**. Documentation is never counted as proof.

---

## 1. Executive Summary

Core is a real, running, heavily-governed FastAPI + PostgreSQL/Timescale + Neo4j system whose intelligence has gone almost entirely into *governing an autonomous Triad development pipeline* rather than into product capability. It is **alive but degraded**, and it is **not yet a safe base for Aegis**, for five concrete reasons:

1. **The verification baseline is red and partly unrunnable.** The documented `pytest` invocation is interrupted at collection because two test modules share the basename `test_application_plan.py` (`tests/` and `tests/products/triad/`, no `__init__.py`/`conftest.py`). With collection errors tolerated: **941 passed, 9 failed, 597 skipped, 1 collection error** in 7m51s. All 9 failures are test fixtures left stale by Oct 1–4 interface changes, not new runtime defects. The QA that closed HEAD ran only focused subsets (86 unit + 51 DB + 7 adversarial tests, partial lint), so this was never seen.
2. **Background loops are burning provider usage with no product value.** The live Core process (port 8000, up since 2026-10-05) re-runs a failing "Day 5A explicit provider verification" against the Codex CLI roughly every 33 minutes (`CodexTurnFailed`, `provider-recovery-codex_cli` BLOCKED, 30-minute retry). Since Oct 5 this produced 164 provider runs and 47 FAILED work items on Oct 8 alone. The previous autonomous run ended because model usage was exhausted; this loop is a plausible contributor.
3. **The Triad worker (port 8101) has been down since 2026-10-05 ~01:47 local and its supervisor cannot revive it.** Root cause verified twice: `tools/ensure_triad_worker.py:30-36` probes 127.0.0.1:8101 with `timeout=2`, and on this host a loopback refusal arrives at ~2.04 s, so the probe raises `TimeoutError` instead of `ConnectionRefusedError` and the supervisor aborts. 1,069 consecutive `NEEDS_ATTENTION` entries in `logs/triad-supervisor.log`.
4. **Scheduled autonomy is ENABLED in the database** (`DailySchedule.enabled=true` since 2026-10-01 02:39 UTC) while `AGENTS.md:18` says "Keep scheduled autonomy disabled until separately authorized." It cannot currently run (worker down, and its `product_policy_id` is stale against the Oct 3 `ProductCyclePolicy`, so `Daily.create` refuses), but it will resume dispatch the moment the worker is revived unless the record is changed. `docs/CORE_CHAT_VISION.md` records an operator agreement to scheduling checks, so the repo contradicts itself; this audit records both and changes neither.
5. **Aegis has nothing to build on yet beyond governance scaffolding.** Aegis is a 33-line FastAPI shell and a 1.7 KB static page. The Core backtest engine is a deterministic fixture-validation harness with no indicators, a strategy protocol that cannot express an indicator-driven exit, a 5k-row/30 s ceiling, and a 2026-only calendar. The only research-eligible data is 3 days of synthetic bars; the 10-year SPY/QQQ/ITOT archives are registered as REAL/FAIL and ineligible by design. There is no React, Vite, Vela, or chart-adapter code anywhere.

What *is* solid: the Core HTTP app and operator auth; the WorkItem state machine and append-only record stores; a populated knowledge graph (40,118 nodes) and Postgres ledger; tightly sandboxed Claude/Grok/Codex CLI integrations (MCP, ACP, exec-server behind Docker) with authenticated CLIs present; the data contracts, quality gate, cost/fill model, metrics and artifact-hashing of the research layer; and the git worktree change broker.

Git is clean on `main` but **207 commits ahead of origin and never pushed since 2026-09-29**, with 42 live worktrees (one dirty) and 17 unmerged branches.

**Recommended next mission (one):** *Mission 1 — Quiet Green Baseline*: stop the failing loops, make an explicit decision on the scheduler record, repair the test baseline, fix the supervisor probe, and push `main`. Details in §17. Do not start Aegis UI work on a red, noisy, unpushed base.

---

## 2. Git State

### 2.1 Snapshot

| Item | Observed |
|---|---|
| Current branch | `main` |
| HEAD | `9b61ed2` — "Resume only exact closed review maintenance checkpoints" (2026-10-04 07:52 -0500, author fordran-orange) |
| Working tree | **clean** (`git status --porcelain` empty before and after all verification runs) |
| Staged changes | none |
| Stashes | none |
| Merge / rebase / cherry-pick / bisect state | none (`.git` has no `MERGE_HEAD`, `REBASE_HEAD`, `CHERRY_PICK_HEAD`, `rebase-*`) |
| Upstream | `origin/main` @ `e9dc503` "Create SECURITY.md" (2026-09-29). **main is ahead 207, behind 1.** Merge base `f8fffa3`. Last fetch 2026-09-29 14:34 (`.git/FETCH_HEAD`). |
| Untracked files | none in the tracked tree. Ignored: `.env`, caches, `.venv`, `build/`, `backups/`, `data/*`, `logs/*`, root Parquet archives (via `.git/info/exclude`, local-only), 42 worktree checkouts under `data/temp` |
| Hooks | none installed (only `.sample`); `core.hooksPath` unset; runtime git calls pass `-c core.hooksPath=NUL` |
| Agent harness config in repo | none (`.claude/`, `CLAUDE.md`, `.codex/`, `.cursorrules` absent). `AGENTS.md` is the only in-repo agent instruction |
| CI | `.github/workflows/milestone1-stabilization.yml` triggers only on `codex/core-stabilize-m1`, `codex/m1-local-launch`, and manual dispatch — **never on `main` or PRs**; runs compileall, ruff on ~15 files, pytest on 7 files |

### 2.2 Commit cadence (unpushed range, all by fordran-orange)

| Day | Commits |
|---|---|
| 2026-09-29 | 53 |
| 2026-09-30 | 45 |
| 2026-10-01 | 51 |
| 2026-10-02 | 19 |
| 2026-10-03 | 31 |
| 2026-10-04 | 16 (last at 08:11 local) |

Subject categories: 21 "Triad protected merge after review", 21 "Triad independent review", 21 "Triad {CODEX|CLAUDE|GROK}: bounded reviewed-candidate improvement", and ~140 governance commits ("Bind…", "Require…", "Preserve…", "Recover…"). Most-changed files: `app/products/triad/sequential.py` (49), `static/product.html` (21), `sequential_recovery.py` (21). **Zero commits in the Oct 3–4 stream touch Aegis or the research/backtest layer.**

### 2.3 Branches and worktrees

| Group | Count | State |
|---|---|---|
| `codex/triad/{claude,codex,grok}/<uuid>` candidate branches | 41 | 27 merged into main; **14 unmerged**, each exactly 1 commit ahead (rejected/unreviewed candidates, dated 09-17 → 10-04) |
| Worktrees `data/temp/day3-worktrees/<uuid>` | 41 | all **clean**; created by `git_tools.py:55-74`; **no code ever removes or prunes them** |
| `data/temp/reconcile-stabilization-20260929` | 1 | branch `codex/provider-object-schema-completeness` @ `28eb45a` (unmerged, 1 ahead); **dirty**: 23 uncommitted added lines in `app/products/triad/sequential_correction_plan.py` (adds a `baseline_approved_file_snapshot` to correction planning) — in-progress work from the interrupted run |
| Other `codex/*` branches | 13 | 10 merged; unmerged: `codex/connected-browser-final-proof` (1 ahead, browser test edit), `codex/provider-object-schema-completeness` (1 ahead: `runtime.py` +3 lines, new `tests/test_strict_provider_schema.py`), `codex/reconcile-stabilization-20260929` (4 ahead / 2 behind; none patch-equivalent to main) |
| Remote-only | `origin/codex/core-stabilize-m1`, `origin/codex/m1-local-launch`, `origin/codex/day8-qa-reference` | not present locally |

Total local branches: 55. The three never-merged `research_readiness.{html,js}` feature files exist only on three unmerged claude worktree branches (`ae69046`, `3455476`, `c4d518e`); `daily_api.py:53-68` returns 503 for that route by design.

---

## 3. Architecture Map

```
Operator browser  ──►  127.0.0.1:8000  platform_host.api:app  (= trading_core.api.app + reverse proxy)
                           │   static HTML/JS (no build step)   /core /core/chat /research /settings/ai-providers ...
                           │   72 Core routes (+7 proxy)         operator token (Bearer, ≥32 chars, loopback Origin)
                           ├─► /triad*, /api/day3/*  ──proxy──►  127.0.0.1:8101  products.triad.server:app   [DOWN since 10-05]
                           └─► /aegis*  (and /p2p → 307)  ───►  127.0.0.1:8102  products.aegis.server:app   [UP, 3 routes]
Core lifespan thread: ProviderControl.monitor_connections() every 300 s (CORE_PROVIDER_MONITOR default on)
Triad lifespan threads (when up): daily_scheduler tick / jobs queue / LISTEN triad_worker_wake

PostgreSQL 17 + Timescale 2.25.2  127.0.0.1:55432  (docker triad-postgres-1, up 3 weeks)
   schema core: 25 tables — work_items, work_events, orchestration_records, day3_records (JSONB ledger),
                intelligence_records (append-only), projection_outbox, autonomy_control, product_* ...
   schema triad: cycle_jobs, cycle_slots, improvement_slots (product-owned)
   dormant: core.candles_1m (hypertable, 0 rows), datasets, experiments, metrics, orders, positions, events
Neo4j 5.26  127.0.0.1:57687  (docker triad-neo4j-1, up 2 weeks) — projection only, 40,118 nodes, 31 constraints
Ollama 0.35.0  127.0.0.1:11434  qwen3:4b (user-level service; supervisor keeps it alive)
Filesystem: data/raw, data/canonical (Parquet, zstd), data/manifests, research/experiments, docs/vault (journal md)

Providers (subscription CLIs, Docker-sandboxed):  claude 2.1.276 (MCP broker) · codex 0.155.0-alpha.2.6 (exec-server) · grok 1.0.34 (ACP)
API transports (anthropic/openai/xai): code present, no keys configured, fallback NEVER

Windows Task "Triad Core Supervisor" (pythonw, every 5 min, Ready) → ensure_core.ps1 → ensure_ollama.ps1 → ensure_triad_worker.py
```

| Capability | What actually exists | Classification |
|---|---|---|
| **Frontend** | Hand-written static HTML/JS/CSS in `app/trading_core/static/` and `app/products/*/static/`, served by `FileResponse`. No package.json, bundler, framework, or TypeScript anywhere outside vendor CLI `node_modules`. CSP allows `'unsafe-inline'`. | VERIFIED WORKING (serving); browser behaviour PRESENT BUT UNVERIFIED (no Core UI tests) |
| **Backend / API** | FastAPI 0.141 app `trading_core.api:app` (title "Trading Core operator services" v0.4.0); six sub-routers (providers, intelligence, integrations, conversation, research, operator). Gateway `platform_host.api` proxies to product workers. `platform_host.legacy` composes Triad in-process for 21 tests. | VERIFIED WORKING live (`/health/live`, `/api/status` 200). Sub-router modules are BROKEN when imported standalone (circular import with `trading_core.api`; works in production order) |
| **Provider integration** | `trading_core/providers/*` + `runtime.py`; CLI transports for Claude/Codex/Grok, HTTP transports for Anthropic/OpenAI/xAI/Ollama; routing in `intelligence/routing.py`. See §7. | PRESENT BUT UNVERIFIED (live re-verification not performed by this audit; DB shows Claude/Grok READY, Codex BLOCKED) |
| **Memory / knowledge** | Postgres JSONB records (authoritative) + Neo4j projection via outbox + Markdown journal export. Chat retrieval = term-overlap over Intake records. No text index, no embeddings. See §6. | Storage VERIFIED WORKING; retrieval PARTIAL; vision beyond Stage 1 DOCUMENTED ONLY |
| **Run / attempt lifecycle** | `work.py` WorkItem + 13-state `State` enum + `TRANSITIONS` table; `Store.create/step` with optimistic revision and `work_events`; per-call ledger records `AgentRunRequest/TransportRun/Usage/AgentRunResult`. No attempt table. | Contracts VERIFIED WORKING (DB-free tests); Store write paths PRESENT BUT UNVERIFIED here (integration tier skipped) |
| **Provenance / logging** | `core.orchestration_records` (Agent, PolicyDecision, ContextPacket, JournalEntry, Handoff, Review, Provenance), `core.day3_records` (Event, Usage, RunAuthority…), append-only `core.intelligence_records`, Neo4j lineage, journal Markdown. Python `logging` used in 2 places; uvicorn logs to `logs/api.*.log`. | VERIFIED WORKING (tables populated: 32,717 day3_records, ~10k intelligence records, 731 work items, 40k graph nodes) |
| **Artifact handling** | `ToolGateway.write` (exclusive-create, ≤64 KB, allowlisted roots), `core.artifact_owners` ownership table, git worktree broker, research Parquet/JSON artifacts with sha256. No retention/purge code. | ToolGateway VERIFIED WORKING (tests); ownership/git/research artifact paths PRESENT BUT UNVERIFIED here |
| **Tools / MCP** | Real MCP *server* subset (`ToolServer`: initialize, tools/list, tools/call, ping over loopback HTTP) consumed by the Claude CLI; Grok via ACP; Codex via `app-server`/`exec-server` with MCP emptied. Internal tool lists: `read_file`, `propose_file_change`; product workspace `list/read/write/delete/rename_file`, `run_command`. **No MCP client in Core.** | ToolServer VERIFIED WORKING (in-process test); native end-to-end runs PRESENT BUT UNVERIFIED |
| **Task / work-item orchestration** | `Orchestrator` (Day-2 demo path), `ExecutionServices` (product-neutral), `provider_slot` advisory-lock queue, `core.projection_outbox` drained by `Brain.flush`, product-owned `triad.cycle_jobs` (`FOR UPDATE SKIP LOCKED`). No generic Core job table. | `provider_slot`/ControlPlane VERIFIED WORKING (unit); outbox/leases PRESENT BUT UNVERIFIED |
| **Governance / gating** | ~25 technical gates inside the autonomous pipeline (ControlPlane, Limits, git broker, protected paths, ProductCyclePolicy, workspace grants, kill switch, sandbox); 16 enforcer tests; AGENTS.md policy. See §8. | VERIFIED WORKING for the pipeline; POLICY-ONLY for direct development |
| **Triad-specific logic** | `app/products/triad/*` (60 modules): daily sequential three-turn cycle (CODEX→CLAUDE→GROK propose/build/QA/merge/verify/debrief), schedulers, jobs, product research tools, operator consoles. | PARTIAL — ran end-to-end 10-01/10-02; runtime BROKEN since 10-05 (worker down, policy-id mismatch) |
| **Aegis** | 33-line shell (3 routes), static page, `012_aegis_lineage` migration, p2p alias. No backtest/chart/data code. | Shell VERIFIED WORKING; everything else DOCUMENTED ONLY |
| **Legacy `app/triad/*`** | 49 five-line `sys.modules` shims to `trading_core.*`, `platform_host.api`, `products.triad.*`. Imported by 19 tests and 21 tools (incl. `tools/health_check.py`). | legacy-but-referenced |

---

## 4. Verified Working Components

Evidence observed in this audit (live check, executed test, or read-only runtime probe at HEAD):

| Component | Evidence |
|---|---|
| Core FastAPI app + gateway on 8000 | PID 33704 since 2026-10-05 06:58; `GET /health/live` → `{"status":"ok","scope":"api_process_only"}`; `GET /api/status` → postgres up, timescale 2.25.2, neo4j up, ollama up (qwen3:4b), git main@9b61ed2 clean; `/api/foundation` 200 |
| Aegis worker on 8102 | PID 9408 since 2026-09-20; `/health/live` 200; `/aegis/api/status` → INACTIVE / PRESERVED / exchange CLOSED / `work_items: []` |
| Reverse proxy semantics | `/triad/*` → 503 "worker unavailable" (as designed when 8101 is down); `/aegis/*` 200 via Core; `/p2p` → 307 (tested) |
| PostgreSQL + Timescale, Neo4j containers | `docker compose ps` both Up/healthy (3 and 2 weeks); ports listening; read-only queries succeeded |
| Ollama + qwen3:4b | `/api/tags` lists qwen3:4b; `health_check.py` `configured_model_installed: true` |
| Operator auth and host middleware | `require_operator` HMAC compare + Origin allowlist (`api.py:70-95`); 401 path exercised in tests |
| WorkItem contracts / state machine / ControlPlane / Registry | `tests/test_orchestration.py`, `test_policy.py`, `test_governance.py` passed in the full run |
| Exchange CLOSED, live trading disabled (type level) | `ExchangeCandidate(status="OPEN")` and `Intent(live_trading_authority=True)` raise `ValidationError`; `import_candidate()` always raises `PermissionError` (live-checked by product agent) |
| Core → product import isolation | grep: 0 product imports in `app/trading_core`; `tests/test_architecture.py` passed (the AST scan and the blocked-import boot test) |
| Memory storage | Postgres: 731 work items, 32,717 day3 records, ~10k intelligence records, 57,548 outbox rows (24 undelivered, newest 23:27 UTC, delivery active). Neo4j: 40,118 nodes (Day3Record 32,797; Mission 785; WorkItem 735; PolicyDecision 708; JournalEntry 670; Evidence 1,512; Commit 1,415; Claim 222), 19 relationship types, 31 constraints |
| Provenance on chat replies and provider runs | `Usage`/`TransportRun`/`AgentRunRequest` records written per call (164 since Oct 5); chat live acceptance log at ancestor revision 4bb14bc shows provider/model/transport/tokens/intake IDs |
| Research fixture pipeline | 12 canonical FIXTURE Parquet files + manifests on disk; 2 experiments / 4 runs with `trades.parquet` (118 rows), `equity.parquet` (2,340 rows), `metrics.json` (27 keys), ACCEPT_RESULT reviews; `tests/test_lab.py` passed |
| MCP ToolServer subset, BoundedTools, OfflineSandbox | `tests/test_native_agents.py`, `test_isolation.py` (real Docker containers) passed in the full run |
| Windows supervisor task | `Triad Core Supervisor` Ready, fires every 5 min; `core-supervisor.log` shows 8 Core recoveries, 0 failures, 2,605 healthy checks |
| Build | `pip wheel` → `triad_foundation-0.2.0-py3-none-any.whl` (244 files, 19 html, 15 sql, 8 js); `compileall` exit 0; `pip check` clean; `docker compose config --quiet` exit 0; `git diff --check` clean; `tools/audit_foundation.py` passed (secret exclusion, lock pinned) |

---

## 5. Partial / Broken Components

| Component | Class | Evidence | Cause (where determined) |
|---|---|---|---|
| Default `pytest` invocation (`testpaths=["tests"]`) | **BROKEN** | "Interrupted: 1 error during collection" — `tests/products/triad/test_application_plan.py` imported first, then `tests/test_application_plan.py` → "import file mismatch" | Duplicate basename, no `__init__.py`/`conftest.py`/`importmode` setting. Product copy added `b019197` (10-03), root copy `f1f37ad` (10-03). Each file passes alone (11 and 3 tests). |
| `tests/test_proposal_recovery.py` (5 tests) | BROKEN TEST | `AttributeError: 'SequentialCycle' object has no attribute 's'` at `sequential.py:327` | Test builds `SequentialCycle` via `object.__new__` (last touched 09-30); `propose()` gained `self.s.rows(...)` in Oct 3–4 commits. Stale fixture. |
| `tests/test_day8_readiness_qa.py` (3 tests) | BROKEN TEST | `PARTIALLY_READY != READY`; `missing` = "Completed independently reviewed checks are missing" | Test stub `records.list(kind, conn=None)` lacks the `matching=` kwarg added to `Quality.require_pass` on 10-01 (`4660a63`, `7a16ebb`) → `TypeError` swallowed in `reviewed_checks` → evidence `None`. Stale fixture. |
| `tests/test_day8_daily_ui_qa.py::test_schedule_requires_existing_local_authorization[200]` | BROKEN TEST | 500 instead of 200; reproduced: `daily_api.py:49 configure` → `'SimpleNamespace' object has no attribute 'host'` | Handler now reads `service.host` (changed 10-02/10-03 `3db0f7f`, `d3fc7fc`); test stub (09-19) lacks it. Stale fixture. |
| Triad worker (8101) | **BROKEN** (down) | no listener; `logs/triad.pid` 37540 dead; `triad.stdout.log` stops 2026-10-05 01:47 | Process exit cause not recorded. Supervisor cannot restart it (next row). |
| Triad auto-recovery (`ensure_triad_worker.py`) | **BROKEN** | 1,069 consecutive `{"status":"NEEDS_ATTENTION","error_class":"TimeoutError"}` since 2026-10-05 06:52 UTC | `occupied()` uses `socket.create_connection(..., timeout=2)` and catches only `ConnectionRefusedError`; on this host loopback RST arrives at ~2.04 s (reproduced: timeout=2 → TimeoutError at 2.04 s; timeout=8 → ConnectionRefusedError at 2.04 s; same on control port 8103). Cause of the 2 s delay unknown (firewall/WFP enumeration denied). Tests monkeypatch `occupied`. |
| Provider recovery loop for Codex | **BROKEN / noisy** | `provider-recovery-codex_cli` = BLOCKED "Compatibility check failed: CodexTurnFailed", `retry_at` +30 min; a FAILED "Day 5A explicit provider verification" work item every ~33 min (47 on 10-08); `transport-status-codex_cli` health OFFLINE | `recovery.py:264-416` re-verifies on every 5-minute monitor pass once `retry_at` passes; verification spawns the Codex CLI (`codex app-server` + Docker exec-server). Why the Codex turn fails was not determined (would require sending a prompt). |
| Scheduled daily autonomy | **PARTIAL / wedged** | DB `DailySchedule.enabled=true` (10-01 02:39 UTC), `product_policy_id=1c953f24…` ≠ latest `ProductCyclePolicy 083309c4…` (10-03 19:04 UTC); claims 10-01..10-04; 10-03 BLOCKED (`ConcurrentUpdate`), 10-04 BLOCKED (`PermissionError: Scheduled authority requires acceptance of the current product policy`, `daily.py:188`) | Operator must re-POST the schedule to re-bind the policy; worker must be up. `ProductAutoRecovery` last: "Automatic recovery stopped after repeated failures" (10-04 14:08 UTC). |
| `tools/health_check.py` | PARTIAL / stale | `postgres_stack: {passed:false, error_type:"AssertionError"}` | Asserts a hypertable `triad.candles_1m`; after the Core extraction the hypertable is `core.candles_1m` (0 rows). Script also imports legacy `triad.settings`. |
| Research experiment reproduction | **BROKEN at HEAD** | `source_hash()` of `research/*.py` now `eb973ed8…`; both on-disk experiments record `37077f94…`/`87a16351…` | `Laboratory._run` raises `CODE_VERSION_MISMATCH` for existing experiments; UI "Reproduce run" is dead for them. New experiments unaffected. |
| Sub-router standalone imports | BROKEN (order-dependent) | importing `trading_core.providers.api` / `intelligence.api` / `integrations.api` / `research.api` / `conversation_api` before `trading_core.api` → circular `ImportError` | Each imports `require_operator` from `trading_core.api`, which imports them at module bottom. |
| Lint | PARTIAL | `ruff check app tools tests` → **46 findings, exit 1** (27 C408, 10 I001, 4 UP017, B023, SIM117, RUF012, RUF007, FURB162); `ruff format --check` → 93 files would be reformatted; with `--select E4,E7,E9,F`: 111 E402 (module-import-not-at-top: the `from trading_core.resources import resource` inserted above module docstrings in `store.py`, `ledger.py`, `runtime.py`, `control.py`, `support.py` and others), 11 E701, 4 E702, 3 E731, 2 F403, 1 F405 | QA at HEAD recorded "All checks passed!" for its focused lint; CI lints ~15 files only. |
| Type checking | ABSENT | no mypy/pyright in venv or config; node present but no TypeScript | — |
| `platform_host.legacy` | PARTIAL boundary | `from products.triad.api import router` — the one host→product import; `test_architecture.py` does not scan `platform_host` as a source | Documented as test-only. |
| Dormant foundation schema | DOCUMENTED ONLY | `core.candles_1m/datasets/experiments/metrics/orders/positions/events/operational_state/exchange_candidates` have no writers; 0 rows | Day-1 relics. |
| Stubs by design | PARTIAL | `ControlPlane.approve_elevation` always raises; `integrations/adapters.py` every broker method raises `CapabilityUnavailable`; `autonomous_cli.py` raise-only; `planning.walk_forward_windows` NOT_IMPLEMENTED | — |
| Docs vs code drift | DOCUMENTED ONLY | `/api/foundation` says phase "Day 4"; `research.html` titled "Day 04"; `docs/AI_PROVIDER_CONTROL.md`, `CODEX_CLI.md`, `PROVIDERS.md` say CLI work items are "not complete/blocked" while code and a 2026-09-18 PASS matrix say otherwise; `docs/KNOWLEDGE_ARCHITECTURE.md` vocabulary ≠ `brain.py`; `products/triad/docs/*` say scheduling disabled; `docs/SCHEDULER.md` describes 30 s ticks vs 300 s | — |
| Installed metadata | PARTIAL | `pip show triad-foundation` → 0.1.0 (stale editable dist-info) vs `pyproject.toml` 0.2.0 | — |
| Double-encoded em dashes | cosmetic | `api.py:210-211` bytes `C3 A2 E2 82 AC E2 80 9D` served by `/api/dashboard` | — |

---

## 6. Memory / Knowledge Assessment

**Storage — VERIFIED WORKING.**
- Authoritative store is PostgreSQL JSONB envelopes: `core.intelligence_records` (append-only trigger, `010_intelligence.sql:9-13`) holds `CoreConversation`, `CoreChatMessage`, `IntakeRecord`, `IdeaDisposition`, QA/ImplementationRun/CapabilityVersion…; every row is mirrored into `core.day3_records` (mutable `ON CONFLICT DO UPDATE`, `ledger.py:95`). `core.orchestration_records` holds ContextPacket/JournalEntry/Handoff/Review/Provenance/PolicyDecision; `core.work_items` + `core.work_events` hold the lifecycle with an authority-protecting trigger.
- Neo4j is a projection only, fed by `core.projection_outbox` via `Brain.flush` (24 undelivered rows, last delivery 23:27 UTC — healthy). Chat and intake rows project only as opaque `Day3Record` nodes; chat never triggers a flush itself.
- Markdown journal projection: 673 files in `docs/vault/02_Journal/generated/` (gitignored).
- **No vector, embedding, tsvector, or any text index exists** anywhere (grep of code, SQL, deps).

**Retrieval — PARTIAL.** The only retrieval chat uses is `Intake.retrieve` (`intake.py:159-182`): load *all* Core-owned IntakeRecords (no LIMIT), split the query into words >2 chars, score by substring hits, return the top 3 with a 1,200-char prefix, **no minimum score** (zero matches still returns the 3 newest). Conversation memory sent to the model = same-conversation messages newest-first up to 10,000 chars. Other conversations, journals, decisions, work items, graph lineage and product records are not retrievable by chat. Graph lineage (`Brain.lineage`, one hop) is used only by `/api/work/{id}`.

**Provenance — VERIFIED WORKING.** Assistant messages carry `run_id, work_item_id, provider, model, transport, billing_source, input/output_tokens, retrieval_source, intake_ids`; `Usage` records are mandatory (`MissingUsageEvidence` otherwise); IntakeRecord carries `content_hash`, `trust_level`, `channel`, server `received_at`. **Missing:** original author/timestamp, attachments, revisions, import-vs-original chronology.

**Schemas — PARTIAL.** Pydantic contracts exist for WorkItem, IntakeRecord, Provenance, ContextPacket, JournalEntry, Handoff, Review, AgentRunRequest/Result. **None exist for `CoreConversation`, `CoreChatMessage`, `IdeaDisposition`** (ad-hoc dicts). SQL is schemaless JSONB; spot-checks of `intelligence_records`, `work_items`, `orchestration_records` DDL vs writers match. Owner CHECK was widened to `aegis` by migration 012. `Submission.destination` is `Literal["core","triad"]` — **no Aegis intake destination**.

**APIs.** Conversation/intake routes (`conversation_api.py`): `GET/POST /api/core/conversations`, `GET /api/core/conversations/{id}`, `POST …/{id}/messages`, `GET/POST /api/core/intake`, `POST …/intake/{id}/disposition` — all operator-token. No search/knowledge/graph route exists. Chat UI does call a real provider (CODEX live-verified at ancestor 4bb14bc; CLAUDE/GROK chat paths unverified), read-only authority, claims forbidden.

**Tests.** `tests/test_core_conversation.py` (4), `test_quality_filtered_lookup.py`, `test_ownership_integration.py`, `test_day2_integration.py` are all `integration`-marked and **skipped** in this run (`TRIAD_INTEGRATION=1` not set; they create a disposable DB). `test_evidence_delivery.py` (unit) passed. No unit test covers `Intake.retrieve` ranking; no `tests/` test covers `conversation.html/js`.

**Startup dependencies — VERIFIED.** `Settings()` requires `POSTGRES_PASSWORD`/`NEO4J_PASSWORD` in `.env`; no DB connection at import or lifespan start (monitor thread catches errors). Postgres down → `/api/dashboard` 503, conversation routes unhandled 500. Neo4j down → chat unaffected, lineage returns `graph_error`.

**Gap vs `docs/CORE_CHAT_VISION.md` "Intake and memory":** implemented = typed text intake, auto-saved native conversations, idea dispositions, run-linked provenance, ownership boundaries. Partial = passage retrieval (record-level, no threshold), evidence summaries (prose citations only), history recall (one conversation). Missing = file/archive/connector intake, revisions, original chronology, any text/semantic index, Aegis destination, artifact/decision linking from chat, memory contracts. **Nothing here should be redesigned by this mission**; it is recorded for Aegis reuse planning.

---

## 7. Provider Integration Assessment

**Transport model.** `providers/contracts.py:8-34` defines 7 transports; the preferred transport for CODEX/CLAUDE/GROK is the vendor **CLI** (subscription billing), with HTTP **API** transports as disabled fallbacks; LOCAL_QWEN uses Ollama HTTP. No `httpx`, `anthropic`, or `openai` SDK in the provider stack — all HTTP via `urllib.request`.

| Provider | Transport actually used | Credential source | Installed / state on this machine | Classification |
|---|---|---|---|---|
| Anthropic / Claude (`claude_code_cli`) | `claude --print --input-format stream-json … --tools "" --strict-mcp-config --mcp-config {triad loopback MCP} --permission-mode dontAsk --allowedTools mcp__triad__read_file[…]` (`native_agents.py:640-681`); hooks/plugins/memory/sessions disabled | claude.ai subscription login (`claude auth status --json` must say `authMethod=claude.ai`) | CLI 2.1.276 at `data/provider-cli/node_modules/@anthropic-ai/claude-code` (preferred), 2.1.295 at `~/.local/bin`; `~/.claude/.credentials.json` exists. DB: INSTALLED, AUTHENTICATED, recovery **READY**, health OFFLINE (`OuterBoundaryUnavailable` = no read-only outer boundary for non-REVIEW roles) | PRESENT BUT UNVERIFIED (REAL PASS artifact 2026-09-18 `claude-sonnet-5`) |
| Anthropic API (`anthropic_api`) | `POST https://api.anthropic.com/v1/messages` (`runtime.py:255-273`) | Windows Credential Manager `Triad/AIProviders/anthropic_api` via `secrets.py`; **`.env` has no `ANTHROPIC_API_KEY`** | DB: NOT_AUTHENTICATED, `CredentialsOrModelNotConfigured` | PRESENT BUT UNVERIFIED; disabled |
| OpenAI / Codex (`codex_cli`) | host `codex app-server --stdio -c mcp_servers={}` + Docker `codex exec-server` in image `triad-codex-executor:0.155.0-alpha.2.6` over a loopback WebSocket relay (`codex_executor.py`); **read-only REVIEW only** | ChatGPT subscription (`codex login status`) | node + `codex.js` 0.155.0-alpha.2.6 (preferred), `codex.exe` 0.162.0-alpha.2; `~/.codex/auth.json` exists. DB: INSTALLED, AUTHENTICATED, recovery **BLOCKED** (`CodexTurnFailed`), retrying every 30 min | PRESENT BUT UNVERIFIED; currently failing verification |
| OpenAI API (`openai_api`) | `POST https://api.openai.com/v1/responses` | Credential Manager; no `OPENAI_API_KEY` in `.env` | NOT_AUTHENTICATED | PRESENT BUT UNVERIFIED; disabled |
| xAI / Grok (`grok_build_cli`) | `grok --no-auto-update --disable-web-search … agent stdio` (ACP JSON-RPC), `GROK_*` disable flags; `fs/read_text_file`→`read_file`, `fs/write_text_file`→`propose_file_change`, everything else denied | OIDC subscription via ACP `authenticate cached_token` | node + `grok` 1.0.34; `~/.grok/auth.json` exists. DB: INSTALLED, AUTHENTICATED, recovery **READY** | PRESENT BUT UNVERIFIED (PASS artifact `grok-4.6`) |
| xAI API (`xai_api`) | `POST https://api.x.ai/v1/chat/completions` | Credential Manager; no `XAI_API_KEY` in `.env` | NOT_AUTHENTICATED | PRESENT BUT UNVERIFIED; disabled |
| Ollama / Qwen (`ollama`) | `POST http://127.0.0.1:11434/api/generate` (think=false, loopback enforced) | none | ollama.exe 0.35.0, qwen3:4b present; DB recovery READY; transport test `TRIAD_TRANSPORT_OK` | VERIFIED WORKING (health probe) / inference PRESENT BUT UNVERIFIED |

**Paid API fallback is disabled by default**: `ProviderPolicy.fallback="NEVER"`, `api_daily_budget=0`, `max_cloud_cost_day=0.0` in live `autonomy_control`; `TransportRouter.select` denies with `APIFallbackDisabled` unless an unexpired `FallbackGrant`, a stored secret, health AVAILABLE and budget all exist.

**Routing** is evidence-gated lookup, not inference: a run needs a `CapabilityVersion` row (provider+model+transport, VERIFIED) per required capability, a proven `TransportStatus` (installed + both REAL proofs + AUTHENTICATED), role table (`codex_cli → REVIEW`; `claude/grok → REVIEW,PROPOSE,IMPLEMENT`; `ollama → SUPPORT`), and ControlPlane ALLOW. `Auto` model is frozen to the last proven `actual_model`.

**Isolation** (relevant to any Aegis task bridge): every file tool runs in `OfflineSandbox` (`docker create --network=none --read-only --cap-drop=ALL … --memory=256m`), models get only `read_file`/`propose_file_change` (≤12 KB), proposals are staged `FileChange`s never written to host. The product-workspace profile (`run_command`, writes) is **hard-wired to Triad**: `PRODUCT_ROOTS=("app/products/triad","products/triad","tests/products/triad")`, `work.owner=="triad"`, QA evidence prefix `product-workspace-v1:`. **Aegis paths are not writable under any current grant.**

**Recovery / durability.** `recovery.py` re-verifies a transport when its `workitem` proof is >1 day old, the model changed, or the executable identity changed; failures set `retry_at = now+30 min`. This is the machinery producing the recurring failing Codex work items. The Oct 3–4 commit stream is about *product-cycle* recovery (`sequential_*`), not provider durability.

**Tests.** 151 provider test functions; CLI paths are all faked (`LineProcess` fakes, monkeypatched discovery) — **0 would fail without CLIs installed**; 11 skip without Docker; 41 skip without `TRIAD_INTEGRATION`. No live-CLI pytest exists; live checks are tools (`check_native_agents.py`, `check_provider_acceptance.py`; `check_codex_executor.py` uses `shutil.which("codex.exe")` and would fail here since codex is off PATH).

**Drift noted:** `native_agents.py:22 VERSIONS` pins are used only by a test; runtime accepts any 2.x/0.x/1.x family, so the newer `claude.exe 2.1.295` or `codex.exe 0.162` would be accepted if found first. Two Ollama inference implementations with different semantics (`HttpProvider` think=false vs legacy `QwenProvider` think=true used by `orchestrator.py`). `app/triad/day5a/*` are live re-export shims, not dead code.

---

## 8. Governance / Gating Map

**Headline:** every *technical* gate found lives inside the autonomous Triad pipeline or in voluntarily-run tests. **No technical mechanism blocks a human or an agent with shell access from committing to `main`** (no hooks, no CODEOWNERS, CI not wired to `main`/PRs, runtime git disables hooks). `AGENTS.md`'s independent-QA rule is **policy only**. There are no repo-level Claude Code / Codex harness rules.

### 8.1 Mechanisms

| # | Mechanism | Location | Trigger | Effect | Type | Impact on rapid Aegis dev |
|---|---|---|---|---|---|---|
| A1 | Independent QA per implementation; builder ≠ verifier; re-QA after correction; no merge without QA + Core governance | `AGENTS.md:9-13` | any implementation | second-agent QA pass per bounded segment | **POLICY** | **HIGH** (process cost on every change; unenforced) |
| A2 | Core imports neither product; exchange CLOSED; live trading disabled; scheduled autonomy disabled | `AGENTS.md:15-18` | any change | preserve boundaries | POLICY (boundary also TECHNICAL via tests) | LOW |
| A3 | "Aegis remains human-directed… this planning direction does not start that build" | `AGENTS.md:20-25` | Aegis work | agents wait for explicit go | POLICY | MEDIUM |
| A4 | Operator direction: bounded Aegis charting/backtesting permitted; Vela behind adapter; "avoid new routine human approval gates" | `docs/CORE_CHAT_VISION.md:139-146,164-166` | Aegis work | enabling | POLICY | LOW (enabling) |
| A5 | CI workflow | `.github/workflows/milestone1-stabilization.yml:3-8` | push to two `codex/*` branches / manual | compileall, partial ruff, 7 test files | TECHNICAL, not wired to main | NONE |
| A6/A7 | Git hooks, CODEOWNERS, branch protection | absent | — | — | ABSENT | NONE |
| A8 | Harness config | repo none; `~/.claude/settings.json` has only `autoUpdatesChannel`; `~/.codex/config.toml` has `sandbox_mode` | tool calls | harness sandbox | CONFIG (harness) | NONE repo-specific |
| B1 | Protected Core paths for autonomous merge | `governance.py:9-40,60-83` | pipeline merge | blocks `app/*` except `app/products/triad/`, all `config/`, `control-plane/`, `tools/`, `infrastructure/`, `.github/`, `AGENTS.md`, dotfiles, **and `app/products/aegis/`** | TECHNICAL | NONE for direct dev; makes Aegis-by-Triad impossible by design |
| B2 | ControlPlane policy | `control.py:113-203` | dispatch/merge | DENY money/trading/LIVE/tier 4; REQUIRE_HUMAN_APPROVAL on permission changes/GOVERNANCE; independent reviewer; `approve_elevation` always raises | TECHNICAL | NONE |
| B3 | Intent / RuntimePolicy contracts | `policy.py:22-26,43`; `control-plane/*.schema.json` | validation | `live_trading_authority` const false; risk limits ≤0 | TECHNICAL | NONE |
| B4 | Autonomy limits | `Limits.schema.json`; live `core.autonomy_control`: epoch 4, paused false, killed false, `require_human_review` false, `max_changes_day` 3, `max_cloud_cost_day` 0.0, `max_migrations` 0, `max_high_risk` 0, `max_files` 3, `max_lines` 180, `allowed_directories` docs/improvements, research/improvements | reservation | caps | TECHNICAL + CONFIG | NONE |
| B5 | Git broker | `git_tools.py:50-53,76-153,201-264` | pipeline git | clean main baseline; only `.md/.json/.txt` on Day-3 path; no deletions; `*_autonomous` always raise; merge needs reviewer≠worker APPROVE, matching commits, unchanged baseline | TECHNICAL | NONE |
| B6 | Product change staging + `ProductCyclePolicy` | `product_changes.py:19,58-121,186-225,265-289,408-462` | pipeline build/QA/merge | Triad roots only; approval cannot waive failed checks; candidate tests run in a reviewed immutable Docker image; changing `sequential.py` needs a Core-QA'd policy activation | TECHNICAL | NONE |
| B7/B8 | Workspace and engineering grants | `product_workspace_grant.py`, `engineering.py` | IMPLEMENT runs | tier 2, independent reviewer, exact files, epoch-bound | TECHNICAL | NONE |
| B9/B10 | Development / Sequential merge | `development.py:545-779`; `sequential.py:1203-1242` | pipeline merge | QA match ×2, ownership, hash/diff equality, then B5. `require_human_review` is checked explicitly only on the legacy `Development.merge` path; the live sequential path relies on `ledger.gate()` | TECHNICAL | NONE |
| B11 | DailySchedule enablement | `daily.py:151-152,796-852`; `daily_api.py:44` | enabling | default `enabled=False`; enabling needs operator token + a COMPLETED manual REAL cycle; scheduled create needs matching schedule/epoch/policy id | TECHNICAL + CONFIG (**live: enabled=true, stale policy id**) | NONE |
| B12 | Scheduler ticks / claims | `daily_scheduler.py:43-112`; legacy `scheduler.py:12-19` (config `enabled:false`) | Triad worker loop | one claim per local date; epoch/prereq guard | TECHNICAL | NONE |
| B13 | Post-merge verification reads Aegis | `daily_verification.py:50-57`; `product_deployment.py:85-127` | after Triad merge | requires `/aegis/api/status` `exchange==CLOSED`, `mode==human_directed`, `work_items==[]`, else auto-revert | TECHNICAL | **MEDIUM** — changing Aegis status shape or giving Aegis work items breaks Triad's deploy check |
| B14–B24 | Deployment rollback, QA reference integrity, ledger kill switch/epoch, provider gate/budget, OfflineSandbox, BoundedTools, `ensure_no_secret`, ownership/exchange, resource/token limits, research method review, agent registry | see §3/§7 files | pipeline runs | as named | TECHNICAL | NONE |
| B25 | Windows task "Triad Core Supervisor" | `install_core_supervisor.ps1`; `run_core_supervisor.py` | logon + every 5 min | restarts Ollama/Core/Triad worker | CONFIG (OS, active) | NONE directly; it is what would revive scheduled dispatch |

### 8.2 Enforcer tests (TECHNICAL, only when pytest runs)

| Test | Fails if… |
|---|---|
| `tests/test_architecture.py:10-39` | `app/trading_core` imports `products|triad|platform_host`; `products/aegis` imports `products.triad|triad|platform_host`; `products/triad` imports `products.aegis|platform_host` |
| `test_architecture.py:42-64` | Core cannot boot with products blocked; `/api/core/control` without token ≠ 401 |
| `test_architecture.py:67-73` | `config/core/*.json` ≠ `app/trading_core/resources/config/*.json`; `resources/sql/*.sql` ≠ `infrastructure/postgres/*.sql` bytes |
| `test_architecture.py:113-125`, `test_day7_a2_qa.py:38-46` | `/aegis` HTML lacks "Aegis product shell" / "INACTIVE" / "PRESERVED"; `/p2p` not 307 |
| `test_governance.py`, `test_reconcile_governance.py` | protected-path classification changes; autonomous git entry points stop raising |
| `test_policy.py:27-62` | Intent accepts live trading / broker tools / non-zero risk |
| `test_product_identity.py` | `CURRENT_PRODUCTS` ≠ {core,triad,aegis}; p2p alias changes |
| `test_daily_scheduler.py`, `test_day8_scheduler_qa.py` | scheduler not DISABLED by default; enable without manual cycle; >1 claim/day |
| `test_day7_ghi_qa.py:146-159` | **any byte change** to `docs/improvements/real-market-readiness-criteria.md` (SHA pinned) or phrase removal from `…-definitions-v2.md` |
| `docs/qa/*_HASHES.json` | **not verified by any test or runtime code** — editing is not test-breaking |
| `tests/test_application_plan.py` (11 governance tests) | **currently never run by the default suite** (shadowed by the basename collision) |

### 8.3 The four things that must stay hard-gated

| Item | Technical protection | Gap |
|---|---|---|
| Live-money execution | ControlPlane DENY; `Literal[False]` contracts; risk limits ≤0; agents max tier 2; no broker/order code exists; Aegis status hard-coded human_directed | protection = absence of capability + pipeline DENY. Nothing technically stops a direct commit adding broker code. |
| Secrets / credentials | `ensure_no_secret` at git/sandbox/QA boundaries; API keys only in Windows Credential Manager via operator route; sandbox passes no env; git env whitelist; `.env` protected from pipeline | no pre-commit/CI secret scan on `main` |
| Destructive actions | pipeline deletions denied / hash-bound; rollback via `revert` only; DB triggers block lineage rewrites; kill switch | human `git push --force`, `rm -rf`, `docker compose down -v` ungated (README warns only) |
| Foundational schema/contract changes | `control-plane/`, `config/`, `infrastructure/`, `app/trading_core/` protected from pipeline merge; `max_migrations=0`; config/SQL mirror tests | direct edits blocked by nothing except running pytest (CI not on main) |

**Net:** all four are hard-gated against the autonomous pipeline; **none** is technically gated against direct commits to `main`.

### 8.4 Scheduled autonomy status (recorded, not changed)

- Legacy Day-3 scheduler: **DISABLED** by config (`config/triad/product.json` `scheduler.enabled:false`, mirrored in packaged copy and `agents/day3.json`).
- Current daily scheduler: **ENABLED in Postgres** — latest `DailySchedule` (`4a558a02…`, 2026-10-01 02:39 UTC) `enabled=true`, 09:00 America/Chicago, all days, `effective_after=2026-10-01`, `control_epoch=4`, `product_policy_id=1c953f24…` (history: true 09-30 → false 10-01 01:38 → true 10-01 02:39). Claims fired 10-01, 10-02, 10-03, 10-04 (14:00 UTC). Outcomes: 10-01 COMPLETED (merge `d2555de`), 10-02 COMPLETED (merge `7f62c18`, CLAUDE NO_CHANGE), 10-03 BLOCKED (`ConcurrentUpdate`), 10-04 BLOCKED (policy-id mismatch). No claims since (worker down).
- The host of the tick loop (Triad worker 8101) is down; the OS supervisor is trying every 5 minutes to bring it back (and failing, §5). **If the worker is revived with the record unchanged, scheduled dispatch resumes** (and will be refused at `Daily.create` until the schedule is re-POSTed against the Oct 3 policy).
- Conflict: `AGENTS.md:18` ("Keep scheduled autonomy disabled until separately authorized") vs `docs/CORE_CHAT_VISION.md` ("The operator agreed to five-minute idle scheduling checks, deadline wake-up at 09:00 local time…") and `docs/CLOSEOUT_2026-09-19.md:43`, `docs/DAY8_REPORT.md:89`. Whether the 10-01 enablement was "separately authorized" is not determinable from the repository.

---

## 9. Runtime Assessment

**Start sequence (documented and observed).** `docker desktop start` → `tools/day4.py init` → `tools/start_backend.ps1` which optionally runs `python -m trading_core.upgrade`, then `Start-Process … -m uvicorn platform_host.api:app --host 127.0.0.1 --port 8000 -WindowStyle Hidden` (logs `logs/api.*.log`, `logs/api.pid`), then `start_product.ps1 -Product triad` (8101) and `-Product aegis` (8102). The venv `python.exe` is a launcher; the listener is its child (PID files point at the launcher, not the listener).

**Canonical commands today.** Backend: `.\tools\start_backend.ps1` (all), `-CoreOnly`, `.\tools\start_product.ps1 -Product triad|aegis`, `-UpgradeDatabase` for migrations. Frontend: **none** — static files served by FastAPI; there is no frontend build.

**Supervision.** Windows Scheduled Task **"Triad Core Supervisor"** (State Ready; at logon + every 5 min, `pythonw.exe tools/run_core_supervisor.py`, `MultipleInstances IgnoreNew`, 10-min limit) → `ensure_core.ps1` (always runs `ensure_ollama.ps1` first and propagates its exit code; if `/health/live` ≠ ok → `docker compose up -d --wait` + `start_backend.ps1 -CoreOnly`) → `ensure_triad_worker.py` (wedged, §5). **Nothing supervises Aegis** (`-CoreOnly`).

**Background tasks inside the apps.** Core lifespan: daemon thread `ProviderControl().monitor_connections()` every 300 s (`CORE_PROVIDER_MONITOR` default "1"; `"0"` disables) → `refresh` + `recover` → the Codex re-verification loop. Triad lifespan (when up): three daemon threads (`loop` → reconcile/daily tick/legacy tick every 300 s; `queue_loop` → `Jobs().once()`; `listen` → `LISTEN triad_worker_wake`); dispatch gated by DB `DailySchedule`. Aegis: none. No APScheduler/`asyncio.create_task`.

**Live state at audit time.**

| Item | State |
|---|---|
| Core 8000 | UP, PID 33704 (launcher 6620) since 2026-10-05 06:58, restarted by the supervisor ("Core recovered") — runs HEAD source |
| Triad 8101 | **DOWN** since ~2026-10-05 01:47 local; `triad.pid` 37540 stale |
| Aegis 8102 | UP, PID 9408 (launcher 37376) since 2026-09-20 |
| Postgres 55432 / Neo4j 57687+57474 | UP (healthy, 3 and 2 weeks) |
| Ollama 11434 | UP (`ollama.exe serve` PID 32576, supervisor-started 09-29); separate user tray app `ollama app.exe` also running |
| Scheduled task | Ready; last run 18:37 local; next +5 min; firing continuously |
| `/health/live` | 200; `/health`, `/health/ready` → 404 (do not exist) |
| `/api/status` | all up; git main@9b61ed2 clean |
| `tools/health_check.py` | **exit 1** — `postgres_stack` AssertionError (asserts legacy `triad.candles_1m` hypertable; actual hypertable is `core.candles_1m`); everything else passed |
| Visible windows | none Triad-owned at audit time |

**Likely source of remaining popup windows.** Every Triad launcher is hidden (`-WindowStyle Hidden`, `CREATE_NO_WINDOW`, pythonw task action). The exception: `daily_process.py:78-86` launches `tools/run_daily_product_cycle.py` with `DETACHED_PROCESS` (console-less), and inside that runner every `git`/`pytest`/`docker` subprocess (`git_tools.py:37-44`, `daily_verification.py:16-32`, `qa_reference.py:37-42`, `product_changes.py:177-179`, `orchestrator.py:26`) is spawned with default creation flags → each gets a **new visible console** for its duration. The recurring Codex verification also spawns `codex app-server` and `docker exec` (`process.py:172`, `codex_executor.py:84` use `CREATE_NO_WINDOW`, so those should be hidden). Not Triad-owned: the user's Ollama tray app started via `cmd.exe`.

**Health checks that exist:** `tools/health_check.py` (DB creds, stale assertion), `GET /health/live` (Core, Triad, Aegis), `GET /api/status`, `GET /api/foundation`, `GET /triad/product-api/health`, `GET /triad/api/readiness`, `POST /api/day3/health` (operator token; live provider probes), `GET /aegis/api/status`.

**Outage root cause (verified by two independent reproductions):** `ensure_triad_worker.occupied()` → `socket.create_connection(("127.0.0.1",8101), timeout=2)` → on this host a closed loopback port returns RST at ~2.04 s → `TimeoutError` (not caught) → supervisor aborts before `start_product.ps1`. With `timeout=8` the same connect yields `ConnectionRefusedError` at 2.04 s. Why loopback refusal takes 2 s here is **UNKNOWN** (firewall/WFP enumeration denied; `codex-windows-sandbox-service` is running — unverified candidate). Why Core and Triad both stopped at ~01:47–01:52 on 10-05 and Core again at ~06:57 is not recorded in any log (Aegis, Ollama, Docker survived → not a reboot).

---

## 10. Build / Test Results

All commands run from `C:\Triad` with `.venv\Scripts\python.exe`; nothing edited to make anything pass.

| Check | Command | Result |
|---|---|---|
| Collection | `pytest --collect-only -q` | 1,547 tests collected, **1 error** (`test_application_plan.py` basename collision) → default `pytest` run is **Interrupted** (exit 2, 0 tests run) |
| Full suite | `pytest -q -ra --durations=25 --continue-on-collection-errors -p no:cacheprovider` | **9 failed, 941 passed, 597 skipped, 1 error, 209 subtests passed, 5 warnings, 471 s** (exit 1) |
| Skips | — | 597 = integration tier (`Enable live integration tests with TRIAD_INTEGRATION=1`; fixture creates a disposable DB). Not enabled by this audit to avoid writing to the live Core database. |
| Failures | — | `test_proposal_recovery.py` ×5 (`SequentialCycle` has no `s`), `test_day8_readiness_qa.py` ×3 (`PARTIALLY_READY`), `test_day8_daily_ui_qa.py` ×1 (500: stub lacks `host`). All stale fixtures vs Oct 1–4 code (§5). |
| Shadowed file alone | `pytest tests/test_application_plan.py` | 11 passed (2.2 s); `tests/products/triad/test_application_plan.py` alone: 3 passed |
| Slowest | — | `test_engineering.py::test_actual_offline_approved_checks_and_native_staging` 27.8 s; `test_isolation.py` real-Docker tests 7–20 s each |
| Lint | `ruff check app tools tests` | **46 findings, exit 1** (27 C408, 10 I001, 4 UP017, 1 each FURB162/B023/SIM117/RUF012/RUF007); settings resolved from `pyproject.toml` (ruff 0.16.8). With `--select E4,E7,E9,F`: 111 E402, 11 E701, 4 E702, 3 E731, 2 F403, 1 F405 |
| Format | `ruff format --check` | 93 files would be reformatted, 287 already formatted |
| Type check | — | **none configured** (no mypy/pyright/pyre in venv; no tsc) |
| Compile | `python -m compileall -q app tests tools` | exit 0 |
| Dependencies | `pip check` | "No broken requirements found" |
| Build | `pip wheel --no-deps --no-build-isolation -w <scratch> .` | `triad_foundation-0.2.0-py3-none-any.whl` 546,716 B, 244 files (platform_host 3, products 69, trading_core 113, triad 55); static html/js/sql included |
| Compose | `docker compose config --quiet` | exit 0 |
| Whitespace | `git diff --check` | clean |
| Foundation audit | `tools/audit_foundation.py` | passed (15 folders, 11 files, 856 tracked, secret exclusion, lock pinned, venv) |
| Health | `tools/health_check.py` | **exit 1** (`postgres_stack` AssertionError — stale `triad.candles_1m` hypertable assertion); postgres, timescale 2.25.2, neo4j, ollama (qwen3:4b) passed |
| HTTP health | GET `/health/live`, `/api/status`, `/api/foundation`, `:8102/health/live`, `/aegis/api/status`, `:11434/api/tags` | all 200; `/triad/*` 503 (worker down); `/health`, `/health/ready` 404 |
| QA evidence at HEAD (for comparison) | `logs/qa-maintenance-9b61ed2-*.log` | lint "All checks passed!" (focused files), unit 86 passed, db 51 passed (7m02s), adversarial 7 passed — **a focused subset, not the full suite** |
| Working tree after all checks | `git status --porcelain` | clean (only ignored `logs/health.latest.json`, `build/`, `__pycache__` touched) |

---

## 11. Interrupted-Run Findings

What the interrupted autonomous run left behind, and what has happened since:

1. **Last governed action completed cleanly.** 2026-10-04 07:52 commit `9b61ed2`; independent QA PASS (`closed-qa-maintenance-independent-qa.json`), protected merge PASS, deployment restart at 08:12 with all routes 200 and `loaded_revision 9b61ed2`. The system was idle-but-healthy at that point.
2. **In-progress, uncommitted work:** `data/temp/reconcile-stabilization-20260929` has 23 uncommitted lines in `sequential_correction_plan.py` (adds `baseline_approved_file_snapshot` to correction planning context). Its branch `codex/provider-object-schema-completeness` @ `28eb45a` (08:32 on 10-04 — *after* HEAD) is unmerged and adds `tests/test_strict_provider_schema.py` + 3 lines in `runtime.py`; `logs/provider-object-schema-independent-qa.json` (08:36) exists. `codex/reconcile-stabilization-20260929` is 4 ahead / 2 behind main with no patch-equivalents. `codex/connected-browser-final-proof` (1 ahead) edits `browser_experiment.py`.
3. **Scheduled cycle on 10-04 failed before creation:** `logs/daily-13cec1a0….log` → `PermissionError: Scheduled authority requires acceptance of the current product policy` (`daily.py:188`). A governed cycle `6cec22e9…` exited with `CodexTurnFailed` (`connected-application-live-closed-qa-recovery.json`, 09:08). `ProductAutoRecovery` 14:08 UTC: "Automatic recovery stopped after repeated failures."
4. **Processes died ~18 h later:** Triad worker stdout stops 2026-10-05 01:47; Core recovered by the supervisor at 01:52 and again at 06:58 (current PID). No log explains the exits.
5. **Since then the only activity is machine noise:** per day 47–57 work items (all the failing Codex verification), 77–131 outbox writes per hour, 164 provider runs, 12 `ProviderRuntimeAttestation` and 164 `ResourceAllocation` records — no product work, no merges, no claims.
6. **Test baseline regressed unnoticed** (§5, §10): HEAD's QA ran subsets; the full suite has 9 stale-fixture failures and a collection collision introduced on 10-03.
7. **Accumulated residue:** 41 clean candidate worktrees (never pruned by code), 55 local branches, stale PID files (`triad.pid`, `p2p.pid`, `day6-qa-c-preview.pid`, two `core-conversation-ui-*-fixture.pid`), a full repo checkout under `logs/application-candidate-763b1f3-source/` (7.5 MB) plus ~140 QA source-snapshot directories under `logs/`, three exited Docker leftovers (`pedantic_sutherland`, `awesome_curie`, `triad-baseline-graph-restore`).
8. **No lock files to clear:** all mutual exclusion is Postgres advisory locks (die with the session).
9. **Nothing has been pushed since 2026-09-29**: 207 commits exist only on this machine.

---

## 12. Aegis Readiness

Target vertical slice: chart workspace, strategy control panel, 9 EMA / 30 SMA crossover, independent long/short logic, session windows, deterministic backtest, trade ledger, equity curve, metrics, exhaustive optimizer, heatmap — UI-first against a locked design, React UI, local Python backtest service, local Parquet OHLCV.

| # | Requirement | Rating | Evidence |
|---|---|---|---|
| 1 | React Aegis UI | **SIGNIFICANT WORK** | No React/Vite/TSX/package.json in the repo (only vendor CLI installs). Aegis = `server.py` 33 lines (3 routes) + 1.7 KB static page. Node v24.14 / npm 11.9 are on PATH. Core UI pattern is single-file vanilla JS served by FastAPI; `pyproject.toml` package-data for `products.aegis` covers `static/*.html` and `resources/*` only. Tests pin "Aegis product shell"/"INACTIVE"/"PRESERVED" strings in `/aegis` HTML. No Vela code or chart adapter anywhere (4 prose mentions only). |
| 2 | Local Python backtest service | **SIGNIFICANT WORK** | `trading_core/research/engine.py` is a deterministic close-signal/next-open fixture harness: strategies locked to `Literal["periodic-fixture-v1","hold-fixture-v1"]` with parameters exactly `{period, hold}`; **zero indicators** (grep EMA/SMA/ewm/rolling → none); `exit_logic(index, entry_index, parameters)` receives no price history and `generate_signal` is only called while flat → a crossover exit is not expressible without changing the Strategy protocol; long/short are separate accounting passes with the same parameters; no intraday time window (regular-session purity only); calendar hard-coded to **2026**, `expected()` ≤32 days; `LabLimits` 5k rows / 30 s (max 20k / 120 s); 1,170 bars ×2 took 25.7 s. Sweep = period×hold ≤8 combos, no API, no optimizer/heatmap; walk-forward NOT_IMPLEMENTED. **Reusable:** Bar/DatasetManifest contracts, quality gate, fill/cost model, 27-metric `summarize`, content hashing, artifact layout, `ProductResearch(owner="aegis")` already allowed by `product_sdk.py`. |
| 3 | Local Parquet OHLCV | **SIGNIFICANT WORK** | Eligible data = 12 FIXTURE manifests of synthetic LABTEST (3 days). SPY/QQQ/ITOT 10-year 1-minute archives (950k/948k/627k rows, 2016-09-19 → 2026-09-18, naive timestamps, capitalised columns, no symbol column, schema `hf.raw.parquet.v1`) are registered as **REAL/FAIL**, empty `canonical_paths`, known gaps (adjusted vs UNADJUSTED, 2026-only calendar, resource ceilings, 2.7–36 % missing bars, unauthenticated vendor vintage); root copies are orphans excluded via `.git/info/exclude`. Vision forbids promotion by display. pandas 2.3.3 / pyarrow 23 / numpy 2.5 installed; polars, duckdb, vectorbt, backtrader, ta, matplotlib, plotly absent. |
| 4 | Provider access from Aegis | **SMALL REPAIR for read-only use; SIGNIFICANT WORK for model-driven edits** | Core `/api/providers` and `Runtime.execute` are product-neutral; CLIs installed and authenticated (Claude/Grok READY, Codex BLOCKED). But every *write* grant is hard-wired to Triad roots/owner; Aegis can only receive REVIEW-role reads of exact files. Chat `Submission.destination` excludes aegis. |
| 5 | Experiment persistence | **SIGNIFICANT WORK** | Core `Laboratory` persists experiments/runs (ledger JSONB + Parquet + sha256) but requires Postgres + WorkItem governance (`assigned_agent="CODEX"` per run), existing experiments are non-reproducible at HEAD (`CODE_VERSION_MISMATCH`), product-side `ProductResearch.run` persists nothing, and dedicated `core.experiments/datasets/metrics` tables are unused. |
| 6 | Memory / knowledge reuse | **SMALL REPAIR (storage) / SIGNIFICANT WORK (retrieval)** | Storage, provenance, ownership and the graph are generic and populated; owner `aegis` is accepted by `intelligence_records` after migration 012. Retrieval is term-overlap over Intake only; no search/semantic index; no Aegis intake destination; no reuse path from chat into a backtest workflow. |
| 7 | ChatGPT / Core / Codex-or-Claude task bridge | **SIGNIFICANT WORK** | Mechanics exist and are generic (MCP/ACP/exec-server brokers, Docker boundary, evidence/usage ledgering, `/api/research/runs/{id}/support` → CODEX). Authority is Triad-only (`PRODUCT_ROOTS`, `work.owner=="triad"`, `product-workspace-v1` QA evidence). Codex is currently failing its own verification. A bridge for Aegis needs Core-owned Aegis roots/grants plus the standing QA rule, or a lighter non-pipeline lane (§14). |

Overall: **NOT READY**. Core offers a trustworthy governance/provenance skeleton and reusable research contracts, but no indicator/strategy/optimizer computation, no eligible real data, no UI stack, and no Aegis write authority.

---

## 13. Preserve

Do not weaken or remove in later missions:

- **Live-trading and exchange closure as types and rules:** `policy.py:22-26,43`, `control.py:118-124,182-188`, `exchange.py:8-17`, `gateway.py:38-72`, `tests/test_policy.py`, `tests/test_architecture.py`; Aegis status `human_directed`/`exchange CLOSED` semantics (`aegis/server.py:24-33`) and the lineage/alias migration `012_aegis_lineage.sql` with its immutability triggers.
- **Secret boundaries:** `security.ensure_no_secret`, `WindowsSecretStore` operator-only credential routes, subprocess env whitelist (`process.py:16-34`), sandbox no-env, `.env` ignored and never read by agents, redaction at ledger boundaries.
- **Core ↔ product import direction** and the architecture test (`tests/test_architecture.py`); product ownership (`ownership.py`, `product_identity.py`, `Store(scope=…)`, `artifact_owners`).
- **Append-only canonical records and provenance:** `core.intelligence_records` trigger, `work_events` revision uniqueness, `protect_work_authority` trigger, mandatory `Usage` evidence, `AgentRunRequest/Result/TransportRun` ledgering, Neo4j projection via outbox.
- **Provider isolation:** `OfflineSandbox` flags, `BoundedTools` limits, Claude `--tools ""`/MCP-only, Grok ACP denials, Codex read-only exec-server, paid-API fallback NEVER/budget 0 by default.
- **Research integrity:** `DatasetManifest.mode/quality_status`, `Archive.publish` PASS-only, `LocalCanonicalStore.eligible`, FAIL registration of the HF archives, `tests/test_retained_dataset_projection.py`; deterministic engine hashing; Bar/Manifest contracts (`triad.ohlcv.v2`).
- **Triad's autonomy machinery and its gates as-is** (ProductCyclePolicy, protected paths, git broker, kill switch) — Aegis must not be built *through* it, and it must not be able to touch Aegis.
- **Historical evidence:** `docs/qa/*`, `docs/improvements/real-market-readiness-*` (SHA-pinned by `test_day7_ghi_qa.py`), `logs/*` QA artifacts, the 14 unmerged candidate branches and 41 worktrees until an explicit, separately-authorized cleanup decision.
- **`docs/CORE_CHAT_VISION.md`** as the standing product direction, including its explicit operator corrections.
- **Operator token auth and loopback-only middleware** on every mutating route.
- **The 207 unpushed commits** — push before anything else risks this machine.

---

## 14. Candidate Gating to Relax

Candidates only; none changed by this audit. Each is scoped to *ordinary reversible Aegis product development* and leaves §13 intact.

| Candidate | Current | Why it is friction | Proposed relaxation (for a later mission) | Risk |
|---|---|---|---|---|
| `AGENTS.md:9-13` independent QA per bounded segment | POLICY, applies to everything | Doubles every Aegis UI/backtest change with a second-agent QA run; unenforced technically, so it is pure process cost | Scope the rule: independent QA remains mandatory for Core, governance, schema/contract, secrets, live-money and destructive changes; for reversible `app/products/aegis/**` and `tests/products/aegis/**` work, require passing automated tests + a lightweight review at PR/merge granularity rather than per segment. Record the change in `AGENTS.md` with the operator's explicit approval. | LOW (reversible product code) |
| `AGENTS.md:20-25` "does not start that build" | POLICY | Blocks agents from beginning Aegis work even though `CORE_CHAT_VISION.md:139-146` already authorizes bounded charting/backtesting scope | Operator issues an explicit Aegis build authorization and the line is updated to point at the current scope. | NONE |
| `tests/test_architecture.py:113-125` + `test_day7_a2_qa.py:38-46` pinned strings "Aegis product shell"/"INACTIVE"/"PRESERVED" | TECHNICAL | Any Aegis shell redesign breaks two tests | Replace the string pins with a status-endpoint contract test (`mode`, `exchange`) so the HTML is free to change. | LOW |
| `daily_verification.py:50-57` requires `/aegis/api/status.work_items == []` | TECHNICAL cross-product coupling | Giving Aegis real work items (backtest runs) fails Triad's post-merge verification and triggers auto-revert | Verify only `exchange == CLOSED` and `mode == human_directed`; drop the empty-work-items assertion. Needs a Triad-side change under its own governance. | LOW–MEDIUM |
| `pyproject.toml:26` package-data for `products.aegis` | TECHNICAL | New JS/CSS/feature files not packaged | Widen the glob (or decide Aegis UI is a separate frontend build and not Python package data). | NONE |
| `Submission.destination` `Literal["core","triad"]`; `ResearchInput.owner` already includes aegis | TECHNICAL | Aegis cannot receive intake | Add `aegis` to the Literal (Core change, schema-adjacent, keep QA). | LOW |
| Core `CORE_PROVIDER_MONITOR` default on + 30-min Codex recovery retry | CONFIG | Burns provider usage while Codex is BLOCKED; spawns CLI/Docker processes continuously | Not a "relaxation" — a stabilization item (§17). Consider a backoff ceiling or manual re-arm after N failures. | NONE |
| Research `LabLimits` 5k rows / 30 s, 2026-only calendar, `strategy_version` Literal | TECHNICAL | Make the Core engine unusable for 10-year/1-minute Aegis backtests | **Do not relax in place**; Aegis needs its own backtest service (or a new Core engine behind a contract) — treat as new work, not gate relaxation. | — |
| Autonomous-pipeline gates (B1–B25) | TECHNICAL | None for direct Aegis development | **Leave unchanged.** They only govern Triad's self-modification and correctly exclude Aegis. | — |

**Not to relax:** everything in §13; the four hard-gate categories; anything that would let the autonomous pipeline write outside Triad roots.

---

## 15. Actual Blockers Before Aegis

Ordered by how directly they prevent safe Aegis work:

1. **No trustworthy green baseline.** Default `pytest` is interrupted at collection; 9 stale-fixture failures; 11 governance tests silently never run. Any Aegis change cannot be verified against a known-good suite.
2. **Background provider burn.** The Codex re-verification loop (every ~33 min, failing) plus the 5-minute monitor consume subscription usage and spawn processes continuously; the previous run died of exhausted usage.
3. **Runtime in a half-dead state.** Triad worker down for 4 days with a wedged supervisor; health check script asserting a schema that no longer exists; stale PID files. Aegis is unsupervised.
4. **Unresolved autonomy decision.** `DailySchedule.enabled=true` in the DB versus `AGENTS.md:18`. Reviving the worker without an explicit decision resumes scheduled dispatch.
5. **Unpushed, single-copy history.** 207 commits and all QA evidence exist only on this machine; origin is 9 days stale.
6. **No Aegis development lane.** Governance (A1, A3) is written for the autonomous pipeline and treats every change as needing independent QA; there is no defined, lighter lane for reversible Aegis UI work, and no Aegis write authority for model-assisted development.
7. **No computational foundation for the slice.** No indicators, no crossover-capable strategy protocol, no optimizer/heatmap, no eligible real OHLCV, no chart stack. (Expected — this is the Aegis build itself — but it means Core cannot be "reused" for the engine without a contract change.)
8. **Lint/format debt and no type checking** (46 ruff findings, 93 unformatted files, 111 E402 import-before-docstring insertions) — not blocking, but any new CI for Aegis will inherit it.

---

## 16. Unknowns

- Why the Codex turn fails (`CodexTurnFailed`) — determining this requires sending a prompt through the CLI, which this audit did not do. Whether the `triad-codex-executor:0.155.0-alpha.2.6` Docker image is present was not checked.
- Why loopback TCP refusal takes ~2.0 s on this host (firewall/WFP enumeration returned Access denied; a running `codex-windows-sandbox-service` is an unverified candidate).
- Why Core and the Triad worker exited around 2026-10-05 01:47–01:52 and Core again at ~06:57 (no log records the cause; not a reboot).
- Whether the 2026-10-01 scheduler enablement was "separately authorized" in the sense of `AGENTS.md:18`.
- Whether Windows Credential Manager holds any `Triad/AIProviders/*` API keys (not enumerated; `.env` has none).
- Whether `ledger.gate()` on the live `SequentialCycle.merge` path honours `require_human_review` (body not inspected).
- Results of the 597 integration-tier tests at HEAD (not run; they would create disposable DBs and the HEAD QA ran only 51 of them).
- Whether the Claude/Grok chat paths work live (only CODEX chat has live evidence); whether the three CLIs still pass a REAL acceptance today (last PASS matrix 2026-09-18; DB says Claude/Grok READY as of recent recovery passes).
- Exact Vela project identity, licence and integration requirements (no code or notes in the repo beyond the name).
- Whether server-side GitHub branch protection exists for `origin/main` (not verifiable offline).
- Whether the `ollama app.exe` tray application or the detached daily runner is the actual source of the popups the operator has seen (no Triad-owned visible window existed during the audit).

---

## 17. Exactly ONE Recommended Next Mission

### MISSION 1 — QUIET GREEN BASELINE (stabilize, decide, push; no Aegis build yet)

**Goal:** leave Core idle-quiet, fully verifiable, and backed up, so Aegis work can start on a known-good base. Bounded to repairs that restore intended behaviour; no redesign, no gate relaxation, no new product code.

Scope (in order):

1. **Stop the burn.** Make an explicit operator decision on the Codex transport: either repair the failing verification (diagnose `CodexTurnFailed` once, interactively) or mark `codex_cli` disabled so `recovery.py` stops re-verifying every 30 minutes. Until decided, run Core with `CORE_PROVIDER_MONITOR=0` or an equivalent documented pause. Record the decision.
2. **Decide scheduled autonomy explicitly.** Operator chooses: (a) disable the `DailySchedule` record via the operator route, reconciling the DB with `AGENTS.md:18`; or (b) re-authorize, re-POST the schedule against the Oct 3 `ProductCyclePolicy`, and amend `AGENTS.md:18` to cite the authorization. Do this **before** reviving the Triad worker.
3. **Repair the test baseline (fixtures only, no production behaviour change):** rename one `test_application_plan.py` (or add `tests/conftest.py` with `importmode=importlib`), update the three stale stubs (`SequentialCycle` fixture → provide `s`; readiness `records.list` stub → accept `matching=`; daily UI stub → provide `host`). Target: default `pytest` runs to completion, 0 failed, integration tier still opt-in. Run the integration tier once with `TRIAD_INTEGRATION=1` and record results.
4. **Fix the supervisor probe** (`ensure_triad_worker.occupied()`): treat `TimeoutError` with a longer timeout as "not occupied" only when the HTTP health check also fails, or raise the socket timeout above the observed ~2 s refusal delay; add a test that does not monkeypatch `occupied`. Then let the supervisor revive or deliberately stop the Triad worker per step 2.
5. **Repair `tools/health_check.py`** to assert `core.candles_1m` (or drop the hypertable assertion) and import `trading_core.settings`.
6. **Housekeeping (no deletions of evidence):** commit the dirty reconcile worktree change or stash it to a named branch with a note; list (do not delete) the 14 unmerged candidates and 3 diverged branches for operator disposition; remove stale PID files only.
7. **Push `main` to `origin`** (after fetch; resolve the 1-commit divergence by merging `SECURITY.md`) and push the unmerged branches so history exists off this machine.
8. **Independent QA** of steps 3–5 per `AGENTS.md` (separate agent, exact revision, full suite + ruff + health), then protected merge.

Explicitly out of scope: relaxing any gate in §14, touching Aegis code, changing Core schemas, enabling APIs, cleaning worktrees, Vela evaluation.

Success criteria: `pytest` green by default; `tools/health_check.py` exit 0; no new FAILED verification work items for 24 h; scheduler state matches the written policy; `git status` clean and `main` pushed; a dated note in `docs/` recording the decisions in steps 1–2.

*This mission is recommended, not started.*

---

CORE AUDIT COMPLETE
Core health: DEGRADED — Core API, Aegis shell, Postgres, Neo4j, Ollama up; Triad worker down 4 days with a wedged supervisor; a failing Codex verification loop every ~33 min; stale health script.
Git state: CLEAN tree on main@9b61ed2 but UNPUSHED (207 ahead / 1 behind origin, last fetch 09-29); 42 live worktrees (1 dirty, in-progress edit), 14 unmerged candidate branches + 3 diverged branches; no hooks; CI not wired to main.
Memory: WORKING storage and provenance (Postgres authoritative, 40k-node Neo4j projection, append-only intelligence records); retrieval PRIMITIVE (term-overlap over Intake, top-3, no index); vision beyond Stage 1 is documentation only.
Providers: Claude/Codex/Grok CLIs installed and authenticated (Claude, Grok recovery READY; Codex BLOCKED on CodexTurnFailed); API transports unconfigured and fallback disabled; Ollama qwen3:4b healthy; nothing re-verified live by this audit.
Gating: HEAVY and technical for the autonomous Triad pipeline; POLICY-ONLY for direct development (AGENTS.md independent-QA rule is the main friction); scheduled autonomy ENABLED in DB (wedged) despite AGENTS.md saying disabled.
Aegis readiness: NOT READY — shell only; backtest engine is a fixture harness without indicators; only synthetic data eligible; no React/Vela/chart adapter; no Aegis write authority.
Primary blocker: no quiet, green, pushed baseline — default pytest is broken at collection with 9 stale-fixture failures, background loops are burning provider usage, the runtime is half-dead, and 207 commits exist only on this machine.
Recommended next mission: MISSION 1 — QUIET GREEN BASELINE (stop the Codex re-verification burn, decide the scheduler record explicitly, repair the test baseline and supervisor probe, fix the health script, push main; independent QA; no Aegis build, no gate relaxation).
