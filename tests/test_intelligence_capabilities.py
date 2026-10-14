"""Real persistence, independent revision QA and shared capability read boundaries."""
# ruff: noqa: F811

import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core.intelligence.capabilities import Capabilities
from trading_core.intelligence.contracts import Capability, ImplementationRun, QARun
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.store import Store
from trading_core.work import WorkItem, now

pytestmark = [pytest.mark.integration, pytest.mark.core]


def capability(**changes):
    data = {
        "provider": "xai",
        "model": "example",
        "transport": "grok_build_cli",
        "capability": "native_x_access",
        "native_or_tool_mediated": "native",
        "status": "RESTRICTED",
        "verification_status": "CLAIMED",
        "discovery_source": "documentation",
        "limitations": ("Not enabled in this runtime",),
    }
    return Capability(**{**data, **changes})


def build(records, evidence=(), owner="core"):
    value = ImplementationRun(
        owner=owner,
        builder="builder",
        provider="host",
        model="test",
        transport="host",
        base_commit="base",
        change_commit="revision-a",
        files=("registry",),
        tests=("checks",),
        evidence=evidence,
    )
    Quality(records).implementation(value)
    return value


def qa(value, **updates):
    data = {
        "implementation_run_id": value.implementation_run_id,
        "qa_agent": "independent-reviewer",
        "qa_provider": "host",
        "qa_model": "test",
        "reviewed_commit": value.change_commit,
        "agent_capabilities_used": ("review",),
        "tests_repeated": ("regression",),
        "evidence": ("test-log",),
        "decision": "PASS",
        "execution_mode": "HOST_INDEPENDENT_QA",
    }
    return QARun(**{**data, **updates})


def test_registry_changes_require_exact_update_qa(engine):
    records = Records(engine.host.store)
    caps, quality = Capabilities(records), Quality(records)
    proposed = caps.propose(capability(), actor="operator")
    data = records.get(proposed)
    wrong = build(records)
    quality.review(qa(wrong))
    with pytest.raises(PermissionError):
        caps.approve(proposed, wrong.implementation_run_id, "revision-a")
    implementation = build(records, ("capability:" + data["digest"],))
    with pytest.raises(PermissionError):
        caps.approve(proposed, implementation.implementation_run_id, "revision-a")
    quality.review(qa(implementation, optional_improvements=("Extend discovery later",)))
    identifier = caps.approve(proposed, implementation.implementation_run_id, "revision-a")
    assert caps.current()[0]["capability"]["verification_status"] == "CLAIMED"
    assert records.list("QualityDebt")[0]["status"] == "OPEN"
    with pytest.raises(ValueError):
        caps.approve(proposed, implementation.implementation_run_id, "revision-a")
    for product in ("aegis", "triad"):
        scoped = Records(Store(engine.host.store.settings, scope=product))
        assert scoped.get(identifier)["review_status"] == "APPROVED"
        assert Capabilities(scoped).current()[0]["id"] == identifier
        with pytest.raises(PermissionError):
            Capabilities(scoped).approve(
                proposed, implementation.implementation_run_id, "revision-a"
            )


def test_independent_qa_is_append_only_revision_bound_and_latest_verdict_wins(engine):
    import psycopg

    records = Records(engine.host.store)
    quality = Quality(records)
    implementation = build(records)
    with pytest.raises(PermissionError):
        quality.review(qa(implementation, qa_agent="builder"))
    with pytest.raises(PermissionError):
        quality.review(qa(implementation, reviewed_commit="stale"))
    quality.review(qa(implementation))
    assert quality.require_pass(implementation.implementation_run_id, "revision-a")
    quality.review(qa(implementation, decision="CHANGES_REQUIRED", required_changes=("Fix",)))
    with pytest.raises(PermissionError):
        quality.require_pass(implementation.implementation_run_id, "revision-a")
    with pytest.raises(psycopg.errors.RaiseException), records.store.connect() as conn:
        conn.execute(
            "UPDATE core.intelligence_records SET payload='{}' WHERE id=%s",
            (implementation.implementation_run_id,),
        )


def test_products_propose_only_for_own_work_and_cannot_publish_truth(engine):
    records = Records(Store(engine.host.store.settings, scope="triad"))
    caps = Capabilities(records)
    work = WorkItem(owner="triad", title="inspect", description="inspect", assigned_agent="CODEX")
    records.store.create(work)
    with pytest.raises(PermissionError):
        caps.propose(capability(), actor="CLAUDE", work_id=work.work_item_id)
    identifier = caps.propose(capability(), actor="CODEX", work_id=work.work_item_id)
    assert records.get(identifier)["review_status"] == "PENDING"
    assert caps.current() == []
    with pytest.raises(PermissionError):
        Records(Store(engine.host.store.settings, scope="aegis")).get(identifier)


def test_runtime_discovery_is_narrow_and_requires_actual_proof(engine):
    from trading_core.providers.contracts import SPECS

    class Observed:
        def snapshot(self, transport):
            if transport != "grok_build_cli":
                return {}
            return {
                "workitem": {
                    "success": True,
                    "mode": "REAL",
                    "actual_model": "grok-observed",
                    "proof_id": "proof",
                    "run_id": "run",
                    "completed_at": now().isoformat(),
                    "billing_source": "SUBSCRIPTION",
                    "latency": 12,
                }
            }

    assert "grok_build_cli" in SPECS
    discoveries = Capabilities(Records(engine.host.store)).discover_runtime(Observed())
    assert {c.capability for c in discoveries} == {
        "structured_output",
        "isolated_text_read",
        "document_analysis",
    }
    assert all(c.verification_status == "VERIFIED" for c in discoveries)
