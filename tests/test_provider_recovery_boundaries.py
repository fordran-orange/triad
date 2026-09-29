"""Recovery uses canonical owners, existing authority and bounded retries."""

# ruff: noqa: F811
import hashlib
from types import SimpleNamespace

import pytest
from test_day3_integration import engine  # noqa: F401
from test_intelligence_capabilities import qa
from test_provider_recovery_integration import IDENTITY, approve_policy, control_for, setup
from trading_core.intelligence.quality import Quality
from trading_core.providers.recovery import recover
from trading_core.providers.recovery_probe import probe_write, validate_write
from trading_core.runtime import Runtime

pytestmark = pytest.mark.integration


def test_unverified_installation_cannot_execute_legacy_work(engine, monkeypatch):
    from trading_core.contracts import AgentRunRequest, AgentRunResult
    from trading_core.runtime import ProviderError
    from trading_core.work import WorkItem

    work = engine.host.create(
        WorkItem(
            title="Legacy read fixture",
            description="No inference",
            assigned_agent="CODEX",
            reviewer="GROK",
            work_type="review",
            authority_tier=0,
            allowed_tools=("read_file",),
            allowed_paths=("README.md",),
            execution_permissions=("read",),
        )
    )
    work, policy = engine.start_work(work)
    request = AgentRunRequest(
        agent_id="CODEX",
        work_item_id=work.work_item_id,
        mission_id=work.mission_id,
        role="REVIEW",
        objective="No inference",
        acceptance_criteria=work.acceptance_criteria,
        context_packet={},
        allowed_tools=("read_file",),
        allowed_paths=work.allowed_paths,
        execution_permissions=("read",),
        reasoning_budget=512,
        token_budget=512,
        policy_decision=policy.model_dump(mode="json"),
        required_output_schema=AgentRunResult.model_json_schema(),
        control_epoch=engine.ledger.control()["epoch"],
    )
    adapter = SimpleNamespace(
        transport_type="CLI",
        transport_id="codex_cli",
        identity_data=lambda: {"new": True},
        control=SimpleNamespace(
            snapshot=lambda _: {
                "test": {"runtime_identity": {"old": True}},
                "workitem": {"runtime_identity": {"old": True}},
            },
            proven=lambda _: True,
        ),
    )
    monkeypatch.setattr("trading_core.providers.control.TransportRouter.select", lambda *a: adapter)
    with pytest.raises(ProviderError, match="RuntimeCompatibilityCheckRequired"):
        engine.runtime.execute(request)
    assert not engine.ledger.records("Usage")


def test_revoked_policy_stops_before_verification(engine, monkeypatch):
    _, records, _, _, _, _ = setup(engine)
    _, implementation = approve_policy(records)
    Quality(records).review(
        qa(implementation, decision="CHANGES_REQUIRED", findings=("revoked",), severity="LOW")
    )
    monkeypatch.setattr(
        "trading_core.providers.verification.verify",
        lambda *a, **kw: pytest.fail("Revoked recovery ran inference"),
    )
    with pytest.raises(PermissionError):
        recover(control_for(records), "grok_build_cli")


def test_failed_probe_has_cooldown_and_one_transition_event(engine, monkeypatch):
    _, records, _, _, status, _ = setup(engine)
    approve_policy(records)
    control = control_for(records)
    records.ledger.put(
        "TransportStatus",
        {**status, "test": None, "workitem": None},
        identifier="transport-status-grok_build_cli",
    )
    calls = []
    monkeypatch.setattr(
        "trading_core.providers.verification.verify",
        lambda *a, **kw: calls.append(kw) or {"success": False, "error": "ProtocolMismatch"},
    )
    recover(control, "grok_build_cli")
    recover(control, "grok_build_cli")
    assert len(calls) == 1
    assert calls[0]["expected_epoch"] == records.ledger.control()["epoch"]
    assert control.read("provider-recovery-grok_build_cli")["status"] == "BLOCKED"
    assert (
        len(
            [
                e
                for e in records.ledger.records("Event", 1000)
                if e.get("event") == "provider_recovery_blocked"
            ]
        )
        == 1
    )


def test_installation_swap_during_recovery_cannot_publish(engine):
    _, records, _, _, _, _ = setup(engine)
    approve_policy(records)
    control = control_for(records)
    control.transport = lambda _: SimpleNamespace(identity_data=lambda: {"changed": True})
    recover(control, "grok_build_cli")
    assert not records.list("ProviderRuntimeAttestation")
    assert "changed during" in control.read("provider-recovery-grok_build_cli")["message"]


@pytest.mark.parametrize("engineering", [False, True])
def test_staging_probe_preserves_product_owner_and_validates_canonical_evidence(
    engine, monkeypatch, engineering
):
    _, records, raw, _, _, _ = setup(engine)
    if engineering:
        with records.store.connect() as conn:
            raw = conn.execute(
                "SELECT definition FROM core.agent_instances WHERE id='CLAUDE'"
            ).fetchone()["definition"]
    baseline = {
        "templates": [
            {
                "capability": {
                    "capability": "isolated_product_ui_edit"
                    if engineering
                    else "isolated_text_proposal"
                }
            }
        ]
    }

    def execute(runtime, request, **kwargs):
        assert kwargs["compatibility_probe"] is True
        work = runtime.ledger.store.get(request.work_item_id)
        assert (
            "write_code" in work.execution_permissions
            if engineering
            else "write_research" in work.execution_permissions
        )
        path = (
            "app/products/triad/features/provider_compatibility_probe.html"
            if engineering
            else "docs/provider_compatibility_probe.md"
        )
        content = (
            "<h1>Provider compatibility verified</h1>"
            if engineering
            else "Provider compatibility verified"
        )
        common = {
            "run_id": request.run_id,
            "agent": raw["agent_id"],
            "provider": raw["provider"],
            "transport": raw["preferred_transport"],
            "actual_model": "fixture-model",
            "status": "SUCCESS",
            "billing_source": "SUBSCRIPTION",
            "runtime_identity": IDENTITY,
        }
        runtime.ledger.put(
            "TransportRun",
            common,
            identifier="transport-run-" + request.run_id,
            work_id=work.work_item_id,
        )
        runtime.ledger.put(
            "Usage", {**common, "mode": "REAL", "usage_known": True}, work_id=work.work_item_id
        )
        runtime.ledger.event(
            "native_executor_evidence",
            work.work_item_id,
            run_id=request.run_id,
            boundary="DOCKER_OFFLINE_TOOLS",
            calls=[{"tool": "propose_file_change", "path": path}],
        )
        return SimpleNamespace(files_changed=[SimpleNamespace(path=path, content=content)])

    monkeypatch.setattr(Runtime, "execute", execute)
    monkeypatch.setattr(
        "trading_core.providers.recovery_probe.run_approved_checks",
        lambda grant, files, script, **kw: {
            "status": "PASS",
            "exit_code": 0,
            "test_sha256": hashlib.sha256(script.encode()).hexdigest(),
            "snapshot": {p: hashlib.sha256(v.encode()).hexdigest() for p, v in files.items()},
        },
    )
    identifier = probe_write(
        control_for(records), raw, baseline, epoch=records.ledger.control()["epoch"]
    )
    value = {"write_proof": identifier, "model": "fixture-model", "runtime_identity": IDENTITY}
    with records.store.connect() as conn:
        validate_write(records, raw, value, conn=conn, require_engineering=engineering)
        with pytest.raises(PermissionError):
            validate_write(
                records,
                raw,
                {**value, "runtime_identity": {"changed": True}},
                conn=conn,
                require_engineering=engineering,
            )
