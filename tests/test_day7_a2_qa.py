"""Independent regressions for Aegis alias context and response encoding."""

import pytest
from fastapi.testclient import TestClient
from trading_core.context import packet_for
from trading_core.work import WorkItem, now

pytestmark = pytest.mark.core


@pytest.mark.parametrize("kind", ["journals", "handoffs", "decisions"])
def test_shared_nonproduct_records_do_not_break_private_context(kind):
    work = WorkItem(owner="aegis", title="Private context", description="Preserve scope")
    record = {"owner": "shared", "mission_id": work.mission_id, "work_item_id": None}
    packet = packet_for(work, **{kind: [record]})
    assert not packet.recent_journal_entries
    assert not packet.prior_handoff
    assert not packet.relevant_decisions


def test_legacy_context_retains_identity_without_foreign_product_content():
    work = WorkItem(owner="aegis", title="Current work", description="Legacy context")
    base = {
        "mission_id": work.mission_id,
        "journal_id": "legacy-context",
        "timestamp": now(),
        "agent": "CODEX",
    }
    packet = packet_for(
        work,
        journals=[
            {**base, "owner": "p2p", "results": "LEGACY_PRIVATE"},
            {**base, "owner": "triad", "results": "FOREIGN_PRIVATE"},
        ],
    )
    assert [p.text for p in packet.recent_journal_entries] == ["LEGACY_PRIVATE"]
    assert "FOREIGN_PRIVATE" not in packet.model_dump_json()


def test_aegis_html_response_matches_declared_utf8_encoding():
    from products.aegis.server import app

    response = TestClient(app).get("/aegis")
    assert response.status_code == 200
    assert "charset=utf-8" in response.headers["content-type"]
    text = response.content.decode("utf-8", errors="strict")
    assert "Aegis" in text
    assert "\ufffd" not in text
