"""Track B: the finalize report's analysis steps on n synthetic sampled cells of the bench surface
(10 parameters), in a fresh process: wall time, numpy peak (tracemalloc) and peak working set.
argv: n step   (step = neighbours | clusters)."""
import random
import sys
import time
import tracemalloc

import numpy as np
import pyarrow as pa

from common import mem
from products.aegis import analysis

n, step = int(sys.argv[1]), sys.argv[2]
SHAPE = (12, 12, 14, 14, 19, 12, 12, 14, 14, 19)
STRIDES = np.cumprod((1,) + SHAPE[::-1][:-1])[::-1]


class FakeGrid:
    shape = SHAPE

    def positions(self, cell):
        return [(cell // int(s)) % d for s, d in zip(STRIDES, SHAPE)]


size = int(np.prod(SHAPE, dtype=np.float64))
rng = random.Random(1)
cells = sorted(rng.sample(range(10**11), n))
base = mem()
tracemalloc.start()
t = time.perf_counter()
if step == "neighbours":
    relation = analysis.neighbours_sampled(FakeGrid(), cells, 2 * len(SHAPE))
else:
    r = np.random.default_rng(1)
    cols = {"cell": pa.array(cells, pa.int64()), "valid": pa.array([True] * n)}
    for m in ("net_return", "max_drawdown", "trade_count", "exposure", "net_pnl"):
        cols[f"combined.{m}"] = pa.array(r.normal(size=n))
    out = analysis.clusters(pa.table(cols), 1)
secs = time.perf_counter() - t
cur, peak = tracemalloc.get_traced_memory()
m = mem()
print(f"{step:10s} n={n:6d}: {secs:6.2f} s, numpy/py peak {peak / 2**20:7.1f} MB, "
      f"peak working set +{m['peak_ws_mb'] - base['ws_mb']:7.1f} MB")
