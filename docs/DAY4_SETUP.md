# Day 4 research laboratory

The actual Day 4 scope is the portable market-data, experiment and backtest foundation. Earlier durable cycle queue work remains available; see DAY4_DURABILITY_SETUP.md. Research is a separate host-controlled workflow; no broker or live trading API exists.

Open http://127.0.0.1:8000/research. The engineering dashboard links here. Run from C:/Triad:

```powershell
.\.venv\Scripts\python.exe tools/research.py demo
.\.venv\Scripts\python.exe tools/research.py catalog
.\.venv\Scripts\python.exe tools/research.py run <experiment-id>
.\.venv\Scripts\python.exe tools/research.py review <run-id>
```

Demo preserves a small LABTEST fixture, writes canonical minute Parquet and five derived resolutions, defines a non-alpha reproducibility hypothesis, runs it twice and performs separate host method verification. Mode FIXTURE and HOST_VERIFIER_NOT_MODEL never imply real market downloads or cloud reviews. Repeating demo creates new immutable datasets/experiments; use run to reproduce an existing definition.

The existing operator token protects mutation APIs. Research WorkItems use the explicitly added research_artifact capability at Tier 1 with read/write-research scope. The host invokes only allowlisted fixture strategies, never uploaded Python or arbitrary shell. Pause/kill gates ingestion, runs and review. The established daily model/autonomous-change ledger is retained; host research has its own strict resource ceilings in agents/research.json and does not buy model calls or consume change slots.

Parquet artifacts are ignored in Git. Code, schemas, configuration and manifests' contract definitions are tracked. Actual manifests/artifacts are retained locally and catalogued in PostgreSQL with graph/Markdown projections. Backups remain an operator deployment concern.

Reruns verify canonical file hashes, dataset version/timeframe and lab source hash. The experiment records Git commit, package versions, parameters, costs, sizing, partition and random seed. Check out compatible source if the code hash changed; do not overwrite an old experiment. tools/portable_research.py reads the bundle without Triad imports or services.

The supported fixture is unadjusted USD equity OHLCV. Calendar coverage is deliberately 2026/XNYS only. Higher timeframes use regular-session boundaries. See EXECUTION_ASSUMPTIONS.md and RESULT_METRICS.md for interpretation and limitations.
