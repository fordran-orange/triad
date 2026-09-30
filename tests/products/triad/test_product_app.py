import unittest

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


if __name__ == "__main__":
    unittest.main()
