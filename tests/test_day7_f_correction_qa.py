"""Offline fixtures exercise REAL-mode authority; no real-market data is claimed."""
# ruff: noqa: F811

import json

import pytest
from test_day3_integration import engine  # noqa: F401
from test_day7_de_qa import approve
from test_day7_f_qa import setup
from test_intelligence_capabilities import qa
from trading_core.integrations.registry import definition_fingerprint
from trading_core.intelligence.contracts import ImplementationRun
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.research.data import FixtureProvider

pytestmark = pytest.mark.integration


def adopted(engine, tmp_path):
    access, adapter, req = setup(engine, tmp_path)
    registry = access.registry
    identifier = approve(registry)
    run = ImplementationRun(
        owner="core",
        builder="fixture-builder",
        provider="host",
        model="fixture",
        transport="host",
        base_commit="base",
        change_commit="fixture-adapter-commit",
        files=("app/trading_core/integrations/fixture.py",),
        tests=("Fixture test",),
        evidence=(),
    )
    adapter.data_mode = "REAL"
    adapter.definition = adapter.definition.model_copy(
        update={
            "provider": "Synthetic provider",
            "candidate_id": identifier,
            "implementation_run_id": run.implementation_run_id,
            "implementation_commit": run.change_commit,
        }
    )
    run = run.model_copy(
        update={
            "evidence": (
                "integration-candidate:" + identifier,
                "integration-definition-sha256:" + definition_fingerprint(adapter.metadata()),
            )
        }
    )
    registry.host.append("IntegrationDefinition", adapter.metadata(), owner="core")
    Quality(registry.host).implementation(run)
    Quality(registry.host).review(qa(run))
    registry.mark_implemented(
        identifier, adapter.definition.integration_id, run.implementation_run_id, run.change_commit
    )
    return access, adapter, req.model_copy(update={"mode": "REAL"}), identifier


def test_exact_adoption_allows_offline_real_mode_path_and_deprecation_blocks(engine, tmp_path):
    access, adapter, req, identifier = adopted(engine, tmp_path)
    manifest = access.ingest(adapter, req, operator_authorized=True)[0]
    assert manifest.mode == "REAL" and manifest.row_count == 5
    access.registry.decide(identifier, "DEPRECATED", "Retire fixture adapter")
    with pytest.raises(PermissionError):
        access.ingest(adapter, req, operator_authorized=True)


def test_unadopted_core_build_cannot_borrow_prior_candidate_adoption(engine, tmp_path):
    access, adapter, req, _ = adopted(engine, tmp_path)
    unrelated = ImplementationRun(
        owner="core",
        builder="another-builder",
        provider="host",
        model="fixture",
        transport="host",
        base_commit="base",
        change_commit="unadopted-commit",
        files=("docs/unrelated.md",),
        tests=("Unrelated host test",),
        evidence=("integration-definition-sha256:" + definition_fingerprint(adapter.metadata()),),
    )
    Quality(access.registry.host).implementation(unrelated)
    Quality(access.registry.host).review(qa(unrelated))
    adapter.definition = adapter.definition.model_copy(
        update={
            "implementation_run_id": unrelated.implementation_run_id,
            "implementation_commit": unrelated.change_commit,
        }
    )
    access.registry.host.append("IntegrationDefinition", adapter.metadata(), owner="core")
    with pytest.raises(PermissionError):
        access.ingest(adapter, req, operator_authorized=True)


def test_deprecation_between_symbols_stops_next_real_mode_fetch(engine, tmp_path, monkeypatch):
    access, adapter, req, identifier = adopted(engine, tmp_path)
    req = req.model_copy(update={"symbols": ("LABTEST", "SECOND")})
    calls = []

    def fetch(request):
        symbol = request.symbols[0]
        calls.append(symbol)
        raw = FixtureProvider().fetch_bars("LABTEST", request.start, request.end)
        return json.dumps([{**r, "symbol": symbol} for r in json.loads(raw)]).encode()

    monkeypatch.setattr(adapter, "fetch_historical_bars", fetch)
    original = Records.append
    retired = False

    def append(records, kind, payload, **kwargs):
        nonlocal retired
        value = original(records, kind, payload, **kwargs)
        if (
            kind == "DataAcquisition"
            and payload.get("status") == "COMPLETED"
            and len(calls) == 1
            and not retired
        ):
            retired = True
            access.registry.decide(identifier, "DEPRECATED", "Retire between fetches")
        return value

    monkeypatch.setattr(Records, "append", append)
    with pytest.raises(PermissionError):
        access.ingest(adapter, req, operator_authorized=True)
    assert calls == ["LABTEST"]
