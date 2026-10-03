"""Chromium against candidate assets and mounted real API."""
import json
from pathlib import Path
from browser_product import ProductBrowserTest
from test_research_dataset import payload

class DatasetBrowserTest(ProductBrowserTest):
    def submit(self, data):
        for key,value in data.items():
            locator=self.page.locator("#ds-"+("csv" if key=="csv_text" else key))
            if key=="mode": locator.select_option(value)
            else: locator.fill(value)
        self.page.locator("#dataset-form button").click()
        self.page.wait_for_function("!document.getElementById('ds-results').hidden")

    def test_geometry_navigation_and_downloads(self):
        self.submit(payload(45,("AAA","BBB")))
        self.assertEqual(self.page.locator(".candle").count(),40)
        # high=102.5, low=99.25: y(open)=166.1538; y(close)=89.2308.
        candle=self.page.locator(".candle").first
        self.assertAlmostEqual(float(candle.get_attribute("y")),89.2307692308)
        self.assertAlmostEqual(float(candle.get_attribute("height")),76.9230769231)
        self.assertEqual(float(self.page.locator(".volume").first.get_attribute("height")),0)
        self.assertEqual(float(self.page.locator(".volume").last.get_attribute("height")),60)
        self.assertIn("100.125",self.page.locator("#ds-rows").inner_text())
        self.assertIn("UTC",self.page.locator("#ds-chart").text_content())
        self.page.locator("#ds-next").click()
        self.assertEqual(self.page.locator(".candle").count(),5)
        self.page.locator("#ds-symbol").select_option("BBB")
        self.assertEqual(self.page.locator(".candle").count(),40)
        self.assertIn("BBB",self.page.locator("#ds-rows").inner_text())
        self.page.locator("#ds-next").click();self.page.locator("#ds-prev").click()
        self.assertIn("1–40",self.page.locator("#ds-range").inner_text())
        downloads=[]
        for button in ("report","core"):
            with self.page.expect_download() as event:
                self.page.locator("#ds-"+button).click()
            downloads.append(json.loads(Path(event.value.path()).read_text()))
        report,core=downloads
        self.assertEqual(core,report["core_input"])
        self.assertEqual(core["dataset_id"],report["prepared_sha256"])
        self.assertEqual(core["bars"][0]["source"],"synthetic-test")
        actual=self.page.request.post(self.url.replace("/product","/product-api/research/dataset-preparation"),data=payload(45,("AAA","BBB"))).json()
        self.assertEqual(report,actual)

    def test_flat_single_irregular_and_accessibility(self):
        data=payload(1);data["csv_text"]=data["csv_text"].replace("100.125,102.50,99.25,101.375","100,100,100,100")
        self.submit(data)
        self.assertEqual(self.page.locator(".candle").get_attribute("height"),"1")
        self.assertEqual(self.page.locator(".volume").get_attribute("height"),"0")
        self.assertTrue(self.page.locator("#ds-core").is_disabled())
        self.assertIn("Core rejected",self.page.locator("#ds-eligibility").inner_text())
        data=payload(3);data["csv_text"]=data["csv_text"].replace("13:31:00","13:31:30")
        self.submit(data)
        self.assertEqual(self.page.locator(".candle").count(),3)
        self.assertTrue(self.page.locator("#ds-core").is_disabled())
        self.page.set_viewport_size({"width":390,"height":844})
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"),390)
        self.page.get_by_label("Chart symbol").focus()
        self.assertEqual(self.page.evaluate("document.activeElement.id"),"ds-symbol")
        self.assertEqual(self.page.locator("#ds-status").get_attribute("role"),"status")
        self.assertTrue(self.page.get_by_role("region",name="Exact OHLCV values").is_visible())

    def assert_cleared(self):
        self.assertTrue(self.page.locator("#ds-results").is_hidden())
        self.assertTrue(self.page.locator("#ds-core").is_disabled())
        self.assertTrue(self.page.locator("#ds-report").is_disabled())
        self.assertEqual(self.page.locator(".candle").count(),0)

    def test_edits_failures_and_superseded_response(self):
        self.submit(payload())
        self.page.locator("#ds-source").fill("<script>bad()</script>")
        self.assert_cleared()
        self.page.locator("#dataset-form button").click()
        self.page.wait_for_function("!document.getElementById('ds-results').hidden")
        self.page.locator("#ds-csv").fill("malformed")
        self.assert_cleared()
        self.page.locator("#dataset-form button").click()
        self.page.wait_for_function("document.getElementById('ds-status').textContent.startsWith('Preparation failed')")
        self.assert_cleared()
        self.submit(payload())
        self.page.route("**/research/dataset-preparation",lambda route:route.abort())
        self.page.locator("#dataset-form button").click()
        self.page.wait_for_function("document.getElementById('ds-status').textContent.startsWith('Preparation failed')")
        self.assert_cleared()
        self.page.unroute("**/research/dataset-preparation")
        # Deliberately ignore AbortSignal and hold the actual response past an edit.
        self.page.evaluate("""() => {
          const original=window.fetch;
          window.fetch=async (url,options)=>{
            delete options.signal;
            const response=await original(url,options);
            await new Promise(resolve=>window.releaseDataset=resolve);
            return response;
          };
        }""")
        self.page.locator("#dataset-form button").click()
        self.page.wait_for_function("typeof window.releaseDataset==='function'")
        self.page.locator("#ds-source").fill("edited")
        self.page.evaluate("window.releaseDataset()")
        self.page.wait_for_timeout(150)
        self.assert_cleared()
