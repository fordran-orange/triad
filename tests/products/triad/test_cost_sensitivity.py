"""Offline arithmetic and isolated API checks; no browser execution."""
import math
import unittest

from fastapi.testclient import TestClient
from products.triad.cost_sensitivity import calculate_cost_sensitivity
from products.triad.product_app import app

EXAMPLE = dict(direction="LONG", quantity=10, entry_price=100, exit_price=110,
               commission_per_order=1, commission_per_share=0.01,
               commission_bps=2, full_spread_bps=10, slippage_bps=3)
LIMITS = dict(quantity=1000000, entry_price=1000000, exit_price=1000000,
              commission_per_order=1000, commission_per_share=100,
              commission_bps=1000, full_spread_bps=1000, slippage_bps=1000)
COSTS = list(LIMITS)[3:]


class CostSensitivityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def post(self, payload):
        return self.client.post("/research/cost-sensitivity", json=payload)

    def test_known_arithmetic_and_contract(self):
        for direction, gross, net in [("LONG", 100, 95.7), ("SHORT", -100, -104.3)]:
            with self.subTest(direction=direction):
                payload = dict(EXAMPLE, direction=direction)
                response = self.post(payload)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data, calculate_cost_sensitivity(payload))
                self.assertEqual(data["direction"], direction)
                self.assertEqual(data["currency"], "USD")
                self.assertEqual(data["return_unit"], "percent")
                self.assertEqual(data["monetary_encoding"], "decimal strings")
                self.assertEqual(data["assumptions"], {k: str(v) for k, v in payload.items()})
                self.assertAlmostEqual(float(data["gross_pnl"]), gross)
                self.assertAlmostEqual(float(data["round_trip_reference_notional"]), 2100)
                unit_total = 4.3
                self.assertAlmostEqual(float(data["breakeven_cost_multiplier"]), gross / unit_total)
                previous = gross
                for m, scenario in enumerate(data["scenarios"], 1):
                    self.assertEqual(scenario["multiplier"], m)
                    self.assertEqual(scenario["label"], f"{m}x supplied costs")
                    for key, value in dict(commission=2.62, spread_cost=1.05,
                                           slippage_cost=0.63, total_cost=4.3).items():
                        self.assertAlmostEqual(float(scenario[key]), m * value)
                    self.assertAlmostEqual(float(scenario["net_pnl"]), gross - m * 4.3)
                    self.assertLessEqual(float(scenario["net_pnl"]), previous)
                    previous = float(scenario["net_pnl"])
                self.assertAlmostEqual(float(data["scenarios"][0]["net_pnl"]), net)
                if direction == "LONG":
                    self.assertAlmostEqual(float(data["scenarios"][0]["net_return_on_entry_notional_pct"]), 9.57)

    def test_edges(self):
        zero = dict(EXAMPLE, **dict.fromkeys(COSTS, 0))
        data = self.post(zero).json()
        self.assertIsNone(data["breakeven_cost_multiplier"])
        for scenario in data["scenarios"]:
            self.assertEqual(float(scenario["total_cost"]), 0)
            self.assertEqual(float(scenario["net_pnl"]), 100)
        equal = self.post(dict(EXAMPLE, exit_price=100)).json()
        self.assertEqual(float(equal["gross_pnl"]), 0)
        self.assertLess(float(equal["scenarios"][0]["net_pnl"]), 0)
        small = self.post(dict(EXAMPLE, exit_price=100.01)).json()
        self.assertGreater(float(small["gross_pnl"]), 0)
        self.assertLess(float(small["scenarios"][0]["net_pnl"]), 0)
        fractional = self.post(dict(zero, quantity=0.5)).json()
        self.assertEqual(float(fractional["gross_pnl"]), 5)
        response = self.post(dict(direction="SHORT", **LIMITS))
        self.assertEqual(response.status_code, 200)
        for scenario in response.json()["scenarios"]:
            for key, value in scenario.items():
                if key != "label":
                    self.assertTrue(math.isfinite(float(value)))

    def test_required_and_unknown_fields(self):
        for field in EXAMPLE:
            payload = EXAMPLE.copy()
            del payload[field]
            with self.subTest(missing=field):
                self.assertEqual(self.post(payload).status_code, 422)
        for payload in [dict(EXAMPLE, extra=0), dict(EXAMPLE, direction="long"),
                        dict(EXAMPLE, direction="BUY")]:
            self.assertEqual(self.post(payload).status_code, 422)

    def test_numeric_validation(self):
        for field, maximum in LIMITS.items():
            invalid = [-1, maximum + 1, "NaN", "Infinity", "-Infinity", "1e9999", None, True]
            if field not in COSTS:
                invalid.append(0)
            for value in invalid:
                with self.subTest(field=field, value=value):
                    self.assertEqual(self.post(dict(EXAMPLE, **{field: value})).status_code, 422)

    def test_small_positive_values_do_not_underflow(self):
        payload = dict(EXAMPLE, quantity="1e-200", entry_price="1e-200", exit_price="1e-200")
        response = self.post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Infinity", response.text)


if __name__ == "__main__":
    unittest.main()
