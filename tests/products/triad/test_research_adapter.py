"""Actual product-to-Core contract tests; no mocked engine or host service."""

import unittest
from datetime import UTC, datetime, timedelta

from products.triad.research_adapter import run_research
from trading_core.product_sdk import ResearchInput
from trading_core.research.contracts import Bar, Experiment, Partition


def fixture():
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
    experiment = Experiment(
        name="Contract conformance",
        description="Synthetic engine integration",
        hypothesis="Fixture only",
        dataset_id=supplied.dataset_id,
        dataset_version=supplied.dataset_version,
        symbols=("LABTEST",),
        start_time=start,
        end_time=end,
        parameters={"period": 4, "hold": 2},
        directions=("LONG",),
        code_commit="fixture-test",
        environment={"purpose": "unit test"},
        acceptance_criteria=("Explicit fixture identity and deterministic result",),
        partitions=(Partition(name="test", start=start, end=end),),
    )
    return supplied, experiment


class ResearchAdapterTest(unittest.TestCase):
    def test_real_core_engine_preserves_identity_and_is_repeatable(self):
        data, experiment = fixture()
        first = run_research(data, experiment)
        repeated = run_research(data, experiment)
        self.assertEqual(first["results"]["content_hash"], repeated["results"]["content_hash"])
        self.assertEqual(first["owner"], "triad")
        self.assertEqual(first["mode"], "FIXTURE")
        self.assertEqual(first["contract"], "core.product-research.v1")
        self.assertTrue(first["results"]["trades"])
        self.assertEqual(first["dataset_version"], data.dataset_version)

    def test_other_product_input_cannot_enter_triad_adapter(self):
        data, experiment = fixture()
        with self.assertRaises(PermissionError):
            run_research(data.model_copy(update={"owner": "aegis"}), experiment)

    def test_missing_bar_and_version_mismatch_are_rejected_not_repaired(self):
        data, experiment = fixture()
        for invalid in (
            data.model_copy(update={"bars": data.bars[:5] + data.bars[6:]}),
            data.model_copy(update={"dataset_version": "other"}),
        ):
            with self.assertRaises(ValueError):
                run_research(invalid, experiment)

    def test_unknown_calendar_year_is_not_assumed_eligible(self):
        data, experiment = fixture()
        bars = tuple(
            bar.model_copy(
                update={
                    "timestamp": bar.timestamp.replace(year=2025),
                    "ingested_at": bar.ingested_at.replace(year=2025),
                }
            )
            for bar in data.bars
        )
        invalid = data.model_copy(
            update={
                "bars": bars,
                "start": data.start.replace(year=2025),
                "end": data.end.replace(year=2025),
            }
        )
        with self.assertRaises(ValueError):
            run_research(
                invalid,
                experiment.model_copy(
                    update={"start_time": invalid.start, "end_time": invalid.end}
                ),
            )

    def test_guard_stops_computation(self):
        data, experiment = fixture()

        def stopped():
            raise PermissionError("stopped")

        with self.assertRaises(PermissionError):
            run_research(data, experiment, guard=stopped)
