# Reconciliation installed-package independent QA

Decision: **PASS**, bounded to frozen revision `beea93c53c7d36e70906fb4695ca475e7a064fd3`.

Built an exact Git archive offline using pip wheel --no-deps --no-build-isolation --no-index, then installed that wheel with --no-deps --no-index into a disposable target. The fresh Python process used -I, explicitly imported that target, used a disposable TRADING_HOME, blocked application network/database connections, and did not enter any application lifespan.

- All **131** selected Python/config/static/SQL files under the three owned package trees exactly matched frozen source SHA-256 values (full map in accompanying JSON).
- **19** installed Core/Triad/Aegis shell/asset/health route checks returned 200; provider HTML response bytes exactly matched the installed reviewed asset.
- **6** cross-product API route probes returned 404. This verifies route namespace separation, not database ownership behavior.
- Both Research Readiness feature routes returned their honest expected **503** awaiting reviewed build. This is **not feature completion or Day 8 acceptance**.
- All **13** mirrored SQL assets were installed, including migrations 010, 011, 012 and 013.
- The actual installed QA reference module executed successfully against the frozen Git base, with installed schema module paths and seven hashed authoritative sources; no checkout import fallback. Bundle digest `6ad02a37951997d9bfd9a188b9fb8b83436f36656f0d14a1fd77ea0feec04214`.

Wheel SHA-256: `64c45678b0f98b79353ed468767b1ff19500bf77d31031420830468638f093e4`.
Source archive SHA-256: `f955cbd01e3954f0a00da3688e6957df444f0b22a1bfc86ee47b5e5d01f23cd9`.
Evidence directory: `C:\Users\fordr\AppData\Local\Temp\reconcile-package-qa-qn5es_2s`.

Command: `C:/Triad/.venv/Scripts/python.exe C:/Triad/logs/reconcile-package-qa.py` (final installed checks reused the same successfully built/installed frozen wheel via PACKAGE_QA_REUSE).
Logs: `reconcile-package-qa-run.log`, exit **0**, JSON full file hashes/routes, script with exact hash in JSON. Two harness failures are retained in `reconcile-package-qa-harness-initial.log` and `reconcile-package-qa-harness-socketpair.log`; these were the mistaken SQL inventory path and the overbroad network guard blocking Windows asyncio's internal socketpair. Neither required candidate edits.

No browser JavaScript/rendering, provider inference, credential operations, DB writes, scheduled worker startup or live service acceptance was performed. Candidate files were unchanged. Independent reviewer: /root/day6_qa_a.
