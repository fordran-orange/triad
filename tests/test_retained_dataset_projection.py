"""Offline projection regression; spies preserve graph query/property semantics."""

import copy
from types import SimpleNamespace

import pytest
from trading_core.brain import Brain

pytestmark = pytest.mark.core


class Transaction:
    def __init__(self):
        self.calls = []

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        return SimpleNamespace(consume=lambda: None)


def payload(quality="FAIL", canonical=()):
    return {
        "record_kind": "DatasetManifest",
        "resolution": "1m",
        "mode": "REAL",
        "quality_status": quality,
        "canonical_paths": canonical,
        "dataset_version": "retained-source",
        "checksum": "a" * 64,
        "raw_sources": [
            {"path": "retained/archive.csv", "provider": "fixture-source", "checksum": "b" * 64}
        ],
        "provenance": {},
        "owner": "core",
    }


@pytest.mark.parametrize("shape", ["empty", "missing"])
def test_failed_retained_archive_projects_without_false_normalization(shape):
    data = payload()
    if shape == "missing":
        del data["canonical_paths"]
    original = copy.deepcopy(data)
    tx = Transaction()
    Brain.project(tx, "Day3Record", "failed-archive", data)
    assert data == original
    assert any(
        "MERGE (n:Dataset " in q
        and p["props"]["quality"] == "FAIL"
        and p["props"]["mode"] == "REAL"
        for q, p in tx.calls
    )
    assert any(
        "MERGE (n:DatasetVersion " in q and p["props"]["checksum"] == "a" * 64 for q, p in tx.calls
    )
    assert not any("RawDataset" in q or "NORMALIZED_INTO" in q for q, _ in tx.calls)


def test_even_known_raw_id_does_not_claim_normalized_retained_failure():
    data = payload()
    data["raw_sources"][0]["raw_id"] = "actual-retained-source"
    tx = Transaction()
    Brain.project(tx, "Day3Record", "failed-archive", data)
    assert not any("NORMALIZED_INTO" in q for q, _ in tx.calls)


@pytest.mark.parametrize(
    "quality,canonical",
    [("PASS", ("canonical.parquet",)), ("PASS", ()), ("FAIL", ("canonical.parquet",))],
)
def test_ostensibly_normalized_manifest_still_requires_raw_identity(quality, canonical):
    with pytest.raises(KeyError, match="raw_id"):
        Brain.project(Transaction(), "Day3Record", "strict", payload(quality, canonical))


@pytest.mark.parametrize("quality", ["PASS", "FAIL"])
def test_existing_canonical_dataset_retains_observed_normalization_lineage(quality):
    data = payload(quality, ("canonical.parquet",))
    data["raw_sources"][0]["raw_id"] = "observed-raw"
    tx = Transaction()
    Brain.project(tx, "Day3Record", "canonical", data)
    edges = [p for q, p in tx.calls if "NORMALIZED_INTO" in q]
    assert len(edges) == 1 and edges[0]["left"] == "observed-raw"
    assert edges[0]["right"] == "canonical"


@pytest.mark.parametrize("owner", ["core", "triad", "aegis"])
def test_retained_failure_projection_keeps_owner_and_idempotent_merge_identity(owner):
    data = payload()
    data["owner"] = owner
    first, second = Transaction(), Transaction()
    Brain.project(first, "Day3Record", "retained-id", data)
    Brain.project(second, "Day3Record", "retained-id", data)
    assert first.calls == second.calls
    assert all(query.startswith("MERGE") for query, _ in first.calls)
    assert all(
        parameters["props"]["owner"] == owner
        for _, parameters in first.calls
        if "props" in parameters
    )
    assert all(
        parameters["left_owner"] == parameters["right_owner"] == owner
        for _, parameters in first.calls
        if "left_owner" in parameters
    )
