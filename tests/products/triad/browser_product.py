"""Executed Chromium interactions against candidate HTML and real local API."""

import socket
import threading
import unittest
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from playwright.sync_api import sync_playwright
from products.triad.product_app import app as product


class ProductBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()
        app.mount("/triad/product-api", product)

        @app.get("/triad/product")
        def page():
            return HTMLResponse(Path("app/products/triad/static/product.html").read_text())

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        cls.url = "http://127.0.0.1:" + str(sock.getsockname()[1]) + "/triad/product"
        cls.server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        cls.thread = threading.Thread(target=lambda: cls.server.run(sockets=[sock]), daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.should_exit = True
        cls.thread.join(5)

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1100, "height": 900})
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.url)

    def tearDown(self):
        self.assertEqual(self.errors, [])
        self.page.close()

    def test_bar_inspector_reaches_real_candidate_api(self):
        self.page.locator("#bar-csv").fill(
            "timestamp,symbol,open,high,low,close,volume\n2026-10-02T13:30:00Z,LABTEST,100,102,99,101,1000\n2026-10-02T13:31:00Z,LABTEST,101,103,100,102,1200"
        )
        self.page.locator("#bar-form button[type=submit]").click()
        self.page.wait_for_function("!document.getElementById('bar-results').hidden")
        self.assertIn("LABTEST", self.page.locator("#bar-coverage-rows").inner_text())

    def test_ledger_sample_is_analyzable_through_real_api(self):
        self.page.locator("#ledger-sample").click()
        self.page.locator("#ledger-form button[type=submit]").click()
        self.page.wait_for_function("!document.getElementById('ledger-results').hidden")
        self.assertFalse(self.page.locator("#ledger-download").is_disabled())

    def test_keyboard_and_narrow_viewport_can_reach_tool(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.locator("#bar-csv").focus()
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "bar-csv")
        self.page.keyboard.press("Tab")
        self.assertEqual(self.page.evaluate("document.activeElement.tagName"), "BUTTON")
        self.assertTrue(self.page.locator("#bar-form button[type=submit]").is_visible())
