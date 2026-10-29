"""The cache-miss read: store.trials for the summary's 15 columns, profiled; is _canonical's sort
the identity; the pool's peak during the read; and the page view, profiled warm."""
import cProfile
import io
import pstats
import time

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from common import mem, operations, setup
from products.aegis.lab import sources as lab_sources
from products.aegis.lab import store as lab_store

store, cache, document, call = setup()
meta = lab_sources.cached_meta(document, cache)
cols = lab_sources.COLUMNS_FOR("summary", None, meta.parameters, meta.objective)
cells = store.cells_dir(document.id)
_, snap = lab_store.latest_snapshot(cells)
pool = pa.default_memory_pool()
m0 = mem()
t = time.perf_counter()
prof = cProfile.Profile()
prof.enable()
held = store.trials(document.id, list(cols), snapshot=snap)
prof.disable()
ms = (time.perf_counter() - t) * 1000
m1 = mem()
print(f"read {len(cols)} cols: {ms:.0f} ms (profiled), table {held.table.nbytes / 2**20:.1f} MB, "
      f"pool max {pool.max_memory() / 2**20:.0f} MB, ws +{m1['ws_mb'] - m0['ws_mb']:.0f} MB")
out = io.StringIO()
pstats.Stats(prof, stream=out).sort_stats("tottime").print_stats(12)
print("\n".join(l for l in out.getvalue().splitlines() if l.strip())[:3000])
for name in held.table.column_names:
    col = held.table.column(name)
    print(f"  {name:45s} {str(col.type):35s} {col.nbytes / 2**20:6.1f} MB chunks={col.num_chunks}")
# is the canonical order the identity on this fixture?
tn = held.table.column("trial_no").to_numpy()
print("trial_no sorted:", bool(np.all(tn[1:] > tn[:-1])), "rows", len(tn))
# raw read without _canonical
t = time.perf_counter()
files = lab_store.file_set(cells, *lab_store.latest_snapshot(cells))
raw = pa.concat_tables([lab_store._read(p, list(dict.fromkeys([*cols, "attempt"])), None) for p in files])
print(f"raw read+concat (no _canonical): {(time.perf_counter() - t) * 1000:.0f} ms")
t = time.perf_counter()
_ = lab_store._canonical(raw)
print(f"_canonical alone: {(time.perf_counter() - t) * 1000:.0f} ms")
t = time.perf_counter()
order = pc.sort_indices(raw, sort_keys=[("trial_no", "ascending"), ("block", "ascending"),
                                        ("attempt", "descending")])
print(f"  sort_indices: {(time.perf_counter() - t) * 1000:.0f} ms; identity: "
      f"{bool(np.array_equal(order.to_numpy(), np.arange(len(raw))))}")
del raw, _, held
# a per-column-type cost check: status codes and positions
ops = operations(document)
page = ops["page"][0]
call(*page)
call(*page)
prof = cProfile.Profile()
prof.enable()
call(*page)
prof.disable()
out = io.StringIO()
pstats.Stats(prof, stream=out).sort_stats("tottime").print_stats(14)
print("\n#### page warm")
print("\n".join(l for l in out.getvalue().splitlines() if l.strip()))
