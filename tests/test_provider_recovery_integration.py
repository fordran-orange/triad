"""Automatic runtime adoption reuses reviewed policy, never rewrites static grants."""

# ruff: noqa: F811
from copy import deepcopy

import pytest
from test_agent_model_binding import setup as base_setup
from test_day3_integration import engine  # noqa: F401
from test_intelligence_capabilities import build, qa
from trading_core.intelligence.capabilities import Capabilities
from trading_core.intelligence.quality import Quality
from trading_core.providers.control import ProviderControl
from trading_core.providers.recovery import SOURCE, activate, recover

pytestmark = [pytest.mark.integration, pytest.mark.core]


IDENTITY = {
    "cli_version": "grok fixture",
    "executable_identity": [{"path": "fixture", "sha256": "a" * 64}],
}


def setup(engine):
    result = base_setup(engine)
    _, records, _, _, status, _ = result
    for kind in ("test", "workitem"):
        proof = status[kind]
        proof["runtime_identity"] = IDENTITY
        for identifier in (proof["proof_id"], proof["usage_id"]):
            with records.store.connect() as conn:
                row = conn.execute(
                    "SELECT kind,payload,work_item_id FROM core.day3_records WHERE id=%s",
                    (identifier,),
                ).fetchone()
            records.ledger.put(
                row["kind"],
                {**row["payload"], "runtime_identity": IDENTITY},
                identifier=identifier,
                work_id=row["work_item_id"],
            )
        with records.store.connect() as conn:
            row = conn.execute(
                "SELECT id,payload,work_item_id FROM core.day3_records WHERE kind='TransportRun' AND payload->>'run_id'=%s",
                (proof["run_id"],),
            ).fetchone()
        records.ledger.put(
            "TransportRun",
            {**row["payload"], "runtime_identity": IDENTITY},
            identifier=row["id"],
            work_id=row["work_item_id"],
        )
    status["runtime_identity"] = IDENTITY
    records.ledger.put("TransportStatus", status, identifier="transport-status-grok_build_cli")
    return result


def control_for(records):
    from types import SimpleNamespace

    control = ProviderControl(records.ledger)
    control.transport = lambda _: SimpleNamespace(identity_data=lambda: IDENTITY)
    return control


def approve_policy(records):
    implementation = build(records).model_copy(update={"files": (SOURCE,)})
    # build() already records its original fixture; use a separate exact source record.
    implementation = implementation.model_copy(
        update={"implementation_run_id": __import__("uuid").uuid4().hex}
    )
    Quality(records).implementation(implementation)
    Quality(records).review(qa(implementation))
    return activate(
        records, implementation.implementation_run_id, implementation.change_commit
    ), implementation


def test_automatic_model_adoption_preserves_grant_and_rechecks_revocation(engine):
    agents, records, raw, _request, _status, _ = setup(engine)
    _, implementation = approve_policy(records)
    control = control_for(records)
    recover(control, "grok_build_cli")
    assert agents.get("GROK")["model"] == "grok-4.7"
    assert (
        any(
            v.get("runtime_attestation")
            for v in Capabilities(records).current()
            if v["capability"]["model"] == "grok-4.7"
        )
        is False
    )  # existing reviewed truth wins
    assert len(records.list("ProviderRuntimeAttestation")) == 1
    recover(control, "grok_build_cli")
    assert len(records.list("ProviderRuntimeAttestation")) == 1
    with records.store.connect() as conn:
        assert (
            conn.execute("SELECT definition FROM core.agent_instances WHERE id='GROK'").fetchone()[
                "definition"
            ]
            == raw
        )
    Quality(records).review(
        qa(implementation, decision="CHANGES_REQUIRED", findings=("Revoked",), severity="LOW")
    )
    assert not agents.get("GROK")["execution_eligible"]


def test_new_successful_model_proofs_renew_without_manual_binding(engine):
    agents, records, _raw, _request, status, _ = setup(engine)
    approve_policy(records)
    control = control_for(records)
    recover(control, "grok_build_cli")
    changed = deepcopy(status)
    # Represent a new verified model with new canonical proof IDs and matching run/usage.
    for name in ("test", "workitem"):
        proof = changed[name]
        for identifier in (proof["proof_id"], proof["usage_id"]):
            with records.store.connect() as conn:
                row = conn.execute(
                    "SELECT kind,payload,work_item_id FROM core.day3_records WHERE id=%s",
                    (identifier,),
                ).fetchone()
            records.ledger.put(
                row["kind"],
                {**row["payload"], "actual_model": "grok-4.8"},
                identifier=identifier,
                work_id=row["work_item_id"],
            )
        with records.store.connect() as conn:
            row = conn.execute(
                "SELECT id,payload,work_item_id FROM core.day3_records WHERE kind='TransportRun' AND payload->>'run_id'=%s",
                (proof["run_id"],),
            ).fetchone()
        records.ledger.put(
            "TransportRun",
            {**row["payload"], "actual_model": "grok-4.8"},
            identifier=row["id"],
            work_id=row["work_item_id"],
        )
        proof["actual_model"] = "grok-4.8"
    records.ledger.put("TransportStatus", changed, identifier="transport-status-grok_build_cli")
    recover(control, "grok_build_cli")
    assert agents.get("GROK")["model"] == "grok-4.8", str(
        control.read("provider-recovery-grok_build_cli")
    )
    caps = Capabilities(records).current()
    assert {
        v["capability"]["capability"] for v in caps if v["capability"]["model"] == "grok-4.8"
    } == {"structured_output", "isolated_text_read", "document_analysis"}
