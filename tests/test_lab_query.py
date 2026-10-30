"""Optimization Lab v2, Phase 2: the trial query layer (Task 7). The views are pure functions of a
`TrialFrame` and a `LabFilter`; these tests build frames by hand (`frame_of`) and from a seeded
generator (`synthetic_frame`), and recount every scope by brute force."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from products.aegis import experiments as exp
from products.aegis.lab import identity, policy
from products.aegis.lab import store as lab_store
from products.aegis.lab.cache import LabCache, cache_bytes_from_env
from products.aegis.lab.index import build_index
from products.aegis.lab.query import (
    LabFilter,
    ParameterInfo,
    TrialFrame,
    _axis,
    _numbers,
    counts_view,
    envelope,
    filter_mask,
    marginals_view,
    matrix_view,
    metric_column,
    page_view,
    parallel_view,
    scope_counts,
    square_trials_view,
    top_view,
    undefined_mask,
)
from products.aegis.pool import METRICS, SCOPES
from products.aegis.surface import Parameter, Surface, build_grid
from pydantic import ValidationError
from test_aegis_surface import pinned

pytestmark = pytest.mark.aegis

WHEN = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
METRIC_NAMES = (*METRICS, "sharpe_trade")
X = "long_side.indicators.ema.length"
Y = "long_side.indicators.sma.length"
Z = "short_side.indicators.rsi.length"
W = "short_side.stop_loss"
DROP = ("shown", "basis")


# --- frames ----------------------------------------------------------------------------------


def metrics(**values) -> dict:
    """The same hand-written metrics in every scope: `metrics(net_pnl=5.0)`."""
    return {f"{scope}.{name}": value for scope in SCOPES for name, value in values.items()}


def key_of(params: dict) -> bytes:
    return hashlib.blake2b(json.dumps(params, sort_keys=True).encode(), digest_size=16).digest()


def parameter_of(path: str, lattice) -> ParameterInfo:
    values = sorted(float(v) for v in lattice)
    side = path.split("_side", 1)[0]
    family = f"{side}:{path.split('.')[2] if '.indicators.' in path else 'levels'}"
    step = values[1] - values[0] if len(values) > 1 else 1.0
    return ParameterInfo(path, side, family, "float", values[0], values[-1], step, values)


def frame_of(
    rows: list[dict],
    paths,
    *,
    space: int | None = None,
    valid: int | None = None,
    budget_total: int | None = None,
    scheduled: int | None = None,
    values: dict | None = None,
    duplicates: int = 0,
    source: str = "exp:hand",
) -> TrialFrame:
    """A `_cells_table_v2`-shaped table of hand-written rows (`params`, `metrics` keyed
    `<scope>.<metric>`, optional `trial_no`, `status`, `pass`, `cell`), in the order given."""
    paths = list(paths)
    extra = values or {}
    lattices = {
        path: sorted(
            {float(v) for v in extra.get(path, [])} | {float(r["params"][path]) for r in rows}
        )
        for path in paths
    }
    schema = exp._cells_schema_v2(paths)
    columns: dict[str, list] = {name: [] for name in schema.names}
    for i, row in enumerate(rows):
        trial_no = row.get("trial_no", i)
        status = row.get("status", "ok")
        label = row.get("pass", "grid")
        params = {path: float(row["params"][path]) for path in paths}
        cells = row.get("metrics", {})
        columns["trial_no"].append(trial_no)
        columns["cell"].append(row.get("cell", trial_no))
        for k, path in enumerate(paths):
            columns[f"pos.{k}"].append(lattices[path].index(params[path]))
            columns[path].append(params[path])
        columns["param_key"].append(key_of(params))
        columns["pass"].append(label)
        columns["design"].append(identity.design_of(label))
        columns["block"].append(0)
        columns["reused_from"].append(None)
        columns["status"].append(status)
        columns["valid"].append(status == "ok")
        columns["skip_reason"].append("insufficient bars" if status == "invalid" else None)
        columns["error"].append("boom" if status == "failed" else None)
        columns["attempt"].append(0)
        for scope in SCOPES:
            for name in METRIC_NAMES:
                columns[f"{scope}.{name}"].append(cells.get(f"{scope}.{name}"))
        columns["elapsed_ms"].append(1.0)
        columns["engine"].append("kernel")
        columns["chunk"].append(0)
        columns["finished_at"].append(WHEN)
    size = math.prod(len(lattice) for lattice in lattices.values())
    return TrialFrame(
        source=source,
        table=pa.table(columns, schema=schema),
        parameters=[parameter_of(path, lattices[path]) for path in paths],
        space=size if space is None else space,
        valid=size if valid is None else valid,
        budget_total=len(rows) if budget_total is None else budget_total,
        scheduled=len(rows) if scheduled is None else scheduled,
        reserved=0,
        reused=0,
        duplicates=duplicates,
        snapshot=lab_store.Snapshot(0, 0),
        provisional=False,
        layout=2,
        objective="net_pnl",
    )


def synthetic_frame(n: int, d: int, seed: int) -> TrialFrame:
    """`n` trials over `d` parameters of 4 to 12 lattice values each, seeded: about 86 % ok,
    9 % invalid and 5 % failed, 2 % repeated configurations, gaps in the trial numbers (pending
    trials), whole-number metrics (so values tie), `cagr`, `mar`, `profit_factor` and
    `sharpe_trade` undefined (NaN) on about a tenth of the ok rows."""
    rng = np.random.default_rng(seed)
    paths = [f"{'long' if k < d // 2 else 'short'}_side.indicators.i{k}.length" for k in range(d)]
    sizes = rng.integers(4, 13, size=d)
    lattices = [
        float(rng.integers(2, 10)) + np.arange(size) * float(rng.choice([0.5, 1.0, 2.0]))
        for size in sizes
    ]
    positions = np.stack([rng.integers(0, size, size=n) for size in sizes], axis=1)
    repeat = np.flatnonzero(rng.random(n) < 0.02)
    repeat = repeat[repeat > 0]
    positions[repeat] = positions[repeat - 1]
    status = rng.choice(np.array(["ok", "invalid", "failed"]), size=n, p=[0.86, 0.09, 0.05])
    passes = rng.choice(np.array(["grid", "sample", "refine"]), size=n)
    scheduled = n + n // 10
    trial_no = np.sort(rng.choice(scheduled, size=n, replace=False)).astype(np.int64)
    ok = status == "ok"
    words = pa.dictionary(pa.int32(), pa.string())
    columns: dict[str, pa.Array] = {
        "trial_no": pa.array(trial_no, pa.int64()),
        "cell": pa.array(trial_no, pa.int64()),
    }
    for k in range(d):
        columns[f"pos.{k}"] = pa.array(positions[:, k].astype(np.uint16), pa.uint16())
    for k, path in enumerate(paths):
        columns[path] = pa.array(lattices[k][positions[:, k]], pa.float64())
    columns["param_key"] = pa.array(
        [hashlib.blake2b(row.tobytes(), digest_size=16).digest() for row in positions],
        pa.binary(16),
    )
    columns["pass"] = pa.array(passes.tolist(), words)
    columns["design"] = pa.array([identity.design_of(p) for p in passes.tolist()], words)
    columns["block"] = pa.array(np.zeros(n, dtype=np.uint8), pa.uint8())
    columns["status"] = pa.array(status.tolist(), words)
    columns["valid"] = pa.array(ok, pa.bool_())
    columns["attempt"] = pa.array(np.zeros(n, dtype=np.uint8), pa.uint8())
    for scope in SCOPES:
        for name in METRIC_NAMES:
            values = np.round(rng.normal(0.0, 30.0, size=n))
            if name == "max_drawdown":
                values = np.abs(values)
            if name in ("cagr", "mar", "profit_factor", "sharpe_trade"):
                values[rng.random(n) < 0.1] = np.nan
            columns[f"{scope}.{name}"] = pa.array(values, pa.float64(), mask=~ok)
    schema = exp._cells_schema_v2(paths)
    table = pa.table([columns.get(f.name, pa.nulls(n, f.type)) for f in schema], schema=schema)
    parameters = [parameter_of(path, lattices[k]) for k, path in enumerate(paths)]
    space = int(np.prod(sizes))
    return TrialFrame(
        source=f"exp:synthetic-{seed}",
        table=table,
        parameters=parameters,
        space=space,
        valid=space,
        budget_total=scheduled + 100,
        scheduled=scheduled,
        reserved=0,
        reused=0,
        duplicates=3,
        snapshot=lab_store.Snapshot(1, 7),
        provisional=False,
        layout=2,
        objective="net_pnl",
    )


def arrays_of(frame: TrialFrame) -> dict:
    """Every column of the frame as a numpy array (nulls as NaN for the metrics), for the
    brute-force recounts."""
    out = {}
    for name in frame.table.column_names:
        values = frame.table.column(name).to_pylist()
        if pa.types.is_floating(frame.table.schema.field(name).type):
            out[name] = np.array([np.nan if v is None else v for v in values], dtype=float)
        else:
            out[name] = np.array(values, dtype=object)
    return out


def recount(arrays: dict, frame: TrialFrame, flt: LabFilter, metric: str | None) -> dict:
    """The §6.4 scope by brute force, without `shown` and `basis`."""
    status = arrays["status"]
    base = arrays["block"] == 0
    completed = base & (status == "ok")
    keep = completed.copy()
    for path, (a, b) in flt.ranges.items():
        keep &= (arrays[path] >= min(a, b)) & (arrays[path] <= max(a, b))
    for path, value in flt.values.items():
        keep &= arrays[path] == value
    if flt.pass_:
        keep &= np.isin(arrays["pass"], flt.pass_)
    if flt.status:
        keep &= np.isin(status, flt.status)
    undefined = 0
    if metric is not None:
        undefined = int((keep & ~np.isfinite(arrays[f"{flt.scope}.{metric}"])).sum())
    keys = {arrays["param_key"][i] for i in np.flatnonzero(completed)}
    attempted = int(base.sum())
    return {
        "space": frame.space,
        "valid": frame.valid,
        "budget_total": frame.budget_total,
        "reserved": frame.reserved,
        "scheduled": frame.scheduled,
        "evaluations": frame.scheduled,
        "remaining": max(0, frame.budget_total - frame.reserved - frame.scheduled),
        "reused": frame.reused,
        "attempted": attempted,
        "evaluations_done": int((status == "ok").sum()),
        "completed": int(completed.sum()),
        "invalid": int((base & (status == "invalid")).sum()),
        "failed": int((base & (status == "failed")).sum()),
        "pending": frame.scheduled - attempted,
        "unique": len(keys),
        "duplicates": frame.duplicates,
        "filtered": int(keep.sum()),
        "undefined": undefined,
        "block": 0,
        "filters_active": len(flt.ranges)
        + len(flt.values)
        + (flt.scope != "combined")
        + len(flt.pass_)
        + len(flt.status),
    }


def stripped(scope: dict) -> dict:
    return {k: v for k, v in scope.items() if k not in DROP}


def squares_shown(matrix: dict) -> int:
    return sum(1 for row in matrix["counts"] for count in row if count)


def cells_of(grid: list[list]) -> list:
    return [value for row in grid for value in row]


def grid_rows(spec: list[tuple]) -> list[dict]:
    """Rows from `(x, y, pnl)` or `(x, y, pnl, extra-dict)` tuples on the X x Y lattice."""
    out = []
    for item in spec:
        x, y, pnl = item[:3]
        extra = item[3] if len(item) > 3 else {}
        out.append(
            {
                "params": {X: x, Y: y, **extra.pop("params", {})},
                "metrics": metrics(net_pnl=pnl),
                **extra,
            }
        )
    return out


# --- the exact slice (§7.1) -------------------------------------------------------------------


def test_exact_slice_empty_is_untested():
    rows = [
        {"params": {X: x, Y: y, Z: 14.0}, "metrics": metrics(net_pnl=float(x * y))}
        for x in (5.0, 10.0)
        for y in (20.0, 30.0)
    ]
    frame = frame_of(rows, (X, Y, Z), values={Z: [14.0, 99.0]})
    flt = LabFilter()
    out = matrix_view(frame, flt, rows=X, cols=Y, metric="net_pnl", mode="exact", fixed={Z: 99.0})
    assert out["rows"] == [5.0, 10.0] and out["cols"] == [20.0, 30.0]
    assert all(value is None for value in cells_of(out["values"]))
    assert all(count == 0 for count in cells_of(out["counts"]))
    assert all(trial is None for trial in cells_of(out["trial_ids"]))
    assert all(dup == 0 for dup in cells_of(out["duplicates"]))
    assert out["basis"] == "Tested (exact)"
    assert out["legend"] == "empty = untested"
    assert Z in out["empty"] and "99" in out["empty"]
    scope = scope_counts(frame, flt, squares_shown(out), metric="net_pnl", basis=out["basis"])
    wrapped = envelope("matrix", out, scope, filter_hash=None, snapshot=None, provisional=False)
    assert wrapped["empty"] == out["empty"]  # 4 trials match the filter: the slice is untested
    filled = matrix_view(
        frame, flt, rows=X, cols=Y, metric="net_pnl", mode="exact", fixed={Z: 14.0}
    )
    assert filled["empty"] is None and filled["values"] == [[100.0, 150.0], [200.0, 300.0]]


def test_exact_slice_defaults_to_spec_values():
    spec = pinned()
    donchian = "long_side.indicators.donchian.length"
    rsi = "long_side.indicators.rsi.length"
    ema = "short_side.indicators.ema.length"
    paths, axes = (donchian, rsi, ema), (donchian, rsi)
    on = [(10.0, 7.0, 9.0, 1.0), (20.0, 14.0, 9.0, 2.0)]  # the spec's own ema length, 9
    off = [(10.0, 7.0, 5.0, 3.0), (15.0, 21.0, 13.0, 4.0), (15.0, 21.0, 5.0, 5.0)]
    rows = [
        {"params": {donchian: d, rsi: r, ema: e}, "metrics": metrics(net_pnl=pnl)}
        for d, r, e, pnl in [*off, *on]
    ]
    frame = frame_of(rows, paths)
    fixed = {
        p: v
        for p, v in identity.full_effective_params(spec).items()
        if p in paths and p not in axes
    }
    assert fixed == {ema: 9.0}
    out = matrix_view(
        frame, LabFilter(), rows=donchian, cols=rsi, metric="net_pnl", mode="exact", fixed=fixed
    )
    assert out["rows"] == [10.0, 15.0, 20.0] and out["cols"] == [7.0, 14.0, 21.0]
    assert sum(cells_of(out["counts"])) == len(on)
    held = {
        (r, c): out["trial_ids"][r][c] for r in range(3) for c in range(3) if out["counts"][r][c]
    }
    assert held == {(0, 0): "exp:hand#3", (2, 1): "exp:hand#4"}  # trial numbers by row order
    assert out["values"][0][0] == 1.0 and out["values"][2][1] == 2.0
    for r in range(3):
        for c in range(3):
            if (r, c) not in held:
                assert out["values"][r][c] is None and out["trial_ids"][r][c] is None
    sma = "short_side.indicators.sma.length"  # a tunable path of the spec the frame does not carry
    wider = {**fixed, sma: identity.full_effective_params(spec)[sma]}
    with pytest.raises(ValueError, match="unknown path"):
        matrix_view(
            frame, LabFilter(), rows=donchian, cols=rsi, metric="net_pnl", mode="exact", fixed=wider
        )


def test_exact_slice_holds_first_trial_and_duplicate_count():
    rows = grid_rows(
        [
            (1.0, 10.0, 70.0, {"trial_no": 7}),
            (1.0, 10.0, 30.0, {"trial_no": 3}),
            (2.0, 10.0, 50.0, {"trial_no": 5}),
        ]
    )
    frame = frame_of(rows, (X, Y))
    out = matrix_view(frame, LabFilter(), rows=X, cols=Y, metric="net_pnl", mode="exact")
    assert out["trial_ids"] == [["exp:hand#3"], ["exp:hand#5"]]
    assert out["values"] == [[30.0], [50.0]]  # the lower trial number's value, never the best
    assert out["counts"] == [[2], [1]] and out["duplicates"] == [[1], [0]]


# --- the aggregated projection (§7.2) ---------------------------------------------------------


def test_aggregate_square_stats():
    full = [5.0, -3.0, 12.0, 7.0, 7.0, 0.5, 100.0, -40.0, 2.0]
    low = [1.0, 2.0, 3.0]
    mixed = [4.0, float("nan"), None, 9.0, -2.0, 4.0, 11.0, 0.0]
    spec = [(1.0, 10.0, v) for v in full] + [(1.0, 20.0, v) for v in low]
    spec += [(2.0, 20.0, v) for v in mixed]
    rows = grid_rows(spec)
    for row, pnl in zip(rows, [*full, *low, *mixed], strict=True):
        row["metrics"].update(metrics(max_drawdown=None if pnl is None else abs(pnl)))
    frame = frame_of(rows, (X, Y))
    flt = LabFilter()
    defined = {
        (0, 0): full,
        (0, 1): low,
        (1, 1): [v for v in mixed if v is not None and not math.isnan(v)],
    }
    expect = {
        "best": max,
        "worst": min,
        "median": lambda v: float(np.median(v)),
        "mean": lambda v: float(np.mean(v)),
    }
    for stat, fn in expect.items():
        out = matrix_view(frame, flt, rows=X, cols=Y, metric="net_pnl", mode="aggregate", stat=stat)
        assert out["basis"] == "Aggregated from tested (n = 20)"
        assert out["legend"] == "Aggregated n ≥ 8 / n < 8 low"
        assert out["values"][1][0] is None and out["stats"][1][0] is None
        assert out["counts"] == [[9, 3], [0, 8]]
        for (r, c), values in defined.items():
            assert out["values"][r][c] == pytest.approx(fn(values), rel=1e-12)
    out = matrix_view(frame, flt, rows=X, cols=Y, metric="net_pnl", mode="aggregate")
    for (r, c), values in defined.items():
        stats = out["stats"][r][c]
        assert stats["n"] == out["counts"][r][c]
        assert stats["p25"] == float(np.percentile(values, 25, method="linear"))
        assert stats["p75"] == float(np.percentile(values, 75, method="linear"))
        assert (stats["min"], stats["max"]) == (min(values), max(values))
        assert stats["low_n"] is (stats["n"] < policy.AGG_MIN_N)
    assert [
        out["stats"][0][0]["low_n"],
        out["stats"][0][1]["low_n"],
        out["stats"][1][1]["low_n"],
    ] == [
        False,
        True,
        False,
    ]
    drawdown = matrix_view(frame, flt, rows=X, cols=Y, metric="max_drawdown", mode="aggregate")
    assert drawdown["values"][0][0] == 0.5  # the best drawdown is the smallest
    worst = matrix_view(
        frame, flt, rows=X, cols=Y, metric="max_drawdown", mode="aggregate", stat="worst"
    )
    assert worst["values"][0][0] == 100.0


def test_confounded_flag_from_tvd():
    def square(x, y, zs, ws):
        return [
            {"params": {X: x, Y: y, Z: z, W: w}, "metrics": metrics(net_pnl=1.0)}
            for z, w in zip(zs, ws, strict=True)
        ]

    uniform40 = [v for v in range(4) for _ in range(10)]
    uniform16 = [v for v in range(4) for _ in range(4)]
    rows = [
        *square(1.0, 1.0, [0] * 16, uniform16),  # Z skewed
        *square(1.0, 2.0, uniform40, uniform40),  # balanced
        *square(2.0, 1.0, [0] * 8 + [1] * 8, [3] * 16),  # W skewed more than Z
        *square(2.0, 2.0, uniform40, uniform40),  # balanced
        *square(3.0, 1.0, [2] * 4, [0, 1, 2, 3]),  # skewed but n < 8
    ]
    frame = frame_of(rows, (X, Y, Z, W))
    out = matrix_view(frame, LabFilter(), rows=X, cols=Y, metric="net_pnl", mode="aggregate")
    population = {p: Counter(row["params"][p] for row in rows) for p in (Z, W)}

    def tvd(path, members):
        inside = Counter(row["params"][path] for row in members)
        keys = set(inside) | set(population[path])
        return 0.5 * sum(
            abs(inside[k] / len(members) - population[path][k] / len(rows)) for k in keys
        )

    c_square = [r for r in rows if r["params"][X] == 2.0 and r["params"][Y] == 1.0]
    assert tvd(W, c_square) > tvd(Z, c_square) > policy.CONFOUNDED_TVD
    stats = out["stats"]
    assert stats[0][0]["confounded"] == [Z]
    assert stats[0][1]["confounded"] == []
    assert stats[1][0]["confounded"] == [W, Z]
    assert stats[1][1]["confounded"] == []
    assert stats[2][0]["low_n"] is True and stats[2][0]["confounded"] == []
    assert stats[2][1] is None


def test_square_histogram_counts_sum_to_n():
    rng = np.random.default_rng(5)
    wide = [float(v) for v in rng.normal(0, 50, size=30)]
    wide[3], wide[11], wide[17] = float("nan"), None, float("inf")
    few = [3.0, -1.0, 2.5, 8.0, 0.0]
    flat = [4.0] * 8
    spec = (
        [(1.0, 1.0, v) for v in wide] + [(1.0, 2.0, v) for v in few] + [(2.0, 1.0, v) for v in flat]
    )
    frame = frame_of(grid_rows(spec), (X, Y))
    out = matrix_view(frame, LabFilter(), rows=X, cols=Y, metric="net_pnl", mode="aggregate")
    for (r, c), values in {(0, 0): wide, (0, 1): few, (1, 0): flat}.items():
        stats = out["stats"][r][c]
        histogram = stats["histogram"]
        defined = [v for v in values if v is not None and math.isfinite(v)]
        assert stats["n"] == len(values)
        assert histogram["nulls"] == len(values) - len(defined)
        assert sum(histogram["counts"]) == stats["n"] - histogram["nulls"]
        assert len(histogram["edges"]) == len(histogram["counts"]) + 1
        assert len(histogram["counts"]) <= 20
        counts, edges = np.histogram(defined, bins=min(20, len(defined)))
        assert histogram["counts"] == counts.tolist()
        assert histogram["edges"] == edges.tolist()
    assert len(out["stats"][0][0]["histogram"]["counts"]) == 20
    assert out["stats"][1][1] is None


# --- undefined metrics and the empty scope (Review Focus 2 and 3) ----------------------------


def test_lab_undefined_metric_counts():
    cagr = [5.0, None, 3.0, float("nan"), 3.0, 8.0, float("inf"), 1.0, -2.0, 3.0, 0.0, 6.0]
    rows = [
        {
            "params": {X: float(i // 4), Y: float(i % 4)},
            "metrics": metrics(net_pnl=float(i), cagr=value),
        }
        for i, value in enumerate(cagr)
    ]
    frame = frame_of(rows, (X, Y))
    undefined = {1, 3, 6}
    flt = LabFilter()
    assert scope_counts(frame, flt, metric="cagr")["undefined"] == len(undefined)
    assert scope_counts(frame, flt, metric="net_pnl")["undefined"] == 0
    assert counts_view(frame, flt, metric="cagr")["undefined"] == len(undefined)
    column = frame.table.column("combined.cagr").to_numpy()
    assert sorted(np.flatnonzero(undefined_mask(column)).tolist()) == sorted(undefined)
    for descending in (True, False):
        page = page_view(
            frame,
            flt,
            sort="combined.cagr",
            descending=descending,
            offset=0,
            limit=50,
            metric="cagr",
        )
        order = [row["trial_no"] for row in page["rows"]]
        assert order[-3:] == sorted(undefined)  # last whatever the direction, by trial number
        assert all(row["values"]["combined.cagr"] is None for row in page["rows"][-3:])
        defined = [row["values"]["combined.cagr"] for row in page["rows"][:-3]]
        assert defined == sorted(defined, reverse=descending)
    for mode in ("exact", "aggregate"):
        out = matrix_view(frame, flt, rows=X, cols=Y, metric="cagr", mode=mode)
        for trial in range(len(cagr)):
            r, c = trial // 4, trial % 4
            assert out["counts"][r][c] == 1
            assert (out["values"][r][c] is None) is (trial in undefined)
    top = top_view(frame, flt, metric="cagr", k=50)
    assert {row["trial_no"] for row in top["rows"]} == set(range(len(cagr))) - undefined
    assert [row["trial_no"] for row in top["rows"]][:2] == [5, 11]  # 8.0, then 6.0


def every_envelope(frame, flt, *, rows, cols, metric="net_pnl") -> dict:
    """All seven views through `envelope`, each scope built as the routes build it."""
    exact = "Tested (exact)"

    def wrap(view, payload, shown, basis):
        scope = scope_counts(frame, flt, shown, metric=metric, basis=basis)
        return envelope(view, payload, scope, filter_hash="f00d", snapshot=None, provisional=False)

    filtered = scope_counts(frame, flt)["filtered"]
    aggregated = f"Aggregated from tested (n = {filtered})"
    matrix = matrix_view(frame, flt, rows=rows, cols=cols, metric=metric, mode="exact")
    aggregate = matrix_view(frame, flt, rows=rows, cols=cols, metric=metric, mode="aggregate")
    page = page_view(frame, flt, sort=None, descending=False, offset=0, limit=10, metric=metric)
    top = top_view(frame, flt, metric=metric, k=10)
    marginals = marginals_view(frame, flt, metric=metric)
    parallel = parallel_view(frame, flt, axes=[rows, cols], metric=metric)
    trials = square_trials_view(
        frame,
        flt,
        rows=rows,
        cols=cols,
        row_value=frame.parameters[0].values[0],
        col_value=frame.parameters[1].values[0],
        offset=0,
        limit=10,
    )
    counts = counts_view(frame, flt, metric=metric)
    return {
        "counts": envelope(
            "counts", {}, counts, filter_hash="f00d", snapshot=None, provisional=False
        ),
        "matrix": wrap("matrix", matrix, squares_shown(matrix), exact),
        "matrix-aggregate": wrap("matrix", aggregate, squares_shown(aggregate), aggregated),
        "page": wrap("page", page, len(page["rows"]), exact),
        "top": wrap("top", top, len(top["rows"]), exact),
        "marginals": wrap("marginals", marginals, 0, aggregated),
        "parallel": wrap("parallel", parallel, parallel["shown_bundles"], aggregated),
        "square_trials": wrap("square_trials", trials, len(trials["rows"]), exact),
    }


def test_lab_query_empty_scope():
    frame = synthetic_frame(400, 4, 3)
    rows, cols = frame.parameters[0].path, frame.parameters[1].path
    flt = LabFilter(ranges={rows: (1000.0, 2000.0)})
    scope = scope_counts(frame, flt, metric="net_pnl")
    assert scope["filtered"] == 0 and scope["shown"] == 0 and scope["filters_active"] == 1
    envelopes = every_envelope(frame, flt, rows=rows, cols=cols)
    assert {e["view"] for e in envelopes.values()} == {
        "counts",
        "matrix",
        "page",
        "top",
        "marginals",
        "parallel",
        "square_trials",
    }
    for wrapped in envelopes.values():
        assert wrapped["empty"] == "no trials match: 1 filter active"
        assert wrapped["scope"]["filtered"] == 0 and wrapped["scope"]["shown"] == 0
    for name in ("matrix", "matrix-aggregate"):
        assert all(v is None for v in cells_of(envelopes[name]["values"]))
        assert all(c == 0 for c in cells_of(envelopes[name]["counts"]))
    assert envelopes["page"]["rows"] == [] and envelopes["page"]["total"] == 0
    assert envelopes["top"]["rows"] == [] and envelopes["square_trials"]["rows"] == []
    assert envelopes["parallel"]["bundles"] == [] and envelopes["parallel"]["total_bundles"] == 0
    for entry in envelopes["marginals"]["marginals"].values():
        assert sum(entry["n"]) == 0 and set(entry["best"]) == {None}
    two = LabFilter(ranges={rows: (1000.0, 2000.0)}, scope="long")
    wrapped = every_envelope(frame, two, rows=rows, cols=cols)["page"]
    assert wrapped["empty"] == "no trials match: 2 filters active"
    # a NaN or Infinity bound is a validation error, never a silent match-all or match-nothing
    for bad in (
        {"ranges": {rows: [float("nan"), 1.0]}},
        {"ranges": {rows: [0.0, float("inf")]}},
        {"values": {rows: float("-inf")}},
        {"brush": {}},
    ):
        with pytest.raises(ValidationError):
            LabFilter.model_validate(bad)
    chips = LabFilter.model_validate({"pass": ["grid"], "status": ["ok"], "scope": "short"})
    assert chips.pass_ == ["grid"] and chips.active_count() == 3


def test_one_value_axis_matrix():
    rows = [
        {"params": {Z: 5.0, X: x}, "metrics": metrics(net_pnl=float(k))}
        for k, x in enumerate([1.0, 2.0, 3.0, 4.0, 2.0])
    ]
    frame = frame_of(rows, (Z, X))
    flt = LabFilter()
    filtered = scope_counts(frame, flt)["filtered"]
    for mode in ("exact", "aggregate"):
        out = matrix_view(frame, flt, rows=Z, cols=X, metric="net_pnl", mode=mode)
        assert out["rows"] == [5.0] and out["cols"] == [1.0, 2.0, 3.0, 4.0]
        assert len(out["values"]) == 1 and len(out["values"][0]) == 4
        assert sum(cells_of(out["counts"])) == filtered == 5
    assert matrix_view(frame, flt, rows=Z, cols=X, metric="net_pnl", mode="exact")["values"] == [
        [0.0, 1.0, 2.0, 3.0]
    ]


def test_filter_hash_echoed_verbatim():
    frame = frame_of(grid_rows([(1.0, 1.0, 2.0)]), (X, Y))
    scope = counts_view(frame, LabFilter())
    snapshot = lab_store.Snapshot(3, 41)
    wrapped = envelope(
        "counts", {}, scope, filter_hash="deadbeef", snapshot=snapshot, provisional=True
    )
    assert wrapped["filter_hash"] == "deadbeef" and wrapped["view"] == "counts"
    assert wrapped["snapshot"] == {"generation": 3, "chunk_watermark": 41}
    assert wrapped["provisional"] is True and wrapped["scope"] == scope and wrapped["empty"] is None
    bare = envelope("counts", {}, scope, filter_hash=None, snapshot=None, provisional=False)
    assert bare["filter_hash"] is None and bare["snapshot"] is None


# --- counts (§6.4) ----------------------------------------------------------------------------


def test_count_invariants_hold():
    ok = [
        (1.0, 1.0, 10.0, {"trial_no": 0}),
        (1.0, 2.0, 20.0, {"trial_no": 1}),
        (2.0, 1.0, 30.0, {"trial_no": 2}),
        (2.0, 2.0, 40.0, {"trial_no": 4}),
        (3.0, 1.0, 50.0, {"trial_no": 6}),
        (3.0, 1.0, 60.0, {"trial_no": 9}),  # the configuration of trial 6 again
    ]
    other = [
        (3.0, 2.0, None, {"trial_no": 3, "status": "invalid"}),
        (1.0, 1.0, None, {"trial_no": 5, "status": "invalid"}),
        (2.0, 2.0, None, {"trial_no": 7, "status": "failed"}),
    ]
    frame = frame_of(grid_rows(ok + other), (X, Y), budget_total=20, scheduled=12, duplicates=2)
    flt = LabFilter(ranges={X: (2.0, 3.0)})
    page = page_view(frame, flt, sort=None, descending=False, offset=0, limit=2, metric="net_pnl")
    scope = scope_counts(frame, flt, len(page["rows"]), metric="net_pnl")
    assert stripped(scope) == stripped(
        {
            "space": 6,
            "valid": 6,
            "budget_total": 20,
            "reserved": 0,
            "scheduled": 12,
            "evaluations": 12,
            "remaining": 8,
            "reused": 0,
            "attempted": 9,
            "evaluations_done": 6,
            "completed": 6,
            "invalid": 2,
            "failed": 1,
            "pending": 3,
            "unique": 5,
            "duplicates": 2,
            "filtered": 4,
            "shown": 2,
            "undefined": 0,
            "basis": "Tested (exact)",
            "block": 0,
            "filters_active": 1,
        }
    )
    assert list(scope) == [
        "space",
        "valid",
        "budget_total",
        "reserved",
        "scheduled",
        "evaluations",
        "remaining",
        "reused",
        "attempted",
        "evaluations_done",
        "completed",
        "invalid",
        "failed",
        "pending",
        "unique",
        "duplicates",
        "filtered",
        "shown",
        "undefined",
        "basis",
        "block",
        "filters_active",
    ]
    s = scope
    assert s["scheduled"] + s["remaining"] + s["reserved"] == s["budget_total"]
    assert s["attempted"] + s["pending"] == s["scheduled"]
    assert s["attempted"] == s["completed"] + s["invalid"] + s["failed"]
    assert s["evaluations_done"] <= s["evaluations"]
    assert s["completed"] <= s["evaluations_done"]
    assert s["unique"] <= s["completed"]
    assert s["filtered"] <= s["completed"]
    assert s["shown"] <= s["filtered"]
    assert s["evaluations"] == s["scheduled"] and s["block"] == 0
    assert (s["shown"], s["basis"]) == (2, "Tested (exact)")
    huge = frame_of(grid_rows(ok), (X, Y), space=2**64)
    assert counts_view(huge, LabFilter())["space"] == str(2**64)


def test_counts_stable_under_axis_and_filter_churn():
    for frame in (synthetic_frame(400, 10, 1), synthetic_frame(12_000, 10, 2)):
        arrays = arrays_of(frame)
        paths = [p.path for p in frame.parameters]
        lattice = {p.path: p.values for p in frame.parameters}
        state = {
            "ranges": {},
            "values": {},
            "scope": "combined",
            "pass": [],
            "status": [],
            "axes": (paths[0], paths[1]),
            "stat": "best",
            "mode": "aggregate",
            "metric": "net_pnl",
        }
        matched = 0
        for sequence in range(200):  # each seeded sequence of changes starts where the last ended
            churn(state, np.random.default_rng([sequence, frame.table.num_rows]), paths, lattice)
            flt = LabFilter.model_validate(
                {k: state[k] for k in ("ranges", "values", "scope", "pass", "status")}
            )
            matched += check_one_scope(frame, arrays, flt, state) > 0
        assert matched >= 100  # the churn mostly leaves trials in view, so the checks have content


def churn(state: dict, rng, paths: list[str], lattice: dict) -> None:
    """One or two random changes to the filter, the axes, the stat, the mode or the metric."""
    for _ in range(int(rng.integers(1, 3))):
        move = rng.integers(0, 9)
        path = paths[int(rng.integers(0, len(paths)))]
        values = lattice[path]
        if move == 0 and len(state["ranges"]) < 3:
            a, b = (float(values[int(i)]) for i in rng.integers(0, len(values), size=2))
            state["ranges"][path] = [a, b]  # either order: a range is [min, max]
        elif move == 1 and state["ranges"]:
            state["ranges"].pop(next(iter(state["ranges"])))
        elif move == 2 and not state["values"]:
            state["values"][path] = float(values[int(rng.integers(0, len(values)))])
        elif move == 3:
            state["values"].clear()
        elif move == 4:
            state["scope"] = str(rng.choice(["combined", "long", "short"]))
        elif move == 5:
            state["pass"] = [
                str(p)
                for p in rng.choice(
                    ["grid", "sample", "refine"], size=int(rng.integers(0, 3)), replace=False
                )
            ]
            state["status"] = [
                str(s)
                for s in rng.choice(["ok", "failed"], size=int(rng.integers(0, 2)), replace=False)
            ]
        elif move == 6:
            a, b = rng.choice(len(paths), size=2, replace=False)
            state["axes"] = (paths[int(a)], paths[int(b)])
        elif move == 7:
            state["stat"] = str(rng.choice(["best", "median", "mean", "worst"]))
            state["mode"] = str(rng.choice(["exact", "aggregate"]))
        else:
            state["metric"] = str(rng.choice(["net_pnl", "cagr", "max_drawdown", "sharpe_trade"]))


def check_one_scope(frame: TrialFrame, arrays: dict, flt: LabFilter, state: dict) -> int:
    """Every view's scope against the brute-force recount; the number of trials filtered."""
    metric = state["metric"]
    expected = recount(arrays, frame, flt, metric)
    rows, cols = state["axes"]
    matrix = matrix_view(
        frame, flt, rows=rows, cols=cols, metric=metric, mode=state["mode"], stat=state["stat"]
    )
    page = page_view(frame, flt, sort=None, descending=False, offset=0, limit=50, metric=metric)
    top = top_view(frame, flt, metric=metric, k=20)
    scopes = {
        "counts": counts_view(frame, flt, metric=metric),
        "matrix": scope_counts(
            frame, flt, squares_shown(matrix), metric=metric, basis=matrix["basis"]
        ),
        "page": scope_counts(frame, flt, len(page["rows"]), metric=metric),
        "top": scope_counts(frame, flt, len(top["rows"]), metric=metric),
    }
    for scope in scopes.values():
        assert stripped(scope) == expected
        assert scope["shown"] <= scope["filtered"]
    filtered = expected["filtered"]
    assert page["total"] == filtered == sum(cells_of(matrix["counts"]))
    assert len(top["rows"]) == min(20, filtered - expected["undefined"])
    if state["mode"] == "exact":
        assert matrix["basis"] == "Tested (exact)"
    else:
        assert matrix["basis"] == f"Aggregated from tested (n = {filtered})"
    return filtered


def test_scope_long_short_independent():
    rows = []
    for t in range(6):
        values = {"combined.net_pnl": 0.0, "long.net_pnl": 10.0 * t, "short.net_pnl": -10.0 * t}
        rows.append({"params": {X: float(t // 3), Y: float(t % 3)}, "metrics": values})
    frame = frame_of(rows, (X, Y))
    page_of = {}
    for scope in ("combined", "long", "short"):
        flt = LabFilter(scope=scope)
        page = page_view(
            frame, flt, sort=None, descending=False, offset=0, limit=10, metric="net_pnl"
        )
        page_of[scope] = [row["trial_no"] for row in page["rows"]]
        assert set(page["rows"][0]["values"]) >= {f"{scope}.net_pnl"}
        matrix = matrix_view(frame, flt, rows=X, cols=Y, metric="net_pnl", mode="exact")
        sign = {"combined": 0.0, "long": 10.0, "short": -10.0}[scope]
        assert matrix["values"] == [[sign * (3 * r + c) for c in range(3)] for r in range(2)]
    assert page_of["long"] == [5, 4, 3, 2, 1, 0]
    assert page_of["short"] == [0, 1, 2, 3, 4, 5]
    assert page_of["combined"] == [0, 1, 2, 3, 4, 5]  # all tied at 0: by trial number
    long_scope = scope_counts(frame, LabFilter(scope="long"), metric="net_pnl")
    short_scope = scope_counts(frame, LabFilter(scope="short"), metric="net_pnl")
    combined = scope_counts(frame, LabFilter(), metric="net_pnl")
    assert long_scope == short_scope
    assert {k: v for k, v in long_scope.items() if k != "filters_active"} == {
        k: v for k, v in combined.items() if k != "filters_active"
    }
    assert (long_scope["filters_active"], combined["filters_active"]) == (1, 0)
    assert metric_column("long", "sharpe_trade") == "long.sharpe_trade"


def test_drilldown_preserves_counts():
    frame = synthetic_frame(400, 10, 1)
    rows, cols = frame.parameters[0].path, frame.parameters[1].path
    flt = LabFilter(ranges={frame.parameters[2].path: (frame.parameters[2].values[1], 1000.0)})
    out = matrix_view(frame, flt, rows=rows, cols=cols, metric="cagr", mode="aggregate")
    checked = 0
    for r, row_value in enumerate(out["rows"]):
        for c, col_value in enumerate(out["cols"]):
            n = out["counts"][r][c]
            if out["stats"][r][c] is not None:
                assert out["stats"][r][c]["n"] == n
            square = flt.model_copy(update={"values": {rows: row_value, cols: col_value}})
            page = page_view(
                frame, square, sort=None, descending=False, offset=0, limit=500, metric="cagr"
            )
            trials = square_trials_view(
                frame,
                flt,
                rows=rows,
                cols=cols,
                row_value=row_value,
                col_value=col_value,
                offset=0,
                limit=500,
            )
            assert page["total"] == trials["total"] == n
            listed = [row["trial_no"] for row in trials["rows"]]
            assert listed == sorted(row["trial_no"] for row in page["rows"])
            checked += n > 0
    assert checked > 10


# --- bounds and order (§9.3) ------------------------------------------------------------------


def test_page_bounds_and_order():
    pnl = [float(t % 5) if t % 11 else None for t in range(50)]
    rows = [
        {"params": {X: float(t % 7), Y: float(t % 3)}, "metrics": metrics(net_pnl=value)}
        for t, value in enumerate(pnl)
    ]
    frame = frame_of(rows, (X, Y))
    flt = LabFilter()
    kwargs = {"sort": None, "descending": False, "metric": "net_pnl"}
    with pytest.raises(ValueError):
        page_view(frame, flt, offset=0, limit=policy.PAGE_LIMIT + 1, **kwargs)
    with pytest.raises(ValueError):
        page_view(frame, flt, offset=-1, limit=10, **kwargs)
    with pytest.raises(ValueError):
        square_trials_view(
            frame, flt, rows=X, cols=Y, row_value=0.0, col_value=0.0, offset=0, limit=501
        )
    with pytest.raises(KeyError):
        page_view(
            frame, flt, offset=0, limit=10, sort="nonsense", descending=False, metric="net_pnl"
        )
    assert len(page_view(frame, flt, offset=0, limit=policy.PAGE_LIMIT, **kwargs)["rows"]) == 50
    full = page_view(frame, flt, offset=0, limit=50, **kwargs)
    defined = sorted((t for t in range(50) if pnl[t] is not None), key=lambda t: (-pnl[t], t))
    expected = defined + [t for t in range(50) if pnl[t] is None]
    assert [row["trial_no"] for row in full["rows"]] == expected
    assert full["rows"][0]["trial_id"] == "exp:hand#4" and full["rows"][0]["params"] == {
        X: 4.0,
        Y: 1.0,
    }
    assert full["rows"][0]["values"]["combined.net_pnl"] == 4.0 and full["total"] == 50
    assert {"trial_no", "cell", "params", "values", "valid", "status", "pass", "design"} <= set(
        full["rows"][0]
    )
    assert "combined.net_pnl" in full["columns"]
    by_x = page_view(frame, flt, offset=0, limit=50, sort=X, descending=True, metric="net_pnl")
    assert [row["trial_no"] for row in by_x["rows"]] == sorted(
        range(50), key=lambda t: (-(t % 7), t)
    )
    seen = []
    for offset in range(0, 50, 7):
        seen += [
            row["trial_no"]
            for row in page_view(frame, flt, offset=offset, limit=7, **kwargs)["rows"]
        ]
    assert seen == expected and len(set(seen)) == 50


def test_matrix_bound():
    big, two = "long_side.indicators.big.length", "long_side.indicators.two.length"
    a, b = "short_side.indicators.a.length", "short_side.indicators.b.length"
    values = {
        big: [float(v) for v in range(201)],
        two: [1.0, 2.0],
        a: [float(v) for v in range(200)],
        b: [float(v) for v in range(200)],
    }
    rows = [
        {"params": {big: 0.0, two: 1.0, a: 3.0, b: 4.0}, "metrics": metrics(net_pnl=1.0)},
        {"params": {big: 200.0, two: 2.0, a: 199.0, b: 0.0}, "metrics": metrics(net_pnl=2.0)},
    ]
    frame = frame_of(rows, (big, two, a, b), values=values)
    flt = LabFilter()
    for mode in ("exact", "aggregate"):
        with pytest.raises(ValueError):
            matrix_view(frame, flt, rows=big, cols=two, metric="net_pnl", mode=mode)
        with pytest.raises(ValueError):
            matrix_view(frame, flt, rows=two, cols=big, metric="net_pnl", mode=mode)
        out = matrix_view(frame, flt, rows=a, cols=b, metric="net_pnl", mode=mode)
        assert len(out["values"]) == policy.MATRIX_MAX_AXIS == 200
        assert {len(row) for row in out["values"]} == {200}
        assert out["counts"][3][4] == out["counts"][199][0] == 1
    with pytest.raises(ValueError):
        matrix_view(frame, flt, rows=a, cols=a, metric="net_pnl", mode="exact")
    with pytest.raises(ValueError, match="unknown path"):
        matrix_view(frame, flt, rows=a, cols="nope", metric="net_pnl", mode="exact")


def test_top_k_bound():
    frame = synthetic_frame(12_000, 10, 2)
    flt = LabFilter()
    with pytest.raises(ValueError):
        top_view(frame, flt, metric="net_pnl", k=policy.TOP_LIMIT + 1)
    for metric in ("net_pnl", "max_drawdown", "cagr"):
        top = top_view(frame, flt, metric=metric, k=policy.TOP_LIMIT)
        assert len(top["rows"]) <= 500
        page = page_view(
            frame, flt, sort=None, descending=False, offset=0, limit=500, metric=metric
        )
        assert [row["trial_id"] for row in top["rows"]] == [row["trial_id"] for row in page["rows"]]
        assert all(row["values"][f"combined.{metric}"] is not None for row in top["rows"])


def test_marginals_bucketed_to_200():
    fine, coarse = "long_side.indicators.fine.length", "short_side.indicators.coarse.length"
    rng = np.random.default_rng(9)
    fine_values = [1.0 + v for v in range(300)]
    coarse_values = [2.0 * v for v in range(16)]
    rows = []
    for t in range(1500):
        pnl = float(rng.integers(-50, 50)) if t % 13 else float("nan")
        rows.append(
            {
                "params": {
                    fine: fine_values[int(rng.integers(0, 300))],
                    coarse: coarse_values[int(rng.integers(0, 16))],
                },
                "metrics": metrics(net_pnl=pnl),
                "status": "invalid" if t % 17 == 0 else "ok",
            }
        )
    frame = frame_of(rows, (fine, coarse), values={fine: fine_values, coarse: coarse_values})
    flt = LabFilter()
    filtered = scope_counts(frame, flt)["filtered"]
    out = marginals_view(frame, flt, metric="net_pnl")
    assert policy.MARGINAL_BUCKETS == 200
    assert set(out["marginals"]) == {fine, coarse}
    bucketed = out["marginals"][fine]
    assert "values" not in bucketed and len(bucketed["buckets"]) <= 200
    buckets = bucketed["buckets"]
    assert buckets[0][0] == 1.0 and buckets[-1][1] == 300.0
    widths = [hi - lo for lo, hi in buckets]
    assert max(widths) == pytest.approx(min(widths))
    assert sum(bucketed["n"]) == filtered
    kept = [r for r in rows if r["status"] == "ok"]

    def own(path, key):
        groups = defaultdict(list)
        for row in kept:
            groups[key(row["params"][path])].append(row["metrics"]["combined.net_pnl"])
        return groups

    def last_bucket(v):
        return next(
            i
            for i, (lo, hi) in enumerate(buckets)
            if lo <= v < hi or (i == len(buckets) - 1 and v == hi)
        )

    for path, entry, key, size in (
        (fine, bucketed, last_bucket, len(buckets)),
        (coarse, out["marginals"][coarse], coarse_values.index, 16),
    ):
        groups = own(path, key)
        for i in range(size):
            members = groups.get(i, [])
            defined = [v for v in members if math.isfinite(v)]
            assert entry["n"][i] == len(members)
            assert entry["best"][i] == (max(defined) if defined else None)
            assert entry["median"][i] == (float(np.median(defined)) if defined else None)
    assert out["marginals"][coarse]["values"] == coarse_values
    assert "buckets" not in out["marginals"][coarse]


def test_parallel_bundles_bounded_and_ordered():
    frame = synthetic_frame(12_000, 10, 2)
    axes = [p.path for p in frame.parameters]
    flt = LabFilter()
    out = parallel_view(frame, flt, axes=axes, metric="net_pnl", q=4)
    filtered = scope_counts(frame, flt)["filtered"]
    assert out["axes"] == axes and len(out["bins"]) == 10
    assert out["total_bundles"] > 4_000 and out["total_bundles"] > out["shown_bundles"] == 2_000
    assert policy.PARALLEL_MAX_BUNDLES == 2_000 and len(out["bundles"]) == 2_000
    counts = [bundle["count"] for bundle in out["bundles"]]
    assert counts == sorted(counts, reverse=True)
    assert sum(counts) <= filtered
    assert out["basis"] == (
        f"Aggregated: 2000 of {out['total_bundles']} bundles (≥ {counts[-1]} trials each)"
        " · 0 raw lines drawn"
    )
    mask = filter_mask(frame, flt)
    pnl = frame.table.column("combined.net_pnl").to_numpy()[mask]
    vectors = []
    for k, path in enumerate(axes):
        values = frame.table.column(path).to_numpy()[mask]
        edges = np.quantile(values, np.linspace(0.0, 1.0, 5))
        assert out["bins"][k]["edges"] == edges.tolist() and len(out["bins"][k]["centres"]) == 4
        vectors.append(np.searchsorted(edges[1:-1], values, side="right"))
    groups = defaultdict(list)
    for i, vector in enumerate(zip(*vectors, strict=True)):
        groups[tuple(int(b) for b in vector)].append(pnl[i])
    assert len(groups) == out["total_bundles"]
    assert sum(len(members) for members in groups.values()) == filtered
    for bundle in out["bundles"]:
        members = groups[tuple(bundle["bins"])]
        defined = [v for v in members if math.isfinite(v)]
        assert bundle["count"] == len(members)
        assert bundle["median"] == (float(np.median(defined)) if defined else None)
    shown = {tuple(bundle["bins"]) for bundle in out["bundles"]}
    assert max(len(m) for v, m in groups.items() if v not in shown) <= counts[-1]


# --- legacy rows and the cache ----------------------------------------------------------------


def test_legacy_frame_rows(tmp_path):
    spec = pinned()
    surface = Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=10, stop=20, step=5),
            Parameter(path="long_side.indicators.rsi.length", start=7, stop=28, step=7),
        ]
    )
    grid = build_grid(spec, surface)
    paths = surface.paths()
    folder = tmp_path / "experiments" / "old-one.cells"
    folder.mkdir(parents=True)
    cells = [5, 0, 11, 3, 7]
    rows = [
        {
            "cell": cell,
            "valid": True,
            "skip_reason": None,
            "params": grid.cell_values(cell),
            "metrics": {scope: {m: float(cell + 1) for m in METRICS} for scope in SCOPES},
            "elapsed_ms": 1.0,
            "pass": "grid",
            "engine": "kernel",
        }
        for cell in cells
    ]
    pq.write_table(exp._cells_table(rows, paths), folder / "000000.parquet")
    trials = lab_store.read_latest(folder, legacy=lab_store.LegacyContext(grid, paths))
    assert trials.layout == 1
    frame = TrialFrame(
        source="exp:old-one",
        table=trials.table,
        parameters=[
            ParameterInfo(p.path, "long", "long:x", "int", p.start, p.stop, p.step, p.values())
            for p in surface.parameters
        ],
        space=grid.size,
        valid=grid.valid_count,
        budget_total=grid.size,
        scheduled=grid.size,
        reserved=0,
        reused=0,
        duplicates=trials.duplicates,
        snapshot=trials.snapshot,
        provisional=False,
        layout=trials.layout,
        objective="net_pnl",
    )
    flt = LabFilter()
    page = page_view(frame, flt, sort=None, descending=False, offset=0, limit=10, metric="net_pnl")
    assert [row["trial_id"] for row in page["rows"]] == [
        f"exp:old-one#{row['cell']}" for row in page["rows"]
    ]
    assert sorted(row["cell"] for row in page["rows"]) == sorted(cells)
    assert all(row["trial_no"] == row["cell"] for row in page["rows"])
    top = top_view(frame, flt, metric="net_pnl", k=2)
    assert [row["trial_id"] for row in top["rows"]] == ["exp:old-one#11", "exp:old-one#7"]
    matrix = matrix_view(frame, flt, rows=paths[0], cols=paths[1], metric="net_pnl", mode="exact")
    held = {t for t in cells_of(matrix["trial_ids"]) if t is not None}
    assert held == {f"exp:old-one#{cell}" for cell in cells}
    assert scope_counts(frame, flt)["unique"] == len(cells)  # a key-less legacy row is its own


def test_cache_lru_by_bytes(monkeypatch):
    def table(rows: int) -> pa.Table:
        return pa.table({"x": np.arange(rows, dtype=np.int64)})

    loads = []

    def loader(rows):
        def load():
            loads.append(rows)
            return table(rows)

        return load

    def size(t: pa.Table) -> int:
        return t.nbytes

    cache = LabCache(20_000)
    a = cache.get((("exp", "a"), 0, 0, ("x",)), loader(1000), size=size)
    assert a.nbytes == 8000
    cache.get((("exp", "b"), 0, 0, ("x",)), loader(1001), size=size)
    assert cache.stats() == {"bytes": 16008, "entries": 2, "hits": 0, "misses": 2}
    cache.get((("exp", "a"), 0, 0, ("x",)), loader(9999), size=size)  # a hit: a is the newest
    assert loads == [1000, 1001] and cache.stats()["hits"] == 1
    cache.get((("exp", "c"), 0, 0, ("x",)), loader(1002), size=size)  # evicts b, the oldest
    assert cache.stats() == {"bytes": 16016, "entries": 2, "hits": 1, "misses": 3}
    cache.get((("exp", "b"), 0, 0, ("x",)), loader(1001), size=size)  # b reloads, a goes
    assert loads == [1000, 1001, 1002, 1001]
    huge = cache.get((("exp", "d"), 0, 0, ("x",)), loader(3000), size=size)
    assert huge.num_rows == 3000 and cache.stats()["entries"] == 2  # returned, never cached
    cache.get((("exp", "d"), 0, 0, ("x",)), loader(3000), size=size)
    assert loads[-2:] == [3000, 3000]
    meta = cache.get(
        (("exp-meta", "b"), "2026-10-28"), lambda: {"objective": "cagr"}, size=lambda m: 4096
    )
    assert meta == {"objective": "cagr"}  # sized by its callable: c, the oldest, goes
    assert cache.stats() == {"bytes": 8008 + 4096, "entries": 2, "hits": 1, "misses": 7}
    assert cache.evict(("exp", "b")) == 0  # no prefix of (("exp", "b"), 0, 0, ("x",))
    assert cache.evict((("exp", "b"),)) == 1 and cache.evict((("exp-meta", "b"),)) == 1
    assert cache.stats()["entries"] == 0 and cache.stats()["bytes"] == 0
    monkeypatch.setenv("AEGIS_LAB_CACHE_MB", "7")
    assert cache_bytes_from_env() == 7 * 1024 * 1024
    monkeypatch.delenv("AEGIS_LAB_CACHE_MB")
    assert cache_bytes_from_env() == policy.LAB_CACHE_BYTES == 400 * 1024 * 1024
    assert LabCache().stats() == {"bytes": 0, "entries": 0, "hits": 0, "misses": 0}


# --- the optimizer's reference crossover (Task 8) ---------------------------------------------


def test_reference_crossover_grid_matches_optimizer():
    """The optimizer's 3 x 3 EMA / SMA grid as an `opt:` frame gives `axis_matrix`'s own values
    and counts (one cell per square, nothing skipped), and an experiment frame of the same cells
    and metrics gives the same values and the same best trial."""
    from products.aegis.lab.sources import opt_frame
    from products.aegis.optimize import axis_matrix, expand_grid, grid_values
    from test_aegis_optimize import small_strategy

    strategy = small_strategy()
    plan = expand_grid(strategy.long_side)
    assert len(plan.cells) == 9 and not plan.skipped
    cells = [
        {
            "params": params,
            "fast": params.get(plan.fast_path),
            "slow": params.get(plan.slow_path),
            "metrics": {
                **dict.fromkeys(METRICS, 1.0),
                "net_pnl": float((7 * i) % 9 - 4),
                "trade_count": float(i),
            },
        }
        for i, params in enumerate(plan.cells)
    ]
    status = {
        "job_id": "reference",
        "side": "long",
        "status": "done",
        "objective": "net_pnl",
        "strategy": strategy.model_dump(mode="json"),
        "strategy_hash": "not-read-here",
        "engine": "kernel",
        "data": {"symbol": "QQQ"},
        "cells": cells,
        "total_cells": len(plan.cells),
        "skipped_cells": len(plan.skipped),
    }
    frame = opt_frame(status)
    assert [p.path for p in frame.parameters] == [X, Y]
    long = LabFilter(scope="long")
    reference = axis_matrix(
        cells, plan.fast_path, plan.slow_path, grid_values(strategy.long_side), metrics=("net_pnl",)
    )
    out = matrix_view(frame, long, rows=X, cols=Y, metric="net_pnl", mode="exact")
    assert out["values"] == reference["metrics"]["net_pnl"]["values"]
    assert out["counts"] == reference["counts"]
    assert (out["rows"], out["cols"]) == (reference["rows"], reference["cols"])
    scope = scope_counts(frame, long)
    assert (scope["completed"], scope["unique"], scope["block"]) == (9, 9, 0)
    assert scope["space"] == scope["budget_total"] == scope["scheduled"] == 9
    rows = [
        {
            "params": {f"long_side.{path}": value for path, value in cell["params"].items()},
            "metrics": metrics(net_pnl=cell["metrics"]["net_pnl"]),
        }
        for cell in cells
    ]
    experiment = frame_of(rows, (X, Y))
    same = matrix_view(experiment, LabFilter(), rows=X, cols=Y, metric="net_pnl", mode="exact")
    assert same["values"] == out["values"] and same["counts"] == out["counts"]
    (best_opt,) = top_view(frame, long, metric="net_pnl", k=1)["rows"]
    (best_exp,) = top_view(experiment, LabFilter(), metric="net_pnl", k=1)["rows"]
    assert best_opt["params"] == best_exp["params"] and best_opt["trial_no"] == 5
    assert best_opt["trial_id"] == "opt:reference#5" and best_opt["values"]["long.net_pnl"] == 4.0


# --- the per-snapshot index (Phase 3 Task 0) --------------------------------------------------


def index_answers(
    frame: TrialFrame, flt: LabFilter, state: dict, index, pages, unique: int
) -> dict:
    """Counts, both matrix modes (every aggregate stat), the pages and the marginals of one
    filter, each with its scope as the routes build it (one mask per request, the snapshot's
    `unique`), with `index` (None: computed per request, as Phase 2 did)."""
    metric = state["metric"]
    rows, cols = state["axes"]
    mask = filter_mask(frame, flt, index=index)

    def scope(shown: int, basis: str = "Tested (exact)") -> dict:
        return scope_counts(
            frame, flt, shown, metric=metric, basis=basis, unique=unique, mask=mask, index=index
        )

    out: dict = {
        "mask": np.flatnonzero(mask).tolist(),
        "counts": counts_view(frame, flt, metric=metric, index=index),  # its own mask and unique
    }
    exact = matrix_view(frame, flt, rows=rows, cols=cols, metric=metric, mode="exact", index=index)
    out["exact"] = (exact, scope(squares_shown(exact)))
    aggregate = matrix_view(
        frame,
        flt,
        rows=rows,
        cols=cols,
        metric=metric,
        mode="aggregate",
        stat=state["stat"],
        all_stats=True,
        index=index,
    )
    out["aggregate"] = (aggregate, scope(squares_shown(aggregate), aggregate["basis"]))
    for sort, descending, offset in pages:
        page = page_view(
            frame,
            flt,
            sort=sort,
            descending=descending,
            offset=offset,
            limit=50,
            metric=metric,
            index=index,
        )
        out[f"page {sort} {descending} {offset}"] = (page, scope(len(page["rows"])))
    marginals = marginals_view(frame, flt, metric=metric, index=index)
    out["marginals"] = (marginals, scope(0, aggregated_basis_of(out["counts"])))
    return out


def aggregated_basis_of(counts: dict) -> str:
    return f"Aggregated from tested (n = {counts['filtered']})"


def test_index_answers_equal_per_request_answers():
    """The index is a cache of per-snapshot work, never a second answer: over the Phase 2 churn
    of filters, axes, stats, modes and metrics, every view built with it equals the same view
    computed per request (payload and scope), on five seeded frames."""
    checked = 0
    for seed in range(5):
        whole = synthetic_frame(20_000, 6, seed)
        paths = [p.path for p in whole.parameters]
        metrics_read = [  # the churn's metrics, and the page's, in every scope
            f"{scope}.{name}"
            for scope in SCOPES
            for name in ("net_pnl", "cagr", "max_drawdown", "sharpe_trade", "trade_count")
        ]
        base = ["trial_no", "block", "status", "param_key", "cell", "pass", "design", "valid"]
        stored = [f"pos.{k}" for k in range(len(paths))]  # so the codes come from pos.<k>
        frame = replace(whole, table=whole.table.select([*base, *stored, *paths, *metrics_read]))
        index = build_index(frame)
        unique = scope_counts(frame, LabFilter())["unique"]
        lattice = {p.path: p.values for p in frame.parameters}
        state = {
            "ranges": {},
            "values": {},
            "scope": "combined",
            "pass": [],
            "status": [],
            "axes": (paths[0], paths[1]),
            "stat": "best",
            "mode": "aggregate",
            "metric": "net_pnl",
        }
        for sequence in range(200):
            rng = np.random.default_rng([sequence, seed, 20_000])
            churn(state, rng, paths, lattice)
            flt = LabFilter.model_validate(
                {k: state[k] for k in ("ranges", "values", "scope", "pass", "status")}
            )
            column = metric_column(flt.scope, state["metric"])
            offset = int(rng.integers(0, 2_000))
            pages = [
                (None, False, 0),
                (column, True, offset),
                (column, False, offset),
                (paths[int(rng.integers(0, len(paths)))], True, offset),  # few values: ties
            ]
            fast = index_answers(frame, flt, state, index, pages, unique)
            assert fast == index_answers(frame, flt, state, None, pages, unique), (seed, sequence)
            assert set(fast["aggregate"][0]["values_by_stat"]) == {
                "best",
                "median",
                "mean",
                "worst",
            }
            checked += fast["counts"]["filtered"] > 0
    assert checked >= 500  # the churn mostly leaves trials in view, so the checks have content


def test_index_order_ties_by_trial_no():
    """`order` is the stable order of the whole frame by the metric, equal values by trial
    number in both directions, undefined values last; built once and memoized."""
    spec = [(5, 2.0), (2, 2.0), (9, None), (1, 2.0), (7, 3.0), (3, None), (4, 3.0)]
    rows = [
        {"params": {X: 1.0, Y: float(t % 2)}, "metrics": metrics(net_pnl=v), "trial_no": t}
        for t, v in spec
    ]
    frame = frame_of(rows, (X, Y))
    index = build_index(frame)
    trial = frame.table.column("trial_no").to_numpy()
    ascending = index.order("combined.net_pnl", False, frame.table)
    descending = index.order("combined.net_pnl", True, frame.table)
    assert ascending.dtype == np.int32 and descending.dtype == np.int32
    assert trial[ascending].tolist() == [1, 2, 5, 4, 7, 3, 9]
    assert trial[descending].tolist() == [4, 7, 1, 2, 5, 3, 9]
    assert index.order("combined.net_pnl", True) is descending  # memoized: no table needed
    by_x = index.order(X, True, frame.table)  # one value: every row ties
    assert trial[by_x].tolist() == sorted(trial.tolist())
    with pytest.raises(ValueError, match="never seen"):
        index.order("long.max_drawdown", False)


def test_pos_codes_equal_positions(monkeypatch):
    """A layout-2 frame's `pos.<k>` serve the codes once they equal `_positions` on the first
    chunk; a frame whose `pos.<k>` disagree falls back to `_positions` over the whole column. A
    value off its lattice codes as the lattice's length, and every view agrees with the
    per-request answer on it."""
    from products.aegis.lab import index as lab_index

    lengths: list[int] = []
    original = lab_index._positions

    def spy(values, axis):
        lengths.append(len(values))
        return original(values, axis)

    monkeypatch.setattr(lab_index, "_positions", spy)
    monkeypatch.setattr(lab_index, "CHECKED_ROWS", 100)
    frame = synthetic_frame(3_000, 6, 4)
    index = build_index(frame)

    def positions(frame: TrialFrame, path: str) -> np.ndarray:
        return original(_numbers(frame.table, path), _axis(frame, path))

    for parameter in frame.parameters:
        codes = index.codes[parameter.path]
        assert codes.dtype == np.uint16
        assert np.array_equal(codes, positions(frame, parameter.path))
    assert lengths == [100] * len(frame.parameters)  # the check only: pos.<k> held the codes

    first = frame.parameters[0].path
    width = len(frame.parameters[0].values)
    stored = frame.table.column("pos.0").to_numpy().astype(np.int64)
    at = frame.table.schema.get_field_index("pos.0")
    wrong = frame.table.set_column(
        at, "pos.0", pa.array(((stored + 1) % width).astype(np.uint16), pa.uint16())
    )
    lengths.clear()
    fallback = build_index(replace(frame, table=wrong))
    assert np.array_equal(fallback.codes[first], positions(frame, first))
    assert 3_000 in lengths  # `_positions` over the whole column for pos.0

    # A lattice that lost a value: the trials holding it are off the lattice.
    held = sorted(set(frame.parameters[1].values))
    narrowed = replace(frame.parameters[1], values=held[1:])
    off = replace(frame, parameters=[frame.parameters[0], narrowed, *frame.parameters[2:]])
    narrow_index = build_index(off)
    second = frame.parameters[1].path
    codes = narrow_index.codes[second]
    values = _numbers(frame.table, second)
    assert np.array_equal(codes == len(held) - 1, values == held[0])
    flt = LabFilter()
    for mode in ("exact", "aggregate"):
        kwargs = {"rows": first, "cols": second, "metric": "net_pnl", "mode": mode}
        assert matrix_view(off, flt, **kwargs, index=narrow_index) == matrix_view(
            off, flt, **kwargs
        )
    with_index = marginals_view(off, flt, metric="net_pnl", index=narrow_index)
    assert with_index == marginals_view(off, flt, metric="net_pnl")


def test_index_size_counts_each_array():
    """The cache sizes an index by its own arrays: the mask, each parameter's codes at their own
    width (uint32 for a lattice over 65,535 values), ORDERS_KEPT int32 orders and the position
    table, the codes not held yet at the width they will take."""
    from products.aegis.lab import index as lab_index

    wide, narrow = "long_side.indicators.wide.length", "short_side.indicators.narrow.length"
    rows = [
        {"params": {wide: float(t * 7 % 70_000), narrow: float(t % 3)}, "metrics": metrics()}
        for t in range(300)
    ]
    frame = frame_of(rows, (wide, narrow), values={wide: [float(v) for v in range(70_000)]})
    index = build_index(frame)
    assert index.codes[wide].dtype == np.uint32 and index.codes[narrow].dtype == np.uint16
    orders = (4 * lab_index.ORDERS_KEPT + lab_index.POSITION_ROW_BYTES) * 300
    held = index.completed.nbytes + index.codes[wide].nbytes + index.codes[narrow].nbytes
    assert index.nbytes(frame.parameters) == held + orders == 300 + 1_200 + 600 + orders
    partial = build_index(replace(frame, table=frame.table.drop_columns([wide])))
    assert set(partial.codes) == {narrow}  # the wide codes, not held yet, at their own width
    assert partial.nbytes(frame.parameters) == held + orders
