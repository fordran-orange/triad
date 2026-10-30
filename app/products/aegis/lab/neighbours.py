"""Neighbourhoods by hashed positions (Optimization Lab v2 spec §7.6, Phase 3 Task 7; decision 9).

Pure: numpy over a block-0 `TrialFrame` and its `FrameIndex`, with no I/O and no lock.

- **The hash.** A row's position is its lattice codes, `index.codes_for` per parameter (`pos.<k>`
  on layout 2, value indices on a legacy or `opt:` source). `position_codes` folds them into one
  int64, `Σ code_k × multiplier_k` wrapping around, since a 20-parameter space does not fit a
  mixed-radix int64. A hit is checked against the codes themselves, so a collision can never
  count a wrong neighbour.
- **The lookup.** `position_table` sorts the hashes once per snapshot (held by the index). A
  neighbourhood is one `np.searchsorted` over its positions: at most 800 needles at d = 20,
  m = 2, r = 1 (`4·C(20, 2) + 2·20`, within §7.6's 840), whatever the number of trials.
- **Many at once.** Hashing is linear, so a move adds the same to any position's hash (`_Moves`):
  `p25_around` looks up every candidate's needles in that one pass, without a position matrix, by
  the same arithmetic as `around`, which is the same call with one candidate.
- **t is outside its own neighbourhood.** Every count and quartile is of its surroundings: an
  untested neighbourhood has coverage 0, and an isolated peak can be told at a corner.
- **`valid` is read from the frame**, never from the surface's constraint tables: the on-lattice
  positions, less the ones the pool refused (a row `invalid`); and once every scheduled cell of an
  exhaustive grid was attempted, less the ones without a row (its schedule is its valid cells). A
  sampled surface's constraint cells therefore count as valid and untested, which errs toward
  `unresolved`, never toward a false `stable` or `peak`. `VALID_BASIS` prints what it is.
- **Orientation.** Every value here is oriented so higher is better (`max_drawdown` negated, as
  `analysis.objective_values` does), and `orientation` says so.
- **A tested neighbour** holds a completed trial with a defined value of the metric; a completed
  one without is counted in `undefined`, and supports no claim.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import lru_cache
from itertools import combinations

import numpy as np
import pyarrow as pa

from products.aegis.lab.index import FrameIndex, build_index
from products.aegis.lab.policy import NEIGHBOUR_M_GRID, NEIGHBOUR_M_SAMPLED, NEIGHBOUR_R
from products.aegis.lab.query import (
    BLOCK0,
    LOWER_IS_BETTER,
    TrialFrame,
    _axis,
    _Groups,
    _numbers,
    _status_codes,
    _trial_numbers,
    metric_column,
)

HASH_SEED = 20261030  # the multipliers' seed: fixed, so a position's hash is the same everywhere
VALID_BASIS = "frame"  # `valid` comes from the frame alone (module docstring)
_INVALID = 1  # `query._status_codes`' code of a row the pool refused
_TABLE = "neighbours.positions"  # the position table's name in the index


def _multipliers(d: int) -> np.ndarray:
    """One odd 64-bit multiplier per parameter."""
    drawn = np.random.default_rng(HASH_SEED).integers(
        1, np.iinfo(np.int64).max, size=d, dtype=np.int64
    )
    return drawn | 1


def position_codes(frame: TrialFrame, index: FrameIndex) -> np.ndarray:
    """Each block-0 row's position hash (int64): equal positions hash alike."""
    out = np.zeros(index.rows, dtype=np.int64)
    multipliers = _multipliers(len(frame.parameters))
    for parameter, multiplier in zip(frame.parameters, multipliers, strict=True):
        out += index.codes_for(frame, parameter.path).astype(np.int64) * multiplier
    return out


@dataclass(frozen=True, eq=False)
class PositionTable:
    """Every row's hash, sorted, and the row each belongs to. At one position the completed rows
    come first, each group by row: the first hit is the tested one when there is one, and the
    canonical table's order makes it the lowest trial number."""

    hashes: np.ndarray
    rows: np.ndarray


def position_table(frame: TrialFrame, index: FrameIndex) -> PositionTable:
    """The snapshot's table, sorted once and held by its index."""

    def build() -> PositionTable:
        hashes = position_codes(frame, index)
        ordered = np.concatenate(
            (np.flatnonzero(index.completed), np.flatnonzero(~index.completed))
        )
        rows = ordered[np.argsort(hashes[ordered], kind="stable")]
        sorted_hashes, kept = hashes[rows], rows.astype(np.int32)
        sorted_hashes.setflags(write=False)
        kept.setflags(write=False)
        return PositionTable(sorted_hashes, kept)

    return index.derived(_TABLE, build)


@dataclass(frozen=True)
class Neighbourhood:
    """The tested trials around one trial (module docstring). `probes` is the hash lookups: the
    on-lattice positions within `r` steps in at most `m` parameters. `valid` is those the frame
    does not rule out; `tested` those holding a defined value; `coverage` is tested / valid, 0
    with nothing valid. `trials` and `values` are the tested ones by trial number; `p25`, `p75`
    and `iqr` their quartiles, None with none."""

    trial_no: int
    probes: int
    valid: int
    tested: int
    coverage: float
    trials: list[int]
    values: list[float]
    p25: float | None
    p75: float | None
    iqr: float | None
    r: int
    m: int
    undefined: int
    orientation: int
    valid_basis: str = VALID_BASIS

    def to_json(self) -> dict:
        return asdict(self)


def _exhaustive(frame: TrialFrame) -> bool:
    """Whether the frame's schedule covers every valid cell: an exhaustive grid."""
    return frame.valid > 0 and frame.scheduled >= frame.valid


@dataclass(frozen=True, eq=False)
class _Moves:
    """Every way to move from a position within `r` steps in 1 to `m` parameters, t's own excluded,
    before any lattice's bounds: each elementary step's parameter and signed reach, and the steps
    each move makes (`chosen`, moves x m, -1 past a move's last step)."""

    axes: np.ndarray
    deltas: np.ndarray
    chosen: np.ndarray

    def on_lattice(self, at: np.ndarray, widths: np.ndarray) -> np.ndarray:
        """Per position of `at` (positions x d), the moves that stay on the lattice (positions x
        moves). A value off the lattice takes no step along its axis."""
        code = at[:, self.axes]
        landed = code + self.deltas
        width = widths[self.axes]
        step_open = (code < width) & (landed >= 0) & (landed < width)
        # A -1 in `chosen` reads this last column, always open.
        step_open = np.concatenate((step_open, np.ones((len(at), 1), dtype=bool)), axis=1)
        allowed = step_open[:, self.chosen[:, 0]]
        for j in range(1, self.chosen.shape[1]):
            allowed &= step_open[:, self.chosen[:, j]]
        return allowed

    def shifts(self, multipliers: np.ndarray) -> np.ndarray:
        """What each move adds to a position's hash, wrapping around like the hash itself."""
        per_step = np.append(self.deltas * multipliers[self.axes], np.int64(0))
        return per_step[self.chosen].sum(axis=1, dtype=np.int64)

    def landing(self, at: np.ndarray, moves: np.ndarray) -> np.ndarray:
        """Where one move per row of `at` lands (rows x d)."""
        out = at.copy()
        rows = np.arange(len(out))
        for j in range(self.chosen.shape[1]):
            step = self.chosen[moves, j]
            real = step >= 0
            out[rows[real], self.axes[step[real]]] += self.deltas[step[real]]
        return out


@lru_cache(maxsize=16)
def _moves(d: int, r: int, m: int) -> _Moves:
    """The moves of a `d`-parameter space: a function of (d, r, m) alone, so kept per shape."""
    steps = [(k, step) for k in range(d) for reach in range(1, r + 1) for step in (-reach, reach)]
    axes = np.array([k for k, _ in steps], dtype=np.intp)
    deltas = np.array([step for _, step in steps], dtype=np.int64)
    parts = [np.empty((0, m), dtype=np.intp)]
    for count in range(1, m + 1):
        chosen = np.array(list(combinations(range(len(steps)), count)), dtype=np.intp)
        if not len(chosen):  # more parameters than steps to take
            break
        # `steps` runs by axis, so two steps along one axis are adjacent in a sorted choice
        chosen = chosen[(np.diff(axes[chosen], axis=1) != 0).all(axis=1)]
        padding = np.full((len(chosen), m - count), -1, dtype=np.intp)
        parts.append(np.hstack((chosen, padding)))
    moves = _Moves(axes, deltas, np.concatenate(parts))
    for held in (moves.axes, moves.deltas, moves.chosen):
        held.setflags(write=False)  # shared by every lookup of this shape
    return moves


def default_m(frame: TrialFrame) -> int:
    """How many parameters a neighbour may differ in: §7.6's m by the frame's design."""
    return NEIGHBOUR_M_GRID if _exhaustive(frame) else NEIGHBOUR_M_SAMPLED


class PositionLookup:
    """What every neighbourhood of one frame, metric and scope reads, so a ranking of k candidates
    derives it once: the codes, the table, the oriented values and the trial numbers."""

    def __init__(
        self,
        frame: TrialFrame,
        *,
        metric: str | None = None,
        scope: str = "combined",
        index: FrameIndex | None = None,
    ) -> None:
        if frame.selection != BLOCK0:
            raise ValueError(
                f"a neighbourhood reads block-0 frames only, not a {frame.selection!r} frame"
            )
        self.frame = frame
        self.index = build_index(frame) if index is None else index
        self.metric = metric or frame.objective
        self.scope = scope
        self.orientation = -1 if self.metric in LOWER_IS_BETTER else 1
        column = _numbers(frame.table, metric_column(scope, self.metric))
        self.values = -column if self.orientation < 0 else column
        self.trial_numbers = _trial_numbers(frame.table)
        self.paths = [parameter.path for parameter in frame.parameters]
        self.widths = np.array([len(_axis(frame, path)) for path in self.paths], dtype=np.int64)
        self.multipliers = _multipliers(len(self.paths))
        self.codes = [self.index.codes_for(frame, path) for path in self.paths]
        self.table = position_table(frame, self.index)
        # Every scheduled cell attempted: an exhaustive grid's absent position is a skipped one.
        self.all_attempted = (
            _exhaustive(frame) and self.index.tallies["attempted"] >= frame.scheduled
        )
        self.default_m = default_m(frame)

    def row_of(self, trial_no: int) -> int:
        """The completed row of a trial: KeyError for a trial the frame has no row of, ValueError
        for one that did not complete (a candidate is a tested trial, §7.6)."""
        found = np.flatnonzero(self.trial_numbers == trial_no)
        if not len(found):
            raise KeyError(f"{self.frame.source} has no trial {trial_no}")
        row = int(found[0])
        if not self.index.completed[row]:
            raise ValueError(f"trial {trial_no} of {self.frame.source} is not a completed trial")
        return row

    def _held(self, rows: np.ndarray) -> np.ndarray:
        """The codes (rows x d) of `rows`, read at those rows alone."""
        held = np.empty((len(rows), len(self.codes)), dtype=np.int64)
        for k, code in enumerate(self.codes):
            held[:, k] = code[rows]
        return held

    def _probe(self, needles: np.ndarray, landed: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
        """Each needle's row, -1 for one without: one `np.searchsorted` over every needle, each hit
        checked against the codes of its position (`landed(hits)`, built for the hits alone), and a
        collision walked past."""
        hashes = self.table.hashes
        at = np.searchsorted(hashes, needles)
        rows = np.full(len(needles), -1, dtype=np.int64)
        inside = np.flatnonzero(at < len(hashes))
        hit = inside[hashes[at[inside]] == needles[inside]]
        if not len(hit):
            return rows
        found = self.table.rows[at[hit]].astype(np.int64)
        positions = landed(hit)
        agrees = (self._held(found) == positions).all(axis=1)
        rows[hit[agrees]] = found[agrees]
        for k in np.flatnonzero(~agrees).tolist():  # a collision, which the multipliers make rare
            probe = hit[k]
            rows[probe] = self._walk(int(at[probe]) + 1, int(needles[probe]), positions[k])
        return rows

    def _probe_around(self, rows: np.ndarray, r: int, m: int) -> tuple[np.ndarray, np.ndarray]:
        """Every candidate's on-lattice positions looked up in one pass: per probe, the place in
        `rows` of the candidate it belongs to and the row found there, -1 for none."""
        moves = _moves(len(self.codes), r, m)
        at = self._held(rows)
        owner, move = np.nonzero(moves.on_lattice(at, self.widths))
        base = (at * self.multipliers).sum(axis=1, dtype=np.int64)
        needles = base[owner] + moves.shifts(self.multipliers)[move]
        return owner, self._probe(needles, lambda hit: moves.landing(at[owner[hit]], move[hit]))

    def _reach(self, r: int, m: int | None) -> tuple[int, int]:
        if r < 1:
            raise ValueError(f"r must be at least 1, not {r}")
        m = self.default_m if m is None else m
        if m < 1:
            raise ValueError(f"m must be at least 1, not {m}")
        return r, m

    def _walk(self, start: int, needle: int, position: np.ndarray) -> int:
        """The first row at `position` among the equal hashes from `start`, -1 when none is."""
        hashes, rows = self.table.hashes, self.table.rows
        for at in range(start, len(hashes)):
            if hashes[at] != needle:
                break
            row = int(rows[at])
            held = zip(self.codes, position.tolist(), strict=True)
            if all(int(code[row]) == expected for code, expected in held):
                return row
        return -1

    def _refused(self, rows: np.ndarray) -> int:
        """How many of these rows, none of them completed, the pool refused as invalid."""
        if not len(rows):
            return 0
        taken = self.frame.table.select(["status"]).take(pa.array(rows, pa.int64()))
        return int((_status_codes(taken) == _INVALID).sum())

    def around(self, row: int, *, r: int = NEIGHBOUR_R, m: int | None = None) -> Neighbourhood:
        """The neighbourhood of the trial at `row` (`row_of`)."""
        r, m = self._reach(r, m)
        _, rows = self._probe_around(np.array([row], dtype=np.int64), r, m)
        held = rows[rows >= 0]
        completed = self.index.completed[held]
        probes = len(rows)
        refused = self._refused(held[~completed])
        absent = int((rows < 0).sum())
        valid = probes - refused - (absent if self.all_attempted else 0)
        tested_rows = np.sort(held[completed])
        values = self.values[tested_rows]
        defined = np.isfinite(values)
        tested_rows, values = tested_rows[defined], values[defined]
        tested = len(values)
        p25 = p75 = iqr = None
        if tested:
            low, high = np.percentile(values, [25, 75])
            p25, p75, iqr = float(low), float(high), float(high - low)
        order = np.argsort(self.trial_numbers[tested_rows], kind="stable")
        return Neighbourhood(
            trial_no=int(self.trial_numbers[row]),
            probes=probes,
            valid=valid,
            tested=tested,
            coverage=tested / valid if valid else 0.0,
            trials=self.trial_numbers[tested_rows][order].tolist(),
            values=values[order].tolist(),
            p25=p25,
            p75=p75,
            iqr=iqr,
            r=r,
            m=m,
            undefined=int((~defined).sum()),
            orientation=self.orientation,
        )

    def p25_around(
        self, rows: np.ndarray, *, r: int = NEIGHBOUR_R, m: int | None = None
    ) -> np.ndarray:
        """`around(row).p25` per row, NaN for a row with no tested neighbour: every candidate's
        positions in one lookup and every quartile in one grouping, so n candidates pay for their
        probes and never for n calls."""
        r, m = self._reach(r, m)
        owner, found = self._probe_around(rows, r, m)
        present = found >= 0
        owner, found = owner[present], found[present]
        tested = self.index.completed[found]
        return _Groups(owner[tested], self.values[found[tested]], len(rows)).quantile(0.25)

    def value_at(self, row: int) -> float | None:
        """The oriented value of a row, None where undefined."""
        value = float(self.values[row])
        return value if math.isfinite(value) else None


def neighbourhood(
    frame: TrialFrame,
    trial_no: int,
    *,
    r: int = NEIGHBOUR_R,
    m: int | None = None,
    metric: str | None = None,
    scope: str = "combined",
    index: FrameIndex | None = None,
) -> Neighbourhood:
    """The tested trials within `r` steps in at most `m` parameters of a completed trial (module
    docstring). `m` defaults to NEIGHBOUR_M_GRID on an exhaustive grid and NEIGHBOUR_M_SAMPLED
    otherwise, `metric` to the frame's objective; without the snapshot's `index` one is built."""
    lookup = PositionLookup(frame, metric=metric, scope=scope, index=index)
    return lookup.around(lookup.row_of(trial_no), r=r, m=m)


__all__ = [
    "VALID_BASIS",
    "Neighbourhood",
    "PositionLookup",
    "PositionTable",
    "default_m",
    "neighbourhood",
    "position_codes",
    "position_table",
]
