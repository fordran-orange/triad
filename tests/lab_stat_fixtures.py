"""Optimization Lab v2, Phase 3: the importance tests' statistical fixtures (Tasks 4, 5, 7 and 8;
Ruling P6, decision 17).

`stat_frame` writes a seeded synthetic experiment whose metric is a known function of its inputs,
with `test_lab_query`'s vectorised writer pattern (whole columns, the layout-2 schema, absent
columns null). The generator constants below are fixed once, each with its reason, and never
tuned per assertion: a case that does not hold at them is a finding (R3.5), never hidden.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from dataclasses import replace

import numpy as np
import pyarrow as pa
from products.aegis import experiments as exp
from products.aegis.lab import identity
from products.aegis.lab import store as lab_store
from products.aegis.lab.query import ALL_BLOCKS, BLOCK0, METRIC_NAMES, TrialFrame
from products.aegis.pool import SCOPES
from test_lab_query import parameter_of

# --- the generator constants (decision 17) ----------------------------------------------------

# The noise σ. The §20 generators put coefficients of 2 to 3 on inputs normalised to [0, 1] and
# call the result strong; at σ = 0.5, 3·x₁ explains ≈ 79 % of the variance (S₁ = 0.964 / 1.214
# at 8 values) and 2·XOR 80 % (J = 1 / 1.25), so a strong effect is unambiguous while noise stays
# a fifth of the variance. At σ = 1, 3·x₁ explains 49 %, below case 8's "high" block share.
SIGMA = 0.5
# Values per parameter. Even, so the median split m = ½ of the XOR and parity generators halves
# the values exactly (cases 2, 3, 12); at most 8, so a validity constraint x₂ ≥ x₁ + 2 aliases
# above V = 0.3 (case 10: 10 values give 0.27); a pair's 64 cells hold ≈ 78 of 5,000 rows each
# (≥ PAIR_MIN_N) and each value 625 (≥ IMPORTANCE_MIN_PER_VALUE, n ≥ 30 × 8); the coarse q = 4
# bins then hold two values each, so the coarse grid is not the fine one.
VALUES = 8
# Case 11: sin(8π·x) vanishes on every grid point at 5 or 9 values; 17 = 16 + 1 values put grid
# points on its peaks (x = k / 16), while each coarse bin of about four values still cancels.
SINE_VALUES = 17
# Case 6, as §20 states it: a parameter of 40 values of which 8 are present.
SPARSE_VALUES = 40
SPARSE_PRESENT = 8
# Parameters: §20's experiments have 8 to 20; 8 is the default case, 20 the widest (case 7).
D = 8
D_WIDE = 20
# Rows: §20's 5,000 uniform rows (stat_frame's default), 20,000 for cases 1 and 13 (decision 20).
ROWS = 5_000
PROPOSAL_ROWS = 20_000

# The metrics `undefined` nulls: the ones a backtest can leave undefined (no losing trade, under a
# year, one trade). `net_pnl`, `max_drawdown`, `trade_count` and `exposure` stay defined (§7.3).
UNDEFINABLE = ("cagr", "mar", "profit_factor", "sharpe_trade")
# A validity rule is counted over the whole grid up to this many configurations; beyond, its
# valid share is estimated on VALID_SAMPLE seeded configurations (the space's `valid`).
ENUMERATE_MAX = 1 << 22
VALID_SAMPLE = 1 << 20
_CHUNK = 1 << 18
_PASS = {"uniform": "sample", "adaptive": "refine"}  # a pass of each sampling design (§7.3)

Generator = Callable[[np.ndarray], np.ndarray]
Draw = Callable[[np.random.Generator, int, list[int]], np.ndarray]


def zero(u: np.ndarray) -> np.ndarray:
    """No effect: the metric is noise alone."""
    return np.zeros(len(u))


def high(x: np.ndarray) -> np.ndarray:
    """`x > m`, m the median ½ of a normalised input."""
    return x > 0.5


def aliased_rows(rng: np.random.Generator, n: int, sizes: list[int]) -> np.ndarray:
    """Case 4: uniform rows with x₂ = x₁ plus a jitter of one value at most."""
    rows = rng.integers(0, sizes, size=(n, len(sizes)))
    rows[:, 1] = np.clip(rows[:, 0] + rng.integers(-1, 2, size=n), 0, sizes[1] - 1)
    return rows


def uneven_rows(rng: np.random.Generator, n: int, sizes: list[int]) -> np.ndarray:
    """Case 5: P(x₁ = v) ∝ v (v = 1..B₁, so every value is drawn), and x₃ follows x₁ within one
    value, so the (x₁, x₂) squares are really confounded by x₃."""
    rows = rng.integers(0, sizes, size=(n, len(sizes)))
    weight = np.arange(1, sizes[0] + 1, dtype=np.float64)
    rows[:, 0] = rng.choice(sizes[0], size=n, p=weight / weight.sum())
    rows[:, 2] = np.clip(rows[:, 0] + rng.integers(-1, 2, size=n), 0, sizes[2] - 1)
    return rows


def normalised(positions: np.ndarray, sizes: list[int]) -> np.ndarray:
    """Value indices as inputs in [0, 1]: index / (values - 1), 0 for a single value."""
    span = np.maximum(np.asarray(sizes, dtype=np.float64) - 1.0, 1.0)
    return positions / span


def paths_of(d: int) -> list[str]:
    """The parameters' paths: the first half long, the rest short, one indicator each."""
    return [f"{'long' if k < d // 2 else 'short'}_side.indicators.p{k}.length" for k in range(d)]


def _draw_rows(
    rng: np.random.Generator, n: int, sizes: list[int], draw: Draw | None, valid: Generator | None
) -> np.ndarray:
    """`n` configurations' value indices: uniform (or `draw`'s), keeping the valid ones only."""

    def candidates() -> np.ndarray:
        if draw is None:
            return rng.integers(0, sizes, size=(n, len(sizes)))
        return np.asarray(draw(rng, n, sizes), dtype=np.int64)

    if valid is None:
        return candidates()
    kept, held = [], 0
    for _ in range(1_000):
        batch = candidates()
        batch = batch[np.asarray(valid(normalised(batch, sizes)), dtype=bool)]
        kept.append(batch)
        held += len(batch)
        if held >= n:
            return np.concatenate(kept)[:n]
    raise ValueError("the validity rule keeps almost no configuration")


def _valid_cells(valid: Generator | None, sizes: list[int], seed: int) -> int:
    """The grid's valid configurations: counted over the whole grid up to ENUMERATE_MAX, else the
    valid share of VALID_SAMPLE seeded configurations times the space."""
    space = math.prod(sizes)
    if valid is None:
        return space
    if space <= ENUMERATE_MAX:
        count = 0
        for start in range(0, space, _CHUNK):
            index = np.arange(start, min(space, start + _CHUNK))
            positions = np.stack(np.unravel_index(index, sizes), axis=1)
            count += int(np.asarray(valid(normalised(positions, sizes)), dtype=bool).sum())
        return count
    rng = np.random.default_rng((seed, 1))
    sample = rng.integers(0, sizes, size=(VALID_SAMPLE, len(sizes)))
    share = float(np.asarray(valid(normalised(sample, sizes)), dtype=bool).mean())
    return round(space * share)


def _constant(word: str, total: int) -> pa.DictionaryArray:
    """A dictionary column (the schema's words) holding one word in every row."""
    return pa.DictionaryArray.from_arrays(
        pa.array(np.zeros(total, dtype=np.int32)), pa.array([word], pa.string())
    )


def stat_frame(
    *,
    d: int,
    values: int | list[int],
    n: int = ROWS,
    seed: int,
    y: Generator,
    blocks: dict[int, Generator] | None = None,
    valid: Generator | None = None,
    design: str = "uniform",
    undefined: Generator | None = None,
    draw: Draw | None = None,
) -> TrialFrame:
    """A seeded synthetic experiment of `n` configurations over `d` parameters of `values` values
    each (one count for all, or one per parameter; lattice 1..B), every evaluation `ok`.

    - Its metric is `y(u) + ε`, `u` the configurations' value-normalised inputs (n × d, [0, 1])
      and ε ~ N(0, SIGMA²) the rng's noise, written in every `<scope>.<metric>` column.
    - `blocks` maps each screening block 1..K to its own generator, with its own noise, in rows
      beside block 0's (canonical order: by trial number, then block); the frame then holds every
      block (`ALL_BLOCKS`). Without blocks it is a K = 0 block-0 frame.
    - `valid(u)` keeps the valid configurations: invalid cells are never drawn and leave the space
      as `space - valid` (`_valid_cells`).
    - `undefined(u)` nulls the UNDEFINABLE metrics of those configurations, in every block.
    - `design` labels every row `uniform` (pass `sample`) or `adaptive` (pass `refine`).
    - `draw(rng, n, sizes)` replaces the uniform draw of value indices (cases 4 and 5): an
      addition to the brief's signature, which has no way to draw dependent inputs.
    """
    sizes = [int(values)] * d if isinstance(values, int) else [int(v) for v in values]
    if len(sizes) != d:
        raise ValueError(f"{len(sizes)} value counts for {d} parameters")
    if design not in _PASS:
        raise ValueError(f"unknown design {design!r}")
    blocks = dict(blocks or {})
    if sorted(blocks) != list(range(1, len(blocks) + 1)):
        raise ValueError(f"blocks must be numbered 1..K, not {sorted(blocks)}")
    rng = np.random.default_rng(seed)
    positions = _draw_rows(rng, n, sizes, draw, valid)
    u = normalised(positions, sizes)
    k = len(blocks)
    metric = np.empty((n, k + 1))
    metric[:, 0] = np.asarray(y(u), dtype=np.float64) + rng.normal(0.0, SIGMA, size=n)
    for b in range(1, k + 1):
        metric[:, b] = np.asarray(blocks[b](u), dtype=np.float64) + rng.normal(0.0, SIGMA, size=n)
    nulled = np.zeros(n, dtype=bool)
    if undefined is not None:
        nulled = np.asarray(undefined(u), dtype=bool)

    paths = paths_of(d)
    lattices = [1.0 + np.arange(size, dtype=np.float64) for size in sizes]
    each = k + 1
    total = n * each
    trial_no = np.repeat(np.arange(n, dtype=np.int64), each)
    rows = np.repeat(positions, each, axis=0)
    label = _PASS[design]
    columns: dict[str, pa.Array] = {
        "trial_no": pa.array(trial_no, pa.int64()),
        "cell": pa.array(trial_no, pa.int64()),
    }
    for j in range(d):
        columns[f"pos.{j}"] = pa.array(rows[:, j].astype(np.uint16), pa.uint16())
    for j, path in enumerate(paths):
        columns[path] = pa.array(lattices[j][rows[:, j]], pa.float64())
    keys = [hashlib.blake2b(row.tobytes(), digest_size=16).digest() for row in positions]
    columns["param_key"] = pa.array([key for key in keys for _ in range(each)], pa.binary(16))
    columns["pass"] = _constant(label, total)
    columns["design"] = _constant(identity.design_of(label), total)
    columns["block"] = pa.array(np.tile(np.arange(each, dtype=np.uint8), n), pa.uint8())
    columns["status"] = _constant("ok", total)
    columns["valid"] = pa.array(np.ones(total, dtype=bool), pa.bool_())
    columns["attempt"] = pa.array(np.zeros(total, dtype=np.uint8), pa.uint8())
    flat = metric.ravel()
    mask = np.repeat(nulled, each)
    for scope in SCOPES:
        for name in METRIC_NAMES:
            columns[f"{scope}.{name}"] = pa.array(
                flat, pa.float64(), mask=mask if name in UNDEFINABLE else None
            )
    schema = exp._cells_schema_v2(paths)
    table = pa.table(
        [columns.get(field.name, pa.nulls(total, field.type)) for field in schema], schema=schema
    )
    space = math.prod(sizes)
    return TrialFrame(
        source=f"exp:stat-{seed}",
        table=table,
        parameters=[parameter_of(path, lattices[j]) for j, path in enumerate(paths)],
        space=space,
        valid=_valid_cells(valid, sizes, seed),
        budget_total=n,
        scheduled=n,
        reserved=0,
        reused=0,
        duplicates=0,
        snapshot=lab_store.Snapshot(0, 0),
        provisional=False,
        layout=2,
        objective="net_pnl",
        blocks=k,
        selection=ALL_BLOCKS if k else BLOCK0,
    )


def stack_frames(first: TrialFrame, *others: TrialFrame) -> TrialFrame:
    """`first` with the other frames' rows after its own, their trial numbers continuing its own
    (the frames share their parameters and blocks): one experiment of several passes."""
    tables = [first.table]
    offset = int(first.table.column("trial_no").to_numpy().max()) + 1
    scheduled = first.scheduled
    for frame in others:
        if [p.path for p in frame.parameters] != [p.path for p in first.parameters]:
            raise ValueError("stacked frames must share their parameters")
        trial = frame.table.column("trial_no").to_numpy() + offset
        table = frame.table.set_column(
            frame.table.schema.get_field_index("trial_no"), "trial_no", pa.array(trial)
        )
        table = table.set_column(table.schema.get_field_index("cell"), "cell", pa.array(trial))
        tables.append(table)
        offset = int(trial.max()) + 1
        scheduled += frame.scheduled
    return replace(
        first,
        table=pa.concat_tables(tables),
        budget_total=scheduled,
        scheduled=scheduled,
    )
