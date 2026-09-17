# Day 4 research laboratory — initial verification

This is the original delivery evidence. The subsequent defect review found six issues; corrected implementation, regression tests and a new reproducibility mission are recorded in [DAY4_REVIEW_FIXES.md](DAY4_REVIEW_FIXES.md). Original artifacts and identifiers below remain unchanged.

The authoritative Day 4 scope is market data, experiments and backtesting. Earlier queue/recovery work is retained as supporting infrastructure; its historical reports are archived as DAY4_DURABILITY_*.md. This report covers the supplied research brief.

## Data architecture

Provider-neutral `MarketDataProvider` → immutable `data/raw/<job>/source.json` + request/checksum metadata → UTC canonical one-minute Parquet under `data/canonical/asset_class=equity/symbol=LABTEST/year=2026/month=09/<dataset>/` → portable `data/manifests/<dataset>.json`. Derived resolutions preserve base-dataset lineage. PostgreSQL holds catalog, experiment, run, quality, hypothesis, finding and control-plane records. Neo4j contains metadata relationships, not individual candles.

Only local synthetic LABTEST data was used: source state FIXTURE, real market provider UNAVAILABLE. No paid market access, broker connection, cloud inference or strategy discovery was performed.

## Dataset verification

Three regular XNYS sessions, September 14–16, 2026; 13:30–20:00 UTC each day. All six manifests pass quality checks with zero known gaps. Hourly resampling retains each session's final 30-minute bucket explicitly. Calendar scope is 2026; unsupported years fail closed. Raw NY timezone offsets are preserved; canonical timestamps are UTC.

| Resolution | Rows | Parquet bytes | Quality | Dataset ID |
|---|---:|---:|---|---|
| 1m | 1170 | 65429 | PASS | d073d3d4-1a23-4e2f-8f88-78e2059dfe98 |
| 5m | 234 | 19460 | PASS | 8511af51-3e6e-4429-87a0-3153077cf917 |
| 15m | 78 | 12063 | PASS | a5b4095b-1ca8-4e69-8515-819417919493 |
| 30m | 39 | 9927 | PASS | dd148432-f021-49f2-858f-e7d48f1f3a11 |
| 1h | 21 | 9001 | PASS | 5c3ea96c-155c-4abf-bb5c-01f14f47ded4 |
| 1d | 3 | 7973 | PASS | 2e9f01cc-cd4c-4ca6-b9d3-45661e4314db |

Evidence: `logs/research-demo.json`, `data/manifests/`, PostgreSQL DatasetManifest/QualityReport records, and checksum verification by `tools/verify_research.py`.

## Reproducibility experiment

Experiment: `96dfc8ab-ef5b-4119-9aac-f0f0d3b9645f`.
Hypothesis: identical deterministic inputs reproduce identical research artifacts, not that a strategy has investment merit.
Strategy: `periodic-fixture-v1`, period 20, hold 5, fixed 10 shares, separate LONG and SHORT capital of $10,000 each.
Engine code commit: `bfda7c46a3669df7f0b1644f5a2bea0ca1c5ca96`.
Dataset version: `11411f1d4ab9dc9700fc46e5ab3dffd91bc222510a86663c39528c518d39ebdc`.

Runs:
- `5a71ac47-93f9-4f0b-8abd-9b413f299931`
- `8498f6f0-fe02-49db-9ab5-e823cbb71a94`

Both COMPLETED with deterministic content SHA256 `92fa86ba7608ba1cee91cca0dfb7e4b9c1df0a5355b525b6d3b51e761921b8e8`.
Each has 118 trades (59 per direction), 2,340 equity observations, decision history, parameters, metrics, checksums, execution logs and review under `research/experiments/<experiment>/runs/<run>/`.

Each run has its own scoped WorkItem, policy decision, journal, handoff, canonical Review and separate host-verification pass. Reviews returned ACCEPT_RESULT in mode HOST_VERIFIER_NOT_MODEL. They recomputed from original evidence using the same engine; this is neither a cloud-model review nor a second independent engine implementation. The six-verdict human method-review API also supports rejection, data quality failure, look-ahead risk and inconclusive findings; integration tests exercise it without fabricating human production reviews.

Reproduce from the project venv:

```powershell
.venv\Scripts\python.exe tools/research.py run 96dfc8ab-ef5b-4119-9aac-f0f0d3b9645f
```

This creates another immutable run; the review command is separate. Existing engine source identity remains compatible with the recorded experiment. Subsequent changes to lab source require a new experiment or restoration of compatible source.

## Backtest engine and limitations

Close-time observations feed next-bar-open fills. Closed history contains only permitted OHLCV fields; future price, feature, normalization, regime and corporate-action columns cannot enter the fixture strategy observation. The final-window liquidation is predeclared at the final bar open. Execution, sizing, commission, slippage and spread are recorded in the experiment. Costs are fixed $0.05 + $0.001/share + 0.2 bp per fill; adverse slippage 1 bp plus half a 2 bp spread. No same-bar close-price fills are assumed.

LONG and SHORT are independent portfolios, with separate trade, risk and compound metrics. Net returns were approximately -0.25683% and -0.41309%; these synthetic losses validate accounting, not strategy quality. Geometric mean trade return, arithmetic mean, MAE/MFE, holding time, time-to-profit/failure, costs, drawdown, exposure, turnover and loss streaks are retained. CAGR/Calmar are null for less than one year; volatility/Sharpe/Sortino are null with fewer than 20 daily observations. Null is not zero performance.

Fixed shares, dollars and portfolio percentage sizing are supported. Strategy methods and symbol-keyed positions permit later extension; no cross-asset neutral portfolio, regime model, borrow availability, liquidity/market-impact model, financing, corporate-action adjustment or risk-per-trade sizing is claimed validated. The initial archive is regular-session, unadjusted equity data. Extended-session classifications are documented templates, not a complete venue calendar.

Training/validation/test windows are explicit and nonoverlapping. Sweeps record every attempted variant, reject optimization on the test partition, cap combinations and use one worker. Sweep time is checked between runs and may include the final in-progress bounded run. Walk-forward produces a NOT_RUN plan; parameter selection and forward validation are not fabricated. No best-strategy selection or prohibited research seeding exists.

## Verification matrix

| Requirement | Implementation | Verification | Result | Evidence |
|---|---|---|---|---|
| 1. Provider-neutral entry | MarketDataProvider protocol and fixture adapter | Ingestion pipeline test + recorded mission | PASS | lab/data.py; test_lab_integration.py; research-demo.json |
| 2. Raw preserved | Exclusive raw source + request metadata/checksum | Immutable source and corruption tests | PASS | data/raw/; test_lab.py |
| 3. Canonical 1-minute | Validated UTC Bar contract | Schema/OHLC/timezone tests; 1,170 rows | PASS | control-plane/research/; base manifest |
| 4. Portable Parquet | Partitioned PyArrow archive | Standalone subprocess reads and hashes | PASS | tools/portable_research.py; verification JSON |
| 5. Manifests | Version/checksum/quality/provenance model | Six manifests checked against files | PASS | data/manifests/; test_lab.py |
| 6. Quality tested | Duplicates, gaps, OHLC, signs, ordering, timezone, symbol, corruption | Valid/invalid fixtures, calendar/session tests | PASS | tests/test_lab.py; QualityReport records |
| 7. Derived timeframes | 5m/15m/30m/1h/daily from base | Aggregation tests and 5 production derivatives | PASS | derived manifests; DERIVED_INTO graph edges |
| 8. First-class experiments | Immutable Experiment + Hypothesis, separate BacktestRun | Creation and pipeline integration | PASS | experiment ID above; schemas |
| 9. Reproducible runs | Source/data/config identity and content hash | Two identical run hashes + repeated verifier passes | PASS | both run manifests; determinism test |
| 10. Explicit execution | CLOSE_SIGNAL_NEXT_OPEN; final-open exit | Known-price tests; future-access tests | PASS | EXECUTION_ASSUMPTIONS.md; experiment |
| 11. Costs/slippage | Fixed/share/bp fees, adverse slip/spread | Known-PnL and cost tests | PASS | engine tests; parameters.json |
| 12. Separate directions | Separate capital and ledgers/metrics | Long-only, short-only and paired tests | PASS | two directional metrics; UI |
| 13. Trade ledger | Portable trades.parquet | 118 rows/run read independently | PASS | run artifacts; portable reader |
| 14. Equity artifact | Cash/exposure/equity/drawdown/log returns | 2,340 rows/run; visual chart check | PASS | equity.parquet; browser |
| 15. Geometric performance | Compounding, geometric mean, log returns, sequence analysis | Metric/path tests and recorded metrics | PASS | metrics.json; RESULT_METRICS.md |
| 16. Provenance | Raw/data/source commit/config/run/WorkItem links | Artifact hashes and graph trace | PASS | run manifest; provenance UI |
| 17. Independent review possible | Full packet, host rerun, operator method-review API | 2 host reviews; rejection/auth tests | PASS | ResearchReview/Review/journal records |
| 18. Useful Neo4j lineage | Raw→base→derived, dataset→experiment, run→commit/review, claim→run | Exact mission graph counts asserted | PASS | tools/verify_research.py; graph report |
| 19. Research UI | Catalog, experiments, results, filters, quality, provenance | Browser navigation, charts, 59 SHORT rows, empty unknown-symbol filter | PASS | http://127.0.0.1:8000/research |
| 20. Outside-Triad reading | Python + pyarrow reader, no Triad imports/network | Standalone process validates both production runs | PASS | tools/portable_research.py; portable report |

## Tests and quality checks

| Executed | Passed | Failed | Errors | Skipped | Runtime |
|---:|---:|---:|---:|---:|---:|
| 177 | 177 | 0 | 0 | 0 | 248.99 seconds |

Two upstream TestClient deprecation warnings remain; no application warnings or test failures.

Baseline before research changes: 144 passed, zero failures/errors/skips (`logs/day4-lab-precheck-tests.xml`). Intermediate core suite: 170 passed; final review additions were separately tested (10 passed). Final complete results are recorded above and in `logs/day4-research-tests.xml`.

Static checks: Ruff check/format, pip dependency consistency, Git whitespace checks, foundation/secret exclusion audit. Live verifier checks PostgreSQL, TimescaleDB, Neo4j, Ollama, Git and backend; graph projection pending/errors are zero, model budgets remain unchanged, kill switch is not engaged and live trading authority remains false. These are local verification artifacts, intentionally excluded from Git along with runtime data.

## Performance

One worker and one backtest at a time. Default ceilings: 5,000 dataset rows, 2 MB source bytes, 128 MB tracked Python allocations, 30 seconds per run, eight sweep combinations. Hard configuration maxima are validated. Memory accounting is Python tracemalloc plus bounded input checks, not an OS process/RSS sandbox; use process isolation before untrusted strategy code.

| Run | Runtime | Peak tracked Python bytes | Core artifact bytes |
|---|---:|---:|---:|
| 5a71ac47 | 26.015 s | 16,585,023 | 70,808 |
| 8498f6f0 | 26.218 s | 16,450,512 | 70,808 |

These timings exclude separate review passes. Core artifact sizes exclude manifest/log/review overhead. Total actual archive/artifact directory sizes are recorded in `logs/day4-research-verification.json` (including that overhead). Measured directory totals: raw 179,093 bytes; canonical/derived Parquet 123,853 bytes; manifests 12,180 bytes; experiment artifacts 154,094 bytes. Combined: 469,220 bytes (about 0.45 MiB), excluding database storage and repository logs. Nothing approaches a large historical archive.

## Git

Branch `main`. Research engine/data/schema/UI baseline commit `bfda7c4`; final method-review, usability, verification and documentation changes are committed afterward. Exact final HEAD and clean-working-tree evidence are recorded by the read-only verifier after the last commit. Historical supporting queue changes remain in the history. No runtime data, credentials or venv files are committed.

## Human actions required

None to use or reproduce the Day 4 fixture laboratory. A real market-data adapter later requires a chosen source with appropriate access; independent cloud-model review later requires configured provider credentials/models/budgets. Neither is represented as available today, nor required to validate the allowed fixture path.

## Day 5 recommendation

Next, validate one licensed real-data adapter and broader calendar/corporate-action handling against a small known dataset, then independently cross-check accounting and out-of-sample methodology. Agree that scope before strategy discovery. No Day 5 work, broker integration, live trading, autonomous portfolio management or favored strategy research was begun.
