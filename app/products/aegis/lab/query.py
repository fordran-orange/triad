"""The Lab's query layer (Optimization Lab v2 spec §6.4, §7.1, §7.2, §7.8, §7.9, §9.3): the
filter, the frame a request reads, and the views over it.

Pure: numpy and pyarrow over a `TrialFrame`'s columns, with no I/O, no locks and no loop over
trials (the routes, Task 8, take the snapshot and build the frame). Every view reads the completed
block-0 trials its `LabFilter` selects; the filter's `scope` picks the metric column and never
drops a row. A metric that is null or non-finite is undefined: counted in the scope, never ranked
as zero, never coloured, listed last under its sort. A square no trial has tested holds no value.
`scope_counts` is a function of (frame, filter, metric) except for its `shown` and `basis`, so
every view of one filter repeats the same numbers.

The views that read a snapshot's fixed work (the completed mask, the lattice codes, the metric
orders) take that snapshot's `FrameIndex` (`index.py`) as `index`; with None they compute it per
request, as Phase 2 did, and the answers are the same.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from pydantic import BaseModel, ConfigDict, Field

from products.aegis.lab.policy import (
    AGG_MIN_N,
    CONFOUNDED_TVD,
    MARGINAL_BUCKETS,
    MATRIX_MAX_AXIS,
    PAGE_LIMIT,
    PARALLEL_BINS,
    PARALLEL_MAX_BUNDLES,
    TOP_LIMIT,
)
from products.aegis.lab.store import snapshot_json
from products.aegis.pool import METRICS, SCOPES

if TYPE_CHECKING:
    from products.aegis.lab.index import FrameIndex
    from products.aegis.lab.store import Snapshot

TRIAL_NO = "trial_no"
METRIC_NAMES = (*METRICS, "sharpe_trade")
LOWER_IS_BETTER = frozenset({"max_drawdown"})
STATS = ("best", "median", "mean", "worst")
BASIS_EXACT = "Tested (exact)"
LEGEND_EXACT = "empty = untested"
LEGEND_AGGREGATE = f"Aggregated n ≥ {AGG_MIN_N} / n < {AGG_MIN_N} low"
HISTOGRAM_BINS = 20  # an aggregate square's distribution: at most this many equal-width bins
CONFOUNDED_LISTED = 3  # §7.2: "the panel lists the top flagged parameters"
_STATUSES = ("ok", "invalid", "failed")
_ROW_FIELDS = ("valid", "status", "pass", "design")  # beside `cell`, None when not loaded
_INT64_MAX = 2**63 - 1
_BINCOUNT_SPAN = 1 << 22  # group keys below this are tallied by np.bincount (32 MB of counts)
# A frame's row selection (Ruling P1), in its cache key and on the frame itself: ordinary views
# read block 0; the importance task reads every screening block.
BLOCK0 = "block0"
ALL_BLOCKS = "all"
Selection = Literal["block0", "all"]


def aggregated_basis(filtered: int) -> str:
    """The basis of the aggregated views (matrix aggregate, marginals, parallel)."""
    return f"Aggregated from tested (n = {filtered})"


# --- the filter and the frame ----------------------------------------------------------------

# On the inner float: a NaN or Infinity bound (literals Starlette's json.loads accepts) is a
# validation error, never a silent match-all or match-nothing.
Bound = Annotated[float, Field(allow_inf_nan=False)]


class LabFilter(BaseModel):
    """The Phase 1 client's filter (labStore.ts `LabFilter`, serialized by `canonicalFilter`) plus
    `partition`. A range is `[lo, hi]` in either order and inclusive; a value is an exact match;
    `pass` and `status` keep the trials whose label is listed. A parallel brush arrives as a
    range."""

    model_config = ConfigDict(extra="forbid")

    ranges: dict[str, tuple[Bound, Bound]] = {}
    values: dict[str, Bound] = {}
    scope: Literal["combined", "long", "short"] = "combined"
    pass_: list[str] = Field(default_factory=list, alias="pass")
    status: list[str] = []
    partition: None = None

    def active_count(self) -> int:
        """The client's `activeFilterCount`: ranges, fixed values, a side scope, each pass and
        each status chip."""
        return (
            len(self.ranges)
            + len(self.values)
            + (self.scope != "combined")
            + len(self.pass_)
            + len(self.status)
        )


@dataclass
class ParameterInfo:
    path: str
    side: str
    family: str
    type: str
    start: float
    stop: float
    step: float
    values: list[float]


@dataclass
class TrialFrame:
    """What one request reads: the canonical block-0 trials of one snapshot (`read_trials`'
    table, projected to the columns the view needs) and the source's counts. `blocks` is the
    source's screening-block count K (Lab Phase 3) and `selection` the rows the table holds
    (`BLOCK0`, or `ALL_BLOCKS` for the importance task). A table filtered to block 0 before it
    was cached carries the snapshot's `evaluations_done` (§6.4: every block's ok evaluations,
    counted before the filter); None when the table holds every row it counts from."""

    source: str
    table: pa.Table
    parameters: list[ParameterInfo]
    space: int
    valid: int
    budget_total: int
    scheduled: int
    reserved: int
    reused: int
    duplicates: int
    snapshot: Snapshot | None
    provisional: bool
    layout: int
    objective: str
    blocks: int = 0
    evaluations_done: int | None = None
    selection: Selection = BLOCK0


# --- columns and masks ------------------------------------------------------------------------


def metric_column(scope: str, metric: str) -> str:
    """`<scope>.<metric>`, `sharpe_trade` included."""
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    if metric not in METRIC_NAMES:
        raise ValueError(f"unknown metric {metric!r}")
    return f"{scope}.{metric}"


def undefined_mask(values) -> np.ndarray:
    """True where a metric is undefined: null or non-finite (NaN, +-inf)."""
    if isinstance(values, (pa.Array, pa.ChunkedArray)):
        values = values.cast(pa.float64()).to_numpy(zero_copy_only=False)
    return ~np.isfinite(np.asarray(values, dtype=np.float64))


def _parameter(frame: TrialFrame, path: str) -> ParameterInfo:
    for parameter in frame.parameters:
        if parameter.path == path:
            return parameter
    raise ValueError(f"unknown path {path!r}: not a parameter of {frame.source}")


def _numbers(table: pa.Table, name: str) -> np.ndarray:
    """A column as float64, null as NaN (a missing column is the table's KeyError)."""
    return np.asarray(table.column(name).cast(pa.float64()).to_numpy(), dtype=np.float64)


def _trial_numbers(table: pa.Table) -> np.ndarray:
    return np.asarray(table.column(TRIAL_NO).to_numpy(), dtype=np.int64)


def _labelled(table: pa.Table, name: str, labels: Sequence[str]) -> np.ndarray:
    hits = pc.is_in(table.column(name), value_set=pa.array(list(labels), pa.string()))
    return np.asarray(pc.fill_null(hits, False).to_numpy(), dtype=bool)


def _status_codes(table: pa.Table) -> np.ndarray:
    """Per row 0 for ok, 1 invalid, 2 failed, 3 anything else."""
    codes = pc.index_in(table.column("status"), value_set=pa.array(_STATUSES, pa.string()))
    return np.asarray(pc.fill_null(codes, len(_STATUSES)).to_numpy(), dtype=np.int64)


def _block0(table: pa.Table) -> np.ndarray:
    return _numbers(table, "block") == 0


def _status_tallies(table: pa.Table) -> tuple[np.ndarray, dict[str, int]]:
    """§6.4's one rule for the status counts: the completed rows (ok and block 0) and the
    tallies every scope repeats, `attempted` (block 0), `evaluations_done` (ok, any block),
    `completed`, `invalid` and `failed` (block 0). The index holds them per snapshot."""
    codes = _status_codes(table)
    base = _block0(table)
    completed = base & (codes == 0)
    return completed, {
        "attempted": int(base.sum()),
        "evaluations_done": int((codes == 0).sum()),
        "completed": int(completed.sum()),
        "invalid": int((base & (codes == 1)).sum()),
        "failed": int((base & (codes == 2)).sum()),
    }


def frame_tallies(frame: TrialFrame) -> tuple[np.ndarray, dict[str, int]]:
    """`_status_tallies` of the frame's table, its `evaluations_done` the snapshot's when the
    frame carries it (a table filtered to block 0 counts every block's evaluations no more)."""
    completed, tallies = _status_tallies(frame.table)
    if frame.evaluations_done is not None:
        tallies["evaluations_done"] = frame.evaluations_done
    return completed, tallies


def _completed(frame: TrialFrame, index: FrameIndex | None) -> np.ndarray:
    """The completed (ok, block 0) rows: the index's mask, else computed. Never written to."""
    if index is None:
        return _status_tallies(frame.table)[0]
    if index.rows != frame.table.num_rows:
        raise ValueError(f"an index of {index.rows} rows cannot answer {frame.table.num_rows}")
    return index.completed


def filter_mask(
    frame: TrialFrame, flt: LabFilter, *, index: FrameIndex | None = None
) -> np.ndarray:
    """The completed (ok, block 0) rows the filter's ranges, values, pass and status keep; the
    scope never drops a row, it chooses the metric column."""
    table = frame.table
    mask = _completed(frame, index).copy()
    for path, (a, b) in flt.ranges.items():
        _parameter(frame, path)
        values = _numbers(table, path)
        mask &= (values >= min(a, b)) & (values <= max(a, b))
    for path, value in flt.values.items():
        _parameter(frame, path)
        mask &= _numbers(table, path) == value
    if flt.pass_:
        mask &= _labelled(table, "pass", flt.pass_)
    if flt.status:
        mask &= _labelled(table, "status", flt.status)
    return mask


# --- the scope (§6.4) -------------------------------------------------------------------------


def _distinct_keys(keys: pa.ChunkedArray) -> int:
    """The distinct non-null keys, plus one per null key. A 16-byte key is read as two uint64
    words: sorted by the first, and only the rows sharing a first word with a neighbour sorted
    by both, so the count is exact without hashing every key's bytes."""
    nulls = keys.null_count
    if not (pa.types.is_fixed_size_binary(keys.type) and keys.type.byte_width == 16):
        return pc.count_distinct(keys, mode="only_valid").as_py() + nulls
    valid = keys.drop_null().combine_chunks()
    if not len(valid):
        return nulls
    words = np.frombuffer(
        valid.buffers()[1], dtype=np.uint64, count=2 * (valid.offset + len(valid))
    )
    words = words.reshape(-1, 2)[valid.offset :]
    order = np.argsort(words[:, 0])
    first = words[order, 0]
    same = first[1:] == first[:-1]
    shared = np.r_[same, False] | np.r_[False, same]
    if not shared.any():
        return nulls + len(first)
    a, b = first[shared], words[order[shared], 1]
    by_both = np.lexsort((b, a))
    a, b = a[by_both], b[by_both]
    distinct_shared = 1 + int(((a[1:] != a[:-1]) | (b[1:] != b[:-1])).sum())
    return nulls + int((~shared).sum()) + distinct_shared


def scope_counts(
    frame: TrialFrame,
    flt: LabFilter,
    shown: int = 0,
    *,
    metric: str | None = None,
    basis: str = BASIS_EXACT,
    unique: int | None = None,
    mask: np.ndarray | None = None,
    index: FrameIndex | None = None,
) -> dict:
    """The §6.4 counts of one filter. `snapshot` and `provisional` are the envelope's, never the
    scope's. `unique` counts the distinct `param_key` of the completed trials; a row without a
    key (a promoted layout-1 trial, whose cell is its configuration) counts as its own. A caller
    that already holds them passes `unique` (a function of the frame alone, so one count serves
    every request on a snapshot) and the filter's `mask` (`filter_mask(frame, flt)`); the
    snapshot's `index` holds the status tallies."""
    table = frame.table
    if index is None:
        completed, tallies = frame_tallies(frame)
    else:
        completed = _completed(frame, index)
        tallies = index.tallies
    attempted = tallies["attempted"]
    if mask is None:
        mask = filter_mask(frame, flt, index=index)
    undefined = 0
    if metric is not None:
        column = _numbers(table, metric_column(flt.scope, metric))
        undefined = int(undefined_mask(column[mask]).sum())
    if unique is None:
        keys = table.column("param_key").filter(pa.array(completed, pa.bool_()))
        unique = _distinct_keys(keys)
    return {
        "space": frame.space if frame.space <= _INT64_MAX else str(frame.space),
        "valid": frame.valid,
        "budget_total": frame.budget_total,
        "reserved": frame.reserved,
        "scheduled": frame.scheduled,
        "evaluations": frame.scheduled * (frame.blocks + 1),  # K = 0 without screening blocks
        "remaining": max(0, frame.budget_total - frame.reserved - frame.scheduled),
        "reused": frame.reused,
        "attempted": attempted,
        "evaluations_done": tallies["evaluations_done"],
        "completed": tallies["completed"],
        "invalid": tallies["invalid"],
        "failed": tallies["failed"],
        "pending": frame.scheduled - attempted,
        "unique": int(unique),
        "duplicates": frame.duplicates,
        "filtered": int(mask.sum()),
        "shown": shown,
        "undefined": undefined,
        "basis": basis,
        "block": 0,  # §7.3a: every ordinary view reads block 0 and says so
        "filters_active": flt.active_count(),
    }


def counts_view(
    frame: TrialFrame,
    flt: LabFilter,
    *,
    metric: str | None = None,
    unique: int | None = None,
    mask: np.ndarray | None = None,
    index: FrameIndex | None = None,
) -> dict:
    """The counts view: the scope itself (`shown` 0, `Tested (exact)`), which the route sends as
    the envelope's `scope` beside an empty payload. With a metric, `undefined` is counted over
    its column, as the other views count it."""
    return scope_counts(frame, flt, 0, metric=metric, unique=unique, mask=mask, index=index)


# --- grouped statistics, without a loop over trials ------------------------------------------


def _by_value(values: np.ndarray) -> np.ndarray:
    """The indices of the defined values, by value (stable)."""
    defined = np.flatnonzero(np.isfinite(values))
    return defined[np.argsort(values[defined], kind="stable")]


def _narrow(size: int) -> type:
    """The narrowest integer type for group ids below `size`: numpy's stable sort is a radix
    sort on 8- and 16-bit integers."""
    return np.uint8 if size <= 1 << 8 else np.uint16 if size <= 1 << 16 else np.int64


def _tally(
    keys: np.ndarray, span: int, *, inverse: bool = True
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray]:
    """The distinct keys of `keys` (each in [0, span)), each row's index among them (with
    `inverse`) and their counts: `np.bincount` when the span is small enough to count directly,
    else `np.unique`."""
    if span <= _BINCOUNT_SPAN:
        counts = np.bincount(keys, minlength=span)
        present = np.flatnonzero(counts)
        if not inverse:
            return present, None, counts[present]
        lookup = np.zeros(span, dtype=np.int64)
        lookup[present] = np.arange(len(present))
        return present, lookup[keys], counts[present]
    if not inverse:
        present, counts = np.unique(keys, return_counts=True)
        return present, None, counts
    return np.unique(keys, return_inverse=True, return_counts=True)


class _Groups:
    """Rows in `size` groups: `n` rows per group, and each group's defined metric values sorted
    (`m` of them from `start` in `sorted`), so every statistic is a few vector operations. The
    sort is by value, then a radix sort by group; `by_value` (`_by_value(values)`) can be shared
    by several groupings of the same values."""

    def __init__(
        self, group: np.ndarray, values: np.ndarray, size: int, by_value: np.ndarray | None = None
    ) -> None:
        group = np.asarray(group, dtype=np.int64)
        self.size = size
        self.n = np.bincount(group, minlength=size)
        if by_value is None:
            by_value = _by_value(values)
        g = group[by_value]
        order = np.argsort(g.astype(_narrow(size)), kind="stable")
        self.group, self.sorted = g[order], values[by_value][order]
        self.m = np.bincount(self.group, minlength=size)
        self.start = np.cumsum(self.m) - self.m
        self.any = self.m > 0

    def _at(self, offset: np.ndarray) -> np.ndarray:
        """Each group's sorted value at `offset`, NaN for a group without a defined value."""
        out = np.full(self.size, np.nan)
        out[self.any] = self.sorted[(self.start + offset)[self.any]]
        return out

    def minimum(self) -> np.ndarray:
        return self._at(np.zeros(self.size, dtype=np.int64))

    def maximum(self) -> np.ndarray:
        return self._at(self.m - 1)

    def mean(self) -> np.ndarray:
        total = np.bincount(self.group, weights=self.sorted, minlength=self.size)
        out = np.full(self.size, np.nan)
        np.divide(total, self.m, out=out, where=self.any)
        return out

    def median(self) -> np.ndarray:
        """`np.median`'s: the middle value, or the mean of the two middle ones."""
        half = self.m // 2
        upper, lower = self._at(half), self._at(np.maximum(half - 1, 0))
        even = self.any & (self.m % 2 == 0)
        out = upper.copy()
        out[even] = (lower[even] + upper[even]) / 2
        return out

    def quantile(self, q: float) -> np.ndarray:
        """`np.percentile(..., method="linear")` per group, with numpy's own arithmetic (its
        virtual index and its two-sided interpolation), so the numbers agree to the bit."""
        h = self.m * q + (1.0 - q) - 1.0
        below = np.floor(h)
        at_end = h >= self.m - 1
        gamma = np.where(at_end, 0.0, h - below)
        a = self._at(np.where(at_end, self.m - 1, below).astype(np.int64))
        b = self._at(np.where(at_end, self.m - 1, below + 1).astype(np.int64))
        diff = b - a
        out = a + diff * gamma
        upper = gamma >= 0.5
        out[upper] = b[upper] - diff[upper] * (1.0 - gamma[upper])
        return out

    def stat(self, stat: str, metric: str) -> np.ndarray:
        if stat == "median":
            return self.median()
        if stat == "mean":
            return self.mean()
        best = (stat == "best") != (metric in LOWER_IS_BETTER)
        return self.maximum() if best else self.minimum()

    def histograms(self) -> tuple[list[float], list[int], np.ndarray, np.ndarray, np.ndarray]:
        """`np.histogram` of each group's defined values with `min(HISTOGRAM_BINS, m)` bins:
        numpy's edges (`linspace` over [min, max], widened by 0.5 each way when they are equal)
        and its bin rule (the last bin closed). Returns the flat edges, the flat counts, each
        group's bin count and where its edges and its counts start."""
        bins = np.minimum(HISTOGRAM_BINS, self.m)
        first, last = self.minimum(), self.maximum()
        flat = self.any & (first == last)
        first[flat] -= 0.5
        last[flat] += 0.5
        edge_n = np.where(self.any, bins + 1, 0)
        edge_start = np.cumsum(edge_n) - edge_n
        owner = np.repeat(np.arange(self.size), edge_n)
        j = np.arange(int(edge_n.sum())) - edge_start[owner]
        step = (last - first) / np.where(self.any, bins, 1)
        edges = j * step[owner] + first[owner]
        closing = j == bins[owner]
        edges[closing] = last[owner][closing]
        g, v = self.group, self.sorted
        width = bins[g]
        index = (((v - first[g]) / (last[g] - first[g])) * width).astype(np.intp)
        index[index == width] -= 1
        base = edge_start[g]
        index[v < edges[base + index]] -= 1
        index[(v >= edges[base + index + 1]) & (index != width - 1)] += 1
        count_start = np.cumsum(bins) - bins
        counts = np.bincount(count_start[g] + index, minlength=int(bins.sum()))
        return edges.tolist(), counts.tolist(), bins, edge_start, count_start


def _optional(values: np.ndarray) -> list[float | None]:
    """A float per entry, None where undefined: an undefined value is never sent as a number."""
    return [value if math.isfinite(value) else None for value in values.tolist()]


def _finite(value):
    return None if value is None or not math.isfinite(value) else value


def _grid(flat: list, rows: int, width: int) -> list[list]:
    return [flat[r * width : (r + 1) * width] for r in range(rows)]


def _number(value: float) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)


# --- the matrix: exact slice (§7.1) and aggregated projection (§7.2) -------------------------


def _axis(frame: TrialFrame, path: str) -> np.ndarray:
    """A parameter's values, sorted."""
    return np.unique(np.asarray(_parameter(frame, path).values, dtype=np.float64))


def _positions(values: np.ndarray, axis: np.ndarray) -> np.ndarray:
    """Each value's index on the sorted axis, -1 for a value off it. A lattice's index is read
    arithmetically (its values are evenly spaced) and kept only where the axis holds exactly
    that value; any other value is searched for."""
    if len(axis) < 2:
        return np.where(values == axis[0], 0, -1) if len(axis) else np.full(len(values), -1)
    guess = np.rint((values - axis[0]) / ((axis[-1] - axis[0]) / (len(axis) - 1)))
    guess = np.clip(np.where(np.isfinite(guess), guess, 0), 0, len(axis) - 1)
    at = guess.astype(np.int64)
    miss = np.flatnonzero(axis[at] != values)
    if len(miss):
        found = np.minimum(np.searchsorted(axis, values[miss]), len(axis) - 1)
        at[miss] = np.where(axis[found] == values[miss], found, -1)
    return at


def _confounded(
    frame: TrialFrame,
    population: np.ndarray,
    square: np.ndarray,
    n: np.ndarray,
    axes: tuple[str, str],
    index: FrameIndex | None = None,
) -> list[list[str]]:
    """Per square of n >= AGG_MIN_N, the other parameters whose value distribution inside it is
    more than CONFOUNDED_TVD (total variation distance) from the matrix's population, by
    descending distance, at most CONFOUNDED_LISTED. Over the values a square holds,
    TVD = (1 + sum(|p - q| - q)) / 2, since the population's q sums to one. The lattice
    positions are the index's codes when it is given."""
    size = len(n)
    others = [p.path for p in frame.parameters if p.path not in axes]
    supported = n >= AGG_MIN_N
    member = supported[square]
    out: list[list[str]] = [[] for _ in range(size)]
    if not others or not member.any():
        return out
    inside = square[member]
    tvd = np.zeros((len(others), size))
    for k, path in enumerate(others):  # a loop over the parameters
        lattice = _axis(frame, path)
        width = len(lattice)
        if index is None:
            code = _positions(_numbers(frame.table, path)[population], lattice)
            off = bool((code < 0).any())
        else:
            code = index.codes_for(frame, path)[population]
            off = bool((code == width).any())
        if off:  # a value off the lattice: the values held are the categories
            _, code = np.unique(_numbers(frame.table, path)[population], return_inverse=True)
            width = int(code.max()) + 1
        q = np.bincount(code, minlength=width) / len(population)
        joint, _, count = _tally(inside * width + code[member], size * width, inverse=False)
        s, v = joint // width, joint % width
        excess = np.abs(count / n[s] - q[v]) - q[v]
        tvd[k] = 0.5 * (1.0 + np.bincount(s, weights=excess, minlength=size))
    tvd[:, ~supported] = 0.0
    flagged = tvd > CONFOUNDED_TVD
    for s in np.flatnonzero(flagged.any(axis=0)).tolist():  # a loop over the flagged squares
        ks = np.flatnonzero(flagged[:, s])
        ranked = ks[np.argsort(-tvd[ks, s], kind="stable")][:CONFOUNDED_LISTED]
        out[s] = [others[k] for k in ranked.tolist()]
    return out


def matrix_view(
    frame: TrialFrame,
    flt: LabFilter,
    *,
    rows: str,
    cols: str,
    metric: str,
    mode: Literal["exact", "aggregate"],
    stat: Literal["best", "median", "mean", "worst"] = "best",
    fixed: Mapping[str, float] | None = None,
    index: FrameIndex | None = None,
    all_stats: bool = False,
) -> dict:
    """One square per (rows, cols) value pair over the filtered trials that also match `fixed`
    (None: no constraint). Exact (§7.1): a tested square holds its lowest trial number's value
    and id, with the other trials on it counted as `duplicates`. Aggregate (§7.2): the `stat` of
    the square's defined values with its n, quartiles, range, `low_n`, `confounded` and
    histogram. An untested square is None, never filled. With `all_stats`, an aggregate also
    carries `values_by_stat`, every stat's grid from the same groups (what the routes cache, so
    a stat change is not computed again)."""
    if rows == cols:
        raise ValueError("a matrix needs two different parameters")
    row_axis, col_axis = _axis(frame, rows), _axis(frame, cols)
    for path, axis in ((rows, row_axis), (cols, col_axis)):
        if len(axis) > MATRIX_MAX_AXIS:
            raise ValueError(
                f"{path} has {len(axis)} values; a matrix axis holds at most {MATRIX_MAX_AXIS}"
            )
    fixed = dict(fixed or {})
    for path in fixed:
        _parameter(frame, path)  # a fixed key is never silently ignored
    if mode not in ("exact", "aggregate"):
        raise ValueError(f"unknown matrix mode {mode!r}")
    if stat not in STATS:
        raise ValueError(f"unknown stat {stat!r}")
    column = metric_column(flt.scope, metric)
    table = frame.table
    mask = filter_mask(frame, flt, index=index)
    filtered = int(mask.sum())
    for path, value in fixed.items():
        mask &= _numbers(table, path) == value
    candidates = np.flatnonzero(mask)
    height, width = len(row_axis), len(col_axis)
    if index is None:
        r = _positions(_numbers(table, rows)[candidates], row_axis)
        c = _positions(_numbers(table, cols)[candidates], col_axis)
        on = (r >= 0) & (c >= 0)
    else:  # off the lattice, a code is the lattice's length
        r = index.codes_for(frame, rows)[candidates].astype(np.int64)
        c = index.codes_for(frame, cols)[candidates].astype(np.int64)
        on = (r < height) & (c < width)
    population = candidates[on]
    size = height * width
    square = r[on] * width + c[on]
    counts = np.bincount(square, minlength=size)
    values = _numbers(table, column)[population]
    out: dict = {
        "rows_path": rows,
        "cols_path": cols,
        "rows": row_axis.tolist(),
        "cols": col_axis.tolist(),
    }
    untested = None
    if fixed and not counts.any():
        named = ", ".join(f"{path} = {_number(value)}" for path, value in fixed.items())
        untested = f"untested slice: no trial has {named}"
    if mode == "exact":
        trial = _trial_numbers(table)[population]
        first = np.full(size, _INT64_MAX, dtype=np.int64)
        np.minimum.at(first, square, trial)  # each square's lowest trial number
        lead = np.flatnonzero(trial == first[square])
        value_at = np.full(size, np.nan)
        value_at[square[lead]] = values[lead]
        trial_at = np.where(counts > 0, first, -1)
        ids = [None if t < 0 else f"{frame.source}#{t}" for t in trial_at.tolist()]
        out.update(
            values=_grid(_optional(value_at), height, width),
            counts=_grid(counts.tolist(), height, width),
            basis=BASIS_EXACT,
            legend=LEGEND_EXACT,
            empty=untested,
            trial_ids=_grid(ids, height, width),
            duplicates=_grid(np.maximum(counts - 1, 0).tolist(), height, width),
        )
        return out
    by_value = None if index is None else index.restricted(table, column, population, values)
    groups = _Groups(square, values, size, by_value)
    confounded = _confounded(frame, population, square, groups.n, (rows, cols), index)
    edges, bin_counts, bins, edge_start, count_start = groups.histograms()
    n, m = groups.n.tolist(), groups.m.tolist()
    p25, p75 = _optional(groups.quantile(0.25)), _optional(groups.quantile(0.75))
    low, high = _optional(groups.minimum()), _optional(groups.maximum())
    bins, edge_start, count_start = bins.tolist(), edge_start.tolist(), count_start.tolist()
    stats: list[dict | None] = []
    for s in range(size):  # a loop over the squares sent, at most 200 x 200
        if not n[s]:
            stats.append(None)
            continue
        stats.append(
            {
                "n": n[s],
                "p25": p25[s],
                "p75": p75[s],
                "min": low[s],
                "max": high[s],
                "low_n": n[s] < AGG_MIN_N,
                "confounded": confounded[s],
                "histogram": {
                    "edges": edges[edge_start[s] : edge_start[s] + bins[s] + 1] if m[s] else [],
                    "counts": bin_counts[count_start[s] : count_start[s] + bins[s]],
                    "nulls": n[s] - m[s],
                },
            }
        )
    out.update(
        values=_grid(_optional(groups.stat(stat, metric)), height, width),
        counts=_grid(n, height, width),
        basis=aggregated_basis(filtered),
        legend=LEGEND_AGGREGATE,
        empty=untested,
        stats=_grid(stats, height, width),
    )
    if all_stats:
        out["values_by_stat"] = {
            name: _grid(_optional(groups.stat(name, metric)), height, width) for name in STATS
        }
    return out


# --- rows: page, top and a square's trials (§9.3) --------------------------------------------


def _check_window(offset: int, limit: int) -> None:
    if offset < 0:
        raise ValueError(f"offset must be >= 0, not {offset}")
    if not 0 <= limit <= PAGE_LIMIT:
        raise ValueError(f"limit must be between 0 and {PAGE_LIMIT}, not {limit}")


def _is_metric(name: str) -> bool:
    scope, _, metric = name.partition(".")
    return scope in SCOPES and metric in METRIC_NAMES


def _sortable(frame: TrialFrame) -> set[str]:
    metrics = (f"{scope}.{metric}" for scope in SCOPES for metric in METRIC_NAMES)
    return {TRIAL_NO, *(p.path for p in frame.parameters), *metrics}


def _ordered(table: pa.Table, members: np.ndarray, column: str, descending: bool) -> np.ndarray:
    """`members` by (column, trial_no), the undefined values last whatever the direction: three
    stable sorts, by trial number (a canonical table is in that order already), by value, then
    defined before undefined."""
    order = members[np.argsort(_trial_numbers(table)[members], kind="stable")]
    values = _numbers(table, column)[order]
    undefined = ~np.isfinite(values)
    key = np.where(undefined, 0.0, values)
    by_key = np.argsort(-key if descending else key, kind="stable")
    order, undefined = order[by_key], undefined[by_key]
    return order[np.argsort(undefined, kind="stable")]


def _rows(frame: TrialFrame, indices: np.ndarray) -> tuple[list[dict], list[str]]:
    """The rows at `indices`, in that order, and the metric columns their `values` carry (every
    `<scope>.<metric>` column the frame loaded)."""
    table = frame.table.take(pa.array(indices, pa.int64()))
    names = table.column_names
    params = [p.path for p in frame.parameters if p.path in names]
    columns = [name for name in names if _is_metric(name)]
    fields = [name for name in ("cell", *_ROW_FIELDS) if name in names]
    data = {name: table.column(name).to_pylist() for name in (TRIAL_NO, *params, *columns, *fields)}
    out = []
    for i, trial_no in enumerate(data[TRIAL_NO]):  # the rows sent, never the trials
        row = {
            "trial_id": f"{frame.source}#{trial_no}",
            "trial_no": trial_no,
            "cell": data["cell"][i] if "cell" in data else None,
            "params": {path: data[path][i] for path in params},
            "values": {name: _finite(data[name][i]) for name in columns},
        }
        row.update({name: data[name][i] if name in data else None for name in _ROW_FIELDS})
        out.append(row)
    return out, columns


def _page(frame: TrialFrame, ordered: np.ndarray, offset: int, limit: int) -> dict:
    rows, columns = _rows(frame, ordered[offset : offset + limit])
    return {"total": len(ordered), "rows": rows, "columns": columns}


def page_view(
    frame: TrialFrame,
    flt: LabFilter,
    *,
    sort: str | None,
    descending: bool,
    offset: int,
    limit: int,
    metric: str,
    index: FrameIndex | None = None,
) -> dict:
    """One offset page of the filtered trials by (sort, trial_no), the undefined values last
    whatever the direction. With no `sort`, the scope's metric column, best first (descending,
    ascending for max_drawdown). With the snapshot's `index`, its order of the whole frame is
    restricted to the filtered rows, never sorted again."""
    _check_window(offset, limit)
    column = metric_column(flt.scope, metric)
    if sort is None:
        sort, descending = column, metric not in LOWER_IS_BETTER
    elif sort not in _sortable(frame):
        raise KeyError(f"unknown sort column {sort!r}")
    mask = filter_mask(frame, flt, index=index)
    if index is None:
        ordered = _ordered(frame.table, np.flatnonzero(mask), sort, descending)
    else:
        whole = index.order(sort, descending, frame.table)
        ordered = whole[mask[whole]].astype(np.int64)
    return _page(frame, ordered, offset, limit)


def top_view(frame: TrialFrame, flt: LabFilter, *, metric: str, k: int) -> dict:
    """The best `k` filtered trials with a defined value, best first by (value, trial_no): an
    undefined value is never ranked."""
    if not 0 <= k <= TOP_LIMIT:
        raise ValueError(f"k must be between 0 and {TOP_LIMIT}, not {k}")
    column = metric_column(flt.scope, metric)
    table = frame.table
    members = np.flatnonzero(filter_mask(frame, flt))
    values = _numbers(table, column)[members]
    defined = np.isfinite(values)
    members, values = members[defined], values[defined]
    descending = metric not in LOWER_IS_BETTER
    chosen = members[:0]
    if k and len(members):
        candidates = pa.table(
            {"value": pa.array(values), TRIAL_NO: pa.array(_trial_numbers(table)[members])}
        )
        picked = pc.select_k_unstable(
            candidates,
            k=min(k, len(members)),
            sort_keys=[
                ("value", "descending" if descending else "ascending"),
                (TRIAL_NO, "ascending"),
            ],
        )
        chosen = _ordered(table, members[picked.to_numpy()], column, descending)
    rows, _ = _rows(frame, chosen)
    return {"metric": column, "rows": rows}


def square_trials_view(
    frame: TrialFrame,
    flt: LabFilter,
    *,
    rows: str,
    cols: str,
    row_value: float,
    col_value: float,
    offset: int,
    limit: int,
) -> dict:
    """The trials an aggregate square holds (the filter plus its two values), by trial number,
    paged like `page_view`: its `total` is the square's n."""
    if rows == cols:
        raise ValueError("a square needs two different parameters")
    _parameter(frame, rows)
    _parameter(frame, cols)
    _check_window(offset, limit)
    table = frame.table
    mask = filter_mask(frame, flt)
    mask &= (_numbers(table, rows) == row_value) & (_numbers(table, cols) == col_value)
    members = np.flatnonzero(mask)
    ordered = members[np.argsort(_trial_numbers(table)[members], kind="stable")]
    return _page(frame, ordered, offset, limit)


# --- marginals and parallel bundles (§7.9) ---------------------------------------------------


def _marginal_groups(
    frame: TrialFrame, parameter: ParameterInfo, members: np.ndarray, index: FrameIndex | None
) -> tuple[np.ndarray, dict, int]:
    """Each member's group on `parameter`, its entry (`values` or `buckets`) and the number of
    groups sent: its lattice position (a value off the lattice in one more group, never sent),
    or its equal-width bucket over [start, stop] when it has more than MARGINAL_BUCKETS values."""
    lattice = np.unique(np.asarray(parameter.values, dtype=np.float64))
    size = len(lattice)
    if size <= MARGINAL_BUCKETS:
        entry: dict = {"values": lattice.tolist()}
        if index is not None:  # a code off the lattice is `size` already
            return index.codes_for(frame, parameter.path)[members], entry, size
        group = _positions(_numbers(frame.table, parameter.path)[members], lattice)
        return np.where(group < 0, size, group), entry, size
    lo, hi = sorted((float(parameter.start), float(parameter.stop)))
    edges = np.linspace(lo, hi, MARGINAL_BUCKETS + 1)
    held = _numbers(frame.table, parameter.path)[members]
    group = np.searchsorted(edges[1:-1], held, side="right")
    entry = {"buckets": np.stack([edges[:-1], edges[1:]], axis=1).tolist()}
    return group, entry, MARGINAL_BUCKETS


def tested_per_value(
    frame: TrialFrame, parameter: ParameterInfo, members: np.ndarray, index: FrameIndex | None
) -> tuple[dict, list[int]]:
    """One parameter's marginal entry (`values` or `buckets`) and its `n`, counted alone: what
    the summary sends, without the marginals' sort of the metric."""
    group, entry, size = _marginal_groups(frame, parameter, members, index)
    return entry, np.bincount(group, minlength=size + 1)[:size].tolist()


def marginals_view(
    frame: TrialFrame,
    flt: LabFilter,
    *,
    metric: str,
    paths: Sequence[str] | None = None,
    index: FrameIndex | None = None,
) -> dict:
    """Per parameter (default: every one), the filtered trials per value, or per bucket when it
    has more than MARGINAL_BUCKETS values (equal-width over [start, stop]), with the best and the
    median defined value of each."""
    column = metric_column(flt.scope, metric)
    chosen = [p.path for p in frame.parameters] if paths is None else list(paths)
    parameters = [_parameter(frame, path) for path in chosen]
    table = frame.table
    members = np.flatnonzero(filter_mask(frame, flt, index=index))
    values = _numbers(table, column)[members]
    # one sort of the metric serves every parameter: the index's, restricted, when it is given
    if index is None:
        by_value = _by_value(values)
    else:
        by_value = index.restricted(table, column, members, values)
    out: dict[str, dict] = {}
    for parameter in parameters:  # a loop over the parameters
        group, entry, size = _marginal_groups(frame, parameter, members, index)
        groups = _Groups(group, values, size + 1, by_value)
        entry["n"] = groups.n[:size].tolist()
        entry["best"] = _optional(groups.stat("best", metric)[:size])
        entry["median"] = _optional(groups.median()[:size])
        out[parameter.path] = entry
    return {"metric": column, "marginals": out}


def parallel_view(
    frame: TrialFrame,
    flt: LabFilter,
    *,
    axes: Sequence[str],
    metric: str,
    q: int = PARALLEL_BINS,
) -> dict:
    """Bundles of the filtered trials sharing one quantile-bin vector over the axes (each axis's
    q bins cut at the quantiles of the filtered population), largest first, at most
    PARALLEL_MAX_BUNDLES, each with its count and its median defined value."""
    axes = list(axes)
    if not axes:
        raise ValueError("parallel coordinates need at least one axis")
    if len(set(axes)) != len(axes):
        raise ValueError("an axis is named twice")
    for path in axes:
        _parameter(frame, path)
    if q < 1:
        raise ValueError(f"q must be at least 1, not {q}")
    if q ** len(axes) - 1 > _INT64_MAX:
        raise ValueError(f"{len(axes)} axes of {q} bins overflow a bundle key")
    column = metric_column(flt.scope, metric)
    table = frame.table
    members = np.flatnonzero(filter_mask(frame, flt))
    key = np.zeros(len(members), dtype=np.int64)
    bins = []
    for path in axes:  # a loop over the axes
        held = _numbers(table, path)[members]
        if not len(members):
            bins.append({"edges": [], "centres": []})
            continue
        edges = np.quantile(held, np.linspace(0.0, 1.0, q + 1))
        bins.append({"edges": edges.tolist(), "centres": ((edges[:-1] + edges[1:]) / 2).tolist()})
        key = key * q + np.searchsorted(edges[1:-1], held, side="right")
    keys, bundle, counts = _tally(key, q ** len(axes))
    order = np.lexsort((keys, -counts))[:PARALLEL_MAX_BUNDLES]  # largest first, then by bins
    rank = np.full(len(keys), -1, dtype=np.int64)
    rank[order] = np.arange(len(order))
    sent = rank[bundle]
    inside = sent >= 0  # the medians of the bundles sent only
    metric_values = _numbers(table, column)[members]
    medians = _Groups(sent[inside], metric_values[inside], len(order)).median()
    radix = np.int64(q) ** np.arange(len(axes) - 1, -1, -1, dtype=np.int64)
    digits = (keys[order][:, None] // radix) % q
    shown = counts[order]
    bundles = [
        {"bins": vector, "count": count, "median": median}
        for vector, count, median in zip(
            digits.tolist(), shown.tolist(), _optional(medians), strict=True
        )
    ]
    least = int(shown.min()) if len(shown) else 0
    return {
        "axes": axes,
        "bins": bins,
        "bundles": bundles,
        "total_bundles": len(keys),
        "shown_bundles": len(order),
        "basis": (
            f"Aggregated: {len(order)} of {len(keys)} bundles (≥ {least} trials each)"
            " · 0 raw lines drawn"
        ),
    }


# --- the envelope ----------------------------------------------------------------------------


def envelope(
    view: str,
    payload: dict,
    scope: dict,
    *,
    filter_hash: str | None,
    snapshot: Snapshot | None,
    provisional: bool,
) -> dict:
    """Every view's response: the echoed `filter_hash`, the scope, the snapshot the rows were
    read at and `empty`, the explicit empty state (no trial matches the filter, else the
    payload's own, such as an untested exact slice), beside the payload."""
    if scope["filtered"] == 0:
        active = scope["filters_active"]
        empty = f"no trials match: {active} filter{'' if active == 1 else 's'} active"
    else:
        empty = payload.get("empty")
    return {
        "view": view,
        "filter_hash": filter_hash,
        "scope": scope,
        "snapshot": snapshot_json(snapshot),
        "provisional": provisional,
        "empty": empty,
        **{key: value for key, value in payload.items() if key != "empty"},
    }
