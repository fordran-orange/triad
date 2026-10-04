"""Executed Chromium interactions against candidate HTML and real local API."""

import json

from tests.products.triad.browser_product import ProductBrowserTest


class ExperimentBrowserTest(ProductBrowserTest):
    def _prepare_eligible_dataset_core_input(self):
        rows = ["timestamp,symbol,open,high,low,close,volume"]
        for i in range(12):
            minute = 30 + i
            rows.append(
                f"2026-10-02T13:{minute:02d}:00Z,LABTEST,{100+i},{102+i},{99+i},{101+i},1000"
            )
        core_input_json = self.page.evaluate(
            "fetch('/triad/product-api/research/dataset-preparation', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({"
            "source:'synthetic-browser',"
            "source_timezone:'America/New_York',"
            "dataset_version:'browser-fixture-v1',"
            "mode:'FIXTURE',"
            "ingested_at:'2026-10-03T00:00:00Z',"
            "start:'2026-10-02T13:30:00Z',"
            "end:'2026-10-02T13:42:00Z',"
            "csv_text:" + json.dumps("\n".join(rows)) + ","
            "market:{resolution:'1m',exchange:'XNYS',session:'REGULAR',currency:'USD',asset_class:'equity',adjustment_status:'UNADJUSTED',confirmed:true}"
            "})}).then(r => r.json()).then(d => JSON.stringify(d.core_input))"
        )
        return json.loads(core_input_json)

    def test_experiment_runs_and_renders_real_result(self):
        core_input = self._prepare_eligible_dataset_core_input()
        self.page.locator("#exp-core_input").fill(json.dumps(core_input))
        self.page.locator("#exp-period").fill("4")
        self.page.locator("#exp-hold").fill("2")
        self.page.locator("[name=direction_long]").check()
        self.page.locator("#exp-form button[type=submit]").click()
        self.page.wait_for_function("!document.getElementById('exp-results').hidden")
        identity = self.page.locator("#exp-identity").inner_text()
        self.assertIn("Dataset SHA-256", identity)
        self.assertIn("fixture", self.page.locator("#exp-limitations").inner_text().lower())
        row_cells = self.page.locator("#exp-rows tr").first.locator("td")
        self.assertGreater(row_cells.count(), 0)
        for cell_index in range(row_cells.count()):
            self.assertNotEqual(row_cells.nth(cell_index).inner_text().strip(), "")
        for label in ("Contract", "Owner", "Mode"):
            value = self.page.locator(f"#exp-summary dt:has-text('{label}') + dd").inner_text()
            self.assertNotEqual(value.strip(), "")

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

    def test_second_completed_result_supersedes_first_stale_one(self):
        core_input = self._prepare_eligible_dataset_core_input()
        self.page.locator("#exp-core_input").fill(json.dumps(core_input))
        self.page.locator("#exp-period").fill("4")
        self.page.locator("#exp-hold").fill("2")
        self.page.locator("[name=direction_long]").check()
        self.page.evaluate(
            """() => {
              const originalFetch = window.fetch.bind(window);
              const form = document.getElementById('exp-form');
              const originalSubmit = form.onsubmit;
              const state = window.__lateExperiment = {
                bodies: {}, finished: {}, handlers: {}, requests: 0, submits: 0
              };
              const gate = new Promise(resolve => state.release = resolve);
              form.onsubmit = function(event) {
                const index = ++state.submits;
                const handler = originalSubmit.call(this, event);
                state.handlers[index] = handler;
                handler.then(() => state.finished[index] = true);
                return handler;
              };
              window.fetch = async function(input, init) {
                if (!String(input).endsWith('/research/experiment')) {
                  return originalFetch(input, init);
                }
                const index = ++state.requests;
                const options = {...init};
                // Only test transport ignores first cancellation, so a completed
                // late body really reaches the unchanged production handler.
                if (index === 1) delete options.signal;
                const response = await originalFetch(input, options);
                state.bodies[index] = await response.clone().json();
                if (index === 1) {
                  state.firstCompleted = true;
                  await gate;
                }
                return response;
              };
            }"""
        )
        self.page.locator("#exp-form button[type=submit]").click()
        self.page.wait_for_function("window.__lateExperiment.firstCompleted === true")
        self.assertFalse(self.page.evaluate("Boolean(window.__lateExperiment.finished[1])"))
        self.page.locator("#exp-period").fill("6")
        self.page.locator("#exp-hold").fill("3")
        self.page.locator("#exp-form button[type=submit]").click()
        self.page.wait_for_function("window.__lateExperiment.finished[2] === true")
        bodies = self.page.evaluate("window.__lateExperiment.bodies")
        first_id = bodies["1"]["experiment_id"]
        second_id = bodies["2"]["experiment_id"]
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(self.page.evaluate("window.__lateExperiment.requests"), 2)
        self.assertFalse(self.page.locator("#exp-results").is_hidden())
        identity = self.page.locator("#exp-identity").inner_text()
        self.assertIn(second_id, identity)
        self.assertNotIn(first_id, identity)
        second_rows = self.page.locator("#exp-rows").inner_text()
        self.page.evaluate(
            "async () => { window.__lateExperiment.release(); "
            "await window.__lateExperiment.handlers[1]; }"
        )
        self.assertTrue(self.page.evaluate("window.__lateExperiment.finished[1] === true"))
        identity = self.page.locator("#exp-identity").inner_text()
        self.assertIn(second_id, identity, "Late first response replaced the newer result")
        self.assertNotIn(first_id, identity)
        self.assertEqual(self.page.locator("#exp-rows").inner_text(), second_rows)

    def test_keyboard_and_narrow_viewport_can_reach_experiment_form(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        core_input = self._prepare_eligible_dataset_core_input()
        self.page.locator("#exp-core_input").fill(json.dumps(core_input))
        self.page.locator("#exp-period").fill("4")
        self.page.locator("#exp-hold").fill("2")
        self.page.locator("[name=direction_long]").check()
        self.page.locator("#exp-core_input").focus()
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "exp-core_input")
        controls = self.page.locator("#exp-form input, #exp-form textarea, #exp-form button").count()
        focused_submit = "document.activeElement === document.querySelector('#exp-form button[type=submit]')"
        for _ in range(controls + 1):
            if self.page.evaluate(focused_submit):
                break
            self.page.keyboard.press("Tab")
        self.assertTrue(self.page.evaluate(focused_submit), "Keyboard did not reach submit")
        self.page.keyboard.press("Enter")
        self.page.wait_for_function("!document.getElementById('exp-results').hidden")
        self.assertIn("experiment:", self.page.locator("#exp-identity").inner_text())
        self.assertLessEqual(self.page.evaluate("document.scrollingElement.scrollWidth"), 390)
