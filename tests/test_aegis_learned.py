"""Mission 14: learned phrases (spec §4.3, with the planning rulings on rules 2 and 4). A substitution
an applied AI reading used is kept only when it is context-free and the AI's substitutions really
explain its rewrite; every applied reading is kept as an example."""

import json

import pytest
from products.aegis.learned import LearnedPhrases
from products.aegis.phrases import read
from products.aegis.strategy import default_strategy

pytestmark = pytest.mark.aegis

PROVENANCE = {"provider": "claude", "model": "claude-sonnet-5", "run_id": "run-1"}
SENTENCE = "buy when 9 ema crosses up 30 sma, exit when it crosses back down"
REWRITE = "buy when 9 ema crosses above 30 sma; sell when 9 ema crosses below 30 sma"


def sub(frm, to):
    return {"from": frm, "to": to}


@pytest.fixture
def phrases(tmp_path):
    return LearnedPhrases(tmp_path / "aegis")


def learn(phrases, text, rewrite, substitutions):
    return phrases.learn(text, rewrite, substitutions, PROVENANCE, default_strategy())


def test_crosses_up_is_learned(phrases):
    kept = learn(
        phrases,
        SENTENCE,
        REWRITE,
        [
            sub("crosses up", "crosses above"),
            sub("exit", "sell"),
            sub("it", "9 ema"),
            sub("crosses back down", "crosses below 30 sma"),
        ],
    )
    assert [(e["from"], e["to"]) for e in kept] == [("crosses up", "crosses above")]
    (entry,) = phrases.list()
    assert entry["example"] == SENTENCE and entry["provider"] == "claude" and entry["id"]


def test_a_pronoun_mapping_is_not_learned(phrases):
    kept = learn(
        phrases,
        "buy when rsi 14 drops under 30, sell when it rises over 70",
        "buy when rsi 14 is below 30; sell when rsi 14 is above 70",
        [sub("drops under", "is below"), sub("it", "rsi 14"), sub("rises over", "is above")],
    )
    assert sorted(e["from"] for e in kept) == ["drops under", "rises over"]


def test_a_phrase_of_known_words_only_is_never_learned(phrases):
    kept = learn(
        phrases,
        "buy when 9 ema crosses above 30 sma and close is above 200 sma",
        "buy when 9 ema crosses above 30 sma and open is above 200 sma",
        [sub("close", "open")],
    )
    assert kept == [] and phrases.list() == []


def test_a_substitution_absent_from_the_text_is_dropped(phrases):
    kept = learn(
        phrases,
        "buy when 9 ema crosses up 30 sma",
        "buy when 9 ema crosses above 30 sma",
        [sub("crosses up", "crosses above"), sub("goes up", "is above")],
    )
    assert [e["from"] for e in kept] == ["crosses up"]


def test_substitutions_that_do_not_explain_the_rewrite_teach_nothing(phrases):
    kept = learn(
        phrases,
        "buy when 9 ema crosses up 30 sma",
        "buy when 9 ema crosses above 30 sma",
        [sub("crosses up", "crosses below")],  # does not give the rewrite's sides
    )
    assert kept == [] and phrases.list() == []


def test_a_newer_meaning_replaces_the_older(phrases):
    learn(
        phrases,
        "buy when 9 ema crosses up 30 sma",
        "buy when 9 ema crosses above 30 sma",
        [sub("crosses up", "crosses above")],
    )
    learn(
        phrases,
        "buy when 9 ema crosses up 30 sma",
        "buy when 9 ema crosses below 30 sma",
        [sub("crosses up", "crosses below")],
    )
    assert [(e["from"], e["to"]) for e in phrases.list()] == [("crosses up", "crosses below")]


def test_remove(phrases):
    (entry,) = learn(
        phrases,
        "buy when 9 ema crosses up 30 sma",
        "buy when 9 ema crosses above 30 sma",
        [sub("crosses up", "crosses above")],
    )
    phrases.remove(entry["id"])
    assert phrases.list() == [] and phrases.pairs() == []
    with pytest.raises(KeyError):
        phrases.remove(entry["id"])


def test_every_applied_reading_is_kept_as_an_example(phrases):
    learn(
        phrases,
        "buy when 9 ema crosses up 30 sma",
        "buy when 9 ema crosses above 30 sma",
        [sub("crosses up", "crosses above")],
    )
    learn(
        phrases,
        "buy when 9 ema crosses up 30 sma",
        "buy when 9 ema crosses above 30 sma",
        [sub("crosses up", "crosses below")],
    )
    examples = phrases.examples()
    assert [e["rewrite"] for e in examples] == ["buy when 9 ema crosses above 30 sma"] * 2
    assert (
        examples[0]["text"] == "buy when 9 ema crosses up 30 sma"
        and examples[0]["model"] == "claude-sonnet-5"
    )
    assert len(examples[1]["learned"]) == 0 and len(examples[0]["learned"]) == 1


def test_examples_are_the_newest_twenty(phrases):
    for n in range(25):
        learn(
            phrases,
            f"buy when rsi {n + 2} goes over 70",
            f"buy when rsi {n + 2} is above 70",
            [sub("goes over", "is above")],
        )
    examples = phrases.examples()
    assert len(examples) == 20 and examples[-1]["text"] == "buy when rsi 26 goes over 70"
    lines = (phrases.folder / "examples.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 25 and json.loads(lines[0])["text"] == "buy when rsi 2 goes over 70"


def test_learned_phrases_make_the_reader_read_the_sentence(phrases):
    learn(
        phrases,
        SENTENCE,
        REWRITE,
        [
            sub("crosses up", "crosses above"),
            sub("it", "9 ema"),
            sub("crosses back down", "crosses below 30 sma"),
            sub("exit", "sell"),
        ],
    )
    reading = read("buy when 9 ema crosses up 30 sma", default_strategy(), learned=phrases.pairs())
    assert reading.reading.startswith("Long entry: EMA 9 crosses above SMA 30.")


# -- the milestone review and QA (2026-10-28): rule 2 counts numbers and symbols as known ----------
@pytest.mark.parametrize(
    ("text", "rewrite", "substitution", "already_read"),
    [
        (
            "buy when 9 ema crosses 200 sma",
            "buy when 9 ema crosses sma",
            sub("200 sma", "sma"),
            "buy when 9 ema crosses 200 sma",
        ),
        (
            "buy when close > 30",
            "buy when close below 30",
            sub(">", "below"),
            "buy when close > 30",
        ),
        (
            "buy when 9 ema 30 sma",
            "buy when 9 ema crosses above 30 sma",
            sub("9 ema", "9 ema crosses above"),
            "sell when 9 ema crosses below 30 sma",
        ),
    ],
)
def test_a_phrase_of_numbers_symbols_and_known_words_is_never_learned(
    phrases, text, rewrite, substitution, already_read
):
    """A learned phrase never changes a sentence the reader already read (spec §4.3 rule 2): a
    number or a symbol is a word the reader knows, so it brings nothing new."""
    before = read(already_read, default_strategy()).reading
    assert learn(phrases, text, rewrite, [substitution]) == [] and phrases.list() == []
    assert read(already_read, default_strategy(), learned=phrases.pairs()).reading == before


def test_an_unreadable_character_counts_as_new(phrases):
    kept = learn(
        phrases,
        "buy when 9 ema → 30 sma",
        "buy when 9 ema crosses above 30 sma",
        [sub("→", "crosses above")],
    )
    assert [(e["from"], e["to"]) for e in kept] == [("→", "crosses above")]


def test_the_same_from_listed_twice_keeps_the_meaning_that_explained_the_rewrite(phrases):
    kept = learn(
        phrases,
        "buy when 9 ema crosses up 30 sma",
        "buy when 9 ema crosses above 30 sma",
        [sub("crosses up", "crosses above"), sub("crosses up", "crosses below")],
    )
    assert [(e["from"], e["to"]) for e in kept] == [("crosses up", "crosses above")]


def test_a_torn_examples_line_is_skipped(phrases):
    learn(
        phrases,
        "buy when 9 ema crosses up 30 sma",
        "buy when 9 ema crosses above 30 sma",
        [sub("crosses up", "crosses above")],
    )
    with phrases.examples_path.open("a", encoding="utf-8") as stream:
        stream.write('{"text": "cut')
    examples = phrases.examples()
    assert [e["text"] for e in examples] == ["buy when 9 ema crosses up 30 sma"]
