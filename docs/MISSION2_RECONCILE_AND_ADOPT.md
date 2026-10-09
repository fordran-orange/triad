# Mission 2 — Reconcile and adopt `aegis/product-first-reset` (2026-10-09)

Follow-up to Mission 1 (`docs/MISSION1_QUIET_GREEN_BASELINE.md`). During Mission 1's fetch,
origin was found to hold `aegis/product-first-reset`: 14 commits pushed 2026-10-08 18:03–18:07
America/Chicago (first commit 18:02:36; author fordran-orange) on top of `e9dc503` (SECURITY.md,
the 2026-09-29 origin/main tip, child of `f8fffa3`), so it did not contain the 207 commits of
governed Core/Triad work that Mission 1 pushed.

## Operator decisions (chat, 2026-10-09)

- Merge the branch **into `main`** (not reset main to it, not rebase the pushed branch).
- The direction change is intended: **Aegis is in product-first build mode; Triad is
  intentionally suspended and resumes later with Aegis as a base to work with.** Recorded as a
  dated operator correction in `docs/CORE_CHAT_VISION.md` and in `AGENTS.md`.
- Mission 2 framing accepted as proposed: merge with three resolutions, run the bare suite plus
  the branch's Aegis tests, one independent QA at the merge commit, push.

## What the branch brings (unchanged by the merge except where noted)

| Path | Content |
|---|---|
| `app/products/aegis/strategy.py` | Pydantic strategy contract: `Direction`, `WindowMode`, `IndicatorSpec`, `RuleSpec`, `StrategySide` (independent long/short), `ClockWindow`, `EventWindow`, `MarketCrossover`, `TemporalContext`, `ExecutionSpec`, `OptimizationParameter`, `StrategySpec`, `default_strategy()` = 9 EMA / 30 SMA cross, next-bar-open execution. Import block re-sorted (ruff I001) in this merge. |
| `app/products/aegis/backtest.py` | Standalone pandas crossover backtester: per-side simulation, clock/event tags, slippage-adjusted fills, metrics, long+short combination, temporal breakdown; `run_backtest(BacktestRequest)`. Imports only `products.aegis.strategy`. `ruff format` would re-wrap one block at line 49; left as authored. |
| `app/products/aegis/server.py` | Adds `GET /aegis/api/strategy/default` and `POST /aegis/api/backtest`; status now `ACTIVE_DEVELOPMENT` / `PRODUCT_FIRST_RESET`, still `mode: human_directed`, `exchange: CLOSED`. |
| `app/products/aegis/static/index.html` | Workstation shell (+255 lines). No longer contains the Day-7 copy "Aegis product shell" / "INACTIVE" / "PRESERVED". |
| `config/aegis/product.json` | `status: ACTIVE_DEVELOPMENT`, `preservation: PRODUCT_FIRST_RESET`, `exchange_enabled: false`. |
| `tests/test_aegis_strategy.py`, `tests/test_aegis_backtest.py` | 8 tests (reference strategy, independent sides, temporal context, next-bar fill, directional + combined results, opening-window breakdown). |
| `tests/test_governance.py` | +1 test: Aegis paths allowed for `product="aegis"`, Triad paths protected from Aegis and vice versa. Auto-merged with main's version. |
| `app/trading_core/governance.py`, `AGENTS.md` | Conflicted with main; resolutions below. |

## Resolutions

1. **`AGENTS.md`** — took the branch's product-first text (risk-based QA for reversible Aegis work; independent QA and Core governance still mandatory for live-money, secrets/credentials, destructive/migration, and shared-contract/boundary/governance changes), then re-added the pointer to `docs/CORE_CHAT_VISION.md` and its dated corrections, and replaced "suspended while Aegis is built" with the operator's exact decision: Triad intentionally suspended (2026-10-09), resumes later with Aegis as a base; scheduled autonomy disabled by `DailySchedule` record `c99fa831`, re-enable only by explicit operator decision through the operator route; exchange CLOSED, live trading disabled, Core imports neither product.
2. **`app/trading_core/governance.py`** — composed both sides in `is_protected_core_path(path, *, product="triad")`: main's `protected_orchestration(value)` check (added since the common base) is kept, and the branch's per-product `PRODUCT_PREFIXES` replace the hard-coded Triad-only prefixes. Existing callers pass no `product`, so Triad behaviour is unchanged; `assert_product_merge_allowed(paths, product="aegis")` now permits `app/products/aegis/**` and `products/aegis/**` only.
3. **Pinned shell copy** — `tests/test_architecture.py::test_aegis_shell_and_legacy_redirect` and `tests/test_day7_a2_qa.py::test_aegis_html_response_matches_declared_utf8_encoding` asserted the Day-7 page strings, which the branch's shell dropped (the branch was red on its own copy of this test). Replaced with the governance contract the rest of the system actually depends on: `/aegis` is 200 HTML containing "Aegis"; `/aegis/api/status` (with `Store` stubbed so the test stays DB-free) reports `product aegis`, `mode human_directed`, `exchange CLOSED`, `work_items []`; `/p2p` → 307 redirect unchanged. This is the relaxation `CORE_STATE_AUDIT.md` §14 proposed; Triad's post-merge verifier (`daily_verification.py:50-57`) reads only those status fields and is unaffected.

Also added: `docs/CORE_CHAT_VISION.md` "Operator corrections" section (2026-10-09 entry) and this record.

## Verification on the merged tree

- Bare `pytest` (default invocation): **973 passed, 596 skipped, 0 failed, exit 0** in 162 s (Mission 1 baseline 964 + the branch's 8 Aegis tests + 1 governance test).
- `ruff check` on `governance.py`, `app/products/aegis/**`, and the five touched/incoming test files: clean (after sorting one import block in `strategy.py` and using `list` instead of a lambda in the new architecture test).
- `ruff format --check`: two branch-authored files would be reformatted and were left as authored: `app/products/aegis/backtest.py` (several hunks, first at line 49) and `tests/test_governance.py:25` (one assertion that fits on a single line). `ruff check` is clean on both.
- Before the merge, the branch's own tests were run from an export of the branch: its 8 Aegis tests and governance test passed; its copy of `test_architecture.py` failed only on the dropped shell strings (resolution 3), plus two export artifacts.

## Independent QA

- Reviewed revision: merge commit `5a7a03fec9cf5f42c40db1a5546af702e684a2c1` (parents `d57992a`, `3de7eb7`), tree clean before and after.
- Reviewer: separate QA agent (not the builder), read-only plus test execution, 2026-10-09 ~11:20–11:40Z.
- Verdict: **PASS_WITH_OBSERVATIONS**, no blocking findings.
- Evidence it produced: exactly two parents; no residual conflict markers; bare `pytest` → 973 passed, 596 skipped, 0 failed, exit 0 (134 s); governance probed at runtime against the pre-merge module — Triad protection identical on all nine probed paths (including main's `protected_orchestration` guard), Aegis confined to its two roots, unknown product raises; existing callers pass no product; `AGENTS.md` contains every required element and agrees with the vision correction and the live schedule record; replaced tests exercise the real status contract through the same `Store` name the handler resolves, DB-free, `/p2p` redirect and utf-8 contracts retained, nothing else depended on the dropped page copy; incoming Aegis code imports only stdlib/pandas/pydantic/its own strategy module, performs no I/O, hard-codes `exchange: CLOSED`, has no order path, and `run_backtest` is deterministic (two runs byte-identical on 300 synthetic bars, 75 ms); diff confined to the 14 permitted paths.
- Findings (non-blocking): (F1) the lint sentence above understated the format-check state — corrected; (F2) `POST /aegis/api/backtest` has no `max_length` on `bars`/`events`, so an oversized body could occupy a worker thread on this loopback-only dev host — candidate for an ordinary Aegis slice. Observations: (O1) base-commit wording — corrected above; (O2) `app/products/aegis/resources/product.json` still says INACTIVE/PRESERVED while `config/aegis/product.json` says ACTIVE_DEVELOPMENT (no runtime reader of either); (O3) Core's `static/launch.html` Aegis card still reads "INACTIVE · PRESERVED" (Core-owned, needs a Core change); (O4) the running Aegis worker on 8102 (started 2026-09-20) and Triad worker on 8101 still serve pre-merge code until restarted.

## Push

Recorded after the push.
