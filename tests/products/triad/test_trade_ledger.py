"""Independent ledger fixtures and isolated API validation."""
import csv
import io
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext
from fastapi.testclient import TestClient
from products.triad.product_app import app
from products.triad.trade_ledger import COLUMNS, analyze_trade_ledger

def row(i="a", **changes):
    result = dict(zip(COLUMNS, [i, "ABC", "LONG", "10", "100", "111",
                               "2026-01-01T09:00:00Z", "2026-01-01T10:00:00Z", "10"]))
    result.update(changes)
    return result

def csv_text(rows, headers=COLUMNS):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows([[r[h] for h in headers] for r in rows])
    return output.getvalue()

def report(rows, initial="1000"):
    return analyze_trade_ledger(initial, csv_text(rows))

class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def post(self, text, **changes):
        return self.client.post("/research/trade-ledger",
            json=dict(initial_balance="1000", csv_text=text, **changes))

    def reject(self, text, initial="1000"):
        with self.assertRaises(ValueError):
            analyze_trade_ledger(initial, text)
        response = self.client.post("/research/trade-ledger",
            json={"initial_balance": initial, "csv_text": text})
        self.assertEqual(response.status_code, 422)
        self.assertLess(len(response.content), 600)
        self.assertNotIn("rows", response.json())

    def test_known_results(self):
        rows = [row(), row("b", direction="SHORT", exit_price="114",
                          exit_time="2026-01-02T10:00:00Z"),
                row("c", exit_price="100", total_cost="0", exit_time="2026-01-03T10:00:00Z"),
                row("d", quantity="5", exit_price="110", total_cost="0",
                    exit_time="2026-01-04T10:00:00Z")]
        data = report(rows)
        expected = dict(initial_balance="1000", gross_pnl="20", total_costs="20",
                        net_pnl="0", ending_realized_balance="1000", win_rate_pct="50",
                        average_net_pnl="0", profit_factor="1", max_drawdown="150")
        for key, value in expected.items():
            self.assertIsInstance(data[key], str)
            self.assertEqual(Decimal(data[key]), Decimal(value))
        self.assertEqual([data[k] for k in ("trade_count","positive_count","negative_count","zero_count")], [4,2,1,1])
        self.assertLess(abs(Decimal(data["max_drawdown_pct"])-Decimal("13.6363636364")), Decimal("1e-10"))
        self.assertEqual([Decimal(r["net_pnl"]) for r in data["rows"]], [100,-150,0,50])
        self.assertEqual(self.post(csv_text(rows)).json(), data)
        self.assertEqual(data, report(list(reversed(rows))))
        self.assertEqual(data["percentage_unit"], "percent")
        self.assertTrue(data["schema_version"])
        self.assertTrue(data["assumptions"])

    def test_grouping_utc_and_baseline(self):
        rows = [row("z", total_cost="0", exit_price="110"),
                row("a", total_cost="0", exit_price="90",
                    exit_time="2026-01-01T05:00:00-05:00")]
        data = report(rows)
        self.assertEqual([r["trade_id"] for r in data["rows"]], ["a","z"])
        self.assertEqual(len(data["realized_balance_curve"]), 2)
        self.assertEqual(data["realized_balance_curve"][0],
                         dict(timestamp=None, balance="1000", drawdown="0", drawdown_pct="0"))
        self.assertEqual(data["max_drawdown"], "0")
        self.assertEqual(data["rows"][0]["exit_time"], "2026-01-01T10:00:00+00:00")

    def test_edges_and_independent_maxima(self):
        for price, counts, factor in [("110", (1,0,0), None), ("90",(0,1,0),"0"), ("100",(0,0,1),None)]:
            data = report([row(exit_price=price, total_cost="0")])
            self.assertEqual(tuple(data[k] for k in ("positive_count","negative_count","zero_count")), counts)
            self.assertEqual(data["profit_factor"], factor)
            self.assertEqual(data["profit_factor_reason"], "no_losses" if factor is None else None)
        data = report([row(quantity="0.5", entry_price="1.1", exit_price="1.3", total_cost="0.01")])
        self.assertEqual(Decimal(data["net_pnl"]), Decimal("0.09"))
        data = report([row(exit_price="1", total_cost="1000")])
        self.assertEqual(data["ending_realized_balance"], "-990")
        self.assertEqual(data["max_drawdown_pct"], "199")
        # 100 -> 50 -> 1000 -> 800: dollars peak at 200; percent at 50%.
        rows = [row(str(i), quantity="1", entry_price="1000", exit_price=str(1000+n),
                    total_cost="0", exit_time=f"2026-01-0{i+1}T10:00:00Z")
                for i,n in enumerate([-50,950,-200])]
        data = report(rows, "100")
        self.assertEqual(data["max_drawdown"], "200")
        self.assertEqual(data["max_drawdown_pct"], "50")
        old = getcontext().prec
        try:
            getcontext().prec = 6
            self.assertEqual(report(rows, "100"), data)
            self.assertEqual(getcontext().prec, 6)
        finally:
            getcontext().prec = old

    def test_csv_rejections(self):
        good = csv_text([row()])
        for text in ["", csv_text([]), good.replace("symbol", "trade_id",1),
                     good.replace("symbol", "unknown",1),
                     csv_text([row()], COLUMNS[:-1]), csv_text([row(),row()]),
                     good.rstrip()+",extra\n", good.rsplit(",10",1)[0]+"\n",
                     good + "\n", good.replace("ABC", '"ABC'),
                     good.replace("ABC", 'AB"C'), good.replace("ABC", '"ABC"x')]:
            with self.subTest(text=text[:100]):
                self.reject(text)

    def test_fields_and_numbers(self):
        cases = {"trade_id":["a"*65,"bad id"], "symbol":["abc","A"*21,"<b>"],
                 "direction":["long","BUY"], "entry_time":["2026-01-01T09:00:00", "2026-02-30T00:00:00Z",
                 "2026-01-02T00:00:00Z"], "exit_time":["bad","2026-01-01T00:00:00+24:00"]}
        for field in ("quantity","entry_price","exit_price","total_cost"):
            cases[field] = ["-1","1000000.00000001","NaN","Infinity","1e2","0.000000001","1"*33]
            if field != "total_cost":
                cases[field].append("0")
        for field in COLUMNS:
            cases.setdefault(field, []).append(" ")
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field,value=value):
                    self.reject(csv_text([row(**{field:value})]))
        for value in ["0","-1","1e3","NaN","1000000000000.00000001","0.000000001","1"*33,1000,True]:
            self.reject(csv_text([row()]), value)

    def test_limits_and_valid_csv(self):
        limits = row(trade_id="A"*64, symbol="A"*20, quantity="1000000",
                     entry_price="1000000",exit_price="1000000",total_cost="1000000")
        text = "\ufeff" + csv_text([limits], tuple(reversed(COLUMNS)))
        self.assertEqual(analyze_trade_ledger("1000000000000",text)["trade_count"],1)
        self.assertEqual(report([row(quantity="0.00000001", entry_price="0.00000001",
                                    exit_price="0.00000001",total_cost="0")])["trade_count"],1)
        text = csv_text([row(symbol=' ABC ')])
        text = text.replace(" ABC ", '" ABC "')
        self.assertEqual(analyze_trade_ledger("1000",text)["rows"][0]["symbol"],"ABC")
        rows = [row(str(i)) for i in range(2000)]
        self.assertEqual(report(rows)["trade_count"],2000)
        self.reject(csv_text(rows+[row("extra")]))
        # Pad across bounded individual fields to exercise the exact byte ceiling.
        rows = [row(str(i), symbol=" " * 400 + "ABC") for i in range(2000)]
        text = csv_text(rows)
        text = text.replace("ABC", " " * (1000000-len(text.encode())) + "ABC",1)
        self.assertEqual(len(text.encode()),1000000)
        self.assertEqual(analyze_trade_ledger("1000",text)["trade_count"],2000)
        self.reject(text+" ")
        self.reject(text.replace(" ", "é",1))
        self.reject(csv_text([row(symbol="x"*140000)]))
        text = csv_text([row(symbol=" " * 900000 + "ABC")])
        self.assertEqual(analyze_trade_ledger("1000", text)["rows"][0]["symbol"], "ABC")
        for symbol in ['A,B', 'A"BC', 'A\nBC']:
            self.reject(csv_text([row(symbol=symbol)]))

    def test_request_contract(self):
        for payload in [{}, {"initial_balance":"1000"}, {"initial_balance":"1000","csv_text":42},
                        {"initial_balance":"1000","csv_text":csv_text([row()]),"extra":"x"*10000}]:
            response = self.client.post("/research/trade-ledger",json=payload)
            self.assertEqual(response.status_code,422)
            self.assertLess(len(response.content),600)


class ExposureTests(unittest.TestCase):
    def exposure(self, rows, initial="1000"):
        return report(rows, initial)["entry_notional_exposure"]

    def test_independent_arithmetic_and_api(self):
        rows = [row(exit_time="2026-01-01T11:00:00Z"),
                row("b", direction="SHORT", quantity="5", entry_price="80",
                    entry_time="2026-01-01T10:00:00Z", exit_time="2026-01-01T12:00:00Z")]
        exposure = self.exposure(rows)
        keys = ("long_entry_notional", "short_entry_notional", "gross_entry_notional", "net_entry_notional")
        expected = [(1000,0,1000,1000,1), (1000,400,1400,600,2),
                    (0,400,400,-400,1), (0,0,0,0,0)]
        for point, values in zip(exposure["timeline"], expected, strict=True):
            self.assertEqual(tuple(Decimal(point[k]) for k in keys), values[:4])
            self.assertEqual(point["active_trade_count"], values[4])
            self.assertIs(type(point["active_trade_count"]), int)
            for k in (*keys, "gross_to_initial_balance_ratio"):
                self.assertIsInstance(point[k], str)
        self.assertEqual(exposure["max_gross_entry_notional"], "1400")
        self.assertEqual(exposure["max_gross_to_initial_balance_ratio"], "1.4")
        self.assertEqual(exposure["max_concurrent_trades"], 2)
        for key in ("max_gross_entry_notional_timestamp", "max_concurrent_trades_timestamp"):
            self.assertEqual(exposure[key], "2026-01-01T10:00:00+00:00")
        changed = [dict(r, exit_price="1", total_cost="999") for r in rows]
        self.assertEqual(self.exposure(changed), exposure)
        response = TestClient(app).post("/research/trade-ledger",
            json={"initial_balance":"1000", "csv_text":csv_text(rows)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), report(rows))
        self.assertEqual(response.json()["schema_version"], "triad.trade-ledger.v1")

    def test_grouping_offsets_microseconds_permutation_and_ties(self):
        rows = [
            row("z", entry_time="2026-01-01T09:00:00.000001Z",
                exit_time="2026-01-01T10:00:00.000001Z"),
            row("a", direction="SHORT", entry_time="2026-01-01T05:00:00.000001-05:00",
                exit_time="2026-01-01T11:00:00.000001Z"),
            row("b", entry_time="2026-01-01T11:00:00.000001Z",
                exit_time="2026-01-01T12:00:00.000001Z")]
        exposure = self.exposure(rows)
        self.assertEqual([p["active_trade_count"] for p in exposure["timeline"]], [1,1,1,0])
        self.assertEqual(exposure["max_concurrent_trades"], 1)
        for key in ("max_concurrent_trades_timestamp", "max_gross_entry_notional_timestamp"):
            self.assertEqual(exposure[key], "2026-01-01T09:00:00.000001+00:00")
        self.assertEqual(exposure, self.exposure([dict(r, trade_id=str(i)) for i,r in enumerate(reversed(rows))]))
        opposite = self.exposure([row(), row("b", direction="SHORT")])
        self.assertEqual(opposite["timeline"][0]["gross_entry_notional"], "2000")
        self.assertEqual(opposite["timeline"][0]["net_entry_notional"], "0")

    def test_zero_duration_retained_only_in_performance(self):
        zero = row(entry_time="2026-01-01T10:00:00Z")
        data = report([zero])
        self.assertEqual(data["trade_count"], 1)
        self.assertEqual(data["net_pnl"], "100")
        exposure = data["entry_notional_exposure"]
        self.assertEqual(exposure, dict(excluded_zero_duration_trade_count=1,
            max_concurrent_trades=0, max_concurrent_trades_timestamp=None,
            max_gross_entry_notional="0", max_gross_to_initial_balance_ratio="0",
            max_gross_entry_notional_timestamp=None, timeline=[]))
        mixed = report([zero, row("b")])
        self.assertEqual(mixed["trade_count"], 2)
        self.assertEqual(mixed["net_pnl"], "200")
        expected = self.exposure([row("b")])
        expected["excluded_zero_duration_trade_count"] = 1
        self.assertEqual(mixed["entry_notional_exposure"], expected)

    def test_decimal_extremes_and_context(self):
        rows = [row(quantity="0.12345678", entry_price="0.87654321"),
                row("b", quantity="1000000", entry_price="1000000")]
        baseline = self.exposure(rows, "0.00000001")
        self.assertEqual(baseline["max_gross_entry_notional"], "1000000000000.1082152022374638")
        self.assertEqual(baseline["max_gross_to_initial_balance_ratio"], "100000000000010821520.22374638")
        old = getcontext().prec
        try:
            getcontext().prec = 6
            self.assertEqual(self.exposure(rows, "0.00000001"), baseline)
            self.assertEqual(getcontext().prec, 6)
        finally:
            getcontext().prec = old
        tiny = self.exposure([row(quantity="0.00000001", entry_price="0.00000001")])
        self.assertEqual(Decimal(tiny["max_gross_entry_notional"]), Decimal("0.0000000000000001"))
        self.assertEqual(self.exposure([row()], "1000000000000")["max_gross_to_initial_balance_ratio"], "0.000000001")

    def test_two_thousand_records_four_thousand_points(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = [row(str(i), quantity="1000000", entry_price="1000000",
                    entry_time=(start + timedelta(microseconds=i)).isoformat(),
                    exit_time=(start + timedelta(microseconds=2000+i)).isoformat())
                for i in range(2000)]
        exposure = self.exposure(rows, "0.00000001")
        self.assertEqual(len(exposure["timeline"]), 4000)
        self.assertEqual(exposure["max_concurrent_trades"], 2000)
        self.assertEqual(exposure["max_gross_entry_notional"], "2000000000000000")
        self.assertEqual(exposure["max_gross_to_initial_balance_ratio"], "200000000000000000000000")
        stamps = [p["timestamp"] for p in exposure["timeline"]]
        self.assertEqual(stamps, sorted(set(stamps)))
        for point in exposure["timeline"]:
            for key in ("long_entry_notional", "short_entry_notional", "gross_entry_notional",
                        "gross_to_initial_balance_ratio"):
                self.assertTrue(Decimal(point[key]).is_finite())
                self.assertGreaterEqual(Decimal(point[key]), 0)
        final = exposure["timeline"][-1]
        self.assertEqual(final["active_trade_count"], 0)
        for key in ("long_entry_notional", "short_entry_notional", "gross_entry_notional",
                    "net_entry_notional", "gross_to_initial_balance_ratio"):
            self.assertEqual(Decimal(final[key]), 0)
