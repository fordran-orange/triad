import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from products.triad.sequential import CurrentProposal, Proposal
from products.triad.sequential_mission import insert_panel, mission_statement, render_panel
from pydantic import ValidationError
from test_sequential_planning import plan, proposal
from trading_core.product_changes import product_path


def test_canonical_mission_matches_local_charter_and_is_protected():
    root = Path(__file__).resolve().parents[1]
    charter = json.loads((root / "config/triad/product.json").read_text(encoding="utf-8"))
    assert mission_statement() == charter["mission"]
    assert "TradingView and thinkorswim" in mission_statement()
    assert "multiple days" in mission_statement()
    for path in (
        "app/products/triad/resources/product.json",
        "app/products/triad/sequential_mission.py",
        "config/triad/product.json",
    ):
        with pytest.raises(PermissionError):
            product_path(path)


def test_old_value_plans_round_trip_exactly_but_new_plans_require_mission_assessment():
    historical = plan()
    historical.pop("mission_contribution")
    historical.pop("major_gaps")
    raw = proposal(value_plan=historical)
    # JSON mode reflects original persisted array representation.
    assert Proposal(**raw).model_dump(mode="json")["value_plan"] == historical
    with pytest.raises(ValidationError):
        CurrentProposal(**raw)
    current = CurrentProposal(**proposal(value_plan=plan()))
    restored = Proposal.model_validate(current.model_dump(mode="json"))
    assert restored.model_dump(mode="json") == current.model_dump(mode="json")
    with pytest.raises(ValidationError):
        CurrentProposal(**proposal(value_plan={**plan(), "major_gaps": []}))


def test_panel_labels_evidence_and_escapes_agent_content():
    state = {
        "id": "cycle-x",
        "status": "BUILDING",
        "turns": {"CODEX": "COMPLETED"},
        "proposals": [
            {"agent": "CODEX", "title": "Delivered", "plan": plan()},
            {
                "agent": "CLAUDE",
                "title": "<script>bad()</script>",
                "plan": {**plan(), "major_gaps": ["<img src=x onerror=bad()>"]},
            },
        ],
    }
    html = render_panel(mission_statement(), state)
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html
    assert "COMPLETED" in html and "Proposed; delivery not verified" in html
    assert "No proposal recorded" in html
    assert "agent assessment" in html
    state["proposals"][0]["plan"] = {}
    assert "Not assessed in this historical plan" in render_panel("Mission", state)


def test_mission_survives_progress_outage(monkeypatch):
    from products.triad import sequential_mission as module

    def fail():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(module, "progress", fail)
    html = module.mission_panel()
    assert "TradingView and thinkorswim" in html
    assert "temporarily unavailable" in html
    assert "database unavailable" not in html


@pytest.mark.parametrize("source", ['<MAIN class="workspace">X</MAIN>', "<body>X</body>", "X"])
def test_mission_survives_product_layout_changes(source):
    assert (
        insert_panel(source, "<section>Mission</section>").count("<section>Mission</section>") == 1
    )
    assert "X" in insert_panel(source, "<section>Mission</section>")


def test_progress_queries_only_latest_cycle_and_triad_owner(monkeypatch):
    from products.triad.sequential_mission import progress
    from trading_core.store import Store

    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, args=None):
            calls.append((sql, args))
            assert "owner='triad'" in sql
            if "kind='CycleRecord'" in sql:
                assert "LIMIT 1" in sql and "SELECT payload " not in sql
                return SimpleNamespace(fetchone=lambda: {"id": "latest", "status": "INSPECTING"})
            assert args == ("latest",)
            return SimpleNamespace(fetchall=list)

    monkeypatch.setattr(Store, "connect", lambda self: Connection())
    assert progress() == {"id": "latest", "status": "INSPECTING", "proposals": [], "turns": {}}
    assert len(calls) == 3
