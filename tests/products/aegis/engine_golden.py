"""Mission 13: the engine's output before stops and rule trees, kept as a golden so every later
task can show that a strategy without stops gives byte-identical results.

    .venv-aegis\\Scripts\\python.exe tests\\products\\aegis\\engine_golden.py capture

writes `tests/fixtures/aegis_engine_golden.json`; `tests/test_aegis_engine_golden.py` compares
`cases()` with it. Studies are pinned by Mission 12's `aegis_study_golden.json`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests" / "fixtures" / "aegis_engine_golden.json"
for path in (ROOT / "app", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _plain(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _backtest(strategy, rows, engine: str, **settings) -> dict:
    from products.aegis.backtest import BacktestRequest, BacktestSettings, run_backtest
    from products.aegis.results import canonical_payload, result_hash

    result = run_backtest(
        BacktestRequest(
            strategy=strategy, bars=rows, settings=BacktestSettings(**settings), engine=engine
        )
    )
    payload = canonical_payload(
        result, strategy, {"source": "supplied_bars", "bar_count": len(rows)}
    )
    carried = {
        side: {key: result[side].get(key) for key in ("open_position", "pending_entry")}
        for side in ("long", "short")
    }
    return _plain({"result_hash": result_hash(payload), "payload": payload, "carried": carried})


def _travelling(engine: str) -> dict:
    """The two cuts `test_aegis_kernel` makes: an exit and an entry signalled on a run's last bar
    and filled by the next run."""
    from products.aegis.backtest import BacktestRequest, OpenPosition, PendingEntry, run_backtest
    from test_aegis_backtest import _long_only, bars

    rows, strategy = bars(), _long_only()
    stamps = [r["timestamp"].isoformat() for r in rows]
    trades = run_backtest(BacktestRequest(strategy=strategy, bars=rows))["long"]["trades"]
    out = {}
    cut = stamps.index(trades[0]["exit_signal_time"])
    first = run_backtest(
        BacktestRequest(
            strategy=strategy,
            bars=rows[: cut + 1],
            settings={"close_at_end": False},
            engine=engine,
        )
    )
    position = OpenPosition(**{**first["long"]["open_position"], "origin_window": 0})
    out["exit_first"] = _backtest(strategy, rows[: cut + 1], engine, close_at_end=False)
    out["exit_second"] = _backtest(
        strategy,
        rows[cut + 1 - 35 :],
        engine,
        initial_capital=first["long"]["ending_cash"],
        initial_position=position,
        evaluate_from=rows[cut + 1]["timestamp"],
    )
    trade = next(t for t in trades if stamps.index(t["signal_time"]) > 40)
    cut = stamps.index(trade["signal_time"])
    first = run_backtest(
        BacktestRequest(
            strategy=strategy,
            bars=rows[: cut + 1],
            settings={"close_at_end": False},
            engine=engine,
        )
    )
    out["entry_second"] = _backtest(
        strategy,
        rows[cut + 1 - 35 :],
        engine,
        initial_capital=first["long"]["ending_cash"],
        initial_entry=PendingEntry(**first["long"]["pending_entry"]),
        evaluate_from=rows[cut + 1]["timestamp"],
    )
    return out


def _experiment_cells() -> list[dict]:
    """Every cell of a 2 × 2 surface through `run_metrics`, the experiment pool's own call."""
    from products.aegis.backtest import (
        BacktestSettings,
        _data_key,
        _prepare_frame,
        prepared_request,
        run_metrics,
    )
    from products.aegis.indicators import IndicatorCache
    from products.aegis.surface import Parameter, Surface, build_grid
    from test_aegis_surface import pinned
    from test_aegis_walkforward import wave_bars

    rows = wave_bars(n=260, period=37.0, amplitude=10.0)
    frame = _prepare_frame(rows)
    key, cache = _data_key(frame), IndicatorCache()
    surface = Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=10, stop=20, step=10),
            Parameter(path="long_side.indicators.rsi.length", start=7, stop=14, step=7),
        ]
    )
    grid = build_grid(pinned(), surface, len(rows))
    cells = []
    for index in grid.valid_indices_iter():
        params = grid.cell_values(index)
        spec = grid.apply_cell(pinned(), params)
        metrics = run_metrics(prepared_request(spec, BacktestSettings()), frame, key, cache, True)
        cells.append({"params": params, "metrics": metrics})
    return _plain(cells)


def _walkforward() -> dict:
    from test_aegis_walkforward import rsi_walkforward_request, run_sync, wave_bars

    snapshot = run_sync(rsi_walkforward_request(), wave_bars())
    return _plain(snapshot)


def cases() -> dict[str, dict]:
    from products.aegis.strategy import default_strategy
    from test_aegis_backtest import _breakout, _long_only, bars
    from test_aegis_walkforward import wave_bars

    strategies = {
        "default": (default_strategy(), bars()),
        "breakout": (_breakout(None), wave_bars(n=300, period=60.0, amplitude=8.0)),
        "long_only": (_long_only(), bars()),
    }
    out: dict[str, dict] = {}
    for name, (strategy, rows) in strategies.items():
        for engine in ("reference", "kernel"):
            out[f"backtest/{name}/{engine}"] = _backtest(strategy, rows, engine)
    for engine in ("reference", "kernel"):
        for name, value in _travelling(engine).items():
            out[f"travelling/{name}/{engine}"] = value
    out["experiment"] = {"cells": _experiment_cells()}
    out["walkforward"] = _walkforward()
    return out


if __name__ == "__main__":
    if sys.argv[1:] != ["capture"]:
        raise SystemExit("usage: engine_golden.py capture")
    FIXTURE.write_text(json.dumps(cases(), sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE} ({FIXTURE.stat().st_size:,} bytes)")
