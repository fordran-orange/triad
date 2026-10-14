"""Independent identity expectations and installed-SDK/API acceptance."""
import hashlib
import json
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from products.triad.product_app import app
from products.triad.research_dataset import DatasetRequest, prepare_dataset
from products.triad.research_adapter import validate_research_input
from trading_core.product_sdk import ProductResearch, ResearchInput
import pytest

pytestmark = pytest.mark.triad

HEADER = "timestamp,symbol,open,high,low,close,volume"
MARKET = dict(resolution="1m", exchange="XNYS", session="REGULAR", currency="USD",
              asset_class="equity", adjustment_status="UNADJUSTED", confirmed=True)


def payload(count=12, symbols=("AAA",)):
    start = datetime(2026, 10, 2, 13, 30, tzinfo=UTC)
    lines = [HEADER] + [
        f"{(start+timedelta(minutes=i)).isoformat()},{symbol},100.125,102.50,99.25,101.375,{i}"
        for i in range(count) for symbol in symbols]
    return dict(csv_text="\n".join(lines), source="synthetic-test", source_timezone="America/New_York",
                mode="FIXTURE", dataset_version="v1", ingested_at="2026-10-03T00:00:00Z",
                start=start.isoformat(), end=(start+timedelta(minutes=count)).isoformat(), market=dict(MARKET))


def prepare(data):
    return prepare_dataset(DatasetRequest(**data))


class DatasetTest(unittest.TestCase):
    def test_independent_identity(self):
        data = payload(1)
        data["source"] = "é-source"
        data["csv_text"] = "\ufeff " + HEADER + " \n2026-10-02T09:30:00-04:00, AAA ,100.12345678,102.50,99.25,101.375,0"
        rows = [dict(timestamp="2026-10-02T13:30:00+00:00", symbol="AAA",
                     open="100.12345678", high="102.50", low="99.25", close="101.375", volume="0")]
        expected = dict(schema_version="triad.research-dataset.v1", owner="triad", rows=rows,
                        metadata=dict(source="é-source", source_timezone="America/New_York",
                                      mode="FIXTURE", dataset_version="v1",
                                      ingested_at="2026-10-03T00:00:00+00:00", market=MARKET),
                        window=dict(start="2026-10-02T13:30:00+00:00", end="2026-10-02T13:31:00+00:00"))
        digest = hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":"),
                                          ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        report = prepare(data)
        self.assertEqual(report["rows"], rows)
        self.assertEqual(report["prepared_sha256"], digest)
        self.assertEqual(prepare(data)["prepared_sha256"], digest)
        self.assertEqual(report["raw_sha256"], hashlib.sha256(data["csv_text"].encode()).hexdigest())
        for text in ("BOM", "whitespace", "UTC", "sorted", "trailing zeros", "floats"):
            self.assertIn(text, " ".join(report["transformations"]))

    def test_material_changes_and_order(self):
        data = payload()
        original = prepare(data)
        lines = data["csv_text"].splitlines()
        reordered = prepare({**data, "csv_text": "\n".join([lines[0]] + lines[:0:-1])})
        self.assertEqual(original["rows"], reordered["rows"])
        self.assertEqual(original["prepared_sha256"], reordered["prepared_sha256"])
        self.assertNotEqual(original["raw_sha256"], reordered["raw_sha256"])
        for key, value in dict(source="é-source", source_timezone="UTC", mode="REAL",
                              dataset_version="v2", ingested_at="2026-10-04T00:00:00Z",
                              end="2026-10-02T13:43:00Z", start="2026-10-02T13:29:00Z",
                              market={**MARKET, "confirmed":False},
                              csv_text=data["csv_text"].replace("100.125","100.126")).items():
            with self.subTest(key=key):
                self.assertNotEqual(original["prepared_sha256"], prepare({**data,key:value})["prepared_sha256"])

    def test_real_sdk_roundtrip_and_owner(self):
        for symbols in (("AAA",), ("AAA","BBB")):
            for mode in ("FIXTURE", "SIMULATED", "REAL"):
                report = prepare({**payload(symbols=symbols), "mode":mode})
                self.assertTrue(report["core_eligibility"]["eligible"])
                supplied = ResearchInput.model_validate_json(json.dumps(report["core_input"]))
                self.assertEqual(supplied.model_dump(mode="json"), report["core_input"])
                self.assertEqual(supplied.owner, "triad")
                self.assertEqual(supplied.mode, mode)
                self.assertEqual(supplied.dataset_version, "v1")
                self.assertEqual(supplied.dataset_id, report["prepared_sha256"])
                self.assertEqual(len(ProductResearch("triad").frame(supplied)),12*len(symbols))
                for bar in supplied.bars:
                    self.assertEqual(bar.provenance_id, supplied.dataset_id)
                    self.assertEqual(bar.source, "synthetic-test")
                    self.assertEqual(bar.source_symbol, bar.symbol)
                    self.assertEqual(bar.timezone, "America/New_York")
                with self.assertRaises(PermissionError):
                    validate_research_input(supplied.model_copy(update={"owner":"aegis"}))

    def test_rejections_keep_every_row(self):
        data = payload()
        lines = data["csv_text"].splitlines()
        cases = [payload(1), payload(symbols=("BRK.B",)),
                 {**data,"csv_text":"\n".join(lines[:5]+lines[6:])},
                 {**data,"csv_text":data["csv_text"].replace("13:30:00","13:30:01")},
                 {**data,"ingested_at":"2026-10-01T00:00:00Z"},
                 {**data,"start":"2026-10-02T13:31:00Z"},
                 {**data,"market":{**MARKET,"confirmed":False}},
                 {k:v.replace("2026","2025") if isinstance(v,str) else v for k,v in data.items()}]
        for case in cases:
            report = prepare(case)
            self.assertFalse(report["core_eligibility"]["eligible"])
            self.assertIsNone(report["core_input"])
            self.assertEqual(len(report["rows"]), len(case["csv_text"].splitlines())-1)
            self.assertLess(len(json.dumps(report["core_eligibility"])), 500)
        with patch("products.triad.research_dataset.validate_research_input") as sdk:
            prepare({**data,"market":{**MARKET,"confirmed":False}})
            sdk.assert_not_called()

    def test_mounted_api_limits_and_private_errors(self):
        host = FastAPI()
        host.mount("/triad/product-api", app)
        client = TestClient(host)
        url = "/triad/product-api/research/dataset-preparation"
        data = payload()
        self.assertEqual(client.post(url,json=data).status_code,200)
        self.assertFalse(client.post(url,json=payload(1)).json()["core_eligibility"]["eligible"])
        bad = [{**data,"SECRET":"SECRET"}, {**data,"source":12}, {**data,"source":" "},
               {**data,"source":"SECRET"*100}, {**data,"source_timezone":"invalid"},
               {**data,"mode":"SECRET"}, {**data,"start":123456789},
               {**data,"start":"2026-10-02T13:30:00"}, {**data,"end":data["start"]},
               {**data,"csv_text":"SECRET"}, {**data,"csv_text":"x"*1000001},
               {**data,"csv_text":"é"*500001}, payload(5001),
               {**data,"csv_text":data["csv_text"]+"\n"+data["csv_text"].splitlines()[1]},
               {**data,"market":{**MARKET,"confirmed":"true"}},
               {**data,"market":{**MARKET,"confirmed":1}},
               {**data,"market":{**MARKET,"currency":"EUR"}}]
        for key in data:
            missing = dict(data); del missing[key]; bad.append(missing)
        for case in bad:
            response = client.post(url,json=case)
            self.assertEqual(response.status_code,422, response.text)
            self.assertLess(len(response.text),300)
            self.assertNotIn("SECRET",response.text)
        with patch("products.triad.research_dataset.validate_research_input") as sdk:
            response=client.post(url,json={**data,"end":"2026-11-02T13:30:00.000001Z"})
            self.assertEqual(response.status_code,422)
            sdk.assert_not_called()
        self.assertEqual(client.post(url,json={**data,"end":"2026-11-02T13:30:00Z"}).status_code,200)
        self.assertEqual(client.post(url,json=payload(5000)).status_code,200)
        # Padding a cell keeps CSV valid at the exact byte ceiling.
        sized = data["csv_text"] + " "*(1_000_000-len(data["csv_text"].encode()))
        self.assertEqual(len(sized.encode()), 1_000_000)
        self.assertEqual(client.post(url,json={**data,"csv_text":sized}).status_code,200)
        self.assertEqual(client.post(url,json={**data,"csv_text":sized+" "}).status_code,422)
