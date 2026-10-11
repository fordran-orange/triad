import pytest
from products.aegis.strategy import (
    Direction,
    OptimizationParameter,
    RuleSpec,
    StrategySide,
    WindowMode,
    apply_parameters,
    default_strategy,
)
from pydantic import ValidationError


def test_reference_strategy_is_9_ema_30_sma_cross_on_both_sides():
    strategy = default_strategy()
    for side in (strategy.long_side, strategy.short_side):
        assert side.indicator("ema").kind == "EMA" and side.indicator("ema").length == 9
        assert side.indicator("sma").kind == "SMA" and side.indicator("sma").length == 30


def test_each_side_owns_its_indicators_and_ranges():
    s = default_strategy()
    assert [i.length for i in s.long_side.indicators] == [9, 30]
    assert [i.length for i in s.short_side.indicators] == [9, 30]
    assert s.long_side.optimization[0].path == "indicators.ema.length"
    assert s.long_side.optimization[1].path == "indicators.sma.length"
    assert s.short_side.optimization is not s.long_side.optimization
    assert not hasattr(s, "indicators") and not hasattr(s, "optimization")


def test_sides_can_diverge_without_shared_state():
    s = default_strategy()
    short = apply_parameters(
        s.short_side, {"indicators.ema.length": 6, "indicators.sma.length": 52}
    )
    assert short.indicator("ema").length == 6 and short.indicator("sma").length == 52
    assert s.long_side.indicator("ema").length == 9
    assert s.short_side.indicator("ema").length == 9  # apply_parameters does not mutate


def test_apply_parameters_rejects_unknown_paths():
    with pytest.raises(ValueError, match="unknown parameter path"):
        apply_parameters(default_strategy().long_side, {"indicators.rsi.length": 14})


def test_rule_referencing_unknown_indicator_is_rejected():
    with pytest.raises(ValidationError, match="unknown indicator"):
        StrategySide(
            direction=Direction.LONG,
            indicators=[],
            entry=RuleSpec(left="ema", operator="crosses_above", right="sma"),
            exit=RuleSpec(left="ema", operator="crosses_below", right="sma"),
        )


def test_long_and_short_sides_are_explicit_and_independent():
    strategy = default_strategy()
    assert strategy.long_side.direction == Direction.LONG
    assert strategy.short_side.direction == Direction.SHORT
    assert strategy.long_side.entry.operator == "crosses_above"
    assert strategy.short_side.entry.operator == "crosses_below"
    changed = strategy.model_copy(
        update={"short_side": strategy.short_side.model_copy(update={"enabled": False})}
    )
    assert changed.long_side.enabled is True
    assert changed.short_side.enabled is False


def test_temporal_context_is_first_class():
    strategy = default_strategy()
    windows = {window.id: window for window in strategy.temporal.clock_windows}
    assert windows["open"].start == "09:30"
    assert windows["close"].end == "16:00"
    assert all(window.mode == WindowMode.ANALYZE for window in windows.values())
    event_types = {window.event_type for window in strategy.temporal.event_windows}
    assert {"FOMC", "EARNINGS", "MACRO_RELEASE", "RUMOR_NEWS"} <= event_types


def test_market_crossovers_are_clock_defined_and_enabled():
    cx = {c.id: c for c in default_strategy().temporal.market_crossovers}
    assert cx["cash_open"].start == "09:25" and cx["cash_open"].end == "09:45"
    assert cx["cash_open"].enabled and cx["cash_open"].mode == WindowMode.ANALYZE
    assert cx["london_new_york"].start == "09:30" and cx["london_new_york"].end == "11:30"
    assert cx["london_new_york"].enabled


def test_reference_strategy_uses_next_bar_open_execution():
    strategy = default_strategy()
    assert strategy.execution.signal_timing == "bar_close"
    assert strategy.execution.fill_timing == "next_bar_open"


def test_optimization_parameter_rejects_reversed_and_fractional_length_ranges():
    with pytest.raises(ValidationError, match="start 20.0 above stop 5.0"):
        OptimizationParameter(path="indicators.ema.length", start=20, stop=5, step=1)
    with pytest.raises(ValidationError, match="integer"):
        OptimizationParameter(path="indicators.ema.length", start=5, stop=10, step=0.5)
    with pytest.raises(ValidationError, match="integer"):
        OptimizationParameter(path="indicators.ema.length", start=5.5, stop=10, step=1)
    assert OptimizationParameter(path="indicators.ema.length", start=5, stop=10, step=1).stop == 10


# --- Mission 5: indicator parameters on the contract ----------------------------------------

DEFAULT_STRATEGY_JSON_SHA256 = "c3ac85379716483e4554e6936f3f4bf970036cff966d9d313fc9dd353252dd30"


def test_default_strategy_json_is_byte_identical():
    import hashlib
    import json

    from products.aegis.strategy import default_strategy

    dumped = json.dumps(default_strategy().model_dump(mode="json"), sort_keys=True)
    assert hashlib.sha256(dumped.encode()).hexdigest() == DEFAULT_STRATEGY_JSON_SHA256
    assert "params" not in dumped


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"kind": "XYZ", "length": 5}, "unknown indicator kind 'XYZ'"),
        ({"kind": "RSI", "length": 5, "params": {"x": 1}}, "RSI has no parameter 'x'"),
        ({"kind": "MACD", "length": 5, "params": {"slow": 0}}, "slow must be positive"),
        (
            {"kind": "MACD", "length": 5, "params": {"slow": 26.5}},
            "slow must be a whole number, got 26.5",
        ),
        ({"kind": "MACD", "length": 26}, "MACD fast length 26 must be below slow 26"),
        (
            {"kind": "BB", "length": 5, "params": {"multiplier": float("inf")}},
            "multiplier must be finite",
        ),
    ],
)
def test_indicator_contract_refuses_named_problems(fields, message):
    from products.aegis.strategy import IndicatorSpec
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match=message):
        IndicatorSpec(id="x", **fields)


@pytest.mark.parametrize("identifier", ["EMA", "1x", "my-ema", ""])
def test_indicator_ids_are_lowercase_names(identifier):
    from products.aegis.strategy import IndicatorSpec
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="id"):
        IndicatorSpec(id=identifier, kind="EMA", length=5)


def test_params_appear_in_dumps_only_when_set():
    from products.aegis.strategy import IndicatorSpec

    assert "params" not in IndicatorSpec(id="e", kind="EMA", length=5).model_dump(mode="json")
    bb = IndicatorSpec(id="bb", kind="BB", length=20, params={"multiplier": 2.5})
    assert bb.model_dump(mode="json")["params"] == {"multiplier": 2.5}
    assert bb.effective_params() == {"multiplier": 2.5}
    macd = IndicatorSpec(id="m", kind="macd", length=12)
    assert macd.effective_params() == {"slow": 26.0, "signal": 9.0}


def _side_with(*extra, optimization=()):
    from products.aegis.strategy import default_strategy

    side = default_strategy().long_side
    data = side.model_dump(mode="json")
    data["indicators"] += [spec.model_dump(mode="json") for spec in extra]
    data["optimization"] = [p.model_dump(mode="json") for p in optimization]
    return StrategySide.model_validate(data)


def test_params_path_round_trips():
    from products.aegis.strategy import IndicatorSpec, apply_parameters

    side = _side_with(
        IndicatorSpec(id="bb", kind="BB", length=20),
        IndicatorSpec(id="macd", kind="MACD", length=12),
    )
    applied = apply_parameters(
        side,
        {
            "indicators.bb.params.multiplier": 2.5,
            "indicators.macd.params.slow": 30.0,
            "indicators.bb.length": 21.0,
        },
    )
    bb, macd = applied.indicator("bb"), applied.indicator("macd")
    assert bb.params == {"multiplier": 2.5} and bb.length == 21
    assert macd.params == {"slow": 30.0}


@pytest.mark.parametrize(
    "path",
    ["indicators.rsi.params.slow", "indicators.rsi.params", "indicators.nope.length", "rsi.length"],
)
def test_unknown_params_path_is_refused(path):
    from products.aegis.strategy import IndicatorSpec, OptimizationParameter

    with pytest.raises(ValueError, match="unknown parameter path"):
        _side_with(
            IndicatorSpec(id="rsi", kind="RSI", length=14),
            optimization=[OptimizationParameter(path=path, start=1, stop=2, step=1)],
        )


def test_integer_parameter_ranges_need_whole_numbers():
    from products.aegis.strategy import IndicatorSpec, OptimizationParameter

    with pytest.raises(ValueError, match="whole-number"):
        _side_with(
            IndicatorSpec(id="macd", kind="MACD", length=12),
            optimization=[
                OptimizationParameter(
                    path="indicators.macd.params.slow", start=20, stop=30, step=2.5
                )
            ],
        )
