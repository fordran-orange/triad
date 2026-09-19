"""Disposable role rollout gates; production capability probe is never invoked."""
# ruff: noqa: F811

import pytest
from psycopg.errors import RaiseException
from psycopg.types.json import Jsonb
from test_day3_integration import engine  # noqa: F401
from test_intelligence_capabilities import build, qa
from trading_core.engineering import adopt_ui_role
from trading_core.intelligence.agents import Agents
from trading_core.intelligence.capabilities import Capabilities
from trading_core.intelligence.contracts import Capability
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.store import Store
from trading_core.work import now

pytestmark = pytest.mark.integration
MARKER = "engineering-role:CLAUDE:isolated_product_ui_edit"


def setup(engine):
    records = Records(engine.host.store)

    class Proof:
        def snapshot(self, _):
            return {"workitem": {"actual_model": "fixture-model"}}

    Agents(records).seed_static(Proof())
    run = build(records, (MARKER,))
    return records, run


def adopt_capability(records, **updates):
    payload = {
        "provider": "anthropic",
        "model": "fixture-model",
        "transport": "claude_code_cli",
        "capability": "isolated_product_ui_edit",
        "native_or_tool_mediated": "tool_mediated",
        "status": "AVAILABLE",
        "verification_status": "VERIFIED",
        "discovery_source": "runtime",
        "evidence": ("Offline authority fixture; no provider proof claimed",),
        "verified_at": now(),
        "verified_by": "independent fixture",
        "permissions_required": ("write_code",),
    }
    caps = Capabilities(records)
    proposal = caps.propose(Capability(**(payload | updates)), actor="QA fixture")
    implementation = build(records, ("capability:" + records.get(proposal)["digest"],))
    Quality(records).review(qa(implementation))
    caps.approve(proposal, implementation.implementation_run_id, implementation.change_commit)


def definition(records):
    with records.store.connect() as conn:
        return conn.execute(
            "SELECT definition FROM core.agent_instances WHERE id='CLAUDE'"
        ).fetchone()["definition"]


def test_role_rollout_requires_qa_capability_and_preserves_other_fields(engine):
    records, run = setup(engine)
    before = definition(records)
    original_record = records.list("AgentDefinition")
    with pytest.raises(PermissionError):
        adopt_ui_role(records, run.implementation_run_id, run.change_commit)
    Quality(records).review(qa(run))
    with pytest.raises(PermissionError, match="Exact role"):
        adopt_ui_role(records, run.implementation_run_id, run.change_commit)
    Quality(records).review(qa(run, evidence=(MARKER,)))
    for cap in (
        {"verification_status": "CLAIMED"},
        {"model": "different-model"},
        {"status": "RESTRICTED"},
    ):
        adopt_capability(records, **cap)
        with pytest.raises(PermissionError, match="verified capability"):
            adopt_ui_role(records, run.implementation_run_id, run.change_commit)
        assert definition(records) == before
    adopt_capability(records)
    scoped = Records(Store(records.store.settings, scope="triad"))
    with pytest.raises(PermissionError):
        adopt_ui_role(scoped, run.implementation_run_id, run.change_commit)
    with pytest.raises(PermissionError):
        scoped.append("EngineeringRoleAdoption", {}, owner="triad")
    with pytest.raises(PermissionError):
        adopt_ui_role(records, run.implementation_run_id, "wrong-commit")
    adopt_ui_role(records, run.implementation_run_id, run.change_commit)
    assert definition(records) == before
    after = Agents(records).get("CLAUDE")
    assert set(after["execution_permissions"]) == set(before["execution_permissions"]) | {
        "write_code"
    }
    assert set(after["capabilities"]) == set(before["capabilities"]) | {"isolated_product_ui_edit"}
    for key in before.keys() - {"execution_permissions", "capabilities"}:
        assert after[key] == before[key]
    assert records.list("AgentDefinition")[: len(original_record)] == original_record
    assert len(records.list("EngineeringRoleAdoption")) == 1


def test_existing_database_grant_immutability_is_retained(engine):
    records, run = setup(engine)
    Quality(records).review(qa(run, evidence=(MARKER,)))
    adopt_capability(records)
    before = definition(records)
    altered = before | {"role": "helper"}
    with (
        pytest.raises(RaiseException, match="Immutable agent grant"),
        records.store.connect() as conn,
    ):
        conn.execute(
            "UPDATE core.agent_instances SET definition=%s WHERE id='CLAUDE'", (Jsonb(altered),)
        )
    assert definition(records) == before
