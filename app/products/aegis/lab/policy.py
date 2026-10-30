"""The Lab's named constants, each with the spec value that sets it (Optimization Lab v2)."""

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

# §7.7 Pareto: ≤ 2,000 front points and one 64 × 64 density grid. §7.9 exact parallel mode:
# ≤ 5,000 lines stratified by metric decile. §7.10 convergence: the robust median per batch of
# 5,000 trials over its top 1 %, at most 1,000 points.
PARETO_FRONT_MAX = 2_000
PARETO_DENSITY_BINS = 64
PARALLEL_MAX_LINES = 5_000
PARALLEL_STRATA = 10
CONVERGENCE_BATCH = 5_000
CONVERGENCE_TOP = 0.01
CONVERGENCE_MAX_POINTS = 1_000

# §9.4 / §9.6 the staged importance task: ≤ 180 s in total, the fine-grid stage within 30 s.
TASK_BUDGET_S = 180
FINE_STAGE_BUDGET_S = 30
# Decision 6: a Lab task's finished results stay in memory, this many least recently used.
TASK_RESULTS = 32
