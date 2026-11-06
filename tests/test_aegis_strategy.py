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

pytestmark = pytest.mark.aegis


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
    with pytest.raises(ValidationError, match="unknown operand"):
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


# --- Mission 5: rule operands, operators and groups -------------------------------------------


def _side(entry, exit=None, extra=()):
    """The reference long side plus Donchian 20, RSI 14 and Bollinger 20, with the given rules."""
    from products.aegis.strategy import default_strategy

    data = default_strategy().long_side.model_dump(mode="json")
    data["indicators"] += [
        {"id": "donchian", "kind": "DONCHIAN", "length": 20},
        {"id": "rsi", "kind": "RSI", "length": 14},
        {"id": "bb", "kind": "BB", "length": 20},
        *extra,
    ]
    data["entry"] = entry
    if exit is not None:
        data["exit"] = exit
    return StrategySide.model_validate(data)


def rule(left, operator, right):
    return {"left": left, "operator": operator, "right": right}


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (rule("foo", "greater_than", "70"), "unknown operand 'foo'"),
        (rule("donchian", "greater_than", "70"), "donchian has outputs upper, lower, middle"),
        (rule("rsi.upper", "greater_than", "70"), "rsi has no output 'upper'"),
        (rule("price.close", "inside_band", "rsi"), r"inside_band needs a band \(bb or donchian\)"),
        (rule("30", "less_than", "70"), "compares two constants"),
        ({"all_of": [rule("rsi", "less_than", "70")]}, "a group needs two members"),
        (
            {
                "all_of": [rule("rsi", "less_than", "70")] * 2,
                "any_of": [rule("rsi", "less_than", "70")] * 2,
            },
            "exactly one of all_of or any_of",
        ),
        (rule("rsi", "between", "70"), "unknown operator 'between'"),
        (rule("70", "inside_band", "bb"), "needs a series on the left"),
    ],
)
def test_rule_validation_names_the_problem(entry, message):
    with pytest.raises(ValidationError, match=message):
        _side(entry)


@pytest.mark.parametrize("constant", ["1e3", "+5", " 70", "NaN", "Infinity", ".5", "70 ", "0x10"])
def test_unusual_constants_are_refused_as_unknown_operands(constant):
    with pytest.raises(ValidationError, match="unknown operand"):
        _side(rule("rsi", "less_than", constant))


@pytest.mark.parametrize("constant", ["70", "-1", "0.5", "100.25"])
def test_plain_decimal_constants_are_accepted(constant):
    side = _side(rule("rsi", "less_than", constant))
    assert side.entry.right == constant


def test_groups_and_bands_validate_and_dump_without_the_unused_key():
    side = _side(
        {
            "all_of": [
                rule("price.close", "crosses_above", "donchian.upper"),
                rule("rsi", "less_than", "70"),
            ]
        },
        exit=rule("price.close", "outside_band", "bb"),
    )
    dumped = side.model_dump(mode="json")
    assert set(dumped["entry"]) == {"all_of"}
    assert dumped["exit"] == {**rule("price.close", "outside_band", "bb"), "timing": "bar_close"}
    assert StrategySide.model_validate(dumped) == side


# --- Mission 13: rules form a tree -----------------------------------------------------------


def _nested(depth: int) -> dict:
    """A group nested `depth` levels deep: each level ANDs a condition with the next level."""
    group = {"any_of": [rule("rsi", "less_than", "70"), rule("rsi", "greater_than", "30")]}
    for _ in range(depth - 1):
        group = {"all_of": [rule("rsi", "less_than", "70"), group]}
    return group


def test_groups_take_any_number_of_members():
    members = [rule("rsi", "less_than", str(70 + i)) for i in range(4)]
    side = _side({"all_of": members})
    assert [c["right"] for c in side.model_dump(mode="json")["entry"]["all_of"]] == [
        "70",
        "71",
        "72",
        "73",
    ]


def test_groups_nest():
    from products.aegis.strategy import conditions

    a, b, c = (
        rule("price.close", "crosses_above", "donchian.upper"),
        rule("rsi", "less_than", "70"),
        rule("rsi", "greater_than", "30"),
    )
    side = _side({"all_of": [a, {"any_of": [b, c]}]})
    assert [(x.left, x.operator, x.right) for x in conditions(side.entry)] == [
        tuple(r.values()) for r in (a, b, c)
    ]
    assert StrategySide.model_validate(side.model_dump(mode="json")) == side


def test_a_group_needs_two_members():
    with pytest.raises(ValidationError, match="a group needs two members"):
        _side(
            {
                "all_of": [
                    rule("rsi", "less_than", "70"),
                    {"any_of": [rule("rsi", "less_than", "70")]},
                ]
            }
        )


def test_nesting_past_32_levels_is_refused():
    assert _side(_nested(32)).entry is not None
    with pytest.raises(ValidationError, match="nested deeper than 32 levels"):
        _side(_nested(33))


def test_nested_operands_are_checked():
    entry = {
        "all_of": [
            rule("rsi", "less_than", "70"),
            {"any_of": [rule("vwap", "less_than", "1"), rule("rsi", "less_than", "60")]},
        ]
    }
    with pytest.raises(ValidationError, match="entry rule references unknown operand 'vwap'"):
        _side(entry)


def test_referenced_columns_walk_the_tree():
    from products.aegis.strategy import referenced_columns

    entry = {
        "all_of": [
            rule("rsi", "less_than", "70"),
            {"any_of": [rule("price.close", "inside_band", "bb"), rule("rsi", "less_than", "60")]},
        ]
    }
    assert referenced_columns(_side(entry)) >= {"rsi", "bb.upper", "bb.lower"}


def test_indicator_id_price_is_reserved():
    with pytest.raises(ValidationError, match="reserved"):
        _side(rule("rsi", "less_than", "70"), extra=[{"id": "price", "kind": "EMA", "length": 5}])


def test_constants_are_ascii_digits_only():
    from products.aegis.strategy import is_constant

    assert is_constant("50") and is_constant("-0.5") and is_constant("100")
    assert not is_constant("٥٠")  # Arabic-Indic digits are not a constant the engine can read
    assert not is_constant("1e3") and not is_constant("1.") and not is_constant(" 50")


# --- Mission 13: stop and target ranges ------------------------------------------------------


def _with_levels(stop=2.0, target=5.0):
    data = default_strategy().long_side.model_dump(mode="json")
    data.update(stop_loss_pct=stop, take_profit_pct=target)
    return StrategySide.model_validate(data)


def test_stop_paths_round_trip():
    side = apply_parameters(_with_levels(), {"stop_loss_pct": 1.5, "take_profit_pct": 4.25})
    assert (side.stop_loss_pct, side.take_profit_pct) == (1.5, 4.25)
    data = _with_levels().model_dump(mode="json")
    data["optimization"] = [{"path": "stop_loss_pct", "start": 1, "stop": 3, "step": 0.5}]
    assert StrategySide.model_validate(data).optimization[0].path == "stop_loss_pct"


def test_ranging_an_unset_stop_is_refused():
    data = default_strategy().long_side.model_dump(mode="json")
    data["optimization"] = [{"path": "stop_loss_pct", "start": 1, "stop": 3, "step": 1}]
    with pytest.raises(
        ValidationError, match="stop_loss_pct: the long side has no stop loss to range"
    ):
        StrategySide.model_validate(data)
    with pytest.raises(
        ValueError, match="take_profit_pct: the long side has no take profit to range"
    ):
        apply_parameters(default_strategy().long_side, {"take_profit_pct": 2})


# -- Mission 13 review I1: the builder's default range around a stop or target -----------------


@pytest.mark.parametrize("pct", [0.05, 0.1, 0.2, 0.25, 2, 60])
def test_the_builders_default_level_range_is_accepted(pct):
    """`levelRange` (ui/src/builder/apply.ts) mirrors `defaultRanges`: half the percentage to
    twice it in quarter steps, a stop loss kept below 100. The formula is written out here so
    the server's validator pins it: every range validates on a side with that level, and the far
    end of the range applies as a level the side accepts."""
    for path in ("stop_loss_pct", "take_profit_pct"):
        stop = min(99, pct * 2) if path == "stop_loss_pct" else pct * 2
        data = _with_levels(stop=pct, target=pct).model_dump(mode="json")
        data["optimization"] = [
            {"path": path, "enabled": False, "start": pct / 2, "stop": stop, "step": pct / 4}
        ]
        side = StrategySide.model_validate(data)
        assert apply_parameters(side, {path: stop}).model_dump(mode="json")[path] == stop


def test_the_old_builder_level_range_was_refused_below_a_quarter_percent():
    """What the review reproduced: a floor of 0.5 on the start put it above a 0.2% stop's 0.4,
    refused on Save or Run while the builder's status read Ready."""
    with pytest.raises(ValidationError, match="stop_loss_pct: start 0.5 above stop 0.4"):
        OptimizationParameter(path="stop_loss_pct", enabled=False, start=0.5, stop=0.4, step=0.5)
