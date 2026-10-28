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
