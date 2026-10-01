import unittest
from datetime import datetime

from fastapi.testclient import TestClient

from products.triad.product_app import app


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
        body = response.json()
        self.assertEqual(body["product"], "triad-trading")
        self.assertEqual(body["stage"], "early")
        self.assertEqual(body["live_account"], False)
        self.assertEqual(body["order_entry"], False)
        self.assertEqual(body["portfolio_management"], False)
        self.assertEqual(body["validated_strategy"], False)
        self.assertEqual(
            body["research_readiness_establishes_strategy_edge"], False
        )
        self.assertEqual(body["schema_version"], "1")
        self.assertIn("generated_at", body)
        parsed = datetime.fromisoformat(body["generated_at"])
        self.assertIsNotNone(parsed.utcoffset())

    def test_boundaries_generated_at_stable_across_requests(self):
        first = self.client.get("/boundaries").json()["generated_at"]
        second = self.client.get("/boundaries").json()["generated_at"]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
