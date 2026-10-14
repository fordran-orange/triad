"""Current adoption and QA authority, exercised with offline synthetic bytes."""
# ruff: noqa: F811

import json

import pytest
from test_day3_integration import engine  # noqa: F401
from test_day7_f_correction_qa import adopted
from test_intelligence_capabilities import qa
from trading_core.intelligence.contracts import ImplementationRun
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.research.data import FixtureProvider

pytestmark = [pytest.mark.integration, pytest.mark.core]


def test_each_adoption_link_is_required(engine, tmp_path):
    access, adapter, _, _ = adopted(engine, tmp_path)
    definition = adapter.metadata()
    access.registry.require_adopted(definition)
    for field in ("integration_id", "implementation_run_id", "implementation_commit", "candidate_id"):
        with pytest.raises(PermissionError):
            access.registry.require_adopted({**definition, field: "not-the-adopted-value"})


def test_failed_latest_qa_between_symbols_stops_next_fetch(engine, tmp_path, monkeypatch):
    access, adapter, request, _ = adopted(engine, tmp_path)
    request = request.model_copy(update={"symbols": ("LABTEST", "SECOND")})
    build = access.registry.host.get(adapter.definition.implementation_run_id)
    build = ImplementationRun.model_validate(
        {key: value for key, value in build.items() if key in ImplementationRun.model_fields}
    )
    calls = []

    def fetch(single):
        symbol = single.symbols[0]
        calls.append(symbol)
        raw = FixtureProvider().fetch_bars("LABTEST", single.start, single.end)
        return json.dumps([{**row, "symbol": symbol} for row in json.loads(raw)]).encode()

    monkeypatch.setattr(adapter, "fetch_historical_bars", fetch)
    original = Records.append
    revoked = False

    def append(records, kind, payload, **kwargs):
        nonlocal revoked
        result = original(records, kind, payload, **kwargs)
        if kind == "DataAcquisition" and payload.get("status") == "COMPLETED" and not revoked:
            revoked = True
            Quality(access.registry.host).review(
                qa(build, decision="CHANGES_REQUIRED", findings=("New independent QA blocker",))
            )
        return result

    monkeypatch.setattr(Records, "append", append)
    with pytest.raises(PermissionError, match="Latest independent QA"):
        access.ingest(adapter, request, operator_authorized=True)
    assert calls == ["LABTEST"]
    acquisitions = access.registry.host.list("DataAcquisition")
    assert any(row["status"] == "COMPLETED" for row in acquisitions)
    assert any(row["status"] == "FAILED" for row in acquisitions)
