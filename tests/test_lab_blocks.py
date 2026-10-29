"""Optimization Lab v2, Phase 3 (spec §7.3a): a screening block is scored on the frame with its
prior history but evaluated only from the block's start. `run_metrics(..., evaluate_from=)`
builds the kernel's `evaluating` mask exactly as the full engine does for a walk-forward window
(`settings.evaluate_from`), so a block row's metrics equal `run_backtest`'s; with
`evaluate_from=None` the metrics path is byte-identical to before."""

import json
from datetime import timedelta

import numpy as np
import pytest
from products.aegis import kernel
from products.aegis.backtest import (
    BacktestRequest,
    BacktestSettings,
    _data_key,
    _side_metrics,
    prepared_request,
    run_backtest,
    run_metrics,
)
from products.aegis.indicators import IndicatorCache
from products.aegis.lab.sharpe import sharpe_scopes
from products.aegis.pool import METRICS, SCOPES, pool_frame
from products.aegis.surface import apply_params
from test_aegis_pool import ROWS, cells, pinned

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
    frame, key, cache = held(ROWS)
    for _, params in cells(2):
        prepared = prepared_request(apply_params(pinned(), params), BacktestSettings(), engine)
        plain = run_metrics(prepared, frame, key, cache, want_curve, True)
        unset = run_metrics(prepared, frame, key, cache, want_curve, True, evaluate_from=None)
        assert json.dumps(unset, sort_keys=True) == json.dumps(plain, sort_keys=True)
        assert plain["first_time"] == ROWS[0]["timestamp"].isoformat()
        assert plain["last_time"] == ROWS[-1]["timestamp"].isoformat()
