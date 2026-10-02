"""Lossless source delivery, optional product memory, and format-only recovery."""

import hashlib
import json
from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel, ValidationError
from trading_core.evidence_delivery import prepare


class Request:
    role = "REVIEW"
    execution_permissions = ("read",)
    allowed_tools = ("read_file",)

    def __init__(self, packet):
        self.context_packet = packet

    def model_copy(self, update):
        return Request(update["context_packet"])


def test_large_evidence_is_lossless_and_memory_is_optional():
    source = "line with Unicode \u2603\n" * 13000
    memory = {"id": "prior-1", "proposal": {"title": "Retained initiative", "change": "x" * 30000}}
    original = Request(
        {
            "evidence_delivery": "files-v1",
            "sources": {"app/product.py": source},
            "product_planning": {
                "mission": "Build a complete product",
                "history": {"ProductProposal": [memory]},
            },
            "proposal": {"change": "y" * 10000},
        }
    )
    delivered, files, required, proof = prepare(original, {})
    index = proof["manifest"]
    row = next(r for r in index if r["source"] == "app/product.py")
    assert "".join(files[p] for p in row["parts"]) == source
    assert row["sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert set(row["parts"]) <= required
    memory_row = next(r for r in index if r["source"].startswith("memory:"))
    assert not set(memory_row["parts"]) & required
    assert json.loads("".join(files[p] for p in memory_row["parts"])) == memory
    assert all(len(s) <= 6000 for s in files.values())
    assert proof["delivered_context_chars"] < proof["original_context_chars"] / 4
    assert original.context_packet["sources"]["app/product.py"] == source
    assert delivered.context_packet["product_planning"]["mission"] == "Build a complete product"


def test_fail_closed_for_conflicts_write_roles_and_oversize():
    r = Request({"evidence_delivery": "files-v1", "sources": {"one": "different"}})
    with pytest.raises(PermissionError, match="Conflicting"):
        prepare(r, {"one": "original"})
    r.role = "IMPLEMENT"
    with pytest.raises(PermissionError, match="read-only"):
        prepare(r, {})
    with pytest.raises(ValueError, match="physical capacity"):
        prepare(Request({"evidence_delivery": "files-v1", "sources": {"large": "x" * 1000001}}), {})


def test_unopted_requests_unchanged():
    r, files = Request({"facts": "original"}), {"a": "source"}
    assert prepare(r, files) == (r, files, {"a"}, {})


def test_typed_and_legacy_artifacts_validate_identically():
    from products.triad.development import parse_product_artifact

    class Shape(BaseModel):
        value: int

    assert parse_product_artifact(Shape, {"value": 3}) == parse_product_artifact(
        Shape, '{"value":3}'
    )
    with pytest.raises(ValidationError):
        parse_product_artifact(Shape, '{"value":')


@pytest.mark.parametrize("complete", [True, False])
def test_format_repair_does_not_repeat_planning_but_incomplete_output_does(complete):
    from products.triad.development import ProductResponseFormatError
    from products.triad.sequential import SequentialCycle

    class Shape(BaseModel):
        value: int

    calls, records = [], []
    flow = object.__new__(SequentialCycle)
    flow.guard = lambda _: None

    def call(*args, **kw):
        calls.append((args, kw))
        if len(calls) == 1:
            raise ProductResponseFormatError(
                "bad field",
                artifact={"value": "three"} if complete else '{"value":',
                run_id="failed-run",
                usage={"input_tokens": 100},
            )
        return None, None, Shape(value=3), {"run_id": "repaired-run", "input_tokens": 20}

    flow.s = NS(
        call=call,
        record=lambda *a, **k: records.append((a, k)),
        daily=NS(current=lambda _: {"parent_work_item_id": "parent"}),
    )
    flow.call(
        "cycle",
        "CLAUDE",
        "Plan the product",
        {"sources": {"source": "big history"}},
        Shape,
        ("source",),
    )
    sent = calls[1][0][4]
    if complete:
        assert "sources" not in sent and "original_artifact" in sent
        assert calls[1][1]["paths"] == ()
        assert "missing facts" in calls[1][0][3]
    else:
        assert "sources" in sent
    retry = next(k for a, k in records if a[0] == "ProductResponseRetry")
    assert retry["usage"]["input_tokens"] == 100
    assert any(a[0] == "ProductResponseRecovery" for a, _ in records)
