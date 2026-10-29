"""Prototype costs of the fix shapes on the matrix-aggregate frame (1M rows): per-snapshot codes,
completed mask and global value order, checked bit-for-bit against the current code."""
import time

import numpy as np
import pyarrow as pa

from common import operations, setup
from products.aegis.lab import query as Q
from products.aegis.lab import sources as lab_sources
from products.aegis.lab import store as lab_store

store, cache, document, call = setup()
ops = operations(document)
meta = lab_sources.cached_meta(document, cache)
mreq = __import__("products.aegis.api", fromlist=["QueryRequest"]).QueryRequest.model_validate(
    ops["filter_heatmap"][0][2])
cols = lab_sources.COLUMNS_FOR("matrix", mreq, meta.parameters, meta.objective)
cols = tuple(dict.fromkeys([*cols, *(f"pos.{k}" for k in range(len(meta.parameters)))]))
frame, handle = lab_sources.open_experiment(document, store, cache, cols)
lab_store.REGISTRY.release(handle)
T = frame.table
flt = mreq.filter
paths = [p.path for p in frame.parameters]


def ms(fn, n=5):
    best = 1e9
    for _ in range(n):
        t = time.perf_counter()
        out = fn()
        best = min(best, (time.perf_counter() - t) * 1000)
    return best, out


# 1. positions: computed vs the stored pos.k columns
t_pos, codes = ms(lambda: [Q._positions(Q._numbers(T, p), Q._axis(frame, p)) for p in paths], 3)
stored = [T.column(f"pos.{k}").to_numpy() for k in range(len(paths))]
same = all(np.array_equal(c, s.astype(np.int64)) for c, s in zip(codes, stored))
print(f"1. _positions x10 (current): {t_pos:.0f} ms; stored pos.k equal to it: {same}")
codes8 = [c.astype(np.uint8) for c in codes]

# 2. completed mask: current (status codes + block) vs cached
t_cm, completed = ms(lambda: Q._block0(T) & (Q._status_codes(T) == 0))
print(f"2. completed mask (current, per call; called 3-4x per request): {t_cm:.1f} ms")
t_mask, mask = ms(lambda: Q.filter_mask(frame, flt))
print(f"   filter_mask with two ranges (current): {t_mask:.1f} ms")


def fast_mask():
    m = completed.copy()
    for path, (a, b) in flt.ranges.items():
        v = Q._numbers(T, path)
        m &= (v >= min(a, b)) & (v <= max(a, b))
    return m


t_fm, m2 = ms(fast_mask)
print(f"   filter_mask from a cached completed mask: {t_fm:.1f} ms; equal {np.array_equal(m2, mask)}")

# 3. by-value order: per request argsort vs restriction of a per-snapshot global order
metric = Q.metric_column(flt.scope, meta.objective)
allv = Q._numbers(T, metric)
t_g, glob = ms(lambda: Q._by_value(allv), 2)  # once per snapshot
population = np.flatnonzero(mask)
values = allv[population]
t_cur, cur = ms(lambda: Q._by_value(values), 3)


def restricted():
    keep = glob[mask[glob]]  # full-table rows, by (value, row)
    rank = np.cumsum(mask) - 1
    return rank[keep]


t_res, res = ms(restricted)
print(f"3. _by_value per request: {t_cur:.0f} ms (n={len(values)}); global order once: {t_g:.0f} ms; "
      f"restricted: {t_res:.1f} ms; identical: {np.array_equal(cur, res)}")

# 4. the whole aggregate matrix now vs with codes + order (groups only)
rows, colp = paths[0], paths[1]
t_mv, out = ms(lambda: Q.matrix_view(frame, flt, rows=rows, cols=colp, metric=meta.objective,
                                     mode="aggregate", stat="best"), 3)
print(f"4. matrix_view aggregate+ranges (current): {t_mv:.0f} ms")
r, c = codes8[0][population].astype(np.int64), codes8[1][population].astype(np.int64)
square = r * 12 + c


def groups_fast():
    return Q._Groups(square, values, 144, restricted())


t_gf, g = ms(groups_fast)
t_gc, g0 = ms(lambda: Q._Groups(square, values, 144))
print(f"   _Groups current: {t_gc:.0f} ms; with restricted order: {t_gf:.0f} ms; same sorted: "
      f"{np.array_equal(g.sorted, g0.sorted, equal_nan=True)}")
t_conf, _ = ms(lambda: Q._confounded(frame, population, square, g0.n, (rows, colp)), 3)


def conf_fast():
    size = 144
    supported = g0.n >= Q.AGG_MIN_N
    member = supported[square]
    inside = square[member]
    for k in range(2, len(paths)):
        code = codes8[k][population]
        width = 19
        q = np.bincount(code, minlength=width) / len(population)
        joint = np.bincount(inside * width + code[member], minlength=size * width)
    return joint


t_cf, _ = ms(conf_fast)
print(f"   _confounded current: {t_conf:.0f} ms; with cached codes (tally core): {t_cf:.0f} ms")
t_h, _ = ms(lambda: g0.histograms())
print(f"   histograms: {t_h:.0f} ms")

# 5. summary's tested_per_value: marginals (best + median, thrown away) vs counts of codes
unf = Q.LabFilter()
t_marg, _ = ms(lambda: Q.marginals_view(frame, unf, metric=meta.objective), 2)
cm = completed
t_cnt, _ = ms(lambda: [np.bincount(c[cm], minlength=19) for c in codes8])
print(f"5. summary marginals_view (current): {t_marg:.0f} ms; per-value counts from codes: {t_cnt:.1f} ms")

# 6. page ordering: 3 stable argsorts vs restriction of a global order
t_ord, o1 = ms(lambda: Q._ordered(T, np.flatnonzero(completed), metric, True), 3)
print(f"6. page _ordered (current): {t_ord:.0f} ms")
