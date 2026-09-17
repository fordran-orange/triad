# Deterministic backtest engine

A time-ordered event loop accepts checksum-verified canonical data and a frozen experiment. Strategies receive only an immutable tuple of closed Observation values. Future feature, regime, normalization and corporate-action columns are not exposed. No uploaded strategy code is executed. Tests perturb future bars and verify unchanged prior decisions.

Strategy protocol separates generate_signal, position_size, entry_logic, exit_logic and risk_logic. Initial periodic and hold fixtures are allowlisted engine tests only. Long and short use separate capital accounts, trades and metrics. The event loop maintains positions by symbol and the protocol admits multi-asset rules; market-neutral/cross-leg strategies and regime models are extension points, not validated implementations. No directional symmetry is claimed.

Sizing supports fixed shares, fixed dollars and fixed portfolio fraction. Capital is bounded per symbol with no leverage and commission headroom; risk-per-trade sizing is not implemented. No sizing optimization, martingale or doubling down exists. Each decision stores rule, available-through timestamp, history checksum and action; realized outcomes remain in the trade ledger, without labelling profitable decisions good.

agents/research.json bounds rows (5000), file bytes (2 MB), tracked Python allocations (128 MB), runtime (30 sec), sweep combinations (8), worker count and parallel runs (1). Database leases serialize backtests. Runtime/cancellation and Python allocation checks occur during iteration; file/row ceilings bound native Parquet work. This is not an OS process-memory sandbox. Python tracemalloc excludes some native allocations, so recorded peak is explicitly an allocation measurement, not total working set.

Actual trade order is retained. sequence_analysis computes compounded return and drawdown for explicit orderings. Fixed-percentage order permutations preserve terminal product but can alter drawdown/clustering; cash sizing and capital constraints can change that relationship. No optimizer or Monte Carlo strategy discovery was added.


Run status files begin RUNNING. Completion is published under the authority gate with database work/run updates in one transaction. Caught late failures reconcile portable manifest/events to FAILED while preserving generated result files. A status-file I/O failure is also recorded in PostgreSQL as StatusPublicationError; filesystem/database transactions are not crash-atomic, so machine/disk failure still requires reconciliation before trusting an export. The portable reader rejects non-COMPLETED manifests.
