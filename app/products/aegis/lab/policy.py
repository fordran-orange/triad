"""The Lab's named constants, each with the spec value that sets it (Optimization Lab v2)."""

from types import MappingProxyType

# §7.2 aggregated projection: a square with fewer trials is dim and labelled `low n`; it is
# flagged `confounded?` when another parameter's distribution inside it is this far (TVD) away.
AGG_MIN_N = 8
CONFOUNDED_TVD = 0.25

# §9.3 response bounds; `top` is this plan's page-sized bound (§9.3 has no `top` row).
PAGE_LIMIT = 500
TOP_LIMIT = 500
MATRIX_MAX_AXIS = 200  # ≤ 200 × 200 squares
MARGINAL_BUCKETS = 200  # per parameter

# §7.9 parallel coordinates, aggregated mode: bundles share a quantile-bin vector over the axes.
PARALLEL_MAX_BUNDLES = 2_000
PARALLEL_BINS = 4  # q = 4 bins per axis

# §9.2 storage: compaction cadence, merged-chunk retention and the compacted part's format.
COMPACT_EVERY = 50  # chunks (≈ 10,000 trials)
RETAIN_MERGED_SECONDS = 600.0
PART_ROW_GROUP = 65_536
PART_COMPRESSION = "zstd"

# §9.2 the Lab cache (`AEGIS_LAB_CACHE_MB` overrides it where the cache is built).
LAB_CACHE_BYTES = 400 * 1024 * 1024

# §9.8: the Lab warns below this much free space on the data root's disk.
LOW_DISK_GB = 10

SHARPE_MIN_TRADES = 20  # §7.12: below this trade count a scope's `sharpe_trade` is flagged low n

# Phase 3 analytics (§7.3-§7.10). §7.3 importance: a seeded bootstrap of B resamples over at most
# IMPORTANCE_ROWS rows with 90 % percentile intervals, and a permutation null whose 95th
# percentile is the detection floor; the coarse decomposition bins each parameter into q = 4.
IMPORTANCE_ROWS = 50_000
BOOTSTRAP_B = 200
PERMUTATION_P = 200
COARSE_BOOTSTRAP_B = 50  # B_c (§7.4)
COARSE_PERMUTATION_P = 50
COARSE_BINS = 4
INTERVAL = 0.90
FLOOR_QUANTILE = 0.95

# §7.3a screening blocks: the planner offers K = 4; a request accepts 0 or 2..8.
SCREEN_BLOCKS = 4
MAX_BLOCKS = 8

# §7.3 / §7.4 coverage and aliasing: `Measured` needs n_uniform ≥ 30 × B_i and 20 rows per value;
# a pair is aliased above Cramér's V 0.3, unresolved when under half its value grid has ≥ 4
# rows, and flagged unbalanced above TVD 0.25; the top 20 triples are shown.
IMPORTANCE_MIN_N_FACTOR = 30
IMPORTANCE_MIN_PER_VALUE = 20
ALIAS_V = 0.3
PAIR_MIN_N = 4
PAIR_MIN_COVERAGE = 0.5
PAIR_BALANCE_TVD = 0.25
TRIPLE_TOP = 20
INTERACTIONS_MAX_PAIRS = 190  # the interactions view's response bound: every pair at d = 20

# §7.4 / §7.4a the rule: the residual vetoes when its lower bound exceeds 0.3, the decomposition
# is inconsistent when its upper bound is below -0.05, and θ_min is the practical floor applied
# to upper bounds.
RESIDUAL_VETO = 0.3
RESIDUAL_INCONSISTENT = -0.05
THETA_MIN = 0.01

# §7.6 robustness. A: neighbours within r steps in ≤ m parameters, resolved at coverage 0.5, a
# peak above P75 + 3 × IQR. B: an L∞ radius of 0.15 on the 6 most important axes, n ≥ 30.
# C: ≥ 3 validation folds of ≥ 30 trades, within [0.5×, 2×] with drawdown ≤ 1.5×.
# D: the stressed replay holds at ≥ 70 % of base with drawdown ≤ 1.3×.
PLATEAU_MIN_COVERAGE = 0.5
NEIGHBOUR_R = 1
NEIGHBOUR_M_GRID = 1
NEIGHBOUR_M_SAMPLED = 2
PEAK_IQR_FACTOR = 3.0
REGION_RADIUS = 0.15
REGION_AXES = 6
REGION_MIN_N = 30
FOLDS_MIN = 3
FOLD_MIN_TRADES = 30
FOLD_RATIO_BAND = (0.5, 2.0)
FOLD_DRAWDOWN_FACTOR = 1.5
STRESS_KEEP = 0.70
STRESS_DRAWDOWN_FACTOR = 1.3
PER_BARS = 1_000  # C's and D's per-unit-time statistics are per this many bars
# The rankings' bounded compute (Ruling P18): the lists hold k rows, the k of §10's stage 2, chosen
# from the top RANK_POOL by `peak`, so a crowd of spikes above a plateau cannot hide it. A is read
# for the whole pool, a neighbourhood per candidate and never one per trial; B, the costly part,
# for the top k and at most RANK_B_MAX rows, whatever k asks. An `opt:` source has no tolerance of
# its own, so it reads the experiments' default, labelled.
RANKING_K = 20
RANK_POOL = 300
RANK_B_MAX = 20
DEFAULT_TOLERANCE = 0.15
# Ruling P19's addendum: where a metric stops losing money, so `stable` never names a value at or
# below it. The money-signed metrics break even at 0, and `profit_factor`, a ratio positive on a
# loss too, at 1. `max_drawdown`, `win_rate`, `trade_count` and `exposure` have no break-even.
BREAK_EVEN = MappingProxyType(
    {
        "net_pnl": 0.0,
        "net_return": 0.0,
        "cagr": 0.0,
        "mar": 0.0,
        "expectancy": 0.0,
        "sharpe_trade": 0.0,
        "profit_factor": 1.0,
    }
)

# §7.7 Pareto: ≤ 2,000 front points and one 64 × 64 density grid. §7.9 exact parallel mode:
# ≤ 5,000 lines stratified by metric decile. §7.10 convergence: the robust median per batch of
# 5,000 trials over its top 1 %, at most 1,000 points, and the panel empty under two batches (§5).
PARETO_FRONT_MAX = 2_000
PARETO_DENSITY_BINS = 64
OBJECTIVES_MIN = 2
OBJECTIVES_MAX = 3
PARALLEL_MAX_LINES = 5_000
PARALLEL_STRATA = 10
# §5.5 Screen E's trellis, read by its panels from the `matrix` and `interactions` responses (a
# UI never holds them). §5.5: "cells n < 30 hatched and excluded" (a square under this many
# trials, or with this few a value, is hatched and left out of the scale).
TRELLIS_MIN_N = 30
# §5.5: "aggregated 16 × 16, n shown" (a trellis matrix shows at most this many squares per axis).
TRELLIS_MAX_SIDE = 16
# §5.5: "Trellis of top pairs" (the trellis draws this many of the top pairs by priority).
TRELLIS_PAIRS = 6
CONVERGENCE_BATCH = 5_000
CONVERGENCE_TOP = 0.01
CONVERGENCE_MAX_POINTS = 1_000
MIN_BATCHES = 2

# §9.4 / §9.6 the staged importance task: ≤ 180 s in total, the fine-grid stage within 30 s.
TASK_BUDGET_S = 180
FINE_STAGE_BUDGET_S = 30
# Decision 6: a Lab task's finished results stay in memory, this many least recently used.
TASK_RESULTS = 32
# Ruling P13: the keys a poll must not restart, the oldest forgotten beyond this many. Apart from
# the results, so no eviction restarts what the user stopped; each holds its delivered stage.
TASK_STOPPED_KEYS = 32
