# Triad product inspection baseline

This is a host-checked description of the current implementation, not a preferred product plan. Frontier inspections receive this same snapshot independently. It contains no P2P conclusions, strategy library, human-preferred indicators or previous model findings.

## Mission and boundaries

Triad is an autonomous system whose mission is to continuously build and improve the best trading application it can create.

The product scope includes architecture, UI/UX, market data, research, strategies, backtesting, scanning, risk, portfolio construction, execution, brokerage integration, observability, testing, reliability, performance, operator workflow and self-improvement. This describes product direction; it does not grant execution authority.

Core owns provider transport, governed capability discovery/routing, configured and temporary agents, bounded execution, budgets, storage, review records, data and backtest infrastructure. Triad owns product decisions and conclusions. P2P is preserved; no exchange is open. Live trading and scheduled autonomy are disabled.

## Observable surfaces

- `/triad`: product cycle history, queue, proposals, reviews, lineage, journal and provider status links. Source: `app/products/triad/static/day3.html`, `app/products/triad/api.py`.
- `/triad/development`: product inspections, candidate backlog, selected improvement, build, separate QA, merge and readable approved artifacts. New Day 6 lifecycle infrastructure, not an autonomous product improvement. Source: `app/products/triad/development.py`, `development_api.py`, `static/development.html`.
- `/research`: shared laboratory dashboard. `/api/research/dashboard` shows datasets, experiments, runs, reviews, quality, hypotheses and findings. Its provider explicitly reports FIXTURE and real_market_provider UNAVAILABLE. Source: `app/trading_core/research/api.py`.
- Laboratory actions can ingest a LABTEST fixture, create an experiment, run and review it, inspect hashes and trades/equity/decisions artifacts. Public requests to `/api/research/fixture`, `/experiments`, `/experiments/{id}/run`, `/runs/{id}/review` require the local operator bearer token. Never publish that token or put it in a model context.
- `/api/research/runs/{id}` verifies artifact checksums before returning trades, equity and decisions, plus experiment, reviews, dataset and hypothesis. It is a read route. Source: `app/trading_core/research/api.py`.

## Existing data and research implementation

Source: `app/trading_core/research/data.py`, `service.py`, `engine.py`, `contracts.py`, `planning.py`.

There is provider-neutral ingestion, raw evidence, canonical and derived Parquet, manifests, session-aware quality, experiment/hypothesis metadata, reproducible bounded backtests and retained artifacts. PostgreSQL/TimescaleDB is authoritative; Neo4j projects lineage. Candle rows are not graph nodes. Research is scoped to its owning product.

The engine has signal/sizing/entry/exit/risk interfaces, fees/slippage, trades/equity/decisions outputs and sequence analysis. The built-in strategy is an engine fixture, not a validated trading strategy. A bounded sweep and walk-forward window planning helper exist; these do not establish validated out-of-sample trading performance. Real market-provider integration is unavailable in the current lab. No live brokerage adapter, real-money order flow or capital allocation is enabled.

Historical experiment results remain immutable with their original source fingerprints. A research review and a source/code fingerprint are distinct evidence. A passing engine check is not evidence of investment merit or profitability.

## Current executable grants, not a product preference

Core evidence verifies all three frontier CLI transports for bounded isolated text reads and structured document analysis. Claude additionally has verified isolated staged text proposals. Grok's latest staged write probe failed the native evidence match and is DEGRADED; that does not revoke its read/review proof. No CLI has verified shell, git, unrestricted repository edits, native X/web or MCP authority through this installation. Qwen3:4b is a local observe-only summarizer.

Current autonomous changes are at most three non-executable Markdown/JSON/text files and 180 changed lines, in `docs/improvements` or `research/improvements`. The host applies tool-staged proposals to isolated Git worktrees. A separate frontier QA WorkItem reviews exact sources/hashes and fresh host checks before a governed merge. Models cannot invoke a host shell, alter permissions, increase budgets, access credentials or enable live trading.

Inspect the product as it exists. Distinguish observed implementation from suggestions. Improvements outside these current grants may remain in the backlog; one feasible improvement is selected for this cycle based on product value, evidence and maturity.
