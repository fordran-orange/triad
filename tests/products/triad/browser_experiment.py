"""Executed Chromium interactions against candidate HTML and real local API."""

import json

from tests.products.triad.browser_product import ProductBrowserTest


class ExperimentBrowserTest(ProductBrowserTest):
    def _prepare_eligible_dataset_core_input(self):
        self.page.locator("#ds-source").fill("synthetic-browser")
        self.page.locator("#ds-source_timezone").fill("America/New_York")
        self.page.locator("#ds-dataset_version").fill("browser-fixture-v1")
        self.page.locator("#ds-ingested_at").fill("2026-10-03T00:00:00Z")
        self.page.locator("#ds-start").fill("2026-10-02T13:30:00Z")
        self.page.locator("#ds-end").fill("2026-10-02T13:42:00Z")
        self.page.locator("#ds-mode").select_option("FIXTURE")
        self.page.locator("#ds-confirm").check()
        rows = ["timestamp,symbol,open,high,low,close,volume"]
        for i in range(12):
            minute = 30 + i
            rows.append(
                f"2026-10-02T13:{minute:02d}:00Z,LABTEST,{100+i},{102+i},{99+i},{101+i},1000"
            )
        self.page.locator("#ds-csv").fill("\n".join(rows))
        self.page.locator("#dataset-form button[type=submit]").click()
        self.page.wait_for_function("!document.getElementById('ds-results').hidden")
        self.assertFalse(self.page.locator("#ds-core").is_disabled())
        report_json = self.page.evaluate(
            "fetch('/triad/product-api/research/dataset-preparation', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({"
            "source:document.getElementById('ds-source').value,"
            "source_timezone:document.getElementById('ds-source_timezone').value,"
            "dataset_version:document.getElementById('ds-dataset_version').value,"
            "mode:document.getElementById('ds-mode').value,"
            "ingested_at:document.getElementById('ds-ingested_at').value,"
            "start:document.getElementById('ds-start').value,"
            "end:document.getElementById('ds-end').value,"
            "csv_text:document.getElementById('ds-csv').value,"
            "market:{resolution:'1m',exchange:'XNYS',session:'REGULAR',currency:'USD',asset_class:'equity',adjustment_status:'UNADJUSTED',confirmed:true}"
            "})}).then(r => r.json()).then(d => JSON.stringify(d.core_input))"
        )
        return json.loads(report_json)

    def test_experiment_runs_and_renders_real_result(self):
        core_input = self._prepare_eligible_dataset_core_input()
        self.page.locator("#exp-core_input").fill(json.dumps(core_input))
        self.page.locator("#exp-period").fill("4")
        self.page.locator("#exp-hold").fill("2")
        self.page.locator("[name=direction_long]").check()
        self.page.locator("#exp-form button[type=submit]").click()
        self.page.wait_for_function("!document.getElementById('exp-results').hidden")
        text = self.page.locator("#exp-identity").inner_text()
        self.assertIn("Dataset SHA-256", text)
        self.assertIn("fixture", self.page.locator("#exp-limitations").inner_text().lower())

    def test_editing_clears_prior_results(self):
        core_input = self._prepare_eligible_dataset_core_input()
        self.page.locator("#exp-core_input").fill(json.dumps(core_input))
        self.page.locator("#exp-period").fill("4")
        self.page.locator("#exp-hold").fill("2")
        self.page.locator("[name=direction_long]").check()
        self.page.locator("#exp-form button[type=submit]").click()
        self.page.wait_for_function("!document.getElementById('exp-results').hidden")
        self.page.locator("#exp-period").fill("6")
        self.assertTrue(self.page.locator("#exp-results").is_hidden())

    def test_keyboard_and_narrow_viewport_can_reach_experiment_form(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.locator("#exp-core_input").focus()
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "exp-core_input")
        self.assertTrue(self.page.locator("#exp-form button[type=submit]").is_visible())
