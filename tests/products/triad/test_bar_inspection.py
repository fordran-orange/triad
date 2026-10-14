"""Offline bar-inspection fixtures."""
import csv
import io
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from products.triad.bar_inspection import inspect_bars
from products.triad.product_app import app
import pytest

pytestmark = pytest.mark.triad


COLUMNS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")


def bar(**changes):
    result = {
        "timestamp": "2026-01-02T15:00:00Z",
        "symbol": "AAPL",
        "open": "10",
        "high": "12",
        "low": "9",
        "close": "11",
        "volume": "100",
    }
    result.update(changes)
    return result


def csv_text(rows, headers=COLUMNS):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows([[row.get(header, "1") for header in headers] for row in rows])
    return output.getvalue()


class BarInspectionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_module_does_not_import_trading_core(self):
        import ast
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        self.assertFalse(any("trading_core" in name for name in imported))
        source = Path(__file__).resolve().parents[3].joinpath(
            "app/products/triad/bar_inspection.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("trading_core", source)

    def test_coverage_is_alphabetical_and_order_independent(self):
        rows = [
            bar(symbol="MSFT", timestamp="2026-01-03T15:00:00Z", open="20.5", high="21", low="20", close="20.25", volume="0"),
            bar(symbol="AAPL", timestamp="2026-01-02T19:30:00-05:00", open="10.10", high="12", low="9.5", close="11", volume="100.5"),
            bar(symbol="AAPL", timestamp="2026-01-01T15:00:00Z", open="9", high="10", low="8", close="9.5", volume="3"),
            bar(symbol="MSFT", timestamp="2026-01-01T00:00:00+00:00"),
        ]
        forward = inspect_bars(csv_text(rows))
        backward = inspect_bars(csv_text(list(reversed(rows))))
        self.assertEqual(forward, backward)
        self.assertEqual(forward["symbols"], ["AAPL", "MSFT"])
        self.assertEqual(forward["row_count"], 4)
        self.assertEqual(forward["duplicate_count"], 0)
        self.assertEqual(
            [(item["symbol"], item["bar_count"], item["first_timestamp"], item["last_timestamp"]) for item in forward["coverage"]],
            [
                ("AAPL", 2, "2026-01-01T15:00:00+00:00", "2026-01-03T00:30:00+00:00"),
                ("MSFT", 2, "2026-01-01T00:00:00+00:00", "2026-01-03T15:00:00+00:00"),
            ],
        )
        priced = next(row for row in forward["rows"] if row["symbol"] == "AAPL" and row["open"] != "9")
        for field, expected in (("open", "10.10"), ("high", "12"), ("low", "9.5"), ("close", "11"), ("volume", "100.5")):
            self.assertIsInstance(priced[field], str)
            self.assertNotIn("e", priced[field].lower())
            self.assertEqual(Decimal(priced[field]), Decimal(expected))
        self.assertTrue(forward["assumptions"])
        self.assertIn("not a market feed", " ".join(forward["assumptions"]))

    def test_rejections_and_bounded_api_body(self):
        cases = [
            "",
            csv_text([]),
            csv_text([bar(high="10", close="11")]),
            csv_text([bar(low="10.5", open="10", close="11", high="12")]),
            csv_text([bar(open="0")]),
            csv_text([bar(close="-1")]),
            csv_text([bar(volume="-1")]),
            csv_text([bar(open="1000001")]),
            csv_text([bar(volume="1000001")]),
            csv_text([bar(symbol="abc")]),
            csv_text([bar(symbol="A" * 21)]),
            csv_text([bar(timestamp="2026-01-02T15:00:00")]),
            csv_text([bar(), bar()]),
            csv_text([bar()], headers=COLUMNS + ("source",)),
            "x" * 1_000_001,
        ]
        for text in cases:
            with self.subTest(text=text[:80]):
                with self.assertRaises(ValueError):
                    inspect_bars(text)
                response = self.client.post("/research/bar-inspection", json={"csv_text": text})
                self.assertEqual(response.status_code, 422)
                self.assertLess(len(response.content), 600)
                body = response.json()
                self.assertNotIn("rows", body)
                if text:
                    self.assertNotIn(text, response.text)

    def test_row_ceiling(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = [
            bar(timestamp=(start + timedelta(minutes=index)).strftime("%Y-%m-%dT%H:%M:%SZ"))
            for index in range(5001)
        ]
        with self.assertRaises(ValueError):
            inspect_bars(csv_text(rows))
        self.assertEqual(inspect_bars(csv_text(rows[:5000]))["row_count"], 5000)

    def test_endpoint_returns_result_and_leaves_boundaries(self):
        text = csv_text([bar(symbol="MSFT"), bar()])
        before_health = self.client.get("/health").json()
        before_boundaries = self.client.get("/boundaries").json()
        response = self.client.post("/research/bar-inspection", json={"csv_text": text})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), inspect_bars(text))
        unknown = self.client.post("/research/bar-inspection", json={"csv_text": text, "feed": "alpaca"})
        self.assertEqual(unknown.status_code, 422)
        self.assertNotIn("rows", unknown.json())
        self.assertNotIn(text, unknown.text)
        self.assertNotIn("alpaca", unknown.text)
        self.assertEqual(self.client.get("/health").json(), before_health)
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/boundaries").json(), before_boundaries)
        self.assertFalse(before_boundaries["live_account"])
        self.assertFalse(before_boundaries["order_entry"])
        self.assertFalse(before_boundaries["portfolio_management"])
        self.assertFalse(before_boundaries["validated_strategy"])
        self.assertFalse(before_boundaries["research_readiness_establishes_strategy_edge"])


if __name__ == "__main__":
    unittest.main()
