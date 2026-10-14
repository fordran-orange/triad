"""Independent adversarial Core A regression checks (QA agent day6_qa_a)."""
# ruff: noqa: F811

import pytest
from test_day3_integration import engine  # noqa: F401
from test_intelligence_capabilities import build, capability, qa
from trading_core.intelligence.capabilities import Capabilities
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.store import Store

pytestmark = [pytest.mark.integration, pytest.mark.core]


def test_discovery_skips_real_unverified_null_workitem_shape(engine):
    class Unverified:
        def snapshot(self, transport):
            return {"health": "OFFLINE", "workitem": None, "test": None}

    assert Capabilities(Records(engine.host.store)).discover_runtime(Unverified()) == []


def test_product_cannot_self_attest_host_independent_qa(engine):
    records = Records(Store(engine.host.store.settings, scope="triad"))
    implementation = build(Records(engine.host.store), owner="triad")
    with pytest.raises(PermissionError):
        Quality(records).review(qa(implementation, execution_mode="HOST_INDEPENDENT_QA"))


def test_raw_product_append_cannot_forge_an_accepted_qa_verdict(engine):
    records = Records(Store(engine.host.store.settings, scope="triad"))
    implementation = build(Records(engine.host.store), owner="triad")
    forged = qa(implementation).model_dump(mode="json")
    forged["tests_repeated"] = []
    forged["evidence"] = []
    with pytest.raises((PermissionError, ValueError)):
        records.append("QARun", forged, owner="triad")
        Quality(records).require_pass(implementation.implementation_run_id, "revision-a")


def test_malformed_host_ingested_qa_cannot_pass_typed_validation(engine):
    records = Records(engine.host.store)
    implementation = build(records)
    malformed = qa(implementation).model_dump(mode="json")
    malformed["tests_repeated"] = []
    malformed["evidence"] = []
    with pytest.raises((PermissionError, ValueError)):
        records.append("QARun", malformed, owner="core")
        Quality(records).require_pass(implementation.implementation_run_id, "revision-a")


def test_mirrored_append_failure_rolls_back_canonical_record(engine, monkeypatch):
    records = Records(engine.host.store)
    before = records.list("AtomicProbe")

    def unavailable(*args, **kwargs):
        raise RuntimeError("simulated outbox failure")

    monkeypatch.setattr(records.ledger, "put", unavailable)
    with pytest.raises(RuntimeError, match="simulated outbox failure"):
        records.append("AtomicProbe", {"evidence": "atomic"})
    assert records.list("AtomicProbe") == before


def test_fixture_qa_cannot_publish_capability_truth(engine):
    records = Records(engine.host.store)
    caps = Capabilities(records)
    proposed = caps.propose(capability(), actor="operator")
    digest = records.get(proposed)["digest"]
    implementation = build(records, ("capability:" + digest,))
    Quality(records).review(qa(implementation, execution_mode="TEST_FIXTURE"))
    with pytest.raises(PermissionError):
        caps.approve(proposed, implementation.implementation_run_id, "revision-a")
    assert caps.current() == []


def test_correction_cannot_reuse_passing_prior_implementation_qa(engine):
    records = Records(engine.host.store)
    quality = Quality(records)
    original = build(records)
    quality.review(qa(original))
    correction = build(records)
    with pytest.raises(PermissionError):
        quality.require_pass(correction.implementation_run_id, correction.change_commit)


def test_pass_with_observation_retains_quality_debt(engine):
    records = Records(engine.host.store)
    implementation = build(records)
    review = qa(
        implementation,
        decision="PASS_WITH_OBSERVATIONS",
        findings=("Narrow runtime proof should be expanded to a second document later",),
        severity="LOW",
    )
    identifier = Quality(records).review(review)
    assert any(
        debt["source_qa_run"] == identifier and debt["finding"] == review.findings[0]
        for debt in records.list("QualityDebt")
    )
