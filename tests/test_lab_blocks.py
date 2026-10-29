"""Optimization Lab v2, Phase 3 (spec §7.3a): a screening block is scored on the frame with its
prior history but evaluated only from the block's start. `run_metrics(..., evaluate_from=)`
builds the kernel's `evaluating` mask exactly as the full engine does for a walk-forward window
(`settings.evaluate_from`), so a block row's metrics equal `run_backtest`'s; with
`evaluate_from=None` the metrics path is byte-identical to before.

Task 2: an experiment with `blocks = K` scores each configuration on the whole range (block 0)
and on K contiguous blocks, in the pool, the job, the planner and the readers; every ordinary
reader sees block 0 only, and the Lab's scope counts every block's evaluations."""

import json
import time
from collections import defaultdict
from datetime import timedelta
from itertools import pairwise

import numpy as np
import pytest
from products.aegis import experiments as exp
from products.aegis import kernel
from products.aegis.backtest import (
    BacktestRequest,
    BacktestSettings,
    _data_key,
    _side_metrics,
    frame_slice,
    prepared_request,
    run_backtest,
    run_metrics,
)
from products.aegis.experiments import block_bounds
from products.aegis.indicators import IndicatorCache
from products.aegis.jobs import JobRunner
from products.aegis.kinds import warmup
from products.aegis.lab import identity, policy, sources
from products.aegis.lab import store as lab_store
from products.aegis.lab.cache import LabCache
from products.aegis.lab.query import LabFilter, _status_tallies, scope_counts
from products.aegis.lab.sharpe import sharpe_scopes
from products.aegis.pool import METRICS, SCOPES, Pool, pool_frame, resample_curve
from products.aegis.surface import (
    Parameter,
    Surface,
    apply_params,
    configuration_bars,
    effective_workers,
    held_bars,
)
from test_aegis_api import RANGE, _experiment_body
from test_aegis_data import write_archive
from test_aegis_experiments import (  # noqa: F401 - `world` is the shared experiments fixture
    PINNED_DATA,
    document_of,
    request,
    start,
    surface12,
    wait_for,
    world,
)
from test_aegis_lab_api import (  # noqa: F401 - `client` and `lab_cache` are the Lab fixtures
    LAB,
    _finished_experiment,
    _open,
    client,
    lab_cache,
)
from test_aegis_pool import ROWS, cells, pinned
from test_lab_store import NOW, layout2_dir, trial_row, write_trials

pytestmark = pytest.mark.aegis

START = 130  # a block start: 130 bars of prior history before it
AT = ROWS[START]["timestamp"]
# The same bars three days apart: the evaluated span from bar 130 passes a year (387 days), so
# each side's `cagr` and `mar` are defined and read the first and last evaluated bars.
YEARS = [
    {**row, "timestamp": ROWS[0]["timestamp"] + timedelta(days=3 * i)} for i, row in enumerate(ROWS)
]
TOLERANCE = 1e-12


def held(rows):
    """The frame, data key and indicator cache a pool worker holds (`pool._init_worker`)."""
    frame = pool_frame(rows, "QQQ")
    return frame, _data_key(frame), IndicatorCache()


@pytest.fixture(params=["kernel", "reference"])
def engine(request, monkeypatch):
    """`kernel`: the metrics path's compiled loop; `reference`: its fallback when numba is
    absent (`run_prepared` on the reference engine)."""
    if request.param == "reference":
        monkeypatch.setattr(kernel, "AVAILABLE", False)
        monkeypatch.setattr(kernel, "IMPORT_ERROR", "ModuleNotFoundError")
    return request.param


def same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= TOLERANCE


def full_run(spec, rows, engine: str, evaluate_from=None) -> dict:
    settings = BacktestSettings(evaluate_from=evaluate_from)
    return run_backtest(BacktestRequest(strategy=spec, bars=rows, settings=settings, engine=engine))


@pytest.mark.parametrize("rows", [ROWS, YEARS], ids=["30m", "3d"])
def test_block_metrics_equal_full_engine_with_evaluate_from(engine, rows):
    frame, key, cache = held(rows)
    at = rows[START]["timestamp"]
    for _, params in cells(4):
        spec = apply_params(pinned(), params)
        prepared = prepared_request(spec, BacktestSettings(), engine)
        block = run_metrics(prepared, frame, key, cache, False, True, evaluate_from=at)
        full = full_run(spec, rows, engine, evaluate_from=at)
        assert block["engine"] == full["engine"] == engine
        for scope in SCOPES:
            for metric in METRICS:
                assert same(block[scope][metric], full[scope]["metrics"][metric]), (
                    params,
                    scope,
                    metric,
                )
        expected = sharpe_scopes(
            np.array([t["return"] for t in full["long"]["trades"]], dtype=np.float64),
            np.array([t["return"] for t in full["short"]["trades"]], dtype=np.float64),
        )
        for scope in SCOPES:
            got, want = block["lab_metrics"][scope], expected[scope]
            assert got["trade_count"] == want["trade_count"] >= 2, (params, scope)
            assert got["low_n"] == want["low_n"], (params, scope)
            assert same(got["sharpe_trade"], want["sharpe_trade"]), (params, scope)
        # The block is not the whole range: the warm-up held trades that the block drops.
        whole = full_run(spec, rows, engine)
        assert whole["combined"]["metrics"]["trade_count"] > block["combined"]["trade_count"]
        assert block["first_time"] == at.isoformat()
        assert block["last_time"] == rows[-1]["timestamp"].isoformat()
        if rows is YEARS:
            assert block["long"]["cagr"] is not None and block["long"]["mar"] is not None


def test_warmup_contributes_no_trades_or_equity(engine):
    frame, key, cache = held(ROWS)
    evaluated_bars = sum(1 for row in ROWS if row["timestamp"] >= AT)
    for _, params in cells(4):
        spec = apply_params(pinned(), params)
        prepared = prepared_request(spec, BacktestSettings(), engine)
        block = run_metrics(prepared, frame, key, cache, True, False, evaluate_from=AT)
        assert block["first_time"] == AT.isoformat()
        full = full_run(spec, ROWS, engine, evaluate_from=AT)
        for side in ("long", "short", "combined"):
            assert all(t["entry_time"] >= AT.isoformat() for t in full[side]["trades"]), side
            assert all(p["timestamp"] >= AT.isoformat() for p in full[side]["equity"]), side
        # The metrics path's curve is exactly the block's equity: no point from the warm-up.
        assert block["curve"] == [float(p["equity"]) for p in full["combined"]["equity"]]
        assert len(block["curve"]) == block["combined"]["trade_count"]
        if engine == "kernel":
            for side in ("LONG", "SHORT"):
                trades, _, flags, returns = _side_metrics(
                    frame, spec, side, BacktestSettings(), cache, key, evaluate_from=AT
                )
                assert all(t["exit_time"] >= AT.isoformat() for t in trades), side
                assert len(flags) == evaluated_bars, side  # one equity point per evaluated bar
                assert len(returns) == len(trades), side


@pytest.mark.parametrize("want_curve", [False, True])
def test_evaluate_from_none_is_byte_identical(engine, want_curve):
    # Cannot fail by construction: the engine golden and the identity scripts guard the None path.
    frame, key, cache = held(ROWS)
    for _, params in cells(2):
        prepared = prepared_request(apply_params(pinned(), params), BacktestSettings(), engine)
        plain = run_metrics(prepared, frame, key, cache, want_curve, True)
        unset = run_metrics(prepared, frame, key, cache, want_curve, True, evaluate_from=None)
        assert json.dumps(unset, sort_keys=True) == json.dumps(plain, sort_keys=True)
        assert plain["first_time"] == ROWS[0]["timestamp"].isoformat()
        assert plain["last_time"] == ROWS[-1]["timestamp"].isoformat()


def test_run_metrics_refuses_a_naive_evaluate_from(engine):
    """The keyword meets the settings' own rule (`BacktestSettings.aware`): a naive datetime is a
    ValueError, which the pool turns into an invalid row, never a pandas TypeError."""
    frame, key, cache = held(ROWS)
    prepared = prepared_request(apply_params(pinned(), cells(1)[0][1]), BacktestSettings(), engine)
    with pytest.raises(ValueError, match="^evaluate_from must be timezone-aware$"):
        run_metrics(prepared, frame, key, cache, evaluate_from=AT.replace(tzinfo=None))


# --- Task 2: screening blocks in the pool, the job, the planner and the readers --------------

DONCHIAN = "long_side.indicators.donchian.length"
POOL_SETTINGS = {"initial_capital": 100_000, "allocation_fraction": 1}
# The Lab fixture archive's two sessions at 1m: 780 bars, 195 to a block at K = 4.
ONE_MINUTE = {"symbol": "QQQ", "timeframe": "1m", **RANGE}
IDENTITY_DATA = {
    "symbol": "QQQ",
    "sha256": "a" * 64,
    "data_hash": "d" * 64,
    "timeframe": "1D",
    "start": "2020-01-02",
    "end": "2024-12-31",
}


def finished(repository, library, document, **overrides) -> exp.ExperimentDocument:
    """One experiment (the 12-cell surface unless overridden) run to `done` by the job."""
    _runner, _job, _job_id, experiment_id = start(repository, library, document, **overrides)
    assert wait_for(lambda: document_of(repository, experiment_id).status in ("done", "failed"))
    done = document_of(repository, experiment_id)
    assert done.status == "done", done.error
    return done


def lab_scope(document, store) -> dict:
    """The unfiltered §6.4 scope of the document's latest snapshot, as the Lab reads it."""
    frame, handle = sources.open_experiment(document, store, LabCache(), sources.BASE)
    try:
        return scope_counts(frame, LabFilter())
    finally:
        lab_store.REGISTRY.release(handle)


def test_block_bounds_are_contiguous_and_cover_the_range():
    assert block_bounds(260, 4) == [(0, 65), (65, 130), (130, 195), (195, 260)]
    assert block_bounds(263, 4)[-1] == (195, 263)
    assert block_bounds(260, 0) == []
    for n in (70, 260, 263, 1001):
        for k in range(2, policy.MAX_BLOCKS + 1):
            bounds = block_bounds(n, k)
            assert len(bounds) == k and bounds[0][0] == 0 and bounds[-1][1] == n
            assert all(left[1] == right[0] for left, right in pairwise(bounds))
            assert {end - start for start, end in bounds[:-1]} == {n // k}
            assert bounds[-1][1] - bounds[-1][0] == n - (k - 1) * (n // k)


def test_pool_returns_one_row_per_block():
    bounds = block_bounds(len(ROWS), 4)
    chunk = cells(3)
    pool = Pool(max_workers=2)
    pool.start(ROWS, "QQQ", pinned().model_dump(mode="json"), POOL_SETTINGS)
    try:
        rows = pool.run_chunk(chunk, want_curve=True, blocks=bounds)
        bars_counted = pool._cell_bars_total
    finally:
        pool.shutdown()
    assert [(row["cell"], row["block"]) for row in rows] == [
        (cell, block) for cell in range(3) for block in range(5)
    ]
    assert all(row["valid"] for row in rows)
    # Each evaluation's own bars: the whole range for block 0, the prefix to its end for block b.
    assert bars_counted == 3 * (len(ROWS) + sum(end for _, end in bounds))
    frame, key, cache = held(ROWS)
    params_of = dict(chunk)
    for row in rows:
        assert row["params"] == params_of[row["cell"]]
        prepared = prepared_request(apply_params(pinned(), row["params"]), BacktestSettings())
        if row["block"] == 0:
            expected = run_metrics(prepared, frame, key, cache, True, True)
            assert row["curve"] == resample_curve(expected["curve"])
        else:
            begin, end = bounds[row["block"] - 1]
            part = frame_slice(frame, 0, end)
            at = part["timestamp"].iloc[begin]
            expected = run_metrics(
                prepared, part, _data_key(part), cache, False, True, evaluate_from=at
            )
            assert row["curve"] is None and row["first_time"] == at.isoformat()
        for scope in SCOPES:
            assert row["metrics"][scope] == expected[scope], (row["cell"], row["block"], scope)
        assert row["lab_metrics"] == expected["lab_metrics"]
        assert (row["first_time"], row["last_time"]) == (
            expected["first_time"],
            expected["last_time"],
        )
    # Not vacuous: the last block scores fewer trades than the whole range does.
    for cell in range(3):
        whole, last = rows[5 * cell], rows[5 * cell + 4]
        assert (
            last["metrics"]["combined"]["trade_count"] < whole["metrics"]["combined"]["trade_count"]
        )


def test_worker_holds_one_prefix_frame_per_block_end():
    """In the worker: one prepared prefix frame per block end (the last block's is the whole range
    itself), at most MAX_BLOCKS + 1 of them, and the indicator cache sized by every frame held."""
    from products.aegis import pool as worker

    worker._init_worker([dict(r) for r in ROWS], "QQQ", pinned().model_dump(mode="json"), {})
    bounds = block_bounds(len(ROWS), 4)
    index, params = cells(1)[0]
    for block, (begin, end) in enumerate(bounds, start=1):
        row = worker._run_cell(index, params, False, block=(block, begin, end))
        assert row["block"] == block and row["valid"] and row["curve"] is None, row
    held_frames = worker._BLOCK_FRAMES
    assert sorted(held_frames) == [65, 130, 195, 260]
    assert held_frames[260][0] is worker._FRAME and held_frames[260][1] == worker._DATA_KEY
    assert [len(held_frames[end][0]) for end in (65, 130, 195)] == [65, 130, 195]
    per_bar = worker.POOL_CACHE_BYTES_PER_BAR
    assert worker._CACHE.max_bytes == per_bar * (260 + 65 + 130 + 195)
    # A prefix shorter than the engine's minimum is an invalid row, never an exception.
    short = worker._run_cell(index, params, False, block=(1, 0, 20))
    assert short["valid"] is False and short["skip_reason"] == "insufficient bars", short
    # Bounded: never more than MAX_BLOCKS + 1 prefix frames.
    for end in range(40, 40 + 2 * policy.MAX_BLOCKS):
        worker._block_frame(end)
    assert len(worker._BLOCK_FRAMES) == policy.MAX_BLOCKS + 1
    kept = sum(len(f) for f, _ in worker._BLOCK_FRAMES.values() if f is not worker._FRAME)
    assert worker._CACHE.max_bytes == per_bar * (len(ROWS) + kept)
    plain = worker._run_cell(index, params, False)
    assert plain["block"] == 0 and plain["valid"]


def test_configuration_identity_across_blocks(world):  # noqa: F811
    repository, library, document = world
    store = exp.ExperimentStore(repository)
    paths = surface12().paths()
    done = finished(repository, library, document, blocks=4)
    assert done.blocks == 4 and done.plan["blocks"] == 4 and done.plan["evaluations"] == 60
    assert done.progress["cells_done"] == 12 and done.progress["cells_planned"] == 12
    counts = done.counts
    assert (counts["attempted"], counts["completed"], counts["scheduled"]) == (12, 12, 12)
    assert (counts["evaluations"], counts["evaluations_done"]) == (60, 60)
    rows = store.trials(done.id).table.to_pylist()
    by_trial = defaultdict(list)
    for row in rows:
        by_trial[row["trial_no"]].append(row)
    assert sorted(by_trial) == list(range(12)) and len(rows) == 60
    for trial_no, evaluations in by_trial.items():
        assert [row["block"] for row in evaluations] == [0, 1, 2, 3, 4], trial_no
        assert len({row["param_key"] for row in evaluations}) == 1, trial_no
        assert len({tuple(row[path] for path in paths) for row in evaluations}) == 1, trial_no
        assert len({row["cell"] for row in evaluations}) == 1, trial_no
        assert len({row["chunk"] for row in evaluations}) == 1, trial_no  # one file holds them
        assert {row["status"] for row in evaluations} == {"ok"}, trial_no
        whole, last = evaluations[0], evaluations[4]
        assert last["combined.trade_count"] < whole["combined.trade_count"], trial_no

    # Compaction: one canonical row per (trial_no, block), no copy.
    cells_dir = store.cells_dir(done.id)
    lab_store.compact(cells_dir, now=time.time())
    latest = lab_store.read_latest(cells_dir)
    assert len(latest.table) == 60 and latest.duplicates == 0

    # Materialization and every ordinary reader read block 0.
    block0 = {row["cell"]: row for row in rows if row["block"] == 0}
    envelope = exp.materialize(done, store, repository, ROWS, PINNED_DATA, 7)
    for scope in SCOPES:
        for metric in METRICS:
            ran = envelope["result"][scope]["metrics"][metric]
            assert exp._same(ran, block0[7][f"{scope}.{metric}"]), (scope, metric)
    assert store.row(done.id, 7)["combined.net_pnl"] == block0[7]["combined.net_pnl"]
    assert sorted(store.done_cells(done.id)) == list(range(12))

    scope = lab_scope(done, store)
    assert (scope["attempted"], scope["completed"], scope["pending"]) == (12, 12, 0)
    assert (scope["evaluations"], scope["evaluations_done"]) == (60, 60)
    assert scope["completed"] <= scope["evaluations_done"] <= scope["evaluations"]

    # Resume after a forced stop after one unit: only the missing configurations run again.
    gate = {"paused": False}

    def after_unit(units):
        if units == 1 and not gate["paused"]:
            gate["paused"] = True
            runner.cancel(job_id)

    runner = JobRunner(repository, after_unit=after_unit)
    created = exp.create(
        store, library, request(document, name="resumed", blocks=4), bars=len(ROWS), max_workers=2
    )
    job = exp.ExperimentJob(created, ROWS, PINNED_DATA, repository)
    job.pause_requested = True  # what POST /pause sets before cancelling
    job_id = runner.start(job)
    assert wait_for(lambda: document_of(repository, created.id).status == "paused")
    paused = document_of(repository, created.id)
    ran = paused.progress["cells_done"]
    assert ran in (5, 10) and paused.counts["evaluations_done"] == 5 * ran
    resumed = exp.ExperimentJob(paused, ROWS, PINNED_DATA, repository)
    assert resumed.cells_done == ran and sorted(resumed.pending_cells()) == list(range(ran, 12))
    JobRunner(repository).start(resumed)
    assert wait_for(lambda: document_of(repository, created.id).status in ("done", "failed"))
    again = document_of(repository, created.id)
    assert again.status == "done", again.error
    assert again.progress["cells_done"] == 12 and again.counts["evaluations_done"] == 60
    trials = lab_store.read_latest(store.cells_dir(created.id))
    assert len(trials.table) == 60 and trials.duplicates == 0
    evaluations = trials.table.select(["trial_no", "block"]).to_pylist()
    assert evaluations == [{"trial_no": t, "block": b} for t in range(12) for b in range(5)]


def test_canonical_attempt_after_retry_across_compacted_files(tmp_path):
    """§7.3a: (trial 7, block 2) failed at attempt 0 in a part, then ok at attempt 1 in a later
    chunk, with a copy of attempt 1 in a second chunk: one canonical ok evaluation, one copy
    collapsed, and the counts read it once."""
    first = [trial_row(7, block=block) for block in (0, 1, 3, 4)]
    first.append(trial_row(7, block=2, attempt=0, error="boom", metrics=None))
    cells_dir = layout2_dir(tmp_path, [first])
    manifest = lab_store.compact(cells_dir, now=NOW)
    retry = [trial_row(7, block=2, attempt=1)]
    index = lab_store.next_chunk_index(cells_dir, manifest)
    write_trials(cells_dir, index, retry)
    write_trials(cells_dir, index + 1, retry)  # a copy of attempt 1 under a second name
    expected = [
        {"trial_no": 7, "block": block, "attempt": int(block == 2), "status": "ok"}
        for block in range(5)
    ]
    for compacted in (False, True):
        if compacted:
            lab_store.compact(cells_dir, now=NOW + 1)  # both chunks into part-2
        trials = lab_store.read_latest(cells_dir)
        assert trials.duplicates == 1, compacted
        rows = trials.table.select(["trial_no", "block", "attempt", "status"]).to_pylist()
        assert rows == expected, compacted
        _, tallies = _status_tallies(trials.table)
        assert (tallies["attempted"], tallies["completed"], tallies["failed"]) == (1, 1, 0)
        assert tallies["evaluations_done"] == 5


def test_short_block_is_invalid_and_counted(world):  # noqa: F811
    """Review Focus 1: a Donchian longer than block 1's 65 bars but shorter than the range. Block
    1's evaluation is `invalid: insufficient bars`, block 0 decides the configuration (ok), and
    the counts carry both."""
    repository, library, document = world
    store = exp.ExperimentStore(repository)
    length = 100
    first_block = block_bounds(len(ROWS), 4)[0]
    assert first_block[1] - first_block[0] <= warmup("DONCHIAN", length) < 2 * first_block[1]
    surface = Surface(parameters=[Parameter(path=DONCHIAN, start=length, stop=length, step=1)])
    done = finished(
        repository, library, document, name="short block", surface=surface.model_dump(), blocks=4
    )
    rows = store.trials(done.id).table.to_pylist()
    assert [row["block"] for row in rows] == [0, 1, 2, 3, 4]
    by_block = {row["block"]: row for row in rows}
    assert by_block[0]["status"] == "ok"
    assert by_block[1]["status"] == "invalid" and by_block[1]["valid"] is False
    assert by_block[1]["skip_reason"].startswith("insufficient bars"), by_block[1]
    assert by_block[1]["combined.net_pnl"] is None
    assert [by_block[block]["status"] for block in (2, 3, 4)] == ["ok", "ok", "ok"]
    scope = lab_scope(done, store)
    assert (scope["attempted"], scope["completed"], scope["invalid"]) == (1, 1, 0)
    assert (scope["evaluations"], scope["evaluations_done"]) == (5, 4)
    assert done.progress["cells_done"] == 1
    assert (done.counts["completed"], done.counts["evaluations_done"]) == (1, 4)
    assert len(store.cells(done.id)) == 1 and store.row(done.id, 0)["valid"] is True


def test_blocks_must_be_zero_or_two_to_eight(client, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    c, _, _ = client
    # 200 one-minute bars: 100 a session over the fixture's two sessions.
    write_archive(tmp_path, "20260301T000000000000Z", "SPY", price=400.0, missing=290)
    url = "/aegis/api/experiments/plan"
    for blocks in (1, 9):
        refused = c.post(url, json=_experiment_body(c, blocks=blocks))
        assert refused.status_code == 422, (blocks, refused.text)
        assert "blocks" in refused.text, refused.text
    two_hundred = {"symbol": "SPY", "timeframe": "1m", **RANGE}
    message = "blocks: 8 blocks of 200 bars leave 25 per block, under the 35-bar minimum"
    refused = c.post(url, json=_experiment_body(c, data=two_hundred, blocks=8))
    assert refused.status_code == 422 and refused.json() == {"detail": message}, refused.text
    body = _experiment_body(c, data=two_hundred, blocks=8)
    created = c.post("/aegis/api/experiments", json=body)
    assert created.status_code == 422 and created.json() == {"detail": message}, created.text
    accepted = c.post(url, json=_experiment_body(c, data=two_hundred, blocks=4))
    assert accepted.status_code == 200, accepted.text
    planned = accepted.json()
    assert planned["bars"] == 200 and planned["blocks"] == 4
    assert planned["evaluations"] == planned["planned_runs"] * 5
    plain = c.post(url, json=_experiment_body(c)).json()
    assert plain["blocks"] == 0 and plain["evaluations"] == plain["planned_runs"]


def test_measured_rate_counts_each_evaluations_bars(world):  # noqa: F811
    """Review B7: the persisted cost per cell-bar divides the evaluations' time by each
    evaluation's own bars, the whole range for block 0 and the bars up to its end for block b:
    exactly the sum of the rows' `elapsed_ms` over the sum of their bars, for a blocked run as for
    an unblocked one. Counting the whole range for every block row would make it ~30 % low at
    K = 4. (A blocked run's rate is not within 10 % of an unblocked one's on this laptop's wall
    clock: the engine's per-evaluation cost is not proportional to bars; see the Task 2 report.)"""
    repository, library, document = world
    store = exp.ExperimentStore(repository)
    for blocks in (0, 4):
        done = finished(repository, library, document, name=f"rate {blocks}", blocks=blocks)
        table = store.trials(done.id, ["valid", "elapsed_ms"]).table
        own_bars = [len(ROWS)] + [end for _, end in block_bounds(len(ROWS), blocks)]
        counted = [
            (ms, own_bars[block])
            for block, ms, valid in zip(
                table.column("block").to_pylist(),
                table.column("elapsed_ms").to_pylist(),
                table.column("valid").to_pylist(),
                strict=True,
            )
            if valid
        ]
        assert len(counted) == 12 * (blocks + 1)
        bars = sum(bar for _, bar in counted)
        assert bars == 12 * sum(own_bars)  # 12 x 910 at K = 4, never 12 x 5 x 260
        expected = sum(ms for ms, _ in counted) / bars
        assert done.ms_per_cell_bar == pytest.approx(expected, rel=1e-9), blocks


def test_inputs_key_changes_with_blocks(world):  # noqa: F811
    settings = {"initial_capital": 100_000.0, "allocation_fraction": 1.0}
    base = identity.inputs_key("s" * 64, IDENTITY_DATA, settings, "b" * 64)
    assert identity.inputs_key("s" * 64, IDENTITY_DATA, settings, "b" * 64, blocks=0) == base
    four = identity.inputs_key("s" * 64, IDENTITY_DATA, settings, "b" * 64, blocks=4)
    eight = identity.inputs_key("s" * 64, IDENTITY_DATA, settings, "b" * 64, blocks=8)
    assert len({base, four, eight}) == 3
    # An experiment's trial identity and its sampler carry its own blocks.
    repository, library, document = world
    store = exp.ExperimentStore(repository)
    keys = {}
    for blocks in (0, 4):
        created = exp.create(
            store,
            library,
            request(document, name=f"blocks {blocks}", blocks=blocks),
            bars=len(ROWS),
            max_workers=2,
            pinned=PINNED_DATA,
            engine_build="e" * 64,
        )
        assert created.blocks == blocks and created.plan["blocks"] == blocks
        assert created.sampler["blocks"] == blocks
        expected = identity.inputs_key(
            created.strategy_hash,
            created.data_pinned,
            created.settings.model_dump(mode="json"),
            "e" * 64,
            blocks=blocks,
        )
        keys[blocks] = sources.experiment_identity(created)["inputs_key"]
        assert keys[blocks] == expected
    assert keys[0] != keys[4]


def test_scope_counts_every_block_in_every_view(client, monkeypatch):  # noqa: F811
    """Ruling P5: `evaluations_done` counts every block's ok evaluations of the snapshot (§6.4),
    though every view reads block 0; every view and the summary repeat the same scope."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch, name="blocked", data=ONE_MINUTE, blocks=4)
    url = f"{LAB}/exp:{experiment_id}/query"
    scopes = {}
    for view in ("counts", "page", "top", "marginals"):
        response = c.post(url, json={"filter": {}, "view": view, "metric": "net_pnl"})
        assert response.status_code == 200, (view, response.text)
        scopes[view] = response.json()["scope"]
    summary = c.get(f"{LAB}/exp:{experiment_id}/summary")
    assert summary.status_code == 200, summary.text
    scopes["summary"] = summary.json()["counts"]
    shared = {
        name: {key: value for key, value in scope.items() if key not in ("shown", "basis")}
        for name, scope in scopes.items()
    }
    first = shared["counts"]
    assert all(scope == first for scope in shared.values()), shared
    assert (first["attempted"], first["completed"], first["scheduled"]) == (4, 4, 4)
    assert (first["evaluations"], first["evaluations_done"]) == (20, 20)
    assert first["completed"] <= first["evaluations_done"] <= first["evaluations"]
    assert first["block"] == 0
    narrowed = c.post(
        url, json={"filter": {"ranges": {DONCHIAN: [10, 12]}}, "view": "counts"}
    ).json()["scope"]
    assert narrowed["filtered"] == 2
    assert (narrowed["evaluations"], narrowed["evaluations_done"]) == (20, 20)


def test_block0_and_every_block_are_two_cache_entries(client, lab_cache, monkeypatch):  # noqa: F811
    """Ruling P1: an ordinary view's table holds block 0 only and the importance task's every
    block; one snapshot's two selections are two cache entries, never one."""
    c, _, repository = client
    experiment_id = _finished_experiment(c, monkeypatch, name="blocked", data=ONE_MINUTE, blocks=4)
    store = exp.ExperimentStore(repository)
    document = store.get(experiment_id)
    lab_cache.evict((("exp", experiment_id),))
    columns = sources.BASE
    _, block0 = _open(repository, lab_cache, experiment_id, columns)
    every, handle = sources.open_experiment(
        document, store, lab_cache, columns, selection=sources.ALL_BLOCKS
    )
    lab_store.REGISTRY.release(handle)
    assert block0.table.num_rows == 4 and set(block0.table.column("block").to_pylist()) == {0}
    assert every.table.num_rows == 20
    assert sorted(set(every.table.column("block").to_pylist())) == [0, 1, 2, 3, 4]
    assert block0.blocks == every.blocks == 4
    keys = [key for key in lab_cache._entries if key[0] == ("exp", experiment_id)]
    assert sorted(key[-2] for key in keys) == sorted([sources.BLOCK0, sources.ALL_BLOCKS])
    assert {key[-1] for key in keys} == {sources.column_set(columns)}
    misses = lab_cache.stats()["misses"]
    _, again = _open(repository, lab_cache, experiment_id, columns)
    assert again.table.num_rows == 4 and lab_cache.stats()["misses"] == misses  # from its entry
    # Whichever rows a frame holds, it carries the snapshot's count of every block's evaluations.
    for frame in (block0, every):
        counted = scope_counts(frame, LabFilter())
        assert (counted["completed"], counted["evaluations_done"]) == (4, 20)


# --- Task 2 review fixes ----------------------------------------------------------------------


def two_or_one(monkeypatch, bars: int, blocks: int) -> None:
    """Free memory for two workers holding `bars` and one holding its screened prefix frames
    too: the usable share sits between two of the first and two of the second."""
    from products.aegis import pool as worker_pool

    def each(held: int) -> int:
        return worker_pool.POOL_WORKER_BYTES + held * worker_pool.POOL_BYTES_PER_BAR

    free = (each(bars) + each(held_bars(bars, blocks))) / worker_pool.MEMORY_HEADROOM
    monkeypatch.setattr(worker_pool, "free_memory_bytes", lambda: int(free))


def test_held_bars_count_every_prefix_frame():
    """A screened worker holds the whole range and the K - 1 shorter prefixes (`frame_slice`
    copies them); the last block's prefix is the range itself."""
    assert held_bars(260, 0) == 260
    assert held_bars(260, 4) == 260 + 65 + 130 + 195
    assert held_bars(800, 8) == 800 + sum(100 * b for b in range(1, 8))  # 4.5 x at K = 8


def test_a_blocked_job_fits_fewer_workers(world, monkeypatch):  # noqa: F811
    """Review fix 1: the job fits its workers to what each one holds, its prefix frames included,
    so a screened experiment on the same range runs on fewer workers when memory is short."""
    repository, library, document = world
    store = exp.ExperimentStore(repository)
    two_or_one(monkeypatch, len(ROWS), 4)
    workers = {}
    for blocks in (0, 4):
        created = exp.create(
            store,
            library,
            request(document, name=f"fit {blocks}", blocks=blocks),
            bars=len(ROWS),
            max_workers=8,
        )
        workers[blocks] = exp.ExperimentJob(created, ROWS, PINNED_DATA, repository).workers
    assert workers == {0: 2, 4: 1}


def test_the_plan_fits_workers_to_the_held_bars(client, monkeypatch):  # noqa: F811
    """Review fix 1: the plan and create routes fit their workers to the held bars, so the plan's
    `workers` and estimate are the ones the job will run on."""
    c, _, _ = client
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "8")
    bars = 780  # ONE_MINUTE
    two_or_one(monkeypatch, bars, 4)
    url = "/aegis/api/experiments/plan"
    plain = c.post(url, json=_experiment_body(c, data=ONE_MINUTE)).json()
    blocked = c.post(url, json=_experiment_body(c, data=ONE_MINUTE, blocks=4)).json()
    assert (plain["bars"], blocked["bars"]) == (bars, bars)
    assert (plain["workers"], blocked["workers"]) == (2, 1)
    per_run = configuration_bars(bars, 4) * blocked["ms_per_cell_bar"] / 1000.0
    expected = blocked["planned_runs"] * per_run / effective_workers(1)
    assert blocked["estimate_seconds"] == pytest.approx(expected, rel=1e-12)
    experiment_id = _finished_experiment(c, monkeypatch, name="fit", data=ONE_MINUTE, blocks=4)
    created = c.get(f"/aegis/api/experiments/{experiment_id}").json()
    assert created["workers"] == 1 and created["plan"]["workers"] == 1


def test_the_snapshot_index_refuses_an_all_blocks_frame(client, lab_cache, monkeypatch):  # noqa: F811
    """Review fix 2: a frame records its row selection, and the snapshot's index (keyed block 0)
    is never built from an every-block frame, so it cannot poison the ordinary views."""
    c, _, repository = client
    experiment_id = _finished_experiment(c, monkeypatch, name="blocked", data=ONE_MINUTE, blocks=4)
    store = exp.ExperimentStore(repository)
    document = store.get(experiment_id)
    every, handle = sources.open_experiment(
        document, store, lab_cache, sources.BASE, selection=sources.ALL_BLOCKS
    )
    lab_store.REGISTRY.release(handle)
    assert every.selection == sources.ALL_BLOCKS and every.table.num_rows == 20
    with pytest.raises(ValueError, match="block-0 frames only"):
        sources.experiment_index(lab_cache, every, document)
    assert not [key for key in lab_cache._entries if key[0] == ("exp-index", experiment_id)]
    _, block0 = _open(repository, lab_cache, experiment_id, sources.BASE)
    assert block0.selection == sources.BLOCK0
    assert sources.experiment_index(lab_cache, block0, document).rows == 4
    response = c.post(f"{LAB}/exp:{experiment_id}/query", json={"filter": {}, "view": "counts"})
    assert response.status_code == 200 and response.json()["scope"]["completed"] == 4
