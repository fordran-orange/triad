"""Plateau walk-forward rules (Mission 8 spec §5): the per-window choice, the per-side capital
chains, flat windows, stitching and the per-rule hashes; then the report and its Markdown."""

import math
from datetime import datetime

import pytest
from products.aegis.backtest import BacktestRequest, BacktestSettings, run_backtest
from products.aegis.strategy import default_strategy
from products.aegis.study_rules import (
    best_cell,
    centre_inside,
    move_distance,
    resample,
    run_window,
    start_chains,
    stitch_rule,
)
from products.aegis.surface import Parameter, Surface, build_grid
from products.aegis.walkforward import cut_windows
from test_aegis_walkforward import wave_bars

pytestmark = pytest.mark.aegis

ROWS = [
    {**row, "timestamp": row["timestamp"].isoformat()}
    for row in wave_bars(n=600, period=37.0, amplitude=10.0)
]
WINDOWS, _ = cut_windows(len(ROWS), 200, 100)
SETTINGS = BacktestSettings(initial_capital=100_000, allocation_fraction=1)
SPEC = default_strategy()  # EMA 9 / SMA 30 on both sides


def walk(spec=SPEC, flat_at=()):
    """Run every window in order on one chain set, as one rule does."""
    chains = start_chains(spec, SETTINGS.initial_capital)
    results = []
    for window in WINDOWS:
        result = run_window(
            spec,
            ROWS,
            window,
            chains,
            SETTINGS,
            last=window is WINDOWS[-1],
            flat=window.index in flat_at,
        )
        results.append(result)
        chains = result["chains"]
    return results


def core(trade):
    return (trade["side"], trade["entry_time"], trade["exit_time"], round(trade["net_pnl"], 9))


def test_frozen_chain_equals_one_continuous_run():
    stitched = stitch_rule(walk(), SETTINGS.initial_capital)
    continuous = run_backtest(
        BacktestRequest(
            strategy=SPEC,
            bars=ROWS,
            settings=SETTINGS.model_copy(
                update={
                    "evaluate_from": datetime.fromisoformat(ROWS[WINDOWS[0].oos_start]["timestamp"])
                }
            ),
        )
    )["combined"]
    assert len(continuous["trades"]) >= 6
    assert [core(t) for t in stitched["trades"]] == [core(t) for t in continuous["trades"]]
    for key, value in continuous["metrics"].items():
        assert stitched["metrics"][key] == pytest.approx(value), key
    assert [p["equity"] for p in stitched["equity"]] == pytest.approx(
        [p["equity"] for p in continuous["equity"]]
    )


def test_an_entry_signalled_on_a_window_last_bar_fills_at_the_next_window_first_bar():
    """Mission 8 QA D1: windows cut so that one ends on an entry signal still chain to one
    continuous run (the entry used to be dropped at the join)."""
    from products.aegis.walkforward import Window

    start = datetime.fromisoformat(ROWS[200]["timestamp"])
    continuous = run_backtest(
        BacktestRequest(
            strategy=SPEC, bars=ROWS, settings=SETTINGS.model_copy(update={"evaluate_from": start})
        )
    )
    stamps = [r["timestamp"] for r in ROWS]
    signal = next(
        stamps.index(t["signal_time"])
        for t in continuous["long"]["trades"]
        if 260 < stamps.index(t["signal_time"]) < 500
    )
    windows = [Window(0, 0, 200, 200, signal + 1), Window(1, 0, 200, signal + 1, len(ROWS))]
    chains = start_chains(SPEC, SETTINGS.initial_capital)
    results = []
    for window in windows:
        result = run_window(SPEC, ROWS, window, chains, SETTINGS, last=window is windows[-1])
        results.append(result)
        chains = result["chains"]
    assert results[0]["chains"]["long"].pending is not None  # the signal travels in the chain
    stitched = stitch_rule(results, SETTINGS.initial_capital)
    assert [core(t) for t in stitched["trades"]] == [
        core(t) for t in continuous["combined"]["trades"]
    ]
    assert stitched["metrics"]["net_pnl"] == pytest.approx(
        continuous["combined"]["metrics"]["net_pnl"]
    )


def test_a_flat_window_drops_a_carried_entry():
    from products.aegis.study_rules import SideChain

    chains = {
        "long": SideChain(
            cash=100_000.0,
            pending={"side": "LONG", "signal_time": ROWS[299]["timestamp"], "entry_tags": []},
        ),
        "short": SideChain(cash=100_000.0),
    }
    flat = run_window(SPEC, ROWS, WINDOWS[1], chains, SETTINGS, last=False, flat=True)
    assert flat["sides"]["long"]["trades"] == [] and flat["chains"]["long"].pending is None


def test_each_side_keeps_its_own_chain_and_carries_across_joins():
    results = walk()
    carried = [
        (k, side)
        for k, result in enumerate(results[:-1])
        for side, record in result["sides"].items()
        if record["open_position"] is not None
    ]
    assert carried, "the wave must leave a position open at some join"
    for k, side in carried:
        assert results[k + 1]["sides"][side]["carried_in"] is True
    assert results[-1]["sides"]["long"]["open_position"] is None  # only the last closes its edge
    for k in range(1, len(results)):
        for side in ("long", "short"):
            assert results[k]["chains"][side].cash == results[k]["sides"][side]["ending_cash"]


def flat_after_an_open_position():
    results = walk()
    k = next(
        k
        for k, result in enumerate(results[:-1])
        if any(record["open_position"] for record in result["sides"].values())
    )
    return k, results[k]


def test_flat_window_closes_a_carried_position_at_its_first_bar_and_opens_nothing():
    k, before = flat_after_an_open_position()
    window = WINDOWS[k + 1]
    flat = run_window(SPEC, ROWS, window, before["chains"], SETTINGS, last=False, flat=True)
    assert flat["flat"] is True
    for side, record in before["sides"].items():
        after = flat["sides"][side]
        assert after["flat"] is True and after["open_position"] is None
        if record["open_position"] is None:
            assert after["trades"] == [] and after["ending_cash"] == before["chains"][side].cash
            continue
        [exit_] = after["trades"]
        assert exit_["exit_time"] == ROWS[window.oos_start]["timestamp"]
        assert exit_["window_flat_exit"] is True
        assert exit_["entry_time"] == record["open_position"]["entry_time"]
    assert flat["combined"]["exposure"] == 0.0


def test_the_window_after_a_flat_window_starts_flat():
    results = walk(flat_at=(2,))
    for record in results[2]["sides"].values():
        assert record["open_position"] is None
    for record in results[3]["sides"].values():
        assert record["carried_in"] is False


def test_window_net_is_its_ending_equity_minus_the_previous():
    results = walk()
    previous = SETTINGS.initial_capital
    for result in results:
        combined = result["combined"]
        assert combined["net_pnl"] == pytest.approx(combined["ending_equity"] - previous)
        previous = combined["ending_equity"]
    stitched = stitch_rule(results, SETTINGS.initial_capital)
    assert sum(r["combined"]["net_pnl"] for r in results) == pytest.approx(
        stitched["metrics"]["net_pnl"]
    )


def test_flat_windows_are_counted_in_the_stitch():
    results = walk(flat_at=(1, 2))
    assert stitch_rule(results, SETTINGS.initial_capital)["flat_windows"] == 2


def rows_of(values: dict[int, float | None], valid: dict[int, bool] | None = None):
    return [
        {"cell": cell, "valid": (valid or {}).get(cell, True), "combined.mar": value}
        for cell, value in values.items()
    ]


def test_best_cell_ties_to_the_lower_index_and_skips_nulls():
    assert best_cell(rows_of({4: 1.0, 2: 1.0, 7: None, 9: 0.5}), "mar") == 2
    assert best_cell(rows_of({4: 3.0, 2: 1.0}, valid={4: False}), "mar") == 2
    drawdown = [
        {"cell": 0, "valid": True, "combined.max_drawdown": 0.3},
        {"cell": 1, "valid": True, "combined.max_drawdown": 0.1},
    ]
    assert best_cell(drawdown, "max_drawdown") == 1


def test_null_objective_window_is_flat_for_both_choosing_rules():  # Review Focus 2
    assert best_cell(rows_of({0: None, 1: None}), "mar") is None
    assert best_cell([], "mar") is None


def grid2():
    return build_grid(
        default_strategy(),
        Surface(
            parameters=[
                Parameter(path="long_side.indicators.ema.length", start=1, stop=9, step=1),
                Parameter(path="long_side.indicators.sma.length", start=21, stop=29, step=1),
            ]
        ),
    )


def test_centre_inside_and_move_distance():
    assert centre_inside([3, 4, 5], 4) is True
    assert centre_inside([3, 4, 5], 8) is False
    assert centre_inside(None, 4) is None and centre_inside([3], None) is None
    grid = grid2()
    corner, opposite = grid.index_at((0, 0)), grid.index_at((8, 8))
    assert move_distance(grid, corner, opposite) == pytest.approx(math.sqrt(2))
    assert move_distance(grid, corner, corner) == 0.0


def test_stitched_hash_reproduces_and_changes_with_a_trade():
    first = stitch_rule(walk(), SETTINGS.initial_capital)
    again = stitch_rule(walk(), SETTINGS.initial_capital)
    assert first["result_hash"] == again["result_hash"] and len(first["result_hash"]) == 64
    results = walk()
    results[0]["combined"]["trades"] = results[0]["combined"]["trades"][1:]
    assert stitch_rule(results, SETTINGS.initial_capital)["result_hash"] != first["result_hash"]


def test_each_side_run_carries_a_hash_of_its_own_trades_and_metrics():  # plan ruling P16
    result = walk()[1]
    hashes = {record["run_hash"] for record in result["sides"].values()}
    assert len(hashes) == 2 and all(len(h) == 64 for h in hashes)


def test_resample_keeps_ends_and_bounds_the_count():
    points = [{"t": i} for i in range(1000)]
    out = resample(points, 256)
    assert len(out) == 256 and out[0] == points[0] and out[-1] == points[-1]
    assert resample(points[:10], 256) == points[:10]


# --- Task 4: the report and its Markdown -------------------------------------------------------

from products.aegis.study_rules import RAW_LABEL, render_study_markdown, study_report

METRIC_KEYS = ("net_pnl", "net_return", "cagr", "max_drawdown", "mar", "trade_count", "exposure")


def stitched(mar, flat=0, windows=16, trades=10, net=1000.0):
    metrics = dict.fromkeys(METRIC_KEYS, 0.1)
    metrics.update(mar=mar, trade_count=trades, net_pnl=net)
    equity = [
        {"timestamp": f"2020-01-{d:02d}T14:30:00+00:00", "equity": 100_000 + d}
        for d in range(1, 29)
    ]
    return {
        "metrics": metrics,
        "flat_windows": flat,
        "windows": windows,
        "result_hash": "a" * 64,
        "trades": [],
        "equity": equity,
    }


def window_record(index, centre=None, inside=None, moved=None, reason=None):
    plateau = (
        None
        if centre is None
        else {
            "id": 1,
            "size": 9,
            "median": 0.5,
            "cliff": 0.2,
            "centre_cell": centre,
            "centre_params": {"long_side.indicators.ema.length": float(centre)},
        }
    )
    return {
        "index": index,
        "oos_start": f"2020-0{index + 1}-01T14:30:00+00:00",
        "oos_end": f"2020-0{index + 1}-28T20:30:00+00:00",
        "plateau": plateau,
        "no_plateau": reason if centre is None else None,
        "best": {"cell": 3, "params": {"long_side.indicators.ema.length": 3.0}, "objective": 0.9},
        "rules": {
            rule: {
                "flat": rule == "plateau" and centre is None,
                "combined": {"net_pnl": 10.0 * index, "trade_count": 2, "exposure": 0.4},
            }
            for rule in ("plateau", "peak", "frozen")
        },
        "centre_inside": inside,
        "moved": moved,
    }


def Doc():
    """The study document fields the report reads."""
    from types import SimpleNamespace

    return SimpleNamespace(
        objective="mar",
        symbols=["QQQ", "SPY", "ITOT"],
        timeframe="1h",
        start="2016-09-19",
        end="2026-09-18",
        frozen_absent=None,
        name="walk breakout",
    )


def three(frozen_absent=None):
    doc = Doc()
    doc.frozen_absent = frozen_absent
    windows = [
        window_record(0, centre=4),
        window_record(1, centre=5, inside=True, moved=0.1),
        window_record(2, reason="no plateau at tolerance 0.15; the best cell is a fragile peak"),
        window_record(3, centre=8, inside=False, moved=0.4),
    ]

    def rules(plateau, peak, frozen):
        out = {"plateau": stitched(plateau, flat=1, windows=4), "peak": stitched(peak, windows=4)}
        out["frozen"] = {"absent": frozen_absent} if frozen_absent else stitched(frozen, windows=4)
        return out

    per_symbol = {
        "QQQ": {"rules": rules(0.80, 0.30, 0.50), "windows": windows},
        "SPY": {"rules": rules(0.61, 0.42, 0.55), "windows": windows},
        "ITOT": {"rules": rules(0.20, 0.35, 0.10), "windows": windows},
    }
    return doc, per_symbol


def test_comparison_sentence_by_objective():
    report = study_report(*three())
    assert report["symbols"]["SPY"]["comparison"] == (
        "On SPY the plateau rule's out-of-sample MAR was 0.61, against 0.42 for the peak rule "
        "and 0.55 for the frozen centre."
    )
    doc, per_symbol = three()
    per_symbol["QQQ"]["rules"]["peak"]["metrics"]["mar"] = None
    assert study_report(doc, per_symbol)["symbols"]["QQQ"]["comparison"].startswith(
        "On QQQ the plateau rule's out-of-sample MAR was 0.80, against — for the peak rule"
    )


def test_flat_windows_line():
    report = study_report(*three())
    assert report["symbols"]["QQQ"]["flat_line"] == "flat in 1 of 4 windows"


def test_cross_symbol_line_and_caveats():
    report = study_report(*three())
    assert report["summary"] == "plateau rule ahead of the peak rule on 2 of 3 symbols by MAR"
    caveats = " ".join(report["caveats"])
    assert "windows: QQQ 4, SPY 4, ITOT 4" in caveats
    assert "plateau rule flat windows: QQQ 1, SPY 1, ITOT 1" in caveats
    assert "no significance test is claimed" in caveats
    doc, per_symbol = three()
    per_symbol["ITOT"]["rules"]["plateau"]["metrics"]["mar"] = None
    assert study_report(doc, per_symbol)["summary"] == (
        "plateau rule ahead of the peak rule on 2 of 2 comparable symbols by MAR (1 not comparable)"
    )


def test_max_drawdown_is_ahead_when_lower():
    doc, per_symbol = three()
    doc.objective = "max_drawdown"
    for symbol, (plateau, peak) in {
        "QQQ": (0.1, 0.2),
        "SPY": (0.3, 0.2),
        "ITOT": (0.1, 0.4),
    }.items():
        per_symbol[symbol]["rules"]["plateau"]["metrics"]["max_drawdown"] = plateau
        per_symbol[symbol]["rules"]["peak"]["metrics"]["max_drawdown"] = peak
    assert study_report(doc, per_symbol)["summary"].startswith(
        "plateau rule ahead of the peak rule on 2 of 3 symbols by max drawdown"
    )


def test_stability_block():
    stability = study_report(*three())["symbols"]["QQQ"]["stability"]
    assert stability["plateau_share"] == 0.75
    assert stability["centre_kept_share"] == 0.5
    assert stability["median_move"] == pytest.approx(0.25)
    assert stability["centre_path"] == {"long_side.indicators.ema.length": [4.0, 5.0, None, 8.0]}


def test_frozen_column_absent_with_its_reason():  # Review Focus 5
    reason = "the parent report has no recommendation"
    report = study_report(*three(frozen_absent=reason))
    assert report["symbols"]["SPY"]["rules"]["frozen"] == {"absent": reason}
    assert report["symbols"]["SPY"]["comparison"] == (
        "On SPY the plateau rule's out-of-sample MAR was 0.61, against 0.42 for the peak rule."
    )
    assert f"Frozen centre: absent — {reason}." in render_study_markdown(report)


def test_markdown_carries_the_raw_archive_label_and_the_window_table():
    report = study_report(*three())
    markdown = render_study_markdown(report)
    assert markdown.startswith("# Plateau walk-forward: plateau rule ahead of the peak rule")
    assert RAW_LABEL == "RAW ARCHIVE · NOT RESEARCH-ELIGIBLE" and RAW_LABEL in markdown
    assert report["raw_archive"] is True
    assert "no plateau at tolerance 0.15" in markdown  # a flat window states its reason
    assert "flat in 1 of 4 windows" in markdown
    assert len(report["symbols"]["QQQ"]["curves"]["plateau"]) == 28


def test_curves_are_bounded():
    doc, per_symbol = three()
    per_symbol["QQQ"]["rules"]["peak"]["equity"] = [
        {"timestamp": str(i), "equity": float(i)} for i in range(5000)
    ]
    curve = study_report(doc, per_symbol)["symbols"]["QQQ"]["curves"]["peak"]
    assert len(curve) == 256 and curve[-1]["equity"] == 4999.0


def test_window_choice_names_the_centre_plainly():
    report = study_report(*three())
    assert report["symbols"]["QQQ"]["window_rows"][0]["choice"] == (
        "plateau 1 (9 cells), centre long_side.indicators.ema.length 4"
    )
    assert "{" not in render_study_markdown(report)


def test_a_two_decimal_tie_is_written_with_three():
    """0.133 against 0.129 must not read "0.13 against 0.13" beside a line counting it ahead."""
    doc, per_symbol = three()
    per_symbol["SPY"]["rules"]["plateau"]["metrics"]["mar"] = 0.1331
    per_symbol["SPY"]["rules"]["peak"]["metrics"]["mar"] = 0.1294
    assert study_report(doc, per_symbol)["symbols"]["SPY"]["comparison"] == (
        "On SPY the plateau rule's out-of-sample MAR was 0.133, against 0.129 for the peak rule "
        "and 0.550 for the frozen centre."
    )


def test_the_window_table_names_peaks_fragile_and_each_rule_flat():  # review finding (spec §7 → §5.5)
    doc, per_symbol = three()
    window = per_symbol["QQQ"]["windows"][2]  # the no-plateau window
    window["peaks"], window["fragile"] = 5, 5
    window["rules"]["peak"]["flat"] = True
    report = study_report(doc, per_symbol)
    row = report["symbols"]["QQQ"]["window_rows"][2]
    assert (row["peaks"], row["fragile"]) == (5, 5)
    assert row["flat_rules"] == {"plateau": True, "peak": True, "frozen": False}
    markdown = render_study_markdown(report)
    assert (
        "| window | out of sample | choice | peaks (fragile) | plateau | peak | frozen |"
        in markdown
    )
    line = next(text for text in markdown.splitlines() if text.startswith("| 2 |"))
    assert "| 5 (5) |" in line and line.count("flat ·") == 2


# --- Mission 12: held bars by index -----------------------------------------------------------------


def _held_by_datetime(trades, open_position, moments, start, end):
    """The pre-Mission-12 body of study_rules._held, kept as the oracle."""
    import bisect

    def moment(value):
        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))

    def index(value):
        return bisect.bisect_left(moments, moment(value))

    held = set()
    for trade in trades:
        first = max(index(trade["entry_time"]), start)
        stop = index(trade["exit_time"])
        if trade.get("exit_signal_time") == trade.get("exit_time"):
            stop += 1
        held.update(range(first, min(stop, end)))
    if open_position is not None:
        held.update(range(max(index(open_position["entry_time"]), start), end))
    return held


def test_held_by_index_equals_held_by_datetime():  # Review Focus 2
    from products.aegis.backtest import _prepare_frame
    from products.aegis.study_rules import _held

    rows = [{**r, "timestamp": r["timestamp"].isoformat()} for r in wave_bars(n=40)]
    stamps = _prepare_frame(rows)["timestamp"].astype("int64").to_numpy()
    iso = [r["timestamp"] for r in rows]
    trades = [
        {"entry_time": iso[5], "exit_time": iso[9], "exit_signal_time": iso[8]},  # inside
        {"entry_time": iso[1], "exit_time": iso[12], "exit_signal_time": iso[11]},  # entered before
        {
            "entry_time": iso[16],
            "exit_time": iso[19],
            "exit_signal_time": iso[19],
        },  # end-of-data close
    ]
    open_position = {"entry_time": iso[17]}
    moments = [datetime.fromisoformat(t) for t in iso]
    for start, end, still_open in ((4, 20, open_position), (0, 40, None), (10, 18, open_position)):
        expected = _held_by_datetime(trades, still_open, moments, start, end)
        assert _held(trades, still_open, stamps, start, end) == expected, (start, end)
