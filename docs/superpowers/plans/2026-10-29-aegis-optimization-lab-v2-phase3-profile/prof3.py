"""Memory over the benchmark's sequence: working set, private bytes, Arrow's pool, numpy's heap
(tracemalloc), the Lab cache. argv[1] = 'trace' turns tracemalloc on."""
import gc
import sys
import time
import tracemalloc

import pyarrow as pa

from common import label, mem, operations, setup

trace = "trace" in sys.argv
store, cache, document, call = setup()
ops = operations(document)
pool = pa.default_memory_pool()
print("pool backend", pool.backend_name)
gc.collect()
base = mem()
if trace:
    tracemalloc.start()


def show(tag):
    m = mem()
    st = cache.stats()
    np_now, np_peak = tracemalloc.get_traced_memory() if trace else (0, 0)
    print(f"{tag:22s} ws +{m['ws_mb'] - base['ws_mb']:6.0f} priv +{m['private_mb'] - base['private_mb']:6.0f} "
          f"peakws +{m['peak_ws_mb'] - base['ws_mb']:6.0f} | arrow now {pa.total_allocated_bytes() / 2**20:5.0f} "
          f"pool max {pool.max_memory() / 2**20:5.0f} | cache {st['bytes'] / 2**20:4.0f} MB/{st['entries']} "
          f"| py-heap now {np_now / 2**20:5.0f} peak {np_peak / 2**20:5.0f}")
    if trace:
        tracemalloc.reset_peak()


show("baseline")
for name in ["open", "open", "filter_heatmap", "filter_heatmap", "stat_change", "stat_change",
             "page", "page", "exact_slice", "parallel", "parallel"]:
    for step in ops[name]:
        call(*step)
        show(f"{name}:{label(step)}"[:22])
gc.collect()
show("after gc")
if hasattr(pool, "release_unused"):
    pool.release_unused()
    show("after release_unused")
cache._entries.clear()
cache._bytes = 0
gc.collect()
pool.release_unused()
show("cache cleared+release")
