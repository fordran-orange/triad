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

        # Capture the real trade markers of both results independently, as the test oracle,
        # before driving the UI so the DOM assertions below do not depend on the DOM itself.
        pair_json = self.page.evaluate(
            "async (core_input) => {"
            "  const post = async (period, hold) => {"
            "    const response = await fetch('/triad/product-api/research/experiment', {"
            "      method: 'POST', headers: {'Content-Type': 'application/json'},"
            "      body: JSON.stringify({core_input, period, hold, directions: ['LONG'],"
            "        fees: {fixed: 0, per_share: 0, bps: 0}, slippage: {bps: 0, spread_bps: 0}})"
            "    });"
            "    return await response.json();"
            "  };"
            "  const first = await post(4, 2);"
            "  const second = await post(6, 3);"
            "  return JSON.stringify([first, second]);"
            "}",
            core_input,
        )
        first_body, second_body = json.loads(pair_json)
        first_trade = first_body["results"]["trades"][0]
        second_trade = second_body["results"]["trades"][0]
        first_marker = first_trade["entry_time"] + "|" + first_trade["exit_time"]
        second_marker = second_trade["entry_time"] + "|" + second_trade["exit_time"]
        self.assertNotEqual(first_marker, second_marker)

        # Install a fetch wrapper that intercepts only the first call to the experiment
        # endpoint. It performs the real network call immediately (so the genuine first
        # response body is produced right away) but withholds delivering that Response
        # back to the page's own `await fetch(...)` call site until the test explicitly
        # releases a page-global gate. The second call passes through untouched.
        self.page.evaluate(
            """
            () => {
              window.__experimentCallCount = 0;
              window.__releaseFirstExperimentResponse = new Promise(resolve => {
                window.__resolveFirstExperimentGate = resolve;
              });
              const originalFetch = window.fetch.bind(window);
              window.fetch = async (url, init) => {
                if (typeof url === 'string' && url.endsWith('/research/experiment')) {
                  window.__experimentCallCount += 1;
                  if (window.__experimentCallCount === 1) {
                    const response = await originalFetch(url, init);
                    await window.__releaseFirstExperimentResponse;
                    return response;
                  }
                }
                return originalFetch(url, init);
              };
            }
            """
        )

        self.page.locator("#exp-core_input").fill(json.dumps(core_input))
        self.page.locator("#exp-period").fill("4")
        self.page.locator("#exp-hold").fill("2")
        self.page.locator("[name=direction_long]").check()
        # Click submit for the first (held) request without waiting for it to resolve;
        # it blocks inside the wrapped fetch at the delivery gate.
        self.page.locator("#exp-form button[type=submit]").click()

        # Immediately submit the second, independent request, which is not intercepted
        # and reaches the unmodified version-guard/render logic in the form handler.
        self.page.locator("#exp-period").fill("6")
        self.page.locator("#exp-hold").fill("3")
        self.page.locator("#exp-form button[type=submit]").click()
        self.page.wait_for_function("!document.getElementById('exp-results').hidden")
        rows_text = self.page.locator("#exp-rows").inner_text()
        self.assertIn(second_trade["entry_time"], rows_text)
        self.assertIn(second_trade["exit_time"], rows_text)

        # Only now release the gate so the real, completed first Response flows back into
        # the first submission's own still-awaiting handler invocation. Its own
        # `if (current !== version) return` guard must prevent it from overwriting the
        # already-painted second result.
        self.page.evaluate(
            "() => { window.__resolveFirstExperimentGate(); return new Promise(r => setTimeout(r, 0)); }"
        )
        self.page.wait_for_timeout(50)

        rows_text = self.page.locator("#exp-rows").inner_text()
        self.assertIn(second_trade["entry_time"], rows_text)
        self.assertIn(second_trade["exit_time"], rows_text)
        self.assertNotIn(first_marker, rows_text)

    def test_keyboard_and_narrow_viewport_can_reach_experiment_form(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.locator("#exp-core_input").focus()
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "exp-core_input")
        for _ in range(6):
            self.page.keyboard.press("Tab")
        self.assertTrue(self.page.locator("#exp-form button[type=submit]").is_visible())
        self.assertLessEqual(self.page.evaluate("document.scrollingElement.scrollWidth"), 390)
