import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from products.triad.product_app import app
from trading_core.product_sdk import ResearchInput
from trading_core.research.contracts import Bar


def core_input_dict(owner="triad"):
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
        owner=owner,
        dataset_id="test-data",
        dataset_version="fixture-v1",
        mode="FIXTURE",
        start=start,
        end=end,
        bars=bars,
    )
    return supplied.model_dump(mode="json")


VALID_PAYLOAD = dict(
    period=4,
    hold=2,
    directions=["LONG"],
    fees={"fixed": 0, "per_share": 0, "bps": 0},
    slippage={"bps": 0, "spread_bps": 0},
)

PREFLIGHT_DETAIL = (
    "Core input rejected: must belong to triad and pass Core research-contract eligibility."
)
REQUEST_SHAPE_DETAIL = (
    "Invalid request: require core_input, period (2-1000), hold (1-999, less than period), "
    "distinct directions (LONG/SHORT) and bounded fees/slippage."
)


class ProductAppHealthTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_returns_200(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_health_returns_status_ok_payload(self):
        response = self.client.get("/health")
        self.assertEqual(response.json(), {"status": "ok"})

    def test_boundaries_returns_contract(self):
        response = self.client.get("/boundaries")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "product": "triad-trading",
                "stage": "early",
                "live_account": False,
                "order_entry": False,
                "portfolio_management": False,
                "validated_strategy": False,
                "research_readiness_establishes_strategy_edge": False,
            },
        )


class ExperimentEndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_valid_payload_returns_200_with_result(self):
        payload = {**VALID_PAYLOAD, "core_input": core_input_dict()}
        response = self.client.post("/research/experiment", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("results", data)
        self.assertEqual(data["strategy_scope"], "Fixture strategy only; not a trading edge.")

    def test_foreign_owner_rejected_with_preflight_422_and_no_engine_call(self):
        payload = {**VALID_PAYLOAD, "core_input": core_input_dict(owner="aegis")}
        with patch("products.triad.product_app.run_experiment") as mock_run:
            response = self.client.post("/research/experiment", json=payload)
        self.assertEqual(response.status_code, 422)
        mock_run.assert_not_called()
        self.assertEqual(response.json()["detail"], PREFLIGHT_DETAIL)

    def test_quality_failing_input_rejected_with_preflight_422_and_no_engine_call(self):
        core_input = core_input_dict()
        core_input["bars"] = core_input["bars"][:5] + core_input["bars"][6:]
        payload = {**VALID_PAYLOAD, "core_input": core_input}
        with patch("products.triad.product_app.run_experiment") as mock_run:
            response = self.client.post("/research/experiment", json=payload)
        self.assertEqual(response.status_code, 422)
        mock_run.assert_not_called()
        self.assertEqual(response.json()["detail"], PREFLIGHT_DETAIL)

    def test_request_shape_errors_rejected_with_distinct_422_and_no_engine_call(self):
        base_core_input = core_input_dict()
        bad_payloads = [
            {**VALID_PAYLOAD, "core_input": base_core_input, "unknown_field": "x"},
            {**VALID_PAYLOAD, "core_input": base_core_input, "period": 1},
            {**VALID_PAYLOAD, "core_input": base_core_input, "hold": 0},
            {**VALID_PAYLOAD, "core_input": base_core_input, "directions": ["LONG", "LONG"]},
            {**VALID_PAYLOAD, "core_input": base_core_input, "period": 4, "hold": 4},
            {**VALID_PAYLOAD, "core_input": base_core_input, "period": 4, "hold": 5},
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with patch("products.triad.product_app.run_experiment") as mock_run, \
                     patch("products.triad.product_app.preflight") as mock_preflight:
                    response = self.client.post("/research/experiment", json=payload)
                self.assertEqual(response.status_code, 422)
                mock_run.assert_not_called()
                mock_preflight.assert_not_called()
                self.assertEqual(response.json()["detail"], REQUEST_SHAPE_DETAIL)
                self.assertNotEqual(response.json()["detail"], PREFLIGHT_DETAIL)

    def test_post_preflight_failure_is_uncaught_500_direct_and_mounted(self):
        payload = {**VALID_PAYLOAD, "core_input": core_input_dict()}
        direct_client = TestClient(app, raise_server_exceptions=False)
        with patch("products.triad.product_app.run_experiment", side_effect=ValueError("boom")):
            response = direct_client.post("/research/experiment", json=payload)
        self.assertEqual(response.status_code, 500)
        for detail in (PREFLIGHT_DETAIL, REQUEST_SHAPE_DETAIL):
            self.assertNotIn(detail, response.text)

        host = FastAPI()
        host.mount("/triad/product-api", app)
        host_client = TestClient(host, raise_server_exceptions=False)
        with patch("products.triad.product_app.run_experiment", side_effect=ValueError("boom")):
            response = host_client.post("/triad/product-api/research/experiment", json=payload)
        self.assertEqual(response.status_code, 500)
        for detail in (PREFLIGHT_DETAIL, REQUEST_SHAPE_DETAIL):
            self.assertNotIn(detail, response.text)


if __name__ == "__main__":
    unittest.main()
