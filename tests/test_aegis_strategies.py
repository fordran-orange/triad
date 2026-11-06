"""Strategy documents (Mission 5 spec §8): the library over the JSON repository, offline."""

import json

import pytest
from products.aegis.runs import JsonRunRepository
from products.aegis.strategies import (
    BUILTIN_ID,
    BuiltinRefused,
    StrategyConflict,
    StrategyLibrary,
    StrategyReferenced,
    slug,
)
from products.aegis.strategy import default_strategy

pytestmark = pytest.mark.aegis


@pytest.fixture
def library(tmp_path):
    return StrategyLibrary(JsonRunRepository(tmp_path / "aegis"))


def test_slug_is_lowercase_dashed_and_never_empty():
    assert slug("Donchian Breakout / RSI < 70") == "donchian-breakout-rsi-70"
    assert slug("  --  ") == "strategy"
    assert slug("日本") == "strategy"
    assert len(slug("x" * 200)) == 48


def test_create_names_the_spec_after_the_document(library):
    doc = library.create("Donchian Breakout", default_strategy())
    assert doc.id == "donchian-breakout" and doc.name == "Donchian Breakout"
    assert doc.spec.id == doc.id and doc.spec.name == doc.name
    assert len(doc.strategy_hash) == 64 and doc.created_at == doc.updated_at
    assert doc.parent is None and doc.builtin is False
    assert library.get(doc.id) == doc


def test_slug_collisions_get_a_hash_suffix(library):
    first = library.create("Breakout", default_strategy())
    second = library.create("Breakout", default_strategy())
    assert first.id == "breakout"
    assert second.id.startswith("breakout-") and len(second.id) == len("breakout-") + 6
    assert library.create("ema9 sma30 cross v1", default_strategy()).id != BUILTIN_ID


def test_update_changes_the_spec_hash_and_updated_at(library):
    doc = library.create("Breakout", default_strategy())
    spec = doc.spec.model_copy(update={"description": "edited"})
    updated = library.update(doc.id, spec=spec, updated_at=doc.updated_at)
    assert updated.strategy_hash != doc.strategy_hash
    assert updated.updated_at >= doc.updated_at and updated.created_at == doc.created_at
    renamed = library.update(doc.id, name="Breakout v2", updated_at=updated.updated_at)
    assert renamed.name == "Breakout v2" and renamed.spec.name == "Breakout v2"
    assert renamed.id == doc.id and renamed.spec.id == doc.id


def test_duplicate_records_its_parent(library):
    doc = library.create("Breakout", default_strategy())
    copy = library.duplicate(doc.id, "Breakout copy")
    assert copy.parent == doc.id and copy.id == "breakout-copy"
    assert copy.spec.long_side == doc.spec.long_side
    assert library.duplicate(BUILTIN_ID, "From the reference").parent == BUILTIN_ID


def test_builtin_is_listed_byte_identical_and_read_only(library):
    builtin = library.get(BUILTIN_ID)
    assert builtin.builtin is True and builtin.created_at is None
    assert json.dumps(builtin.spec.model_dump(mode="json"), sort_keys=True) == json.dumps(
        default_strategy().model_dump(mode="json"), sort_keys=True
    )
    assert library.list()[0]["id"] == BUILTIN_ID
    with pytest.raises(BuiltinRefused):
        library.update(BUILTIN_ID, name="mine now", updated_at=None)
    with pytest.raises(BuiltinRefused):
        library.delete(BUILTIN_ID)


def test_list_summarizes_kinds_and_usage(library):
    doc = library.create("Breakout", default_strategy())
    item = next(i for i in library.list() if i["id"] == doc.id)
    assert item["kinds"] == ["EMA", "SMA"]
    assert item["usage"] == {"runs": 0, "optimizations": 0, "walkforwards": 0}
    assert "spec" not in item


def test_a_mission3_shaped_run_counts_as_a_reference(library):
    """Review Focus 1: envelopes written before Mission 5 carry no strategy_id, only strategy.id."""
    doc = library.create("Breakout", default_strategy())
    library.repository.save_run(
        {
            "run_id": "old-run",
            "created_at": "2026-10-09T01:00:00+00:00",
            "result_hash": "h",
            "data": {},
            "strategy": doc.spec.model_dump(mode="json"),
        }
    )
    assert library.usage(doc.id) == {"runs": 1, "optimizations": 0, "walkforwards": 0}
    with pytest.raises(StrategyReferenced, match="referenced by 1 run, 0 optimizations"):
        library.delete(doc.id)


def test_delete_removes_an_unreferenced_document(library):
    doc = library.create("Breakout", default_strategy())
    library.delete(doc.id)
    with pytest.raises(KeyError):
        library.get(doc.id)
    with pytest.raises(KeyError):
        library.delete(doc.id)


def test_get_lets_a_document_that_no_longer_parses_through_as_a_validation_error(library, tmp_path):
    from pydantic import ValidationError

    doc = library.create("Breakout", default_strategy())
    import gzip

    from products.aegis.runs import JsonRunRepository, document_path

    path = document_path(tmp_path / "aegis" / "strategies", doc.id)
    assert path is not None and path.name.endswith(".json.gz")  # Mission 11
    raw = JsonRunRepository._read(path)
    raw["spec"]["long_side"]["entry"]["right"] = "nope"
    path.write_bytes(gzip.compress(json.dumps(raw).encode("utf-8")))
    with pytest.raises(ValidationError):
        library.get(doc.id)
    with pytest.raises(KeyError):  # an unknown id is still unknown, not a parse failure
        library.get("never-saved")


# --- Mission 13: the builder's canvas is saved beside the strategy --------------------------

CANVAS = {
    "version": 1,
    "long": {
        "blocks": [{"id": "entry", "type": "entry", "x": 690, "y": 0, "settings": {}}],
        "wires": [],
    },
    "short": {"blocks": [], "wires": []},
}


def test_the_canvas_is_kept_outside_the_hash(library):
    doc = library.create("Breakout", default_strategy())
    updated = library.update(doc.id, canvas=CANVAS, updated_at=doc.updated_at)
    assert updated.canvas == CANVAS and updated.strategy_hash == doc.strategy_hash
    assert library.get(doc.id).canvas == CANVAS
    respec = library.update(
        doc.id,
        spec=doc.spec.model_copy(update={"description": "edited"}),
        updated_at=updated.updated_at,
    )
    assert respec.canvas == CANVAS  # a spec saved without a canvas keeps the saved one


def test_a_document_without_a_canvas_dumps_without_one(library):
    doc = library.create("Breakout", default_strategy())
    assert "canvas" not in doc.model_dump(mode="json")
    assert "canvas" not in library.repository.get_strategy(doc.id)


def test_a_canvas_over_256_kb_is_refused(library):
    doc = library.create("Breakout", default_strategy())
    big = {**CANVAS, "short": {"blocks": [], "wires": [], "note": "x" * 262_144}}
    with pytest.raises(ValueError, match="canvas too large"):
        library.update(doc.id, canvas=big, updated_at=doc.updated_at)


def test_duplicate_copies_the_canvas(library):
    doc = library.create("Breakout", default_strategy())
    library.update(doc.id, canvas=CANVAS, updated_at=doc.updated_at)
    assert library.duplicate(doc.id, "Breakout copy").canvas == CANVAS


def test_update_refuses_a_document_saved_since_it_was_loaded(library, monkeypatch):
    """Mission 13 review I3: two tabs edit one strategy. A save carries the `updated_at` of the
    document it loaded; the second save, made from the state the first replaced, is refused and
    changes nothing. `updated_at` moves on every write whatever the clock says, so the refusal
    cannot be missed by two saves inside one tick (or a clock set back)."""
    import products.aegis.strategies as module

    doc = library.create("Breakout", default_strategy())
    monkeypatch.setattr(module, "_now", lambda: doc.updated_at)  # a clock that does not move
    first = library.update(doc.id, name="Tab A", updated_at=doc.updated_at)
    assert first.updated_at > doc.updated_at
    with pytest.raises(StrategyConflict, match="saved elsewhere since you opened it; reload"):
        library.update(doc.id, name="Tab B", updated_at=doc.updated_at)
    assert library.get(doc.id) == first
    second = library.update(doc.id, name="Tab B", updated_at=first.updated_at)
    assert second.name == "Tab B" and second.updated_at > first.updated_at
