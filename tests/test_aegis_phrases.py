"""Mission 13: the phrase reader turns a sentence into whole replacement sides (spec §4.7, §9).
Each expected side is written out in full and validated as a `StrategySide`; nothing is guessed,
so unread words refuse the whole text, naming them."""

import pytest
from products.aegis.phrases import Unread, read
from products.aegis.strategy import StrategySide, default_strategy

pytestmark = pytest.mark.aegis

OPERATOR = "buy when 9 ema crosses 30 sma and price is above 200 sma"
ITEM_37 = (
    "buy when close crosses above donchian upper and rsi below 70; "
    "sell when close crosses below donchian middle"
)


def cond(left, operator, right):
    return {"left": left, "operator": operator, "right": right}


def side(direction, indicators, entry, exit=None, stop=None, target=None, optimization=()):
    data = {
        "direction": direction,
        "enabled": True,
        "indicators": indicators,
        "entry": entry,
        "optimization": list(optimization),
    }
    if exit is not None:
        data["exit"] = exit
    if stop is not None:
        data["stop_loss_pct"] = stop
    if target is not None:
        data["take_profit_pct"] = target
    return StrategySide.model_validate(data)


def ind(identifier, kind, length, **params):
    spec = {"id": identifier, "kind": kind, "length": length}
    if params:
        spec["params"] = params
    return spec


REFERENCE_RANGES = [
    {"path": "indicators.ema.length", "start": 5, "stop": 20, "step": 1},
    {"path": "indicators.sma.length", "start": 20, "stop": 100, "step": 5},
]

CASES = [
    (
        OPERATOR,
        {
            "long_side": side(
                "long",
                [ind("ema", "EMA", 9), ind("sma30", "SMA", 30), ind("sma200", "SMA", 200)],
                {
                    "all_of": [
                        cond("ema", "crosses_above", "sma30"),
                        cond("price.close", "greater_than", "sma200"),
                    ]
                },
                stop=2,
                target=5,
            )
        },
        ["long_side.stop_loss_pct", "long_side.take_profit_pct"],
    ),
    (
        ITEM_37,
        {
            "long_side": side(
                "long",
                [ind("donchian", "DONCHIAN", 20), ind("rsi", "RSI", 14)],
                {
                    "all_of": [
                        cond("price.close", "crosses_above", "donchian.upper"),
                        cond("rsi", "less_than", "70"),
                    ]
                },
                exit=cond("price.close", "crosses_below", "donchian.middle"),
            )
        },
        [],
    ),
    (
        "short when rsi crosses below 70 and (close below 50 sma or close below 20 ema)",
        {
            "short_side": side(
                "short",
                [ind("rsi", "RSI", 14), ind("sma", "SMA", 50), ind("ema", "EMA", 20)],
                {
                    "all_of": [
                        cond("rsi", "crosses_below", "70"),
                        {
                            "any_of": [
                                cond("price.close", "less_than", "sma"),
                                cond("price.close", "less_than", "ema"),
                            ]
                        },
                    ]
                },
                stop=2,
                target=5,
            )
        },
        ["short_side.stop_loss_pct", "short_side.take_profit_pct"],
    ),
    (
        "buy when macd line crosses above macd signal; stop at 1.5%; take profit at 4%",
        {
            "long_side": side(
                "long",
                [ind("macd", "MACD", 12)],
                cond("macd.line", "crosses_above", "macd.signal"),
                stop=1.5,
                target=4,
            )
        },
        [],
    ),
    (
        "go long when close inside bb 20 2. sell when close outside bb 20 2",
        {
            "long_side": side(
                "long",
                [ind("bb", "BB", 20)],
                cond("price.close", "inside_band", "bb"),
                exit=cond("price.close", "outside_band", "bb"),
            )
        },
        [],
    ),
    (
        "BUY when 9 EMA > 30 SMA",
        {
            "long_side": side(
                "long",
                [ind("ema", "EMA", 9), ind("sma", "SMA", 30)],
                cond("ema", "greater_than", "sma"),
                stop=2,
                target=5,
            )
        },
        ["long_side.stop_loss_pct", "long_side.take_profit_pct"],
    ),
    (
        "sell when rsi above 70",
        {
            "long_side": side(
                "long",
                [ind("ema", "EMA", 9), ind("sma", "SMA", 30), ind("rsi", "RSI", 14)],
                cond("ema", "crosses_above", "sma"),
                exit=cond("rsi", "greater_than", "70"),
                optimization=REFERENCE_RANGES,
            )
        },
        [],
    ),
    (
        "buy when 9 ema crosses 30 sma; short when 9 ema crosses 30 sma, stop at 3%",
        {
            "long_side": side(
                "long",
                [ind("ema", "EMA", 9), ind("sma", "SMA", 30)],
                cond("ema", "crosses_above", "sma"),
                stop=2,
                target=5,
            ),
            "short_side": side(
                "short",
                [ind("ema", "EMA", 9), ind("sma", "SMA", 30)],
                cond("ema", "crosses_below", "sma"),
                stop=3,
            ),
        },
        ["long_side.stop_loss_pct", "long_side.take_profit_pct"],
    ),
]


@pytest.mark.parametrize(("text", "sides", "defaults"), CASES, ids=[c[0][:40] for c in CASES])
def test_sentences_build_these_sides(text, sides, defaults):
    reading = read(text, default_strategy())
    assert reading.sides == sides
    assert reading.defaults == defaults


def test_the_operators_sentence_reads_back():
    reading = read(OPERATOR, default_strategy())
    assert reading.reading == (
        "Long entry: EMA 9 crosses above SMA 30 AND close above SMA 200. "
        "Exit: stop loss 2%, take profit 5% (default)"
    )


def span(text, word, nth=0):
    start = -1
    for _ in range(nth + 1):
        start = text.index(word, start + 1)
    return {"start": start, "end": start + len(word), "text": word}


@pytest.mark.parametrize(
    ("text", "message", "unread"),
    [
        ("buy when vwap crosses 30 sma", "didn't understand 'vwap'", ("vwap", 0)),
        ("buy when 9 ema crosses", "crosses needs something on its right", ("crosses", 0)),
        (
            "buy when 9 ema crosses 30 sma, stop at 2",
            "write a stop as a percentage, e.g. 2%",
            ("stop at 2", 0),
        ),
        ("buy when rsi above 70, stop at 2%, stop at 3%", "two stop losses", ("stop at 3%", 0)),
        (
            "buy when donchian crosses 30",
            "donchian has outputs upper, lower, middle: name one, e.g. 'donchian upper'",
            ("donchian", 0),
        ),
        ("buy when close inside rsi", "inside needs a band", ("rsi", 0)),
    ],
)
def test_unread_text_is_refused_naming_it(text, message, unread):
    with pytest.raises(Unread, match=message) as caught:
        read(text, default_strategy())
    assert caught.value.spans == [span(text, *unread)]


def test_levels_alone_change_only_the_levels():
    reading = read("stop at 2%", default_strategy())
    assert reading.reading == "Long side: stop loss 2%"
    assert reading.sides["long_side"] == default_strategy().long_side.model_copy(
        update={"stop_loss_pct": 2.0}
    )


# --- Mission 14: learned phrases and the grammar sent to the AI -------------------------------


def test_learned_phrases_are_read_before_the_grammar():
    text = "buy when 9 ema crosses up 30 sma"
    with pytest.raises(Unread):
        read(text, default_strategy())
    reading = read(text, default_strategy(), learned=[("crosses up", "crosses above")])
    assert reading.sides["long_side"].entry.operator == "crosses_above"


def test_learned_phrases_are_whole_words_longest_first():
    """Review Focus 3: 'cross up' never matches inside 'crosses up'; the longest phrase wins."""
    with pytest.raises(Unread):
        read(
            "buy when 9 ema crosses up 30 sma",
            default_strategy(),
            learned=[("cross up", "crosses above")],
        )
    learned = [("back", "above"), ("crosses back down", "crosses below")]
    reading = read("sell when 9 ema crosses back down 30 sma", default_strategy(), learned=learned)
    assert reading.sides["long_side"].exit.operator == "crosses_below"


def test_unread_spans_point_at_the_original_words():
    text = "buy when 9 ema crosses up vwap"
    with pytest.raises(Unread) as caught:
        read(text, default_strategy(), learned=[("crosses up", "crosses above")])
    (span,) = caught.value.spans
    assert text[span["start"] : span["end"]] == "vwap" == span["text"]


def test_a_comma_or_and_before_an_opener_starts_a_new_clause():
    for joint in (", ", " and "):
        text = f"buy when 9 ema crosses above 30 sma{joint}sell when 9 ema crosses below 30 sma"
        side = read(text, default_strategy()).sides["long_side"]
        assert side.entry.operator == "crosses_above" and side.exit.operator == "crosses_below"


def test_grammar_text_names_every_kind_and_opener():
    from products.aegis.phrases import KIND_WORDS, OPENERS, grammar_text

    grammar = grammar_text()
    for words, _side, _role in OPENERS:
        assert " ".join(words) in grammar
    for word in KIND_WORDS:
        assert word in grammar
    assert "stop at" in grammar and "take profit at" in grammar
