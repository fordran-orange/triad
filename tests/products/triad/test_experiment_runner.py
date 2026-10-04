"""Direct-call tests of the ownership-pinned experiment runner; no TestClient."""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from products.triad.experiment_runner import preflight, run_experiment
from trading_core.product_sdk import ResearchInput
from trading_core.research.contracts import Bar


def core_input_dict():
    start = datetime(2026, 10, 2, 13, 30, tzinfo=UTC)
    end = start + timedelta(minutes=12)
    bars = tuple(
        Bar(
            timestamp=start + timedelta(minutes=i),
            symbol="LABTEST",
            open=100 + i,
            high=102 + i,
            low=99 + i,
            close=101 + i,
            volume=1000,
            source="synthetic-test",
            source_symbol="LABTEST",
            timezone="America/New_York",
            ingested_at=end,
            dataset_version="fixture-v1",
            provenance_id="explicit-unit-fixture",
        )
        for i in range(12)
    )
    supplied = ResearchInput(
        owner="triad",
        dataset_id="test-data",
        dataset_version="fixture-v1",
        mode="FIXTURE",
        start=start,
        end=end,
        bars=bars,
    )
    return supplied.model_dump(mode="json")


DEFAULT_ARGS = dict(
    period=4,
    hold=2,
    directions=("LONG",),
    fees={"fixed": 0, "per_share": 0, "bps": 0},
    slippage={"bps": 0, "spread_bps": 0},
    sizing={"kind": "fixed_shares", "value": 10},
)


class ExperimentRunnerTest(unittest.TestCase):
    def test_valid_request_is_deterministic(self):
        data = core_input_dict()
        first = run_experiment(data, **DEFAULT_ARGS)
        second = run_experiment(data, **DEFAULT_ARGS)
        self.assertEqual(first["dataset_sha256"], second["dataset_sha256"])
        self.assertEqual(first["results"]["content_hash"], second["results"]["content_hash"])

    def test_foreign_owner_rejected_by_preflight_without_constructing_experiment(self):
        data = core_input_dict()
        data["owner"] = "aegis"
        with self.assertRaises(PermissionError):
            preflight(data)
        with self.assertRaises(PermissionError):
            run_experiment(data, **DEFAULT_ARGS)

    def test_coverage_gap_rejected_before_construction(self):
        data = core_input_dict()
        data["bars"] = data["bars"][:5] + data["bars"][6:]
        with self.assertRaises(ValueError):
            preflight(data)
        with self.assertRaises(ValueError):
            run_experiment(data, **DEFAULT_ARGS)

    def test_run_experiment_uses_dataset_identity_from_supplied_input(self):
        data = core_input_dict()
        result = run_experiment(data, **DEFAULT_ARGS)
        self.assertEqual(result["dataset_id"], data["dataset_id"])
        self.assertEqual(result["dataset_version"], data["dataset_version"])

    def test_post_preflight_engine_failure_propagates_unmodified(self):
        data = core_input_dict()
        with patch("products.triad.experiment_runner.run_research", side_effect=ValueError("boom")):
            with self.assertRaisesRegex(ValueError, "^boom$"):
                run_experiment(data, **DEFAULT_ARGS)


if __name__ == "__main__":
    unittest.main()
