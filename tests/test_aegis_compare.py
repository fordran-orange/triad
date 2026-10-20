"""Comparing two backtests (Mission 9 spec §7): identity notes, strategy differences, metrics with
direction marks, both equity curves on one calendar axis, trade summaries."""

import pytest
from products.aegis.backtest import BacktestRequest, BacktestSettings, run_backtest
from products.aegis.compare import compare
from products.aegis.results import envelope
from products.aegis.strategy import StrategySpec, default_strategy
from test_aegis_walkforward import wave_bars

pytestmark = pytest.mark.aegis

ROWS = wave_bars(n=400, period=37.0, amplitude=10.0)
DATA = {
    "source": "raw_archive",
    "symbol": "QQQ",
    "timeframe": "1h",
    "start": "2026-01-05",
    "end": "2026-01-13",
    "data_hash": "d" * 64,
}


def spec(long_ema: int = 9) -> StrategySpec:
    base = default_strategy()
    side = base.long_side.model_copy(
        update={
            "indicators": [
                i.model_copy(update={"length": long_ema}) if i.id == "ema" else i
                for i in base.long_side.indicators
            ]
        }
    )
    return base.model_copy(update={"long_side": side})


def run(strategy: StrategySpec, rows=ROWS, data=DATA, run_id="a", settings=None) -> dict:
    settings = settings or BacktestSettings()
    result = run_backtest(BacktestRequest(strategy=strategy, bars=rows, settings=settings))
    out = envelope(result, strategy, settings, data, 3)
    out["run_id"] = run_id
    return out


def test_identical_requests_read_identical_result():
    a, b = run(spec(), run_id="a"), run(spec(), run_id="b")
    result = compare(a, b)
    assert {"identical result", "same data", "same strategy"} <= set(result["notes"])
    assert result["differences"] == []
    assert all(row["diff"] in (0, 0.0, None) for row in result["metrics"]["combined"])


def test_strategy_differences_name_each_path():
    result = compare(run(spec(9)), run(spec(12), run_id="b"))
    assert result["differences"] == [{"path": "long_side.indicators.ema.length", "a": 9, "b": 12}]
    assert "same strategy" not in result["notes"] and "same data" in result["notes"]


def test_settings_differences_are_listed():
    b = run(
        spec(),
        run_id="b",
        settings=BacktestSettings(initial_capital=50_000, allocation_fraction=0.5),
    )
    paths = [d["path"] for d in compare(run(spec()), b)["differences"]]
    assert paths == ["settings.allocation_fraction", "settings.initial_capital"]


def test_metric_marks_follow_orientation():
    rows = {
        r["metric"]: r
        for r in compare(run(spec(9)), run(spec(12), run_id="b"))["metrics"]["combined"]
    }
    for metric, row in rows.items():
        if row["a"] is None or row["b"] is None:
            assert row["diff"] is None and row["mark"] is None, metric
            continue
        assert row["diff"] == pytest.approx(row["b"] - row["a"]), metric
        if metric in ("trade_count", "exposure") or row["diff"] == 0:
            assert row["mark"] is None, metric
        elif metric == "max_drawdown":
            assert row["mark"] == ("better" if row["diff"] < 0 else "worse")
        else:
            assert row["mark"] == ("better" if row["diff"] > 0 else "worse"), metric
    assert set(rows) == {
        "net_pnl",
        "net_return",
        "cagr",
        "max_drawdown",
        "mar",
        "win_rate",
        "expectancy",
        "profit_factor",
        "trade_count",
        "exposure",
    }


def test_equity_is_percent_on_one_axis():
    a = run(spec(9))
    b = run(
        spec(12),
        rows=ROWS[50:],
        run_id="b",
        data={**DATA, "start": "2026-01-06", "data_hash": "e" * 64},
    )
    result = compare(a, b)
    for key, envelope_ in (("a", a), ("b", b)):
        points = result["equity"][key]
        assert points[0]["pct"] == 0.0 and len(points) <= 1000
        last = envelope_["result"]["combined"]["equity"][-1]["equity"]
        assert points[-1]["usd"] == pytest.approx(last)
        assert points[-1]["pct"] == pytest.approx(last / 100_000 - 1)
    starts = [result["equity"][k][0]["t"] for k in ("a", "b")]
    ends = [result["equity"][k][-1]["t"] for k in ("a", "b")]
    assert result["domain"] == {"start": min(starts), "end": max(ends)}


def test_different_periods_note_the_shared_span():
    b = run(
        spec(),
        run_id="b",
        data={**DATA, "start": "2026-01-08", "end": "2026-01-20", "data_hash": "f" * 64},
    )
    notes = compare(run(spec()), b)["notes"]
    assert "different periods: shared 2026-01-08 → 2026-01-13" in notes and "same data" not in notes


def test_compare_handles_a_run_without_trades():  # Review Focus 2
    flat = spec().model_copy(
        update={
            "long_side": spec().long_side.model_copy(update={"enabled": False}),
            "short_side": spec().short_side.model_copy(update={"enabled": False}),
        }
    )
    a, b = run(spec()), run(flat, run_id="b")
    result = compare(a, b)
    assert [p["pct"] for p in result["equity"]["b"]] == [0.0, 0.0]
    mar = next(r for r in result["metrics"]["combined"] if r["metric"] == "mar")
    if mar["b"] is None:
        assert mar["diff"] is None and mar["mark"] is None
    assert (
        result["trades"]["b"]["long"]["count"] == 0
        and result["trades"]["b"]["long"]["avg_net"] is None
    )


def test_legacy_run_without_settings_assumes_capital():
    a = run(spec())
    legacy = {k: v for k, v in run(spec(12), run_id="b").items() if k != "settings"}
    result = compare(a, legacy)
    assert result["capital_assumed"] == {"a": False, "b": True}
    assert result["identity"]["b"]["initial_capital"] == 100_000


def test_trade_summaries_per_side():
    result = compare(run(spec()), run(spec(12), run_id="b"))
    long = result["trades"]["a"]["long"]
    trades = run(spec())["result"]["long"]["trades"]
    assert long["count"] == len(trades) > 0
    assert long["avg_net"] == pytest.approx(sum(t["net_pnl"] for t in trades) / len(trades))
    assert 0 <= long["win_rate"] <= 1 and long["max_hold_hours"] >= long["avg_hold_hours"] > 0
