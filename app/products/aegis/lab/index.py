"""The Lab's per-snapshot index (Phase 3 Task 0): what every request on one snapshot would
otherwise recompute, derived once and shared by every view and every projection of its rows.

- `completed`: the completed rows (block 0 and `ok`), and the status tallies the scope reads;
- `codes`: each parameter's lattice position per row (uint16), the lattice's length for a value
  off it, so `codes == len(lattice)` is the `-1` of `query._positions`;
- `order(metric_column, descending)`: the stable order of the whole frame by one column, ties by
  trial number, undefined values last, which a view restricts to its filtered rows instead of
  sorting them again.

Every frame of one experiment instance, snapshot and row selection holds the same canonical rows
in the same order, so an index built from one projection serves the others: a part it lacks (a
parameter whose column the first frame did not load, a column it has not ordered by yet) is
derived from the first frame that brings the column, then kept. The routes cache one index per
snapshot beside the tables (`sources.experiment_index`)."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pyarrow as pa

from products.aegis.lab.policy import PART_ROW_GROUP
from products.aegis.lab.query import (
    ParameterInfo,
    TrialFrame,
    _axis,
    _numbers,
    _ordered,
    _positions,
    frame_tallies,
)

CHECKED_ROWS = PART_ROW_GROUP  # a stored `pos.<k>` is trusted once it equals `_positions` here
ORDERS_KEPT = 4  # orders memoized per index, least recently used out (each 4 bytes a row)
_UINT16_MAX = 65_535  # a lattice of up to this many values codes as uint16, its "off" included


@dataclass(frozen=True, eq=False)
class FrameIndex:
    """One snapshot's derived arrays (module docstring). Built by `build_index`; `codes` and the
    orders fill in as frames bring their columns, under the index's own lock. Every array is
    read-only: the cache shares it between requests, and a view copies before it narrows."""

    completed: np.ndarray
    tallies: dict[str, int]
    codes: dict[str, np.ndarray]
    _orders: OrderedDict[tuple[str, bool], np.ndarray] = field(
        default_factory=OrderedDict, repr=False
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def rows(self) -> int:
        return len(self.completed)

    def _aligned(self, table: pa.Table) -> None:
        if table.num_rows != self.rows:
            raise ValueError(
                f"an index of {self.rows} rows cannot answer a frame of {table.num_rows}"
            )

    def codes_for(self, frame: TrialFrame, path: str) -> np.ndarray:
        """`path`'s codes, derived from `frame` the first time they are asked for."""
        held = self.codes.get(path)
        if held is not None:
            return held
        self._aligned(frame.table)
        codes = _frozen(_lattice_codes(frame, path))
        with self._lock:
            return self.codes.setdefault(path, codes)

    def order(
        self, metric_column: str, descending: bool, table: pa.Table | None = None
    ) -> np.ndarray:
        """Every row of the frame by `metric_column` (descending or not), equal values by trial
        number then row, undefined values last: `query._ordered` over the whole frame, as
        int32. Built from `table` the first time and memoized (ORDERS_KEPT of them)."""
        key = (metric_column, bool(descending))
        with self._lock:
            held = self._orders.get(key)
            if held is not None:
                self._orders.move_to_end(key)
                return held
        if table is None:
            raise ValueError(
                f"the index has never seen {metric_column!r}: pass the frame's table to order by it"
            )
        self._aligned(table)
        order = _ordered(table, np.arange(self.rows), metric_column, descending)
        order = _frozen(order.astype(np.int32))
        with self._lock:
            order = self._orders.setdefault(key, order)
            self._orders.move_to_end(key)
            while len(self._orders) > ORDERS_KEPT:
                self._orders.popitem(last=False)
        return order

    def restricted(
        self, table: pa.Table, column: str, population: np.ndarray, values: np.ndarray
    ) -> np.ndarray:
        """`query._by_value(values)` for `values = column[population]` (`population` the
        increasing rows of one filter): the defined values' indices in `values`, ascending by
        value, from the frame's ascending order instead of a sort of the population."""
        order = self.order(column, False, table)
        inside = np.zeros(self.rows, dtype=bool)
        inside[population] = True
        rows = order[inside[order]]
        defined = int(np.isfinite(values).sum())  # defined values precede undefined ones
        rank = np.cumsum(inside, dtype=np.int64) - 1
        return rank[rows[:defined]]

    def nbytes(self, parameters: Sequence[ParameterInfo]) -> int:
        """The index's size once filled (the cache's size of it): each array it holds at its own
        size, the codes of a parameter it does not hold yet at the width they will take, and
        ORDERS_KEPT int32 orders."""
        size = self.completed.nbytes + ORDERS_KEPT * self.rows * np.dtype(np.int32).itemsize
        for parameter in parameters:
            held = self.codes.get(parameter.path)
            if held is not None:
                size += held.nbytes
            else:
                width = len(np.unique(np.asarray(parameter.values, dtype=np.float64)))
                size += self.rows * np.dtype(_code_dtype(width)).itemsize
        return size


def _code_dtype(width: int) -> type:
    """A lattice of `width` values codes as uint16 (its "off" code, `width`, included), as
    uint32 beyond."""
    return np.uint16 if width <= _UINT16_MAX else np.uint32


def _frozen(array: np.ndarray) -> np.ndarray:
    array.setflags(write=False)
    return array


def _lattice_codes(frame: TrialFrame, path: str) -> np.ndarray:
    """A parameter's lattice positions, the lattice's length off it: the frame's `pos.<k>` when
    it loaded them beside the parameter's values and they equal `_positions` on the first
    CHECKED_ROWS rows, else `_positions` over the whole column once. A layout-1 promotion or a
    surface edited after the trials were written can disagree with the stored positions."""
    table = frame.table
    axis = _axis(frame, path)
    width = len(axis)
    dtype = _code_dtype(width)
    k = next(i for i, parameter in enumerate(frame.parameters) if parameter.path == path)
    stored = f"pos.{k}"
    values = _numbers(table, path)
    if stored in table.column_names and table.column(stored).null_count == 0:
        positions = np.asarray(table.column(stored).to_numpy(), dtype=np.int64)
        head = min(len(values), CHECKED_ROWS)
        on_lattice = not len(positions) or int(positions.max()) < width
        if on_lattice and np.array_equal(positions[:head], _positions(values[:head], axis)):
            return positions.astype(dtype)
    codes = _positions(values, axis)
    codes[codes < 0] = width
    return codes.astype(dtype)


def build_index(frame: TrialFrame) -> FrameIndex:
    """The index of `frame`'s rows: the completed mask and the status tallies (the snapshot's
    `evaluations_done` when the frame carries it), and the codes of every parameter whose values
    the frame loaded (the others when a later frame brings them)."""
    table = frame.table
    completed, tallies = frame_tallies(frame)
    index = FrameIndex(completed=_frozen(completed), tallies=tallies, codes={})
    names = set(table.column_names)
    for parameter in frame.parameters:
        if parameter.path in names:
            index.codes_for(frame, parameter.path)
    return index


__all__ = ["CHECKED_ROWS", "ORDERS_KEPT", "FrameIndex", "build_index"]
