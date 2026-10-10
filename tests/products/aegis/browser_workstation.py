"""Aegis workstation acceptance: walks the 22 Mission 3 definition-of-done items and the 14 Mission 4 items (both specs §1) in Chromium
against the running worker and writes logs/aegis-acceptance-<stamp>.json with PASS/FAIL per
item, timings (indicator ms, backtest ms, optimizer cell ms) and both result_hash values.

Run:  .venv/Scripts/python.exe tests/products/aegis/browser_workstation.py [--base URL] [--headed]
Exit code 0 only when all 36 items PASS with no page errors.
Needs `pip install playwright` and `python -m playwright install chromium`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[3]
DASH = "—"
ITEMS = [
    "select QQQ",
    "select 1m, 15m, 30m, 1h or 1D",
    "choose a date range",
    "see real candles from the pinned raw archive",
    "see the permanent RAW ARCHIVE / NOT RESEARCH ELIGIBLE indicator",
    "see the 9 EMA and 30 SMA",
    "run a backtest",
    "inspect real entries and exits",
    "inspect LONG results independently",
    "inspect SHORT results independently",
    "inspect COMBINED results",
    "inspect temporal performance",
    "inspect trades",
    "inspect equity",
    "see real KPIs",
    "reload the saved experiment",
    "launch an optimization",
    "watch progress",
    "cancel it",
    "inspect progressively completed parameter cells",
    "view the final heatmap and table",
    "rerun an identical computational request and obtain the same result_hash",
    # Mission 4 (spec §1 items 1–14)
    "workers opt out of power throttling; gateway and Core latencies recorded",
    "open the Optimize popover in walk-forward mode and see the plan",
    "start a LONG walk-forward on QQQ 1D 2023–2024 and land on the Walk-Forward tab",
    "watch progress advance by window and cell while the status route stays responsive",
    "cancel between cells; completed windows stay and the job is cancelled",
    "start again and let it complete",
    "inspect every window: ranges, chosen configuration, in-sample objective, out-of-sample results, efficiency",
    "inspect the stitched out-of-sample equity with window boundaries",
    "inspect stability: parameter spread, positive out-of-sample windows, mean efficiency",
    "apply the final window's configuration and rerun the combined backtest",
    "reload the finished walk-forward from the persisted list and see the same numbers",
    "rerun an identical walk-forward request and obtain the same result_hash",
    "a walk-forward on a range too short for one window is refused with the bar counts",
    "after the restarts the governance contract and the disabled schedule record are unchanged",
]
WF_HEAD = "document.querySelector('.job-head')?.innerText ?? ''"
WF_ROWS = "document.querySelectorAll('#walkforward-windows-long tbody tr')"
PROGRESS = "document.querySelector('.results .chip.active').innerText.match(/(\\d+)\\/(\\d+)/)"


class Acceptance:
    def __init__(self, page: Page, base: str, stamp: str):
        self.page = page
        self.base = base.rstrip("/") + "/"
        self.stamp = stamp
        self.results: list[dict] = []
        self.timings: dict = {}
        self.hashes: list[str] = []
        self.errors: list[str] = []
        self.first_run: dict = {}
        self.indicators: dict = {}
        page.on("pageerror", lambda error: self.errors.append(str(error)))

    # -- plumbing -----------------------------------------------------------------------------
    def item(self, number: int, check):
        title = ITEMS[number - 1]
        started = time.perf_counter()
        try:
            detail = check()
            status = "PASS"
        except Exception as exc:  # noqa: BLE001 - every item is reported, never hidden
            status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
        ms = int((time.perf_counter() - started) * 1000)
        self.results.append(
            {"item": number, "title": title, "status": status, "detail": detail, "ms": ms}
        )
        print(f"[{status}] {number:>2}. {title} -- {detail}")

    def js(self, script: str):
        return self.page.evaluate(script)

    def header_line(self) -> str:
        return self.js("document.querySelector('.chart-header')?.innerText ?? ''")

    def wait_bars(self, timeout=90_000) -> int:
        self.page.wait_for_function(
            "/\\d[\\d,]* bars ·/.test(document.querySelector('.chart-header')?.innerText ?? '')",
            timeout=timeout,
        )
        return int(re.search(r"([\d,]+) bars ·", self.header_line()).group(1).replace(",", ""))

    def select(self, label: str, value: str):
        self.page.get_by_label(label).select_option(value)

    def api(self, path: str) -> dict:
        return self.page.request.get(self.base + "api/" + path).json()

    def run_state(self) -> str:
        return self.js("document.getElementById('run-state')?.innerText ?? ''")

    def run_backtest(self, timeout=120_000) -> dict:
        previous = self.run_state()
        started = time.perf_counter()
        with self.page.expect_response(
            lambda r: r.url.endswith("/aegis/api/backtest") and r.request.method == "POST",
            timeout=timeout,
        ) as caught:
            self.page.locator("#run-backtest").click()
        response = caught.value
        assert response.ok, f"backtest HTTP {response.status}: {response.text()[:200]}"
        envelope = response.json()
        self.page.wait_for_function(
            "(s => s.startsWith('run ') && s !== "
            + json.dumps(previous)
            + ")(document.getElementById('run-state')?.innerText ?? '')",
            timeout=timeout,
        )
        self.timings.setdefault("backtest_wall_ms", []).append(
            int((time.perf_counter() - started) * 1000)
        )
        self.timings.setdefault("backtest_server_ms", []).append(envelope["elapsed_ms"])
        self.hashes.append(envelope["result_hash"])
        return envelope

    def summary_cell(self, metric: str, side: str) -> str:
        column = {"long": 1, "short": 2, "combined": 3}[side]
        return self.js(
            "[...document.querySelectorAll('#summary-metrics tbody tr')]"
            f".find(r => r.cells[0].innerText === {json.dumps(metric)})?.cells[{column}].innerText ?? ''"
        )

    def tab(self, label: str):
        self.page.locator(".result-tabs button", has_text=label).click()

    def progress(self) -> tuple[int, int]:
        done, total = self.js(PROGRESS + ".slice(1).map(Number)")
        return int(done), int(total)

    def job_head(self) -> str:
        return self.js("document.querySelector('.job-head')?.innerText ?? ''")

    # -- walk-forward plumbing ----------------------------------------------------------------
    def open_walkforward(self, in_sample: int, out_of_sample: int) -> str:
        page = self.page
        if not self.js(
            "!!document.querySelector('.popover')"
        ):  # the button toggles; never close by accident
            page.locator("#optimize").click()
        page.locator("#walkforward-mode").click()
        page.locator("#in-sample-bars").fill(str(in_sample))
        page.locator("#out-of-sample-bars").fill(str(out_of_sample))
        page.wait_for_function(
            f"(t => /{in_sample}/.test(document.getElementById('in-sample-bars')?.value ?? '') && /\\d+ windows/.test(t))"
            "(document.getElementById('walkforward-plan')?.innerText ?? '')",
            timeout=90_000,
        )
        return self.js("document.getElementById('walkforward-plan').innerText")

    def start_walkforward(self) -> None:
        self.page.locator("#start-walkforward").click()
        self.page.wait_for_function(
            "document.querySelector('.result-tabs button.active')?.innerText === 'Walk-Forward'",
            timeout=30_000,
        )
        self.page.wait_for_selector(".job-head", timeout=30_000)

    def wf_cells(self) -> tuple[int, int]:
        done, total = self.js(f"({WF_HEAD}).match(/unit (\\d+) of (\\d+)/).slice(1).map(Number)")
        return int(done), int(total)

    def wf_cells_per_window(self) -> int:
        return int(re.search(r"(\d+) cells each", self.timings["walkforward_plan"]).group(1))

    def wf_done_rows(self) -> int:
        return self.js(
            f"[...{WF_ROWS}].filter(r => r.lastElementChild.innerText === 'done').length"
        )

    def latest_walkforward(self) -> dict:
        jobs = self.api("walkforward")
        assert jobs, "no persisted walk-forward"
        return self.api(f"walkforward/{jobs[0]['job_id']}")

    def walkforward_body(self, in_sample: int, out_of_sample: int) -> dict:
        strategy = self.api("strategy/default")
        return {
            "strategy": strategy,
            "side": "long",
            "data": {
                "symbol": "QQQ",
                "timeframe": "1D",
                "start": "2023-01-01",
                "end": "2024-12-31",
            },
            "settings": {"initial_capital": 100000, "allocation_fraction": 1},
            "objective": "net_pnl",
            "in_sample_bars": in_sample,
            "out_of_sample_bars": out_of_sample,
        }

    def post(self, path: str, body: dict):
        return self.page.request.post(
            self.base + "api/" + path,
            data=json.dumps(body),
            headers={"content-type": "application/json"},
        )

    def screenshot_path(self, label: str) -> Path:
        return ROOT / "logs" / f"aegis-acceptance-{self.stamp}-{label}.png"

    # -- the 22 items -------------------------------------------------------------------------
    def run(self):
        page = self.page
        page.goto(self.base)
        page.wait_for_function(
            "document.getElementById('strategy-name')?.innerText.length > 1", timeout=30_000
        )

        def item1():
            self.select("Symbol", "QQQ")
            line = self.header_line()
            assert line.startswith("QQQ ·"), line
            return "chart header " + line.split("\n")[0]

        self.item(1, item1)

        def item2():
            counts = {}
            # 1m needs a narrow range (50,000-bar cap); the others use the two-year range.
            page.get_by_label("Start date").fill("2024-06-03")
            page.get_by_label("End date").fill("2024-06-07")
            self.select("Timeframe", "1m")
            page.wait_for_function(
                "(document.querySelector('.chart-header')?.innerText ?? '').includes('2024-06-03 → 2024-06-07')",
                timeout=90_000,
            )
            counts["1m"] = self.wait_bars()
            page.get_by_label("Start date").fill("2023-01-01")
            page.get_by_label("End date").fill("2024-12-31")
            for tf in ("15m", "30m", "1h", "1D"):
                self.select("Timeframe", tf)
                page.wait_for_function(
                    f"(document.querySelector('.chart-header')?.innerText ?? '').startsWith('QQQ · {tf}')"
                    " && (document.querySelector('.chart-header')?.innerText ?? '').includes('2023-01-01 → 2024-12-31')",
                    timeout=90_000,
                )
                counts[tf] = self.wait_bars()
            assert all(n > 0 for n in counts.values()), counts
            assert counts["15m"] > counts["30m"] > counts["1h"] > counts["1D"], counts
            self.timings["bars_per_timeframe"] = counts
            return f"bars per timeframe {counts}"

        self.item(2, item2)

        def item3():
            page.get_by_label("Start date").fill("2023-01-01")
            page.get_by_label("End date").fill("2024-12-31")
            started = time.perf_counter()
            with page.expect_response(
                lambda r: r.url.endswith("/aegis/api/indicators") and r.ok, timeout=90_000
            ) as caught:
                self.select(
                    "Timeframe", "1h"
                )  # the last change; its indicator response is the one timed
            self.timings["indicator_ms"] = int((time.perf_counter() - started) * 1000)
            self.indicators = caught.value.json()
            count = self.wait_bars()
            line = self.header_line()
            assert "2023-01-01 → 2024-12-31" in line, line
            assert line.startswith("QQQ · 1h"), line
            return f"QQQ 1h 2023-01-01→2024-12-31: {count} bars; indicators response in {self.timings['indicator_ms']} ms"

        self.item(3, item3)

        def item4():
            bars = self.api("data/bars?symbol=QQQ&timeframe=1h&start=2023-01-01&end=2024-12-31")
            data = bars["data"]
            assert data["source"] == "raw_archive" and data["research_eligible"] is False, data
            assert len(data["sha256"]) == 64 and bars["count"] == len(bars["bars"]) > 0
            canvases = self.js("document.querySelectorAll('#chart-mount canvas').length")
            assert canvases > 0, "no chart canvas mounted"
            assert "vintage " + data["vintage"] in self.header_line()
            return (
                f"{bars['count']} bars, vintage {data['vintage']}, file sha256 {data['sha256'][:12]}…, "
                f"{canvases} canvas layers"
            )

        self.item(4, item4)

        def item5():
            badge = page.locator(".chart-header .badge.raw").first
            assert badge.is_visible(), "RAW badge not visible"
            text = badge.inner_text()
            assert "RAW ARCHIVE" in text and "NOT RESEARCH-ELIGIBLE" in text, text
            return text

        self.item(5, item5)

        def item6():
            legend = self.js("document.querySelector('.chart-header .legend')?.innerText ?? ''")
            assert "EMA 9" in legend and "SMA 30" in legend, legend
            series = self.indicators["series"]
            assert set(series) == {"ema", "sma"}, list(series)
            ema_ready = sum(v is not None for v in series["ema"])
            sma_ready = sum(v is not None for v in series["sma"])
            assert ema_ready > 0 and sma_ready > 0
            assert series["ema"][:8] == [None] * 8 and series["sma"][28] is None
            return f"legend '{legend.replace(chr(10), ' / ')}'; ema {ema_ready} values, sma {sma_ready} values (warm-up gaps null)"

        self.item(6, item6)

        def item7():
            envelope = self.run_backtest()
            assert envelope["state"] == "ok" and envelope["data"]["research_eligible"] is False
            self.first_run = envelope
            return (
                f"run {envelope['run_id'][:8]} in {envelope['elapsed_ms']} ms server / "
                f"{self.timings['backtest_wall_ms'][-1]} ms wall, hash {envelope['result_hash'][:12]}"
            )

        self.item(7, item7)

        def item8():
            markers = self.first_run["markers"]
            legend = self.js("document.querySelector('.chart-header .legend')?.innerText ?? ''")
            assert f"{len(markers)} markers" in legend, legend
            trades = self.first_run["result"]["combined"]["trades"]
            assert len(markers) == 2 * len(trades) > 0, (len(markers), len(trades))
            first = trades[0]
            assert first["entry_time"] > first["signal_time"], first
            return (
                f"{len(markers)} markers for {len(trades)} trades; first entry {first['entry_time'][:16]} "
                f"after signal {first['signal_time'][:16]}"
            )

        self.item(8, item8)

        def side_item(side):
            self.tab("Backtest Summary")
            metrics = self.first_run["result"][side]["metrics"]
            shown = self.summary_cell("Trades", side)
            assert shown == f"{metrics['trade_count']:,}", (shown, metrics["trade_count"])
            pnl = self.summary_cell("Net P&L", side)
            assert pnl != DASH and pnl.strip("-$").replace(",", "").isdigit(), pnl
            return f"{side}: {metrics['trade_count']} trades, net P&L {pnl}, exposure {self.summary_cell('Exposure', side)}"

        self.item(9, lambda: side_item("long"))
        self.item(10, lambda: side_item("short"))
        self.item(11, lambda: side_item("combined"))

        def item12():
            rows = self.js(
                "[...document.querySelectorAll('#temporal-breakdown tbody tr')].map(r => r.cells[0].innerText)"
            )
            assert "ALL" in rows, rows
            assert any(t.startswith("CLOCK:") for t in rows) and any(
                t.startswith("CROSSOVER:") for t in rows
            ), rows
            breakdown = self.first_run["result"]["temporal"]["combined"]
            assert set(rows) >= set(breakdown), (rows, list(breakdown))
            return f"tags {rows}"

        self.item(12, item12)

        def item13():
            self.tab("Trades")
            page.wait_for_selector(".results table tbody tr")
            rows = self.js("document.querySelectorAll('.results table tbody tr').length")
            trades = self.first_run["result"]["combined"]["trades"]
            assert rows == len(trades), (rows, len(trades))
            tags = self.js(
                "document.querySelector('.results table tbody tr').lastElementChild.innerText"
            )
            page.locator(".results .chip", has_text="Long").click()
            long_rows = self.js("document.querySelectorAll('.results table tbody tr').length")
            assert long_rows == len(self.first_run["result"]["long"]["trades"]), long_rows
            return f"{rows} trades listed, {long_rows} long; first row tags '{tags}'"

        self.item(13, item13)

        def item14():
            self.tab("Equity Curve")
            page.wait_for_selector("svg[aria-label='equity curve']")
            paths = self.js(
                "document.querySelectorAll('svg[aria-label=\"equity curve\"] path').length"
            )
            assert paths == 3, paths
            legend = self.js("document.querySelector('.results .legend')?.innerText ?? ''")
            return f"3 curves; legend '{legend.replace(chr(10), ' / ')}'"

        self.item(14, item14)

        def item15():
            strip = self.js("document.querySelector('.status-strip')?.innerText ?? ''")
            metrics = self.first_run["result"]["combined"]["metrics"]
            for label in ("CAGR", "Net P&L", "Max DD", "MAR", "Expectancy", "Exposure"):
                assert re.search(re.escape(label) + r"\s+(?!" + DASH + ")", strip), (label, strip)
            shown_hash = self.js("document.getElementById('result-hash')?.textContent")
            assert shown_hash == self.first_run["result_hash"][:12], shown_hash
            net = re.search(r"Net P&L\s+(\S+)", strip).group(1)
            value = float(net.replace("$", "").replace(",", ""))
            assert abs(value - metrics["net_pnl"]) < 1, (net, metrics["net_pnl"])
            return f"strip shows net P&L {net} (API {metrics['net_pnl']:.2f}), hash {shown_hash}"

        self.item(15, item15)

        def item16():
            run_id = self.first_run["run_id"]
            page.get_by_title("Saved runs").click()
            page.wait_for_selector(".drawer .run-row")
            row = page.locator(
                ".drawer .run-row", has_text=self.first_run["result_hash"][:12]
            ).first
            row.get_by_role("button", name="Load").click()
            page.wait_for_function(
                f"(document.getElementById('run-state')?.innerText ?? '').includes('run {run_id[:8]}')",
                timeout=30_000,
            )
            reloaded = self.api(f"runs/{run_id}")
            assert (
                reloaded["state"] == "ok"
                and reloaded["result_hash"] == self.first_run["result_hash"]
            )
            page.get_by_label("Close saved runs").click()
            shown = self.js("document.getElementById('result-hash')?.textContent")
            assert shown == self.first_run["result_hash"][:12], shown
            return f"run {run_id[:8]} reloaded from the drawer, state {reloaded['state']}, hash unchanged"

        self.item(16, item16)

        def item17():
            self.select("Timeframe", "1D")
            page.wait_for_function(
                "(document.querySelector('.chart-header')?.innerText ?? '').startsWith('QQQ · 1D')"
            )
            self.wait_bars()
            page.locator("#optimize").click()
            page.wait_for_function(
                "/\\d+ valid cells/.test(document.getElementById('optimize-plan')?.innerText ?? '')",
                timeout=90_000,
            )
            plan = self.js("document.getElementById('optimize-plan').innerText")
            page.locator("#start-optimization").click()
            page.wait_for_selector(".job-head", timeout=30_000)
            self.timings["optimize_plan"] = plan
            return f"plan '{plan}'; LONG job started"

        self.item(17, item17)

        def item18():
            page.wait_for_function(
                "(document.querySelector('.job-head')?.innerText ?? '').startsWith('RUNNING')",
                timeout=30_000,
            )
            first, _ = self.progress()
            page.wait_for_function(f"+{PROGRESS}[1] > {first}", timeout=60_000)
            second, total = self.progress()
            assert second > first, (first, second)
            head = " | ".join(self.job_head().split("\n")[:3])
            return f"progress advanced {first} → {second} of {total}; '{head}'"

        self.item(18, item18)

        def item19():
            page.locator("#cancel-optimization").click()
            page.wait_for_function(
                "(document.querySelector('.job-head')?.innerText ?? '').startsWith('CANCELLED')",
                timeout=30_000,
            )
            done, total = self.progress()
            assert 0 < done < total, (done, total)
            elapsed = float(re.search(r"([\d.]+) s elapsed", self.job_head()).group(1))
            self.timings["optimizer_cell_ms_cancelled_job"] = round(1000 * elapsed / done, 1)
            return f"cancelled at {done}/{total} cells after {elapsed} s ({self.timings['optimizer_cell_ms_cancelled_job']} ms per cell)"

        self.item(19, item19)

        def item20():
            done, _ = self.progress()
            rows = self.js("document.querySelectorAll('#optimization-cells-long tbody tr').length")
            filled = self.js(
                f"[...document.querySelectorAll('.heat-grid .cell:not(.h)')].filter(c => c.innerText !== '{DASH}').length"
            )
            grid = self.js("document.querySelectorAll('.heat-grid .cell:not(.h)').length")
            assert rows == done == filled and filled < grid, (rows, done, filled, grid)
            best = self.js(
                "document.querySelector('#optimization-cells-long tbody tr').innerText.replace(/\\t/g, ' | ')"
            )
            return f"{done} completed cells visible in the table and heatmap ({grid} grid cells); best so far '{best}'"

        self.item(20, item20)

        def item21():
            # Shrink the LONG ranges (EMA 5..12 x SMA 20..40 step 5 = 40 cells) so the full run is bounded.
            page.get_by_label("long indicators.ema.length stop").fill("12")
            page.get_by_label("long indicators.sma.length stop").fill("40")
            page.locator("#optimize").click()
            page.wait_for_function(
                "/40 valid cells/.test(document.getElementById('optimize-plan')?.innerText ?? '')",
                timeout=90_000,
            )
            page.locator("#start-optimization").click()
            page.wait_for_function(
                "(document.querySelector('.job-head')?.innerText ?? '').startsWith('DONE')",
                timeout=600_000,
            )
            done, total = self.progress()
            filled = self.js(
                f"[...document.querySelectorAll('.heat-grid .cell:not(.h)')].filter(c => c.innerText !== '{DASH}').length"
            )
            rows = self.js("document.querySelectorAll('#optimization-cells-long tbody tr').length")
            assert done == total == filled == rows == 40, (done, total, filled, rows)
            elapsed = float(re.search(r"([\d.]+) s elapsed", self.job_head()).group(1))
            self.timings["optimizer_cell_ms_completed_job"] = round(1000 * elapsed / done, 1)
            page.screenshot(path=str(self.screenshot_path("optimization")), full_page=True)
            page.locator("#optimization-cells-long tbody tr").first.click()
            previous = self.run_state()
            page.locator("#apply-configs").click()
            page.wait_for_function(
                "document.querySelector('.result-tabs button.active')?.innerText === 'Backtest Summary'"
            )
            page.wait_for_function(
                "(s => s.startsWith('run ') && s !== "
                + json.dumps(previous)
                + ")(document.getElementById('run-state')?.innerText ?? '')",
                timeout=120_000,
            )
            applied = self.js(
                "document.querySelector('.side-card.long .logic').innerText.split('\\n')[0]"
            )
            return (
                f"40/40 cells in {elapsed} s ({self.timings['optimizer_cell_ms_completed_job']} ms per cell); "
                f"applied the best cell → long side now '{applied}'"
            )

        self.item(21, item21)

        def item22():
            self.select("Timeframe", "1h")
            page.wait_for_function(
                "(document.querySelector('.chart-header')?.innerText ?? '').startsWith('QQQ · 1h')"
            )
            self.wait_bars()
            first = self.run_backtest()
            second = self.run_backtest()
            assert first["result_hash"] == second["result_hash"], (
                first["result_hash"],
                second["result_hash"],
            )
            assert first["run_id"] != second["run_id"]
            self.timings["identical_request_hashes"] = [first["result_hash"], second["result_hash"]]
            return (
                f"two identical requests: runs {first['run_id'][:8]} and {second['run_id'][:8]} "
                f"both hash {first['result_hash']}"
            )

        self.item(22, item22)

        # -- Mission 4: walk-forward -------------------------------------------------------------
        def item23():
            import statistics

            def sample(url, n=10):
                ms = []
                for _ in range(n):
                    started = time.perf_counter()
                    assert page.request.get(url).ok, url
                    ms.append((time.perf_counter() - started) * 1000)
                return round(statistics.median(ms)), round(max(ms))

            gateway = sample("http://127.0.0.1:8000/aegis/api/status")
            core = sample("http://127.0.0.1:8000/health/live")
            worker = sample(self.base + "api/status")
            self.timings["latency_ms_median_max"] = {
                "gateway_aegis_status": gateway,
                "core_health": core,
                "aegis_worker_status": worker,
            }
            return f"gateway /aegis/api/status {gateway[0]} ms median ({gateway[1]} max); Core /health/live {core[0]} ms; worker direct {worker[0]} ms"

        self.item(23, item23)

        def item24():
            self.select("Timeframe", "1D")
            page.wait_for_function(
                "(document.querySelector('.chart-header')?.innerText ?? '').startsWith('QQQ \u00b7 1D')"
            )
            self.wait_bars()
            plan = self.open_walkforward(200, 50)
            # The grid size depends on the ranges item 21 left behind; the window layout does not.
            match = re.match(
                r"(\d+) windows · (\d+) cells each · (\d+) units · (\d+) unused tail bars · (\S+) bars",
                plan,
            )
            assert match, plan
            windows, cells, units, tail, bars = match.groups()
            assert (windows, tail, bars) == ("6", "2", "502"), plan
            assert int(units) == 6 * (int(cells) + 1), plan
            self.timings["walkforward_plan"] = plan
            page.locator(".popover .btn", has_text="Close").click()
            return f"plan '{plan}'"

        self.item(24, item24)

        def item25():
            self.open_walkforward(200, 50)
            self.start_walkforward()
            head = self.job_head().split("\n")[0:2]
            assert re.search(r"window 1 of 6 · cell \d+ of \d+ · unit \d+ of \d+", head[1]), head
            return f"started: '{' | '.join(head)}'"

        self.item(25, item25)

        def item26():
            first, total = self.wf_cells()
            page.wait_for_function(
                f"+({WF_HEAD}).match(/unit (\\d+) of/)[1] > {first}", timeout=60_000
            )
            second, _ = self.wf_cells()
            job = self.latest_walkforward()
            started = time.perf_counter()
            assert page.request.get(self.base + f"api/walkforward/{job['job_id']}").ok
            latency = int((time.perf_counter() - started) * 1000)
            assert latency < 500, latency
            assert second > first, (first, second)
            assert total == 6 * (self.wf_cells_per_window() + 1), total
            return (
                f"cells {first} \u2192 {second} of {total}; status route {latency} ms while running"
            )

        self.item(26, item26)

        def item27():
            page.wait_for_function(
                f"[...{WF_ROWS}].some(r => r.lastElementChild.innerText === 'done')",
                timeout=300_000,
            )
            done_before = self.wf_done_rows()
            page.locator("#cancel-walkforward").click()
            page.wait_for_function(f"({WF_HEAD}).startsWith('CANCELLED')", timeout=60_000)
            status = self.latest_walkforward()
            assert (
                status["status"] == "cancelled"
                and 0 < status["windows"]["done"] < status["windows"]["total"]
            )
            assert self.wf_done_rows() == status["windows"]["done"] >= done_before
            assert status["result_hash"] is None
            self.timings["walkforward_cancelled_at"] = status["progress"]
            return f"cancelled at window {status['windows']['done']} of {status['windows']['total']} (cell {status['progress']['done']} of {status['progress']['total']}); {self.wf_done_rows()} done window(s) still shown"

        self.item(27, item27)

        def item28():
            self.open_walkforward(200, 50)
            started = time.perf_counter()
            self.start_walkforward()
            page.wait_for_function(f"({WF_HEAD}).startsWith('DONE')", timeout=900_000)
            seconds = round(time.perf_counter() - started, 1)
            status = self.latest_walkforward()
            assert status["status"] == "done" and status["windows"] == {"done": 6, "total": 6}
            self.wf_status = status
            self.timings["walkforward_seconds"] = seconds
            self.timings["walkforward_cell_ms"] = round(
                1000 * seconds / status["progress"]["total"], 1
            )
            return f"6/6 windows, {status['progress']['total']} units in {seconds} s ({self.timings['walkforward_cell_ms']} ms per unit); hash {status['result_hash'][:12]}"

        self.item(28, item28)

        def item29():
            rows = self.js(f"[...{WF_ROWS}].map(r => [...r.cells].map(c => c.innerText))")
            assert len(rows) == 6, len(rows)
            for i, row in enumerate(rows):
                assert row[0] == str(i + 1) and row[-1] == "done", row
                assert "\u2192" in row[1] and "\u2192" in row[2], row
                assert row[3].startswith("EMA ") and "SMA" in row[3], row
                assert row[4] != DASH and row[5] != DASH and row[7] != DASH, row
            api_rows = self.wf_status["window_records"]
            assert all(r["status"] == "done" for r in api_rows)
            chosen = [r["best"]["params"] for r in api_rows]
            return f"6 windows; chosen {[f'{int(c["indicators.ema.length"])}/{int(c["indicators.sma.length"])}' for c in chosen]}; efficiencies {[None if r['efficiency'] is None else round(r['efficiency'], 2) for r in api_rows]}"

        self.item(29, item29)

        def item30():
            paths = self.js(
                "document.querySelectorAll('svg[aria-label=\"stitched out-of-sample equity\"] path').length"
            )
            lines = self.js(
                "document.querySelectorAll('svg[aria-label=\"stitched out-of-sample equity\"] line').length"
            )
            assert paths == 1 and lines == 5, (paths, lines)
            stitched = self.wf_status["stitched"]
            assert len(stitched["equity"]) == 6 * 50 and stitched["metrics"]["trade_count"] == len(
                stitched["trades"]
            )
            shown = self.js("document.getElementById('walkforward-stitched-long').innerText")
            return f"one curve, 5 window boundaries, {len(stitched['equity'])} points; '{shown.replace(chr(10), ' ')}'"

        self.item(30, item30)

        def item31():
            text = self.js("document.getElementById('walkforward-stability-long').innerText")
            assert (
                "EMA" in text
                and "SMA" in text
                and "Positive OOS windows" in text
                and "Mean efficiency" in text
            ), text
            stability = self.wf_status["stability"]
            assert (
                stability["windows_evaluated"] == 6 and 0 <= stability["positive_oos_windows"] <= 6
            )
            spread = stability["parameters"]["indicators.ema.length"]
            assert spread["min"] <= spread["mean"] <= spread["max"]
            return f"EMA {spread['min']:.0f}–{spread['max']:.0f} (mean {spread['mean']:.1f}, std {spread['std']:.2f}); positive OOS windows {stability['positive_oos_windows']} of 6; mean efficiency {stability['mean_efficiency']}"

        self.item(31, item31)

        def item32():
            choice = self.wf_status["window_records"][-1]["best"]["params"]
            previous = self.run_state()
            page.locator("#apply-walkforward").click()
            page.wait_for_function(
                "document.querySelector('.result-tabs button.active')?.innerText === 'Backtest Summary'"
            )
            page.wait_for_function(
                "(s => s.startsWith('run ') && s !== "
                + json.dumps(previous)
                + ")(document.getElementById('run-state')?.innerText ?? '')",
                timeout=120_000,
            )
            card = self.js(
                "document.querySelector('.side-card.long .logic').innerText.split('\\n')[0]"
            )
            ema, sma = int(choice["indicators.ema.length"]), int(choice["indicators.sma.length"])
            assert f"EMA({ema})" in card and f"SMA({sma})" in card, (card, choice)
            trades = self.summary_cell("Trades", "combined")
            return f"applied EMA {ema} / SMA {sma} \u2192 '{card}'; combined rerun with {trades} trades"

        self.item(32, item32)

        def item33():
            listed = self.api("walkforward")
            summary = next(j for j in listed if j["job_id"] == self.wf_status["job_id"])
            assert summary["status"] == "done" and summary["windows"] == {"done": 6, "total": 6}
            again = self.api(f"walkforward/{summary['job_id']}")
            assert again["result_hash"] == self.wf_status["result_hash"]
            assert again["stitched"]["metrics"] == self.wf_status["stitched"]["metrics"]
            return f"persisted job {summary['job_id'][:8]} reloaded: hash {again['result_hash'][:12]}, stitched net P&L {again['stitched']['metrics']['net_pnl']:.2f}"

        self.item(33, item33)

        def item34():
            body = self.walkforward_body(200, 50)
            hashes = []
            for _ in range(2):
                started = self.post("walkforward", body)
                assert started.status == 202, started.text()
                job_id = started.json()["job_id"]
                deadline = time.monotonic() + 900
                while time.monotonic() < deadline:
                    status = self.api(f"walkforward/{job_id}")
                    if status["status"] in ("done", "failed", "cancelled"):
                        break
                    time.sleep(1)
                assert status["status"] == "done", status.get("error")
                hashes.append(status["result_hash"])
            assert hashes[0] == hashes[1], hashes
            self.timings["identical_walkforward_hashes"] = hashes
            return f"two identical requests \u2192 the same hash {hashes[0]}"

        self.item(34, item34)

        def item35():
            response = self.post("walkforward/plan", self.walkforward_body(500, 100))
            assert response.status == 422, response.text()
            detail = response.json()["detail"]
            assert "range too short: 502 bars" in detail, detail
            return f"422: {detail}"

        self.item(35, item35)

        def item36():
            status = page.request.get("http://127.0.0.1:8000/aegis/api/status").json()
            schedule = page.request.get("http://127.0.0.1:8000/triad/api/daily-schedule").json()
            assert status["mode"] == "human_directed" and status["exchange"] == "CLOSED", status
            assert schedule["enabled"] is False and schedule["id"].startswith("c99fa831"), schedule
            return f"aegis {status['mode']} / {status['exchange']}; DailySchedule {schedule['id'][:8]} enabled={schedule['enabled']}"

        self.item(36, item36)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8102/aegis/")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the report uses arrows and dashes
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (ROOT / "logs").mkdir(exist_ok=True)
    started = time.perf_counter()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=not args.headed, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        # bypass_csp lets Playwright evaluate its probes; the worker's own CSP (no unsafe-eval)
        # is what the product ships with and the chart spike verified against it.
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, bypass_csp=True)
        acceptance = Acceptance(page, args.base, stamp)
        acceptance.run()
        page.screenshot(path=str(acceptance.screenshot_path("final")), full_page=True)
        browser.close()
    report = {
        "stamp": stamp,
        "base": args.base,
        "total_ms": int((time.perf_counter() - started) * 1000),
        "passed": sum(r["status"] == "PASS" for r in acceptance.results),
        "failed": sum(r["status"] == "FAIL" for r in acceptance.results),
        "items": acceptance.results,
        "timings": acceptance.timings,
        "result_hashes": acceptance.hashes,
        "page_errors": acceptance.errors,
    }
    out = ROOT / "logs" / f"aegis-acceptance-{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"\n{report['passed']}/{len(ITEMS)} PASS, {report['failed']} FAIL, page errors {len(acceptance.errors)} -> {out}"
    )
    ok = report["failed"] == 0 and len(acceptance.results) == len(ITEMS) and not acceptance.errors
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
