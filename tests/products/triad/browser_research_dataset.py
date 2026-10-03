"""Chromium checks against mounted candidate API; no mocked acceptance."""
import json
from pathlib import Path
from browser_product import ProductBrowserTest
from test_research_dataset import payload

class DatasetBrowserTest(ProductBrowserTest):
    def submit(self, data):
        for key,value in data.items():
            if key=="market":
                self.page.locator("#ds-confirm").set_checked(value["confirmed"])
            elif key=="mode":
                self.page.locator("#ds-mode").select_option(value)
            else:
                self.page.locator("#ds-"+("csv" if key=="csv_text" else key)).fill(value)
        self.page.locator("#dataset-form button").click()
        self.page.wait_for_function("!document.getElementById('ds-results').hidden")

    def cleared(self):
        for key in ("report","core"):
            self.assertTrue(self.page.locator("#ds-"+key).is_disabled())
        self.assertTrue(self.page.locator("#ds-results").is_hidden())
        self.assertEqual(self.page.locator(".candle").count(),0)
        self.assertEqual(self.page.locator("#ds-identity").inner_text(),"")

    def test_chart_and_downloads(self):
        data=payload(45,("AAA","BBB"))
        self.submit(data)
        self.assertEqual(self.page.locator(".candle").count(),40)
        candle=self.page.locator(".candle").first
        self.assertAlmostEqual(float(candle.get_attribute("y")),89.2307692308)
        self.assertAlmostEqual(float(candle.get_attribute("height")),76.9230769231)
        wick=self.page.locator(".wick").first
        self.assertEqual(float(wick.get_attribute("y1")),20)
        self.assertEqual(float(wick.get_attribute("y2")),220)
        self.assertEqual(float(self.page.locator(".volume").first.get_attribute("height")),0)
        self.assertEqual(float(self.page.locator(".volume").last.get_attribute("height")),60)
        self.assertIn("102.50",self.page.locator("#ds-rows").inner_text())
        self.assertIn("observed-bar order",self.page.locator("#dataset-workspace").inner_text())
        self.assertIn("UTC",self.page.locator("#ds-range").inner_text())
        self.page.locator("#ds-next").click()
        self.assertEqual(self.page.locator(".candle").count(),5)
        self.page.locator("#ds-symbol").select_option("BBB")
        self.assertEqual(self.page.locator(".candle").count(),40)
        self.assertIn("BBB",self.page.locator("#ds-rows").inner_text())
        self.page.locator("#ds-next").click()
        self.page.locator("#ds-prev").click()
        self.assertIn("1–40",self.page.locator("#ds-range").inner_text())
        actual=self.page.request.post(self.url.replace("/product","/product-api/research/dataset-preparation"),data=data).json()
        for button,expected in (("report",actual),("core",actual["core_input"])):
            with self.page.expect_download() as event:
                self.page.locator("#ds-"+button).click()
            self.assertEqual(json.loads(Path(event.value.path()).read_text()),expected)

    def test_flat_single_and_accessibility(self):
        data=payload(1)
        data["csv_text"]=data["csv_text"].replace("100.125,102.50,99.25,101.375","100,100,100,100")
        self.submit(data)
        self.assertEqual(self.page.locator(".candle").get_attribute("height"),"1")
        self.assertEqual(self.page.locator(".volume").get_attribute("height"),"0")
        self.assertTrue(self.page.locator("#ds-core").is_disabled())
        self.page.set_viewport_size({"width":390,"height":844})
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"),390)
        self.page.locator("#ds-symbol").focus()
        self.page.keyboard.press("Tab")
        self.assertEqual(self.page.locator("#ds-status").get_attribute("role"),"status")
        self.page.get_by_role("region",name="Exact OHLCV values").focus()
        self.assertEqual(self.page.evaluate("document.activeElement.getAttribute('role')"),"region")

    def test_edits_errors_and_safe_source(self):
        data=payload()
        data["source"]="<img src=x onerror=alert(1)>"
        self.submit(data)
        self.assertIn(data["source"],self.page.locator("#ds-source-label").inner_text())
        self.assertEqual(self.page.locator("#ds-source-label img").count(),0)
        for field in ("source","source_timezone","dataset_version","ingested_at","start","end","csv"):
            self.page.locator("#ds-"+field).fill("changed")
            self.cleared()
            self.submit(payload())
        self.page.locator("#ds-mode").select_option("REAL")
        self.cleared()
        self.submit(payload())
        self.page.locator("#ds-confirm").uncheck()
        self.cleared()
        self.submit(payload())
        self.page.locator("#ds-csv").fill("malformed")
        self.page.locator("#dataset-form button").click()
        self.page.wait_for_function("document.getElementById('ds-status').textContent.startsWith('Preparation failed')")
        self.cleared()
        self.submit(payload())
        self.page.route("**/research/dataset-preparation",lambda route:route.abort())
        self.page.locator("#dataset-form button").click()
        self.page.wait_for_function("document.getElementById('ds-status').textContent.startsWith('Preparation failed')")
        self.cleared()

    def test_delayed_responses_after_edit_and_new_submission(self):
        self.submit(payload())
        self.page.evaluate("""() => {
          const original=window.fetch;
          window.pending=[];
          window.fetch=async (url,options)=>{
            delete options.signal;
            const response=await original(url,options);
            await new Promise(resolve=>window.pending.push(resolve));
            return response;
          };
        }""")
        self.page.locator("#dataset-form button").click()
        self.page.wait_for_function("window.pending.length===1")
        self.page.locator("#ds-source").fill("edited")
        self.page.evaluate("window.pending.shift()()")
        self.page.wait_for_timeout(100)
        self.cleared()
        self.page.locator("#dataset-form button").click()
        self.page.wait_for_function("window.pending.length===1")
        self.page.locator("#ds-source").fill("newest")
        self.page.locator("#dataset-form button").click()
        self.page.wait_for_function("window.pending.length===2")
        self.page.evaluate("window.pending.pop()()")
        self.page.wait_for_function("!document.getElementById('ds-results').hidden")
        self.page.evaluate("window.pending.shift()()")
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.locator("#ds-source-label").inner_text(),"Caller-supplied source: newest")
