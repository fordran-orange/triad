"""Independent dataset identity, real SDK and mounted API checks."""
import hashlib
import json
import unittest
from datetime import UTC, datetime, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from products.triad.product_app import app
from products.triad.research_dataset import DatasetRequest, prepare_dataset
from trading_core.product_sdk import ProductResearch, ResearchInput

HEADER = "timestamp,symbol,open,high,low,close,volume"
def payload(count=12, symbols=("LABTEST",)):
    start = datetime(2026, 10, 2, 13, 30, tzinfo=UTC)
    lines = [HEADER]
    for i in range(count):
        for symbol in symbols:
            lines.append(f"{(start+timedelta(minutes=i)).isoformat()},{symbol},100.125,102.50,99.25,101.375,{i}")
    return dict(csv_text="\n".join(lines), source="synthetic-test",
                source_timezone="America/New_York", mode="FIXTURE", dataset_version="v1",
                ingested_at="2026-10-03T00:00:00Z",
                start=start.isoformat(), end=(start+timedelta(minutes=count)).isoformat())

def prepare(data):
    return prepare_dataset(DatasetRequest(**data))

class DatasetTest(unittest.TestCase):
    def test_identity_and_normalization(self):
        data=payload(1, ("BRK.B",))
        data["csv_text"]="\ufeff "+HEADER+" \n 2026-10-02T09:30:00-04:00 , BRK.B ,100.125,102.50,99.25,101.375,0 "
        report=prepare(data)
        rows=[dict(timestamp="2026-10-02T13:30:00+00:00",symbol="BRK.B",
                   open="100.125",high="102.50",low="99.25",close="101.375",volume="0")]
        self.assertEqual(report["rows"],rows)
        self.assertEqual(report["coverage"],[dict(symbol="BRK.B",bar_count=1,
                         first_timestamp=rows[0]["timestamp"],last_timestamp=rows[0]["timestamp"])])
        expected=dict(schema_version="triad.research-dataset.v1",owner="triad",
                      rows=rows,metadata=dict(source="synthetic-test",source_timezone="America/New_York",
                      mode="FIXTURE",dataset_version="v1",ingested_at="2026-10-03T00:00:00+00:00"),
                      window=dict(start="2026-10-02T13:30:00+00:00",end="2026-10-02T13:31:00+00:00"))
        digest=hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        self.assertEqual(report["prepared_sha256"],digest)
        self.assertEqual(report["raw_sha256"],hashlib.sha256(data["csv_text"].encode()).hexdigest())
        self.assertEqual(prepare(data)["prepared_sha256"],digest)
        self.assertTrue(any("BOM" in x for x in report["transformations"]))
        self.assertFalse(report["core_eligibility"]["eligible"])

    def test_material_changes_and_reordering(self):
        data=payload(); original=prepare(data)
        lines=data["csv_text"].splitlines()
        reordered=prepare({**data,"csv_text":"\n".join([lines[0]]+lines[:0:-1])})
        self.assertEqual(original["prepared_sha256"],reordered["prepared_sha256"])
        self.assertNotEqual(original["raw_sha256"],reordered["raw_sha256"])
        for key,value in dict(source="other",source_timezone="UTC",mode="REAL",dataset_version="v2",
                              ingested_at="2026-10-04T00:00:00Z",end="2026-10-02T13:43:00Z",
                              csv_text=data["csv_text"].replace("100.125","100.126")).items():
            self.assertNotEqual(original["prepared_sha256"],prepare({**data,key:value})["prepared_sha256"])

    def test_real_core_roundtrip(self):
        data=payload(symbols=("AAA","BBB")); report=prepare(data)
        self.assertTrue(report["core_eligibility"]["eligible"])
        supplied=ResearchInput.model_validate(report["core_input"])
        frame=ProductResearch("triad").frame(supplied)
        self.assertEqual(len(frame),24)
        self.assertEqual(supplied.owner,"triad")
        self.assertEqual(supplied.mode,"FIXTURE")
        self.assertEqual(supplied.dataset_version,"v1")
        self.assertEqual(supplied.bars[0].source,"synthetic-test")
        self.assertEqual(supplied.bars[0].source_symbol,"AAA")
        self.assertEqual(supplied.bars[0].timezone,"America/New_York")
        self.assertEqual(supplied.bars[0].provenance_id,report["prepared_sha256"])
        self.assertEqual(supplied.bars[0].ingested_at.isoformat(),"2026-10-03T00:00:00+00:00")

    def test_core_rejections_retain_rows(self):
        data=payload()
        missing=data["csv_text"].splitlines();del missing[5]
        cases=[payload(1),payload(symbols=("BRK.B",)),
               {**data,"csv_text":"\n".join(missing)},
               {**data,"csv_text":data["csv_text"].replace("13:30:00","13:30:01")},
               {**data,"ingested_at":"2026-10-01T00:00:00Z"},
               {k:v.replace("2026","2025") if isinstance(v,str) else v for k,v in data.items()}]
        for case in cases:
            report=prepare(case)
            self.assertFalse(report["core_eligibility"]["eligible"])
            self.assertIsNone(report["core_input"])
            self.assertTrue(report["rows"])

    def test_mounted_api_and_bounded_errors(self):
        host=FastAPI();host.mount("/triad/product-api",app)
        client=TestClient(host);url="/triad/product-api/research/dataset-preparation"
        self.assertEqual(client.post(url,json=payload()).json()["schema_version"],"triad.research-dataset.v1")
        self.assertFalse(client.post(url,json=payload(1)).json()["core_eligibility"]["eligible"])
        data=payload()
        bad=[{**data,"owner":"triad"},{**data,"unknown":"SECRET"},{**data,"source":"SECRET"*100},
             {**data,"mode":"SECRET"},{**data,"start":"2026-10-02T13:30:00"},
             {**data,"end":data["start"]},{**data,"csv_text":"SECRET"},
             {**data,"csv_text":"x"*1000001},{**data,"csv_text":"é"*500001},
             {**data,"csv_text":data["csv_text"]+"\n"+data["csv_text"].splitlines()[1]},
             payload(5001)]
        for case in bad:
            response=client.post(url,json=case)
            self.assertEqual(response.status_code,422)
            self.assertLess(len(response.text),300)
            self.assertNotIn("SECRET",response.text)
