"""Per-request timings, cache traffic and process memory, in the benchmark's order."""
import gc
import json
import time

from common import label, mem, operations, setup

store, cache, document, call = setup()
ops = operations(document)
print("baseline", json.dumps({k: round(v, 1) for k, v in mem().items()}))
order = ["open", "open", "open", "filter_heatmap", "filter_heatmap", "filter_heatmap",
         "stat_change", "stat_change", "stat_change", "page", "page", "exact_slice", "exact_slice",
         "parallel", "parallel", "open", "filter_heatmap", "stat_change"]
for name in order:
    t_op = time.perf_counter()
    parts = []
    for step in ops[name]:
        before = cache.stats()
        t = time.perf_counter()
        call(*step)
        ms = (time.perf_counter() - t) * 1000
        after = cache.stats()
        parts.append(
            f"{label(step)}={ms:.0f}ms(miss+{after['misses'] - before['misses']},"
            f"hit+{after['hits'] - before['hits']})"
        )
    total = (time.perf_counter() - t_op) * 1000
    st = cache.stats()
    m = mem()
    print(f"{name:15s} {total:7.0f} ms | {' '.join(parts)} | cache {st['bytes'] / 2**20:.0f} MB "
          f"{st['entries']} entries | ws {m['ws_mb']:.0f} priv {m['private_mb']:.0f} "
          f"peak {m['peak_ws_mb']:.0f}")

print("\ncache entries:")
for key, (value, nbytes) in cache._entries.items():
    cols = key[-1] if isinstance(key[-1], tuple) else None
    print(f"  {key[0]} {nbytes / 2**20:8.1f} MB  cols={len(cols) if cols else '-'} "
          f"{list(cols) if cols else key[1:]}")
gc.collect()
print("after gc", json.dumps({k: round(v, 1) for k, v in mem().items()}))
