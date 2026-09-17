# Experiments and hypotheses

Experiment is immutable and separate from BacktestRun. It binds hypothesis, creator/time/status, strategy version, exact dataset/version, symbols/timeframe/window, parameters, fees/slippage/sizing/execution assumptions, seed, Git commit, environment, criteria and named partitions. A new parameter configuration produces a separate run; search metadata records all attempts.

Hypothesis records statement/origin/rationale/expected behavior/falsification and evidence for/against. States include PROPOSED, TESTABLE, TESTING, SUPPORTED, NOT_SUPPORTED, INCONCLUSIVE and SUPERSEDED. A fixture reproduction supports only the stated software determinism hypothesis, never an alpha claim.

Partitions are aware nonoverlapping [start,end) training/validation/test intervals. Test windows cannot be used for parameter sweeps. The initial mission uses one explicit test partition and no fitting. walk_forward_windows provides a bounded train-then-test scheduling skeleton, labelled NOT_RUN with no parameter-selection implementation. It does not claim walk-forward validation.

Sweeps take explicit period/hold ranges, max eight combinations, sequential execution and a runtime budget. Parameter count, planned variants, attempts, run IDs and selection_method=NONE are persisted, including failures. All variants are retained; no best-in-sample result is promoted as out-of-sample success.
