"""Aegis workstation acceptance: walks the 22 Mission 3 definition-of-done items, the 14 Mission 4
items, the 11 Mission 5 items, the 13 Mission 6 items, the 9 Mission 8 items, the 7 Mission 9
items, the 5 limits items and the 5 Mission 10 items in Chromium against the running worker and writes logs/aegis-acceptance-<stamp>.json with PASS/FAIL per item, timings
(indicator ms, backtest ms, optimizer cell ms, experiment cell ms) and the result_hash values.
Items 51 and 63 restart the worker detached through WMI (tools/start_product.ps1), as the DoD asks.

Run:  .venv/Scripts/python.exe tests/products/aegis/browser_workstation.py [--base URL] [--headed]
Exit code 0 only when all 86 items PASS with no page errors.
Needs `pip install playwright` and `python -m playwright install chromium`.
"""

from __future__ import annotations

import argparse
import itertools
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
    # Mission 5 (spec §1 items 1–11)
    "build a Donchian / RSI breakout in the Strategy Lab from a new document and save it",
    "use it on QQQ 1h 2023–2024: Donchian on the price pane, RSI in its own pane, the crosshair reads the study",
    "run its backtest: trades, markers, long/short/combined metrics and a result_hash",
    "optimize Donchian 10–40 step 10 x RSI 7–21 step 7 (12 cells) and apply the best cell",
    "walk the long side forward 1000/250: positions carry across joins, only the final window may close at its edge",
    "duplicate, rename and delete a copy; deleting the referenced original is refused",
    "the default strategy still produces the recorded Mission 3 identical-request hash",
    "rerun the new strategy's backtest unchanged and obtain the same result_hash",
    "the Indicators tab lists kind, parameters, source, pane and latest values; removing a read indicator is refused",
    "invalid rules and parameters are refused with 422 naming the problem",
    "governance unchanged and no file under Core, the platform host or Triad changed",
    # Mission 6 (spec §2 items 1–13)
    "every earlier item ran on the kernel engine: the status reports it available and the recorded Mission 3 and 5 hashes are reproduced",
    "define the 252-cell experiment on the breakout document (four parameters across both sides, MAR): the plan says exhaustive, 252 runs, priced",
    "start it: progress advances by chunk while the status route stays responsive (the pause is requested during the first chunk)",
    "pause, restart the worker: the experiment is paused, not lost; resume it; it finishes with every cell present exactly once",
    "the report: the recommended plateau with its centre and supported peak, every peak's standing, main effects, interaction heatmaps, sensitivity, clusters or their refusal",
    "materialize the centre twice: the same result_hash, equal to a direct backtest of the pinned spec with those parameters",
    "use the centre in the workspace: the Charts page with unsaved edits, the side cards show its parameters, a backtest runs on them",
    "record the decision accepted with a note: shown on the experiment and in the list",
    "refine: a queued child with the parent linked and ranges narrowed around the plateau, not started",
    "plan the over-budget experiment (step 1, budget 2,000): sampled with its fraction and the levers; freezing the two short-side parameters gives 682 cells, exhaustive",
    "recompute the finished experiment's report with net P&L and tolerance 0.10 without rerunning: both reports kept",
    "every refusal is honest over HTTP: no parameters, eleven, a path on the wrong side, a fractional step, a budget of zero, a pause on a finished experiment, a delete of a running one",
    "governance unchanged, no file under Core, the platform host or Triad changed, and pyproject.toml changed by the one optional-extra line only",
    # Mission 8 (spec §3 items 1–9)
    "plan a study from the finished breakout experiment: per symbol the windows, 252 cells per window exhaustive, the runs and an estimate priced from the measured cost",
    "start it on QQQ, SPY and ITOT 1h 2016-09-19 → 2026-09-18 with 3,493 + 873 bars: progress advances by window while the status route answers under 500 ms",
    "pause, restart the worker: the study is paused, not lost; resume; it finishes with every window of every symbol present exactly once",
    "the report: per symbol the three rules side by side, the flat windows, stability, the equity chart and the window table; the cross-symbol line; the raw-archive label",
    "recompute one window independently: its cells re-analysed give the same plateau centre, and the plateau rule's out-of-sample run equals a direct backtest by hash",
    "an identical study reproduces every per-rule result hash",
    "every refusal answers 422 or 409 naming the problem",
    "record the decision accepted with a note: shown on the study and in the list under its experiment",
    "governance unchanged and no file under Core, the platform host or Triad changed since the Mission 8 plan",
    # Mission 9 (spec §3 items 1–7)
    "the Library lists saved results of all five kinds with each kind's headline numbers, 50 rows per page",
    "filters, search and sort narrow and order the list; a label and star set on item 22's run are found by search and by Starred",
    "item 22's run opens read-only with its chart, markers and results; the workspace is unchanged; Load then loads it, asking first over unsaved edits",
    "item 21's optimization opens with its matrix and table, item 28's walk-forward with its windows, stitched equity and stability; the experiment and study open on the Experiments page selected",
    "item 22's pair compares as identical; item 39's run against item 54's lists exactly the differing parameters, carries ▲/▼ marks and draws both curves on one calendar axis",
    "delete → Recently deleted → restore keeps the result hash; the refusals answer 409 naming a parent with studies, a running study and a study whose parent is trashed",
    "governance unchanged, no file under Core, the platform host or Triad changed since the Mission 9 plan, items 1–69 still pass and Recently deleted was never emptied",
    # the limits change (2026-10-20)
    "a ten-year 15m backtest (65,107 bars) runs and its chart loads under the 2,000,000-bar guard",
    "a three-parameter grid of more than 400 cells runs on the pool; its matrix switches axes, a square's best cell loads and its backtest equals the cell",
    "a grid of more than 1,000 cells sends its best 1,000 and pages the rest; the saved job keeps every cell",
    "ten years of 1m now select; the grid refusal is honest, and a run estimated over ten minutes asks before it starts",
    "governance unchanged since the limits plan and items 1–76 still pass",
    # Mission 10: no limit (spec §10)
    "a saved run is slim: no per-bar series, side equity at most 2,000 points, format 2, under 1 MB, its hash unchanged; a run saved before the mission opens with its equity",
    "ten years of 1m in the page: 947,519 bars shown as aggregated candles; a wheel zoom swaps to native candles and back out to aggregated ones; indicators and markers follow; Run Backtest completes",
    "the ten-year run opens in the Library and compares with item 22's run",
    "Save only what I keep: a backtest is not in the Library until Keep; the mode switches back to every",
    "governance unchanged since the Mission 10 plan and items 1–81 still pass",
]
RECORDED_IDENTICAL_HASH = "cdbc9abd2238542ee299e694209241b40561f39bfdd3632f58c93350b237e360"
MISSION5_BASE = (
    "a73f70e"  # the Mission 5 spec commit; Core, platform host and Triad are frozen since
)

RECORDED_WALKFORWARD_HASH = (  # item 34 as the Mission 5 record kept it (run 20261011T184458Z)
    "5d9371614fc09596e6fb2c8b4a36a7182adc0c427d7d333dab88cf337763230a"
)
RECORDED_LAB_WALKFORWARD_PREFIX = "783f07c3146b"  # item 28's hash as the Mission 5 record kept it
MISSION6_BASE = (
    "5189e12"  # the Mission 6 plan commit; Core, platform host and Triad are frozen since
)
# Mission 6's merged head. Item 60 checks Mission 6's own pyproject.toml change over its own range;
# later missions may change pyproject.toml (Mission 7 added the triad extra and owner markers).
MISSION6_END = "90e94d0"
MISSION8_BASE = (
    "31bddc8"  # the Mission 8 plan commit; Core, platform host and Triad are frozen since
)
MISSION9_BASE = (
    "d56485a"  # the Mission 9 plan commit; Core, platform host and Triad are frozen since
)
LIBRARY_KINDS = ["backtest", "optimization", "walkforward", "experiment", "study"]
LIMITS_BASE = "9d13297"  # the limits design and plan commit; Core, platform host and Triad frozen
NO_LIMIT_BASE = "b6960b8"  # the Mission 10 plan commit; Core, platform host and Triad frozen since
TEN_YEARS_1M = 947_519  # QQQ 1m bars over STUDY_RANGE in the 20260919 vintage
MISSION10_STARTED = "2026-10-20T20:00:00"  # runs saved before this are format 1 (per-bar series)
THREE_PARAMETERS = [  # 7 x 4 x 20 = 560 cells: more than 400, so the pool runs it
    ("indicators.donchian.length", 10, 40, 5),
    ("indicators.rsi.length", 7, 28, 7),
    ("indicators.ema.length", 10, 200, 10),
]
PAGED_PARAMETERS = [  # 16 x 8 x 20 = 2,560 cells: more than the 1,000 a status sends
    ("indicators.donchian.length", 10, 40, 2),
    ("indicators.rsi.length", 7, 28, 3),
    ("indicators.ema.length", 10, 200, 10),
]
QUESTION_PARAMETERS = [  # 31 x 4 x 191 = 23,684 cells on ten years of 15m: well over ten minutes
    ("indicators.donchian.length", 10, 40, 1),
    ("indicators.rsi.length", 7, 28, 7),
    ("indicators.ema.length", 10, 200, 1),
]
THROWAWAY_SURFACE = [  # item 75: 3 × 3 = 9 cells, a finished experiment in seconds
    ("long_side.indicators.donchian.length", 10, 30, 10),
    ("long_side.indicators.rsi.length", 7, 21, 7),
]
STUDY_SYMBOLS = ["QQQ", "SPY", "ITOT"]
STUDY_RANGE = ("2016-09-19", "2026-09-18")  # spec §3 item 2: the archive's whole span today
EXPERIMENT_SURFACE = [  # spec §2 item 2: 7 × 4 × 3 × 3 = 252 cells across both sides
    ("long_side.indicators.donchian.length", 10, 40, 5),
    ("long_side.indicators.rsi.length", 7, 28, 7),
    ("short_side.indicators.ema.length", 5, 15, 5),
    ("short_side.indicators.sma.length", 20, 40, 10),
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

    # -- experiment plumbing (Mission 6) ------------------------------------------------------
    def wait_until(self, predicate, timeout: float, interval: float = 0.2) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(interval)
        return False

    def experiment(self, experiment_id: str) -> dict:
        return self.api(f"experiments/{experiment_id}")

    def experiment_body(self, surface, budget_runs=2000, objective="mar", name=None) -> dict:
        return {
            "name": name or f"Breakout surface {self.stamp}",
            "strategy_id": self.lab["id"],
            "data": {
                "symbol": "QQQ",
                "timeframe": "1h",
                "start": "2023-01-01",
                "end": "2024-12-31",
            },
            "settings": {"initial_capital": 100000, "allocation_fraction": 1},
            "objective": objective,
            "surface": {
                "parameters": [
                    {"path": p, "start": a, "stop": b, "step": s} for p, a, b, s in surface
                ]
            },
            "budget": {"runs": budget_runs, "seconds": None},
            "tolerance": 0.15,
            "seed": 1,
        }

    # -- study plumbing (Mission 8) -------------------------------------------------------------
    def study(self, study_id: str) -> dict:
        return self.api(f"studies/{study_id}")

    def study_body(self) -> dict:
        return {
            "experiment_id": self.exp_id,
            "symbols": list(STUDY_SYMBOLS),
            "start": STUDY_RANGE[0],
            "end": STUDY_RANGE[1],
            "in_sample_bars": 3493,
            "out_of_sample_bars": 873,
        }

    def study_hashes(self, document: dict) -> dict:
        return {
            symbol: {rule: entry["rules"][rule].get("result_hash") for rule in entry["rules"]}
            for symbol, entry in document["report"]["symbols"].items()
        }

    def wait_study(self, study_id: str, statuses, timeout: float) -> dict:
        assert self.wait_until(lambda: self.study(study_id)["status"] in statuses, timeout, 2), (
            self.study(study_id)["status"]
        )
        return self.study(study_id)

    def open_planner(self) -> None:
        """New experiment; when the gate asks, revert the workspace's unsaved edits (an
        experiment pins the saved spec)."""
        page = self.page
        page.locator("#experiment-new").click()
        page.wait_for_selector("#experiment-planner, #experiment-gate", timeout=30_000)
        if self.js("!!document.getElementById('experiment-gate')"):
            page.locator("#experiment-gate-revert").click()
            page.wait_for_selector("#experiment-planner", timeout=30_000)

    def add_surface(self, surface) -> None:
        """Fill the planner with these parameters in order; rows surface-0.. follow it."""
        page = self.page
        for i, (path, start, stop, step) in enumerate(surface):
            page.locator("#surface-add").select_option(path)
            page.wait_for_selector(f"#surface-path-{i}")
            for field, value in (("start", start), ("stop", stop), ("step", step)):
                page.locator(f"#surface-{field}-{i}").fill(str(value))

    def plan_text(self) -> str:
        return self.js("document.getElementById('experiment-plan')?.innerText ?? ''")

    def wait_plan(self, needle: str, timeout=90_000) -> str:
        self.page.wait_for_function(
            f"(document.getElementById('experiment-plan')?.innerText ?? '').includes({json.dumps(needle)})",
            timeout=timeout,
        )
        return self.plan_text()

    def progress_text(self) -> str:
        return self.js("document.getElementById('experiment-progress')?.innerText ?? ''")

    def worker_pid(self) -> int | None:
        import subprocess

        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "(Get-NetTCPConnection -LocalPort 8102 -State Listen -ErrorAction SilentlyContinue"
                    " | Select-Object -First 1).OwningProcess"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        return int(out) if out.isdigit() else None

    def restart_worker(self) -> tuple[int | None, int]:
        """Relaunch the worker detached through WMI (as Missions 3–5 did by hand) and wait for
        the new listener to answer the status route; returns (old, new) listener PIDs."""
        import subprocess

        old = self.worker_pid()
        script = str(ROOT / "tools" / "start_product.ps1")
        command = (
            "Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine="
            f"'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass"
            f" -File {script} -Product aegis'; CurrentDirectory='{ROOT}'}} | Out-Null"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            check=True,
            capture_output=True,
            text=True,
        )
        deadline = time.monotonic() + 120
        new, last_error = None, "no new listener yet"
        while time.monotonic() < deadline:
            pid = self.worker_pid()
            if pid is not None and pid != old:
                try:
                    status = self.page.request.get(self.base + "api/status", timeout=3_000)
                    if status.ok and status.json().get("kernel_available"):
                        new = pid
                        break
                    last_error = f"HTTP {status.status}"
                except Exception as exc:  # noqa: BLE001 - the worker is still coming up
                    last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(1)
        assert new is not None, (
            f"the worker did not come back within 120 s (old pid {old}): {last_error}"
        )
        return old, new

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
            self.opt_job_id = self.api("optimize")[0]["job_id"]  # newest first
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
            assert first["result_hash"] == RECORDED_IDENTICAL_HASH, first["result_hash"]
            assert first["run_id"] != second["run_id"]
            self.timings["identical_request_hashes"] = [first["result_hash"], second["result_hash"]]
            self.identical_runs = (first, second)
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

        # -- Mission 5 (spec §1 items 1–11) ----------------------------------------------------

        def set_number(selector: str, value) -> None:
            page.locator(selector).fill(str(value))

        def wait_text(selector: str, needle: str, timeout=30_000) -> None:
            page.wait_for_function(
                f"(document.querySelector({json.dumps(selector)})?.innerText ?? '').includes({json.dumps(needle)})",
                timeout=timeout,
            )

        def doc_rows() -> list[str]:
            return self.js("[...document.querySelectorAll('.lab-table tbody tr')].map(r => r.id)")

        def item37():
            page.locator("#nav-lab").click()
            page.wait_for_selector("#doc-ema9-sma30-cross-v1")  # the list has loaded
            before = set(doc_rows())
            page.locator("#lab-new").click()
            page.wait_for_function(
                f"[...document.querySelectorAll('.lab-table tbody tr')].length > {len(before)}",
                timeout=30_000,
            )
            new_row = next(r for r in doc_rows() if r not in before)
            doc_id = new_row[len("doc-") :]
            name = f"Donchian RSI breakout {self.stamp}"
            page.locator(f"#rename-{doc_id}").click()
            page.locator("#rename-input").fill(name)
            page.locator("#rename-confirm").click()
            wait_text(f"#doc-{doc_id}", name)
            page.locator(f"#use-{doc_id}").click()
            page.wait_for_selector("#chart-mount")
            wait_text("#document-name", name)
            # Indicators on the long side only (plan ruling P11).
            page.locator("#right-tab-indicators").click()
            page.locator("#focus-long").click()
            for kind in ("DONCHIAN", "RSI"):
                page.locator("#add-indicator-kind").select_option(kind)
                page.locator("#add-indicator").click()
            page.wait_for_selector("#indicator-donchian")
            page.wait_for_selector("#indicator-rsi")
            # Rules: entry = close crosses above donchian.upper AND rsi < 70; exit on the middle.
            page.locator("#right-tab-strategy").click()
            page.locator("#long-entry-left-0").select_option("price.close")
            page.locator("#long-entry-operator-0").select_option("crosses_above")
            page.locator("#long-entry-right-0").select_option("donchian.upper")
            page.locator("#long-entry-add-condition").click()
            page.locator("#long-entry-join").select_option("all")
            page.locator("#long-entry-left-1").select_option("rsi")
            page.locator("#long-entry-operator-1").select_option("less_than")
            page.locator("#long-entry-right-1").select_option("__constant__")
            set_number("#long-entry-constant-1", 70)
            page.locator("#long-exit-left-0").select_option("price.close")
            page.locator("#long-exit-operator-0").select_option("crosses_below")
            page.locator("#long-exit-right-0").select_option("donchian.middle")
            # The crossover indicators are no longer read on the long side: remove them.
            page.locator("#right-tab-indicators").click()
            for gone in ("ema", "sma"):
                page.locator(f"#remove-{gone}").click()
                page.wait_for_selector(f"#indicator-{gone}", state="detached")
            page.wait_for_selector("#unsaved-edits")  # its label is uppercased by CSS
            page.locator("#save-document").click()
            page.wait_for_selector("#unsaved-edits", state="detached", timeout=30_000)
            saved = self.api(f"strategies/{doc_id}")
            side = saved["spec"]["long_side"]
            assert [i["id"] for i in side["indicators"]] == ["donchian", "rsi"], side["indicators"]
            assert side["entry"] == {
                "all_of": [
                    {
                        "left": "price.close",
                        "operator": "crosses_above",
                        "right": "donchian.upper",
                        "timing": "bar_close",
                    },
                    {"left": "rsi", "operator": "less_than", "right": "70", "timing": "bar_close"},
                ]
            }, side["entry"]
            assert side["exit"]["right"] == "donchian.middle", side["exit"]
            self.lab = {"id": doc_id, "name": name, "hash": saved["strategy_hash"]}
            card = self.js("document.querySelector('.side-card.long .logic')?.innerText ?? ''")
            return f"document {doc_id} '{name}' saved, hash {saved['strategy_hash'][:12]}; card '{card.splitlines()[0] if card else ''}'"

        self.item(37, item37)

        def item38():
            page.locator("#right-tab-strategy").click()
            self.select("Timeframe", "1h")
            page.get_by_label("Start date").fill("2023-01-01")
            page.get_by_label("End date").fill("2024-12-31")
            page.wait_for_function(
                "(document.querySelector('.chart-header')?.innerText ?? '').startsWith('QQQ · 1h')"
            )
            count = self.wait_bars()
            page.wait_for_function(
                "(document.querySelector('.chart-header .legend')?.innerText ?? '').includes('RSI 14')",
                timeout=60_000,
            )
            legend = self.js(
                "[...document.querySelectorAll('.chart-header .legend b')].map(b => [b.innerText, b.title])"
            )
            panes = dict(legend)
            for title in ("DONCHIAN 20 upper", "DONCHIAN 20 lower", "DONCHIAN 20 middle"):
                assert panes.get(title) == "drawn on the price pane", (title, legend)
            assert panes.get("RSI 14") == "drawn in its own pane", legend
            box = page.locator("#chart-mount").bounding_box()
            readout = ""
            for offset in range(12, int(box["height"] * 0.5), 12):
                page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] - offset)
                page.wait_for_timeout(60)
                readout = self.js("document.getElementById('study-readout')?.innerText ?? ''")
                if "RSI 14" in readout:
                    break
            assert "RSI 14" in readout, readout
            page.mouse.move(box["x"] + 5, box["y"] + 5)
            page.screenshot(path=str(self.screenshot_path("lab-panes")), full_page=True)
            return (
                f"{count} bars; legend {[t for t, _ in legend]}; study readout '{readout.strip()}'"
            )

        self.item(38, item38)

        def item39():
            envelope = self.run_backtest()
            long_metrics = envelope["result"]["long"]["metrics"]
            assert long_metrics["trade_count"] >= 1, long_metrics
            assert envelope["markers"], "no markers"
            assert envelope["strategy_id"] == self.lab["id"], envelope["strategy_id"]
            assert len(envelope["result_hash"]) == 64
            for side in ("long", "short", "combined"):
                assert self.summary_cell("Trades", side) not in ("", DASH), side
            self.lab_run = envelope
            return (
                f"run {envelope['run_id'][:8]}: long {long_metrics['trade_count']} trades, net "
                f"{long_metrics['net_pnl']:.2f}; {len(envelope['markers'])} markers; hash {envelope['result_hash']}"
            )

        self.item(39, item39)

        def item40():
            for path, start, stop, step in (
                ("indicators.donchian.length", 10, 40, 10),
                ("indicators.rsi.length", 7, 21, 7),
            ):
                page.get_by_label(f"long {path} start").fill(str(start))
                page.get_by_label(f"long {path} stop").fill(str(stop))
                page.get_by_label(f"long {path} step").fill(str(step))
                box = page.get_by_label(f"long {path} enabled")
                if not box.is_checked():
                    box.check()
            page.locator("#optimize").click()
            page.wait_for_function(
                "/12 valid cells/.test(document.getElementById('optimize-plan')?.innerText ?? '')",
                timeout=90_000,
            )
            plan = self.js("document.getElementById('optimize-plan').innerText")
            page.locator("#start-optimization").click()
            page.wait_for_function(
                "(document.querySelector('.job-head')?.innerText ?? '').startsWith('DONE')",
                timeout=600_000,
            )
            done, total = self.progress()
            assert done == total == 12, (done, total)
            page.locator("#optimization-cells-long tbody tr").first.click()
            best = self.js(
                "document.querySelector('#optimization-cells-long tbody tr').innerText.replace(/\\t/g, ' | ')"
            )
            previous = self.run_state()
            page.locator("#apply-configs").click()
            page.wait_for_function(
                "(s => s.startsWith('run ') && s !== "
                + json.dumps(previous)
                + ")(document.getElementById('run-state')?.innerText ?? '')",
                timeout=120_000,
            )
            card = self.js(
                "document.querySelector('.side-card.long .logic').innerText.split('\\n')[0]"
            )
            return f"plan '{plan}'; 12/12 cells; best '{best}' applied → '{card}'"

        self.item(40, item40)

        def item41():
            plan = self.open_walkforward(1000, 250)
            assert "9 windows" in plan and "12 cells each" in plan, plan
            with page.expect_response(
                lambda r: r.url.endswith("/aegis/api/walkforward") and r.request.method == "POST"
            ) as caught:
                self.start_walkforward()
            job_id = caught.value.json()["job_id"]
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                status = self.api(f"walkforward/{job_id}")
                if status["status"] in ("done", "failed", "cancelled"):
                    break
                time.sleep(1)
            assert status["status"] == "done", status.get("error")
            records = status["window_records"]
            for record in records[:-1]:
                assert not any(t["window_edge_exit"] for t in record["oos"]["trades"]), record[
                    "index"
                ]
            for before, after in itertools.pairwise(records):
                assert before["open_at_end"] == after["carried_in"], before["index"]
            baseline = status["settings"]["initial_capital"]
            for record in records:
                net = record["oos"]["metrics"]["net_pnl"]
                assert abs(net - (record["ending_equity"] - baseline)) < 1e-6, record["index"]
                baseline = record["ending_equity"]
            carried = [t for r in records for t in r["oos"]["trades"] if "carried_from_window" in t]
            joins = sum(1 for r in records if r["open_at_end"])
            assert status["strategy_id"] == self.lab["id"], status["strategy_id"]
            self.lab_walkforward = status
            wait_text("#walkforward-stitched-long", "Net P&L")
            return (
                f"9/9 windows; {joins} joins crossed holding a position, {len(carried)} carried trades; "
                f"no interior edge close; stitched net {status['stitched']['metrics']['net_pnl']:.2f}; "
                f"hash {status['result_hash']}"
            )

        self.item(41, item41)

        def item42():
            original = self.lab["id"]
            page.locator("#nav-lab").click()
            page.wait_for_selector(f"#doc-{original}")
            before = set(doc_rows())
            page.locator(f"#duplicate-{original}").click()
            page.locator("#duplicate-input").fill(f"Breakout copy {self.stamp}")
            page.locator("#duplicate-confirm").click()
            page.wait_for_function(
                f"[...document.querySelectorAll('.lab-table tbody tr')].length > {len(before)}"
            )
            copy = next(r for r in doc_rows() if r not in before)[len("doc-") :]
            assert self.api(f"strategies/{copy}")["parent"] == original
            page.locator(f"#rename-{copy}").click()
            page.locator("#rename-input").fill(f"Breakout copy renamed {self.stamp}")
            page.locator("#rename-confirm").click()
            wait_text(f"#doc-{copy}", "renamed")
            page.locator(f"#delete-{copy}").click()
            page.locator("#delete-confirm").click()
            page.wait_for_selector(f"#doc-{copy}", state="detached")
            page.locator(f"#delete-{original}").click()
            page.locator("#delete-confirm").click()
            wait_text("#lab-error", "is referenced by")
            refusal = self.js("document.getElementById('lab-error').innerText")
            assert refusal.startswith("409"), refusal
            assert original in [r[len("doc-") :] for r in doc_rows()]
            page.locator("#lab-page button", has_text="Cancel").click()
            page.locator("#nav-charts").click()
            page.wait_for_selector("#chart-mount")
            self.wait_bars()
            return f"copy {copy} (parent {original}) renamed and deleted; original refused: '{refusal}'"

        self.item(42, item42)

        def item43():
            first, second = self.timings["identical_request_hashes"]
            assert first == second == RECORDED_IDENTICAL_HASH, (first, second)
            return f"item 22 produced the recorded Mission 3 hash {first}"

        self.item(43, item43)

        def item44():
            first = self.run_backtest()
            second = self.run_backtest()
            assert first["result_hash"] == second["result_hash"], (
                first["result_hash"],
                second["result_hash"],
            )
            assert first["strategy_id"] == second["strategy_id"] == self.lab["id"]
            return f"runs {first['run_id'][:8]} and {second['run_id'][:8]} both hash {first['result_hash']}"

        self.item(44, item44)

        def item45():
            page.locator("#right-tab-indicators").click()
            page.locator("#focus-long").click()
            donchian = self.js("document.getElementById('indicator-donchian')?.innerText ?? ''")
            rsi = self.js("document.getElementById('indicator-rsi')?.innerText ?? ''")
            assert (
                "DONCHIAN" in donchian and "price pane" in donchian and "donchian.upper" in donchian
            ), donchian
            assert "RSI" in rsi and "own pane" in rsi and "source" in rsi, rsi
            latest = self.js(
                "[...document.querySelectorAll('#indicator-rsi .latest b')].map(b => b.innerText)"
            )
            assert latest and all(v != DASH for v in latest), latest
            page.locator("#remove-rsi").click()
            wait_text("#indicator-error", "entry rule")
            refusal = self.js("document.getElementById('indicator-error').innerText")
            assert self.js("!!document.getElementById('indicator-rsi')"), "rsi was removed"
            page.locator("#right-tab-strategy").click()
            return f"donchian '{donchian.splitlines()[0]}', rsi latest {latest}; removal refused: '{refusal}'"

        self.item(45, item45)

        def item46():
            spec = self.api(f"strategies/{self.lab['id']}")["spec"]
            data = {"symbol": "QQQ", "timeframe": "1h", "start": "2024-06-03", "end": "2024-06-07"}

            def refused(mutate, needle):
                bad = json.loads(json.dumps(spec))
                mutate(bad["long_side"])
                response = self.post("backtest", {"strategy": bad, "data": data})
                assert response.status == 422, (needle, response.status, response.text()[:200])
                assert needle in response.text(), (needle, response.text()[:300])
                return needle

            condition = {"left": "rsi", "operator": "less_than", "right": "70"}
            checks = [
                refused(lambda s: s["exit"].update(right="foo"), "unknown operand 'foo'"),
                refused(lambda s: s["exit"].update(right="donchian"), "donchian has outputs"),
                refused(
                    lambda s: s.update(
                        exit={"left": "price.close", "operator": "inside_band", "right": "rsi"}
                    ),
                    "needs a band",
                ),
                refused(
                    lambda s: s.update(entry={"all_of": [condition]}),
                    "a group needs two conditions",
                ),
                refused(
                    lambda s: s.update(entry={"any_of": [condition] * 3}),
                    "at most two conditions in this slice",
                ),
                refused(
                    lambda s: s["indicators"][1].update(params={"x": 1}), "RSI has no parameter 'x'"
                ),
            ]
            return "422 for each: " + "; ".join(checks)

        self.item(46, item46)

        def item47():
            import subprocess

            status = page.request.get("http://127.0.0.1:8000/aegis/api/status").json()
            assert status["mode"] == "human_directed" and status["exchange"] == "CLOSED", status
            paths = ["app/trading_core", "app/platform_host", "app/products/triad"]
            committed = subprocess.run(
                ["git", "diff", "--name-only", MISSION5_BASE, "HEAD", "--", *paths],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            pending = subprocess.run(
                ["git", "status", "--porcelain", "--", *paths],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            assert committed == "" and pending == "", (committed, pending)
            return f"aegis {status['mode']} / {status['exchange']}; no change under {', '.join(paths)} since {MISSION5_BASE}"

        self.item(47, item47)

        # -- Mission 6 (spec §2 items 1–13) ----------------------------------------------------

        def item48():
            status = self.api("status")
            assert status["kernel_available"] is True and status["kernel_error"] is None, status
            engines = {self.first_run["engine"], self.lab_run["engine"]}
            assert engines == {"kernel"}, engines
            first, second = self.timings["identical_request_hashes"]
            assert first == second == RECORDED_IDENTICAL_HASH, (first, second)
            lab_wf = self.wf_status["result_hash"]
            assert lab_wf.startswith(RECORDED_LAB_WALKFORWARD_PREFIX), lab_wf
            api_wf = self.timings["identical_walkforward_hashes"]
            assert api_wf == [RECORDED_WALKFORWARD_HASH] * 2, api_wf
            self.timings["walkforward_hash_item28"] = lab_wf
            return (
                f"kernel available; runs report engine kernel; item 22 {first[:12]}…, item 28 "
                f"{lab_wf[:12]}… and item 34 {api_wf[0][:12]}… match the Mission 3 and 5 records"
            )

        self.item(48, item48)

        def item49():
            page.locator("#nav-experiments").click()
            page.wait_for_selector("#experiments-page")
            page.wait_for_function(
                "document.getElementById('experiment-new') && !document.getElementById('experiment-new').disabled",
                timeout=30_000,
            )
            self.open_planner()
            page.locator("#experiment-name").fill(f"Breakout surface {self.stamp}")
            self.add_surface(EXPERIMENT_SURFACE)
            page.locator("#experiment-objective").select_option("mar")
            page.locator("#budget-runs").fill("2000")
            line = self.wait_plan("252 cells")
            assert "4 parameters" in line and "exhaustive" in line, line
            planned = self.post("experiments/plan", self.experiment_body(EXPERIMENT_SURFACE)).json()
            assert planned["mode"] == "exhaustive", planned
            assert planned["planned_runs"] == planned["valid_cells"] == 252, planned
            assert planned["skipped"] == 0 and planned["bars"] == 3493, planned
            priced = (
                "the measured cost of an earlier experiment on this worker"
                if abs(planned["ms_per_cell_bar"] - 0.01) > 1e-12
                else "the starting guess of 0.01 ms per cell-bar (no experiment has finished on this worker yet)"
            )
            self.timings["experiment_plan"] = {
                k: planned[k]
                for k in (
                    "mode",
                    "valid_cells",
                    "planned_runs",
                    "estimate_seconds",
                    "ms_per_cell_bar",
                    "workers",
                    "bars",
                )
            }
            return (
                f"plan '{line}'; API: exhaustive, 252 of 252 valid cells, ≈ {planned['estimate_seconds']:.1f} s "
                f"on {planned['workers']} workers at {planned['ms_per_cell_bar'] * planned['bars']:.1f} ms per cell, "
                f"priced at {priced}"
            )

        self.item(49, item49)

        def item50():
            with page.expect_response(
                lambda r: r.url.endswith("/aegis/api/experiments") and r.request.method == "POST",
                timeout=60_000,
            ) as caught:
                page.locator("#experiment-start").click()
            started = caught.value
            assert started.status == 202, started.text()
            self.exp_id = started.json()["experiment_id"]
            assert self.wait_until(
                lambda: self.experiment(self.exp_id)["status"] == "running", 30
            ), self.experiment(self.exp_id)["status"]
            latencies = []
            for _ in range(10):
                t = time.perf_counter()
                assert page.request.get(self.base + f"api/experiments/{self.exp_id}").ok
                latencies.append(int((time.perf_counter() - t) * 1000))
            assert max(latencies) < 500, latencies
            # Requested during the first chunk; it lands at the chunk boundary, after 200 cells.
            paused = self.post(f"experiments/{self.exp_id}/pause", {})
            assert paused.status == 200, paused.text()
            page.wait_for_function(
                "/200 of 252 cells/.test(document.getElementById('experiment-progress')?.innerText ?? '')",
                timeout=180_000,
            )
            doc = self.experiment(self.exp_id)
            assert doc["progress"]["cells_done"] == 200, doc["progress"]
            assert doc["progress"]["chunks_done"] == 1, doc["progress"]
            self.timings["experiment_status_latency_ms_max"] = max(latencies)
            return (
                f"experiment {self.exp_id} started; status route {max(latencies)} ms max over 10 calls "
                f"while running; progress advanced 0 → 200 of 252 with the first chunk; the pause "
                f"requested during it took effect at the chunk boundary"
            )

        self.item(50, item50)

        def item51():
            assert self.wait_until(
                lambda: self.experiment(self.exp_id)["status"] == "paused", 180
            ), self.experiment(self.exp_id)["status"]
            page.wait_for_function(
                "(document.getElementById('experiment-progress')?.innerText ?? '').includes('paused')",
                timeout=30_000,
            )
            old, new = self.restart_worker()
            after = self.experiment(self.exp_id)
            assert after["status"] == "paused" and after["progress"]["cells_done"] == 200, (
                after["status"],
                after["progress"],
            )
            page.locator("#nav-charts").click()
            page.wait_for_selector("#chart-mount")
            page.locator("#nav-experiments").click()
            page.wait_for_selector(f"#exp-{self.exp_id}", timeout=60_000)
            page.locator(f"#exp-{self.exp_id}").click()
            page.wait_for_function(
                "(document.getElementById('experiment-progress')?.innerText ?? '').includes('paused')",
                timeout=30_000,
            )
            shown = self.progress_text().replace("\n", " | ")
            started = time.perf_counter()
            with page.expect_response(
                lambda r: (
                    r.url.endswith(f"/experiments/{self.exp_id}/resume")
                    and r.request.method == "POST"
                ),
                timeout=120_000,
            ) as caught:
                page.locator("#experiment-resume").click()
            assert caught.value.status == 202, caught.value.text()
            assert self.wait_until(
                lambda: self.experiment(self.exp_id)["status"] in ("done", "failed", "cancelled"),
                600,
                0.5,
            ), self.experiment(self.exp_id)["status"]
            doc = self.experiment(self.exp_id)
            assert doc["status"] == "done", doc.get("error")
            seconds = round(time.perf_counter() - started, 1)
            page.wait_for_selector("#experiment-report", timeout=60_000)
            cells = self.api(f"experiments/{self.exp_id}/cells?limit=300")
            indices = [r["cell"] for r in cells["rows"]]
            assert cells["total"] == len(indices) == len(set(indices)) == 252, (
                cells["total"],
                len(indices),
                len(set(indices)),
            )
            assert all(r["valid"] for r in cells["rows"])
            self.exp_doc = doc
            self.timings["experiment_ms_per_cell_bar"] = doc["ms_per_cell_bar"]
            self.timings["experiment_ms_per_cell"] = round(
                doc["ms_per_cell_bar"] * doc["plan"]["bars"], 1
            )
            self.timings["experiment_resume_seconds"] = seconds
            return (
                f"worker restarted (listener pid {old} → {new}); after it the experiment read "
                f"'{shown}'; resumed and done in {seconds} s; 252 rows, 252 distinct cells, all valid; "
                f"measured {self.timings['experiment_ms_per_cell']} ms per cell per worker"
            )

        self.item(51, item51)

        def item52():
            report = self.api(f"experiments/{self.exp_id}/report")
            rec = report["recommendation"]
            assert rec is not None, report["statement"]
            plateau = next(p for p in report["plateaus"] if p["id"] == rec["plateau"])
            assert rec["centre"]["cell"] in plateau["cells"] and plateau["size"] >= 9, (
                rec["centre"],
                plateau["size"],
            )
            text = self.js("document.getElementById('recommendation-text')?.innerText ?? ''")
            assert f"plateau {rec['plateau']}" in text.lower(), text
            assert f"cell {rec['centre']['cell']}" in text, text
            assert self.js(f"!!document.getElementById('plateau-{rec['plateau']}')"), (
                "no plateau row"
            )
            fragile = [p for p in report["peaks"] if p["fragile"]]
            standing = self.js(
                "[...document.querySelectorAll('#experiment-report .badge')].map(b => b.innerText)"
                ".filter(t => / · fragile$/.test(t) || / · plateau \\d+$/.test(t))"
            )
            assert len(standing) == min(len(report["peaks"]), 40), (
                len(standing),
                len(report["peaks"]),
            )
            assert (
                sum(t.endswith("fragile") for t in standing) == len(fragile)
                or len(report["peaks"]) > 40
            )
            effects = self.js("document.querySelectorAll('[id^=\"effect-\"]').length")
            assert effects == len(report["main_effects"]) == 4, (
                effects,
                list(report["main_effects"]),
            )
            heatmaps = self.js("document.querySelectorAll('.heat-grid').length")
            assert heatmaps == len(report["interactions"]) > 0, (heatmaps, report["interactions"])
            sensitivity_rows = self.js(
                "[...document.querySelectorAll('#experiment-report .report-section')]"
                ".find(s => s.querySelector('h4')?.innerText === 'Sensitivity')?.querySelectorAll('tbody tr').length"
            )
            assert sensitivity_rows == len(report["sensitivity"]["shares"]) + 1 == 5, (
                sensitivity_rows
            )
            clusters = self.js("document.getElementById('clusters')?.innerText ?? ''")
            if "refused" in report["clusters"]:
                assert "Not reported:" in clusters and report["clusters"]["refused"] in clusters, (
                    clusters
                )
                groups = f"refused: {report['clusters']['refused']}"
            else:
                assert "groups, silhouette" in clusters, clusters
                groups = f"{report['clusters']['k']} groups, silhouette {report['clusters']['silhouette']:.2f}"
            uncertainty = self.js("document.getElementById('uncertainty')?.innerText ?? ''")
            assert "out-of-sample" in uncertainty, uncertainty
            supported = rec["supported_peak"]
            page.screenshot(path=str(self.screenshot_path("experiment-report")), full_page=True)
            return (
                f"plateau {rec['plateau']}: {plateau['size']} cells, median {report['objective']} "
                f"{plateau['median']:.4f}, centre cell {rec['centre']['cell']} {rec['centre']['params']}; "
                f"supported peak {None if supported is None else supported['cell']}; {len(fragile)} fragile "
                f"of {len(report['peaks'])} peaks, each badge with its standing; {effects} main-effect charts, "
                f"{heatmaps} interaction heatmaps, sensitivity shares for 4 paths; clusters {groups}"
            )

        self.item(52, item52)

        def apply_params(spec: dict, params: dict) -> dict:
            strategy = json.loads(json.dumps(spec))
            for path, value in params.items():
                side, _, identifier, field = path.split(".", 3)
                indicator = next(i for i in strategy[side]["indicators"] if i["id"] == identifier)
                if field == "length":
                    indicator["length"] = int(value)
                else:
                    indicator.setdefault("params", {})[field.split(".", 1)[1]] = value
            return strategy

        def item53():
            rec = self.api(f"experiments/{self.exp_id}/report")["recommendation"]
            centre = rec["centre"]["cell"]
            runs = [
                self.post(f"experiments/{self.exp_id}/cells/{centre}/materialize", {})
                for _ in range(2)
            ]
            assert all(r.status == 200 for r in runs), [r.text()[:200] for r in runs]
            envelopes = [r.json() for r in runs]
            hashes = [e["result_hash"] for e in envelopes]
            assert hashes[0] == hashes[1] and envelopes[0]["run_id"] != envelopes[1]["run_id"], (
                hashes
            )
            assert envelopes[0]["experiment_id"] == self.exp_id and envelopes[0]["cell"] == centre
            doc = self.exp_doc
            direct = self.post(
                "backtest",
                {
                    "strategy": apply_params(doc["spec"], rec["centre"]["params"]),
                    "data": doc["data"],
                    "settings": doc["settings"],
                },
            )
            assert direct.status == 200, direct.text()[:300]
            assert direct.json()["result_hash"] == hashes[0], (
                direct.json()["result_hash"],
                hashes[0],
            )
            page.locator("#cells-plateau").select_option(str(rec["plateau"]))
            page.wait_for_selector(f"#cell-{centre}", timeout=30_000)
            page.locator(f"#materialize-{centre}").click()
            page.wait_for_function(
                f"(document.getElementById('cell-{centre}')?.innerText ?? '').includes('hash')",
                timeout=60_000,
            )
            shown = re.search(
                r"hash (\S+)", self.js(f"document.getElementById('cell-{centre}').innerText")
            ).group(1)
            assert hashes[0].startswith(shown.rstrip("…")), (shown, hashes[0])
            self.hashes.append(hashes[0])
            self.timings["materialized_hash"] = hashes[0]
            return (
                f"centre cell {centre} materialized twice → the same hash {hashes[0]}; a direct backtest of "
                f"the pinned spec with {rec['centre']['params']} → the same hash; the row shows hash {shown}"
            )

        self.item(53, item53)

        def item54():
            rec = self.api(f"experiments/{self.exp_id}/report")["recommendation"]
            params = rec["centre"]["params"]
            page.locator(f"#recommendation #use-cell-{rec['centre']['cell']}").click()
            page.wait_for_selector("#chart-mount", timeout=30_000)
            page.wait_for_selector("#unsaved-edits", timeout=30_000)
            self.wait_bars()
            long_card = self.js("document.querySelector('.side-card.long .logic')?.innerText ?? ''")
            short_card = self.js(
                "document.querySelector('.side-card.short .logic')?.innerText ?? ''"
            )
            donchian = int(params["long_side.indicators.donchian.length"])
            rsi = int(params["long_side.indicators.rsi.length"])
            ema = int(params["short_side.indicators.ema.length"])
            sma = int(params["short_side.indicators.sma.length"])
            assert f"DONCHIAN({donchian})" in long_card and f"RSI({rsi})" in long_card, (
                long_card,
                params,
            )
            assert f"EMA({ema})" in short_card and f"SMA({sma})" in short_card, (short_card, params)
            envelope = self.run_backtest()
            spec = envelope["strategy"]
            assert (
                next(i for i in spec["long_side"]["indicators"] if i["id"] == "rsi")["length"]
                == rsi
            )
            assert (
                next(i for i in spec["short_side"]["indicators"] if i["id"] == "ema")["length"]
                == ema
            )
            same = envelope["result_hash"] == self.timings["materialized_hash"]
            self.centre_run = envelope
            return (
                f"the Charts page with unsaved edits; long '{long_card.splitlines()[0]}', short "
                f"'{short_card.splitlines()[0]}'; backtest run {envelope['run_id'][:8]} hash "
                f"{envelope['result_hash'][:12]}… ({'equal to' if same else 'differs from'} the materialized hash)"
            )

        self.item(54, item54)

        def item55():
            page.locator("#nav-experiments").click()
            page.wait_for_selector(f"#exp-{self.exp_id}", timeout=60_000)
            page.locator(f"#exp-{self.exp_id}").click()
            page.wait_for_selector("#decision-save", timeout=60_000)
            note = f"centre is robust on QQQ 1h; walk it forward before any use ({self.stamp})"
            page.locator("#decision-verdict").select_option("accepted")
            page.locator("#decision-notes").fill(note)
            page.locator("#decision-save").click()
            page.wait_for_function(
                f"(document.getElementById('decision')?.innerText ?? '').includes({json.dumps(note)})",
                timeout=30_000,
            )
            page.wait_for_function(
                f"(document.getElementById('exp-{self.exp_id}')?.innerText ?? '').includes('accepted')",
                timeout=30_000,
            )
            doc = self.experiment(self.exp_id)
            assert doc["decision"]["verdict"] == "accepted" and doc["decision"]["notes"] == note, (
                doc["decision"]
            )
            listed = next(e for e in self.api("experiments") if e["id"] == self.exp_id)
            assert listed["decision"]["verdict"] == "accepted", listed
            return f"accepted at {doc['decision']['decided_at']} with the note; shown on the experiment and in its list row"

        self.item(55, item55)

        def item56():
            parent = self.exp_doc
            with page.expect_response(
                lambda r: (
                    r.url.endswith(f"/experiments/{self.exp_id}/refine")
                    and r.request.method == "POST"
                ),
                timeout=60_000,
            ) as caught:
                page.locator("#experiment-refine").click()
            assert caught.value.status == 201, caught.value.text()
            child = caught.value.json()
            self.child_id = child["id"]
            page.wait_for_selector(f"#exp-{self.child_id}", timeout=30_000)
            row = self.js(f"document.getElementById('exp-{self.child_id}').innerText")
            assert f"refines {self.exp_id}" in row and "queued" in row, row
            page.wait_for_function(
                "(document.getElementById('experiment-progress')?.innerText ?? '').includes('queued')",
                timeout=30_000,
            )
            assert child["status"] == "queued" and child["parent"] == self.exp_id, (
                child["status"],
                child["parent"],
            )
            assert child["progress"]["cells_done"] == 0 and child["latest_report"] is None
            parents = {p["path"]: p for p in parent["surface"]["parameters"]}
            narrowed = []
            for p in child["surface"]["parameters"]:
                before = parents[p["path"]]
                assert before["start"] <= p["start"] <= p["stop"] <= before["stop"], (before, p)
                assert p["step"] == before["step"], (before, p)
                if (p["stop"] - p["start"]) < (before["stop"] - before["start"]):
                    narrowed.append(p["path"].split(".")[-2])
            assert narrowed, child["surface"]
            ranges = "; ".join(
                f"{p['path'].split('.')[-2]} {p['start']:g}–{p['stop']:g}"
                for p in child["surface"]["parameters"]
            )
            return (
                f"child {self.child_id} queued (not started), parent {self.exp_id}, plan "
                f"{child['plan']['mode']} {child['plan']['planned_runs']} runs; narrowed {narrowed}: {ranges}"
            )

        self.item(56, item56)

        def item57():
            wide = [(p, a, b, 1) for p, a, b, _ in EXPERIMENT_SURFACE]
            self.open_planner()  # the gate shows: the workspace holds the centre as unsaved edits
            page.locator("#experiment-name").fill(f"Breakout wide {self.stamp}")
            self.add_surface(wide)
            page.locator("#experiment-objective").select_option("mar")
            page.locator("#budget-runs").fill("2000")
            line = self.wait_plan("157,542 cells")
            assert "sampled" in line, line
            planned = self.post("experiments/plan", self.experiment_body(wide)).json()
            assert planned["mode"] == "sampled" and planned["planned_runs"] == 2000, planned
            assert planned["valid_cells"] == 157_542, planned
            assert abs(planned["sampled_fraction"] - 2000 / 157_542) < 1e-9, planned
            levers = planned["levers"]
            assert len(levers) >= 14 and all(lv["valid_cells"] > 0 for lv in levers), len(levers)
            shown = self.js("[...document.querySelectorAll('[id^=lever-]')].map(b => b.innerText)")
            assert len(shown) == len(levers), (len(shown), len(levers))
            freeze = {lv["parameter"]: lv for lv in levers if lv["kind"] == "freeze"}
            page.locator("#lever-freeze-2").click()
            self.wait_plan(f"{freeze['short_side.indicators.ema.length']['valid_cells']:,} cells")
            page.locator("#lever-freeze-3").click()
            line2 = self.wait_plan("682 cells")
            assert "exhaustive" in line2, line2
            assert not self.js("!!document.querySelector('[id^=lever-]')"), (
                "levers shown for an exhaustive plan"
            )
            page.locator("#experiment-planner .panel-title button", has_text="Close").click()
            page.wait_for_selector("#experiment-planner", state="detached")
            return (
                f"plan '{line}'; API sampled 2,000 of 157,542 ({planned['sampled_fraction']:.2%}), first pass "
                f"{planned['first_pass']}, refinement {planned['refinement']}; {len(levers)} levers listed, e.g. "
                f"freeze ema → {freeze['short_side.indicators.ema.length']['valid_cells']:,} cells, freeze sma → "
                f"{freeze['short_side.indicators.sma.length']['valid_cells']:,}; both frozen → '{line2}'"
            )

        self.item(57, item57)

        def item58():
            page.locator(f"#exp-{self.exp_id}").click()
            page.wait_for_selector("#report-recompute", timeout=60_000)
            before = self.experiment(self.exp_id)
            page.locator("#report-objective").select_option("net_pnl")
            page.locator("#report-tolerance").fill("0.10")
            with page.expect_response(
                lambda r: (
                    r.url.endswith(f"/experiments/{self.exp_id}/report")
                    and r.request.method == "POST"
                ),
                timeout=120_000,
            ) as caught:
                page.locator("#report-recompute").click()
            assert caught.value.status == 200, caught.value.text()[:300]
            page.wait_for_function(
                "(document.getElementById('experiment-report')?.innerText ?? '').includes('2 reports kept')",
                timeout=30_000,
            )
            after = self.experiment(self.exp_id)
            assert [r["report_id"] for r in after["reports"]] == [1, 2], after["reports"]
            assert after["latest_report"] == 2 and after["status"] == "done", after["latest_report"]
            assert after["progress"] == before["progress"], (before["progress"], after["progress"])
            first = self.api(f"experiments/{self.exp_id}/report?n=1")
            second = self.api(f"experiments/{self.exp_id}/report?n=2")
            assert (first["objective"], first["tolerance"]) == ("mar", 0.15), first["objective"]
            assert (second["objective"], second["tolerance"]) == ("net_pnl", 0.1), second[
                "objective"
            ]
            text = self.js("document.getElementById('recommendation-text')?.innerText ?? ''")
            return (
                f"report 2: net_pnl at tolerance 0.10 → {len(second['plateaus'])} plateau(s), "
                f"{sum(p['fragile'] for p in second['peaks'])} fragile of {len(second['peaks'])} peaks, "
                f"'{text[:140]}'; report 1 (mar, 0.15) kept; cells untouched "
                f"({after['progress']['cells_done']} done, {after['progress']['chunks_done']} chunks)"
            )

        self.item(58, item58)

        def item59():
            body = self.experiment_body(EXPERIMENT_SURFACE, name=f"refusals {self.stamp}")

            def refused(label, mutate, needle):
                bad = json.loads(json.dumps(body))
                mutate(bad)
                response = self.post("experiments/plan", bad)
                assert response.status == 422, (label, response.status, response.text()[:200])
                assert needle in response.text(), (label, response.text()[:300])
                return f"{label} → 422 {needle!r}"

            eleven = [
                {"path": f"long_side.indicators.x{i}.length", "start": 1, "stop": 2, "step": 1}
                for i in range(11)
            ]
            wrong_side = {
                "path": "short_side.indicators.donchian.length",
                "start": 10,
                "stop": 40,
                "step": 5,
            }
            checks = [
                refused(
                    "no parameters",
                    lambda b: b["surface"].update(parameters=[]),
                    "a surface needs at least one parameter",
                ),
                refused(
                    "eleven parameters",
                    lambda b: b["surface"].update(parameters=eleven),
                    "at most 10 parameters",
                ),
                refused(
                    "a path on the wrong side",
                    lambda b: b["surface"]["parameters"].__setitem__(0, wrong_side),
                    "unknown parameter path 'short_side.indicators.donchian.length'",
                ),
                refused(
                    "a fractional step on a whole-number parameter",
                    lambda b: b["surface"]["parameters"][0].update(step=0.5),
                    "ranges of whole-number parameters need integer start, stop and step",
                ),
                refused(
                    "a budget of zero",
                    lambda b: b.update(budget={"runs": 0, "seconds": None}),
                    "runs must be positive",
                ),
            ]
            pause = self.post(f"experiments/{self.exp_id}/pause", {})
            assert pause.status == 409 and "is done, not running" in pause.text(), (
                pause.status,
                pause.text(),
            )
            checks.append(f"pause on the finished experiment → 409 {pause.json()['detail']!r}")
            # The refined child: resumed, a delete while it runs is refused; then paused again.
            resumed = self.post(f"experiments/{self.child_id}/resume", {})
            assert resumed.status == 202, resumed.text()
            deleted = page.request.delete(self.base + f"api/experiments/{self.child_id}")
            assert deleted.status == 409 and "cancel it first" in deleted.text(), (
                deleted.status,
                deleted.text(),
            )
            checks.append(f"delete of the running child → 409 {deleted.json()['detail']!r}")
            paused = self.post(f"experiments/{self.child_id}/pause", {})
            assert paused.status == 200, paused.text()
            assert self.wait_until(
                lambda: self.experiment(self.child_id)["status"] in ("paused", "done"), 300, 0.5
            ), self.experiment(self.child_id)["status"]
            child = self.experiment(self.child_id)
            self.timings["child_after_item59"] = {
                "status": child["status"],
                "cells_done": child["progress"]["cells_done"],
            }
            return "; ".join(checks) + (
                f"; child left {child['status']} at {child['progress']['cells_done']} of "
                f"{child['progress']['cells_planned']} cells"
            )

        self.item(59, item59)

        def item60():
            import subprocess

            def git(*args) -> str:
                return subprocess.run(
                    ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
                ).stdout

            status = page.request.get("http://127.0.0.1:8000/aegis/api/status").json()
            assert status["mode"] == "human_directed" and status["exchange"] == "CLOSED", status
            assert status["kernel_available"] is True, status
            schedule = page.request.get("http://127.0.0.1:8000/triad/api/daily-schedule").json()
            assert schedule["enabled"] is False and schedule["id"].startswith("c99fa831"), schedule
            paths = ["app/trading_core", "app/platform_host", "app/products/triad"]
            committed = git("diff", "--name-only", MISSION6_BASE, "HEAD", "--", *paths).strip()
            pending = git("status", "--porcelain", "--", *paths).strip()
            assert committed == "" and pending == "", (committed, pending)
            diff = git("diff", MISSION6_BASE, MISSION6_END, "--", "pyproject.toml").splitlines()
            added = [line for line in diff if line.startswith("+") and not line.startswith("+++")]
            removed = [line for line in diff if line.startswith("-") and not line.startswith("---")]
            assert added == ['+aegis = ["numba>=0.61,<0.69"]'] and removed == [], (added, removed)
            return (
                f"aegis {status['mode']} / {status['exchange']}, kernel available; DailySchedule "
                f"{schedule['id'][:8]} enabled={schedule['enabled']}; no change under {', '.join(paths)} "
                f"since {MISSION6_BASE}; pyproject.toml over Mission 6 ({MISSION6_BASE}..{MISSION6_END}): "
                f"one added line {added[0][1:]!r}, nothing removed"
            )

        self.item(60, item60)

        # -- Mission 8 (spec §3 items 1–9) ----------------------------------------------------
        def item61():
            page.locator("#nav-charts").click()
            page.wait_for_selector("#chart-mount")
            page.locator("#nav-experiments").click()
            page.wait_for_selector(f"#exp-{self.exp_id}", timeout=60_000)
            page.locator(f"#exp-{self.exp_id}").click()
            page.wait_for_function(
                "document.getElementById('experiment-walk-forward') && !document.getElementById('experiment-walk-forward').disabled",
                timeout=60_000,
            )
            page.locator("#experiment-walk-forward").click()
            page.wait_for_function(
                "/runs · ≈/.test(document.getElementById('study-plan')?.innerText ?? '')",
                timeout=120_000,
            )
            checked = self.js(
                "[...document.querySelectorAll('#study-symbols input')].filter(i => i.checked)"
                ".map(i => i.id.replace('study-symbol-check-', ''))"
            )
            assert sorted(checked) == sorted(STUDY_SYMBOLS), checked
            lengths = self.js(
                "[document.getElementById('study-in-sample').value, document.getElementById('study-out-of-sample').value]"
            )
            assert lengths == ["3493", "873"], lengths
            line = self.js("document.getElementById('study-plan').innerText").splitlines()[0]
            response = self.post("studies/plan", self.study_body())
            assert response.ok, response.text()
            planned = response.json()
            assert (planned["in_sample_bars"], planned["out_of_sample_bars"]) == (3493, 873), (
                planned
            )
            for entry in planned["symbols"]:
                assert entry["mode"] == "exhaustive" and entry["cells_per_window"] == 252, entry
                assert entry["first_window"]["is_start"].startswith("2016-09-19"), entry
            assert planned["price_source"] == "measured", planned
            assert f"{planned['total_runs']:,} runs" in line and "measured on this host" in line, (
                line
            )
            self.study_plan = planned
            windows = {e["symbol"]: e["windows"] for e in planned["symbols"]}
            self.timings["study_plan"] = {
                "windows": windows,
                "bars": {e["symbol"]: e["bars"] for e in planned["symbols"]},
                "total_runs": planned["total_runs"],
                "estimate_seconds": planned["estimate_seconds"],
                "ms_per_cell_bar": planned["ms_per_cell_bar"],
            }
            return (
                f"plan line '{line}'; API: windows {windows}, 252 cells per window exhaustive, "
                f"{planned['total_runs']:,} runs, ≈ {planned['estimate_seconds']:.0f} s at the measured "
                f"{planned['ms_per_cell_bar']:.4f} ms per cell-bar"
            )

        self.item(61, item61)

        def item62():
            page.locator("#study-start-date").fill(STUDY_RANGE[0])
            page.locator("#study-end-date").fill(STUDY_RANGE[1])
            time.sleep(1.5)  # the plan line's 300 ms debounce, then its request
            page.wait_for_function(
                "!document.getElementById('study-start').disabled", timeout=120_000
            )
            with page.expect_response(
                lambda r: r.url.endswith("/aegis/api/studies") and r.request.method == "POST",
                timeout=120_000,
            ) as caught:
                page.locator("#study-start").click()
            started = caught.value
            assert started.status == 202, started.text()
            self.study_id = started.json()["study_id"]
            self.study_request = json.loads(started.request.post_data)
            for key, value in self.study_body().items():
                assert self.study_request[key] == value, (key, self.study_request[key], value)
            self.study_started = time.perf_counter()
            seen, latencies = [], []
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                t = time.perf_counter()
                response = page.request.get(self.base + f"api/studies/{self.study_id}")
                latencies.append(int((time.perf_counter() - t) * 1000))
                assert response.ok, response.text()
                done = response.json()["progress"]["windows_done"]
                if not seen or seen[-1] != done:
                    seen.append(done)
                if len(seen) >= 3:
                    break
                time.sleep(0.25)
            assert len(seen) >= 3 and seen == sorted(seen), seen
            assert max(latencies) < 500, max(latencies)
            page.wait_for_function(
                "/of \\d+ windows/.test(document.getElementById('study-progress')?.innerText ?? '')",
                timeout=60_000,
            )
            progress = self.js("document.getElementById('study-progress').innerText")
            self.timings["study_status_latency_ms_max"] = max(latencies)
            return (
                f"study {self.study_id} started from the page with {self.study_request['symbols']} "
                f"{STUDY_RANGE[0]} → {STUDY_RANGE[1]}, 3,493 + 873 bars; windows done advanced "
                f"{' → '.join(map(str, seen))}; status route {max(latencies)} ms max over "
                f"{len(latencies)} calls; the page reads '{progress.splitlines()[-1]}'"
            )

        self.item(62, item62)

        def item63():
            paused = self.post(f"studies/{self.study_id}/pause", {})
            assert paused.status == 200, paused.text()
            doc = self.wait_study(self.study_id, ("paused",), 900)
            before = doc["progress"]["windows_done"]
            old, new = self.restart_worker()
            after = self.study(self.study_id)
            assert after["status"] == "paused", after["status"]
            assert after["progress"]["windows_done"] == before, after["progress"]
            resumed_at = time.perf_counter()
            resumed = self.post(f"studies/{self.study_id}/resume", {})
            assert resumed.status == 202, resumed.text()
            doc = self.wait_study(self.study_id, ("done", "failed", "cancelled"), 5400)
            assert doc["status"] == "done", doc.get("error")
            total = 0
            for entry in self.study_plan["symbols"]:
                indices = [w["index"] for w in doc["windows"][entry["symbol"]]]
                assert indices == list(range(entry["windows"])), (entry["symbol"], indices)
                total += entry["windows"]
            assert doc["progress"]["windows_done"] == total, doc["progress"]
            self.study_doc = doc
            self.timings["study_seconds"] = {
                "start_to_done": round(time.perf_counter() - self.study_started, 1),
                "resume_to_done": round(time.perf_counter() - resumed_at, 1),
                "ms_per_cell_bar": doc.get("ms_per_cell_bar"),
            }
            counts = ", ".join(f"{e['symbol']} {e['windows']}" for e in self.study_plan["symbols"])
            return (
                f"paused at {before} of {total} windows; worker {old} → {new}; the study stayed "
                f"paused at {before}; resumed and finished in {self.timings['study_seconds']['resume_to_done']} s; "
                f"every window present once ({counts})"
            )

        self.item(63, item63)

        def item64():
            page.locator("#nav-charts").click()
            page.wait_for_selector("#chart-mount")
            page.locator("#nav-experiments").click()
            page.wait_for_selector(f"#exp-{self.exp_id}", timeout=60_000)
            page.locator(f"#exp-{self.exp_id}").click()
            page.wait_for_selector(f"#study-row-{self.study_id}", timeout=60_000)
            page.locator(f"#study-row-{self.study_id}").click()
            page.wait_for_selector("#study-summary", timeout=60_000)
            summary = self.js("document.getElementById('study-summary').innerText")
            assert "RAW ARCHIVE · NOT RESEARCH-ELIGIBLE" in summary, summary
            assert "plateau rule ahead of the peak rule on" in summary, summary
            assert "no significance test is claimed" in summary, summary
            report = self.study_doc["report"]
            assert report["raw_archive"] is True and report["frozen_absent"] is None, report[
                "frozen_absent"
            ]
            lines = []
            for entry in self.study_plan["symbols"]:
                symbol = entry["symbol"]
                rows = self.js(
                    f"document.querySelectorAll('#study-rules-{symbol} tbody tr').length"
                )
                paths = self.js(f"document.querySelectorAll('#study-chart-{symbol} path').length")
                windows = self.js(
                    f"document.querySelectorAll('#study-windows-{symbol} tbody tr[id^=\"study-window-{symbol}-\"]').length"
                )
                assert rows == 3 and paths == 3, (symbol, rows, paths)
                assert windows == entry["windows"], (symbol, windows)
                assert self.js(f"!!document.getElementById('study-stability-{symbol}')"), symbol
                section = report["symbols"][symbol]
                lines.append(f"{section['comparison']} ({section['flat_line']})")
            self.timings["study_report"] = {
                "summary": report["summary"],
                "symbols": {
                    s: {
                        "comparison": e["comparison"],
                        "flat_line": e["flat_line"],
                        "stability": {
                            k: v for k, v in e["stability"].items() if k != "centre_path"
                        },
                        "rules": {r: v.get("metrics") for r, v in e["rules"].items()},
                    }
                    for s, e in report["symbols"].items()
                },
            }
            page.screenshot(path=str(self.screenshot_path("study")), full_page=True)
            return f"'{report['summary']}'; " + " ".join(lines)

        self.item(64, item64)

        def item65():
            import hashlib
            import subprocess
            from datetime import UTC as utc
            from datetime import datetime as dt

            symbol = "QQQ"
            doc = self.study_doc
            candidates = [
                w
                for w in doc["windows"][symbol]
                if w["plateau"] and not w["rules"]["plateau"]["flat"] and w["index"] > 0
            ]
            carried = [
                w
                for w in candidates
                if any(c.get("carry") for c in w["chains_in"]["plateau"].values())
            ]
            window = (carried or candidates)[0]
            k = window["index"]
            cells = self.api(f"studies/{self.study_id}/windows/{symbol}/{k}/cells?limit=5000")
            payload = {
                "rows": cells["rows"],
                "spec": doc["spec"],
                "surface": doc["surface"],
                "in_sample": doc["in_sample_bars"],
                "objective": doc["objective"],
                "tolerance": doc["tolerance"],
                "mode": window["mode"],
                "seed": doc["seed"] + k,
            }
            script = (
                "import json, sys\n"
                "sys.path.insert(0, 'app')\n"
                "from products.aegis.analysis import analyse\n"
                "from products.aegis.strategy import StrategySpec\n"
                "from products.aegis.surface import Surface, build_grid\n"
                "data = json.load(sys.stdin)\n"
                "grid = build_grid(StrategySpec.model_validate(data['spec']), "
                "Surface.model_validate(data['surface']), data['in_sample'])\n"
                "report = analyse(data['rows'], grid, data['objective'], data['tolerance'], "
                "data['mode'], data['seed'], 'recompute')\n"
                "rec = report['recommendation']\n"
                "print(json.dumps({'centre': rec['centre']['cell'] if rec else None, "
                "'statement': report['statement']}))\n"
            )
            ran = subprocess.run(
                [str(ROOT / ".venv-aegis" / "Scripts" / "python.exe"), "-c", script],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                cwd=ROOT,
                check=True,
            )
            recomputed = json.loads(ran.stdout.strip().splitlines()[-1])
            assert recomputed["centre"] == window["plateau"]["centre_cell"], (
                recomputed,
                window["plateau"],
            )

            bars = self.api(
                f"data/bars?symbol={symbol}&timeframe=1h&start={STUDY_RANGE[0]}&end={STUDY_RANGE[1]}"
            )["bars"]
            plan = next(e for e in self.study_plan["symbols"] if e["symbol"] == symbol)
            assert len(bars) == plan["bars"], (len(bars), plan["bars"])
            rows = [
                {
                    "timestamp": dt.fromtimestamp(b["time"] / 1000, utc).isoformat(),
                    "open": b["open"],
                    "high": b["high"],
                    "low": b["low"],
                    "close": b["close"],
                    "volume": b["volume"],
                    "symbol": symbol,
                }
                for b in bars
            ]
            oos_start = k * 873 + 3493
            oos_end = oos_start + 873
            assert rows[oos_start]["timestamp"] == window["oos_start"], (
                rows[oos_start],
                window["oos_start"],
            )
            last = k == plan["windows"] - 1
            params = window["rules"]["plateau"]["params"]
            matched = []
            for side, record in window["rules"]["plateau"]["sides"].items():
                chain = window["chains_in"]["plateau"][side]
                spec = json.loads(json.dumps(doc["spec"]))
                other = "short_side" if side == "long" else "long_side"
                spec[other]["enabled"] = False
                for path, value in params.items():
                    side_key, _, rest = path.partition(".")
                    parts = rest.split(
                        "."
                    )  # indicators.<id>.length or indicators.<id>.params.<name>
                    indicator = next(i for i in spec[side_key]["indicators"] if i["id"] == parts[1])
                    if parts[2] == "length":
                        indicator["length"] = round(value)
                    else:
                        indicator.setdefault("params", {})[parts[3]] = value
                body = {
                    "strategy": spec,
                    "bars": rows[:oos_end],
                    "settings": {
                        "initial_capital": chain["cash"],
                        "allocation_fraction": doc["settings"]["allocation_fraction"],
                        "evaluate_from": window["oos_start"],
                        "initial_position": chain["carry"],
                        "initial_entry": chain.get("pending"),  # an entry carried across the join
                        "close_at_end": last,
                    },
                }
                response = self.post("backtest", body)
                assert response.ok, response.text()[:300]
                result = response.json()["result"][side]
                digest = hashlib.sha256(
                    json.dumps(
                        {"trades": result["trades"], "metrics": result["metrics"]},
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                ).hexdigest()
                assert digest == record["run_hash"], (side, digest, record["run_hash"])
                matched.append(
                    f"{side} {len(result['trades'])} trades from ${chain['cash']:,.0f}"
                    + (" with a carried position" if chain.get("carry") else "")
                    + f" → {digest[:12]}"
                )
            return (
                f"{symbol} window {k} ({window['oos_start'][:10]} → {window['oos_end'][:10]}): its "
                f"{len(cells['rows'])} cells re-analysed out of process give centre cell "
                f"{recomputed['centre']} as recorded; the plateau rule's runs equal direct "
                f"backtests on the same bars, evaluate_from, capital and carry: "
                + "; ".join(matched)
            )

        self.item(65, item65)

        def item66():
            started = self.post("studies", self.study_request)
            assert started.status == 202, started.text()
            twin_id = started.json()["study_id"]
            twin = self.wait_study(twin_id, ("done", "failed", "cancelled"), 5400)
            assert twin["status"] == "done", twin.get("error")
            first, second = self.study_hashes(self.study_doc), self.study_hashes(twin)
            assert first == second, (first, second)
            self.twin_id = twin_id
            count = sum(len(v) for v in first.values())
            return (
                f"study {twin_id} on the identical request reproduced all {count} per-rule hashes: "
                + "; ".join(
                    f"{s} " + ", ".join(f"{r} {h[:12]}" for r, h in v.items())
                    for s, v in first.items()
                )
            )

        self.item(66, item66)

        def item67():
            checks = []

            def refused(response, status, needle, label):
                assert response.status == status and needle in response.text(), (
                    label,
                    response.status,
                    response.text()[:300],
                )
                checks.append(f"{label} → {status}")

            base = self.study_body()
            refused(
                self.post("studies/plan", {**base, "symbols": ["ZZZ"]}),
                422,
                "unknown symbol 'ZZZ'",
                "unknown symbol",
            )
            refused(
                self.post("studies/plan", {**base, "in_sample_bars": 30}),
                422,
                "in_sample_bars 30 below 35",
                "in-sample under the floor",
            )
            refused(
                self.post("studies/plan", {**base, "out_of_sample_bars": 10}),
                422,
                "out_of_sample_bars 10 below 20",
                "out-of-sample under the floor",
            )
            refused(
                self.post("studies/plan", {**base, "start": "2026-01-02"}),
                422,
                "range too short",
                "a range shorter than one window",
            )
            refused(
                self.post(
                    "studies/plan", {**base, "in_sample_bars": 700, "out_of_sample_bars": 200}
                ),
                422,
                "needs an in-sample span of at least 365 days",
                "MAR on under a year in-sample",
            )
            refused(
                self.post("studies/plan", {**base, "symbols": []}),
                422,
                "at least one symbol",
                "no symbol",
            )
            refused(
                self.post(f"studies/{self.study_id}/pause", {}),
                409,
                "not running",
                "pause of a finished study",
            )
            refused(
                page.request.delete(self.base + f"api/experiments/{self.exp_id}"),
                409,
                "has studies",
                "delete of a parent experiment",
            )
            small = {**base, "symbols": ["QQQ"], "name": f"refusals {self.stamp}"}
            started = self.post("studies", small)
            assert started.status == 202, started.text()
            running = started.json()["study_id"]
            refused(
                self.post("studies", small),
                409,
                "another job is running",
                "a second start while one runs",
            )
            refused(
                page.request.delete(self.base + f"api/studies/{running}"),
                409,
                "cancel it first",
                "delete of a running study",
            )
            queued = self.post(
                "experiments", self.experiment_body(EXPERIMENT_SURFACE, name=f"queued {self.stamp}")
            )
            assert queued.status == 202 and queued.json()["status"] == "queued", queued.text()
            queued_id = queued.json()["experiment_id"]
            refused(
                self.post("studies/plan", {**base, "experiment_id": queued_id}),
                422,
                "a study needs a finished experiment with a report",
                "a study of an unfinished experiment",
            )
            assert self.post(f"experiments/{queued_id}/cancel", {}).ok
            assert page.request.delete(self.base + f"api/experiments/{queued_id}").ok
            assert self.post(f"studies/{running}/cancel", {}).ok
            self.wait_study(running, ("cancelled",), 900)
            assert page.request.delete(self.base + f"api/studies/{running}").ok
            return (
                "; ".join(checks)
                + "; the refusals' study and experiment were cancelled and deleted"
            )

        self.item(67, item67)

        def item68():
            page.locator("#nav-charts").click()
            page.wait_for_selector("#chart-mount")
            page.locator("#nav-experiments").click()
            page.wait_for_selector(f"#exp-{self.exp_id}", timeout=60_000)
            page.locator(f"#exp-{self.exp_id}").click()
            page.wait_for_selector(f"#study-row-{self.study_id}", timeout=60_000)
            page.locator(f"#study-row-{self.study_id}").click()
            page.wait_for_selector("#study-decision-save", timeout=60_000)
            note = f"plateau walk-forward recorded; no significance claimed ({self.stamp})"
            page.locator("#study-decision-verdict").select_option("accepted")
            page.locator("#study-decision-notes").fill(note)
            page.locator("#study-decision-save").click()
            page.wait_for_function(
                f"(document.getElementById('study-decision-current')?.innerText ?? '').includes({json.dumps(note)})",
                timeout=30_000,
            )
            page.wait_for_function(
                f"(document.getElementById('study-row-{self.study_id}')?.innerText ?? '').includes('accepted')",
                timeout=30_000,
            )
            doc = self.study(self.study_id)
            assert doc["decision"]["verdict"] == "accepted" and doc["decision"]["notes"] == note, (
                doc["decision"]
            )
            listed = next(
                s
                for s in self.api(f"studies?experiment_id={self.exp_id}")
                if s["id"] == self.study_id
            )
            assert listed["decision"]["verdict"] == "accepted", listed
            return f"accepted at {doc['decision']['decided_at']} with the note; shown on the study and in its row under the experiment"

        self.item(68, item68)

        def item69():
            import subprocess

            def git(*args) -> str:
                return subprocess.run(
                    ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
                ).stdout

            status = page.request.get("http://127.0.0.1:8000/aegis/api/status").json()
            assert status["mode"] == "human_directed" and status["exchange"] == "CLOSED", status
            schedule = page.request.get("http://127.0.0.1:8000/triad/api/daily-schedule").json()
            assert schedule["enabled"] is False and schedule["id"].startswith("c99fa831"), schedule
            paths = ["app/trading_core", "app/platform_host", "app/products/triad"]
            committed = git("diff", "--name-only", MISSION8_BASE, "HEAD", "--", *paths).strip()
            pending = git("status", "--porcelain", "--", *paths).strip()
            assert committed == "" and pending == "", (committed, pending)
            return (
                f"aegis {status['mode']} / {status['exchange']}; DailySchedule {schedule['id'][:8]} "
                f"enabled={schedule['enabled']}; no change under {', '.join(paths)} since {MISSION8_BASE}"
            )

        self.item(69, item69)
        self.mission9()
        self.limits()
        self.no_limit()

    # -- Mission 9 plumbing: the Results library ---------------------------------------------
    def library_rows(self) -> list[str]:
        return self.js(
            "[...document.querySelectorAll('#library-list .library-row')].map(r => r.id)"
        )

    def library_change(self, action) -> dict:
        """Do one filter change and wait for the list request it causes; returns that page."""
        with self.page.expect_response(
            lambda r: "/aegis/api/library?" in r.url and r.request.method == "GET", timeout=60_000
        ) as caught:
            action()
        page_ = caught.value.json()
        self.page.wait_for_timeout(150)  # React renders the page it just received
        return page_

    def open_library(self) -> dict:
        """The Library with its default filters: it keeps no state across visits, so leaving for
        the Experiments page and coming back resets them."""
        page = self.page
        if self.js("!!document.getElementById('library-page')"):
            page.locator("#nav-experiments").click()
            page.wait_for_selector(".experiments-page", timeout=30_000)
        return self.library_change(lambda: page.locator("#nav-library").click())

    def library_kind(self, kind: str) -> dict:
        return self.library_change(lambda: self.page.locator(f"#library-kind-{kind}").click())

    def library_select(self, element_id: str, value: str) -> dict:
        if value:
            self.page.wait_for_selector(
                f'#{element_id} option[value="{value}"]', state="attached", timeout=30_000
            )
        return self.library_change(lambda: self.page.locator(f"#{element_id}").select_option(value))

    def library_search(self, text: str) -> dict:
        return self.library_change(lambda: self.page.locator("#library-search").fill(text))

    def library_row(self, kind: str, item_id: str):
        locator = self.page.locator(f'[id="lib-{kind}-{item_id}"]')
        locator.wait_for(timeout=30_000)
        return locator

    def library_open(self, kind: str, item_id: str) -> None:
        self.library_row(kind, item_id).click()
        self.page.wait_for_selector("#library-view .library-view-head", timeout=60_000)

    def pair_filters(self) -> None:
        """Narrow to the default strategy's QQQ 1h backtests, where item 22's pair is listed."""
        self.library_kind("backtest")
        self.library_select("library-symbol", "QQQ")
        self.library_select("library-timeframe", "1h")
        self.library_select("library-strategy", self.identical_runs[0]["strategy_id"])

    def workspace_snapshot(self) -> dict:
        page = self.page
        page.locator("#nav-charts").click()
        page.wait_for_selector("#chart-mount", timeout=30_000)
        self.wait_bars()
        return self.js(
            "({run: document.getElementById('run-state')?.innerText ?? '',"
            " instrument: document.querySelector('.chart-header .instrument')?.innerText ?? '',"
            " range: document.querySelector('.chart-header .ohlc')?.innerText ?? '',"
            " long: document.querySelector('.side-card.long .logic')?.innerText ?? '',"
            " short: document.querySelector('.side-card.short .logic')?.innerText ?? '',"
            " unsaved: !!document.getElementById('unsaved-edits')})"
        )

    def compare_ticked(self, a: str, b: str) -> None:
        page = self.page
        for run_id in (a, b):
            page.locator(f'[id="lib-check-backtest-{run_id}"]').check()
        page.wait_for_function("!document.getElementById('library-compare').disabled")
        with page.expect_response(lambda r: "/aegis/api/library/compare?" in r.url, timeout=60_000):
            page.locator("#library-compare").click()
        page.wait_for_selector("#compare-notes", timeout=30_000)

    # -- Mission 9 items --------------------------------------------------------------------------
    def mission9(self):
        page = self.page

        def item70():
            assert self.wait_until(lambda: self.api("library?limit=1")["preparing"] == 0, 600, 2), (
                "headlines still preparing"
            )
            self.open_library()
            own = {
                "backtest": self.identical_runs[1]["run_id"],
                "optimization": self.opt_job_id,
                "walkforward": self.wf_status["job_id"],
                "experiment": self.exp_id,
                "study": self.study_id,
            }
            seen = []
            for kind in LIBRARY_KINDS:
                listed = self.api(f"library?kind={kind}&limit=200")
                assert own[kind] in [e["id"] for e in listed["entries"]], (kind, own[kind])
                shown = self.library_kind(kind)
                rows = self.library_rows()
                assert rows and all(r.startswith(f"lib-{kind}-") for r in rows), (kind, rows[:3])
                assert len(rows) == min(50, shown["total"]), (kind, len(rows), shown["total"])
                first = self.js(
                    "document.querySelector('#library-list .library-row .library-row-body > .small:last-child')?.innerText ?? ''"
                )
                assert first and "preparing" not in first, (kind, first)
                seen.append(f"{kind} {shown['total']} ('{first[:48]}')")
                self.library_kind(kind)  # off again
            return "; ".join(seen) + "; the walk's own items are indexed"

        self.item(70, item70)

        def item71():
            a, b = self.identical_runs
            totals = [self.open_library()["total"]]
            totals.append(self.library_kind("backtest")["total"])
            totals.append(self.library_select("library-symbol", "QQQ")["total"])
            totals.append(self.library_select("library-timeframe", "1h")["total"])
            totals.append(self.library_select("library-strategy", a["strategy_id"])["total"])
            assert all(x >= y for x, y in itertools.pairwise(totals)) and totals[-1] >= 2, totals
            self.library_open("backtest", b["run_id"])
            self.pair_label = f"identical pair B {self.stamp}"
            page.locator("#library-label").fill(self.pair_label)
            page.locator("#library-notes").fill("Mission 9 acceptance: item 22's second run")
            with page.expect_response(
                lambda r: r.url.endswith("/annotation"), timeout=30_000
            ) as saved:
                page.locator("#library-save-annotation").click()
            assert saved.value.ok, saved.value.text()
            star = page.locator(f'[id="lib-star-backtest-{b["run_id"]}"]')
            if star.get_attribute("aria-pressed") != "true":  # a fresh walk's run is unstarred
                with page.expect_response(
                    lambda r: r.url.endswith("/annotation"), timeout=30_000
                ) as starred:
                    star.click()
                assert starred.value.ok and starred.value.json()["starred"] is True, (
                    starred.value.text()
                )
            note = self.api(f"library?kind=backtest&q={self.pair_label.replace(' ', '+')}")
            assert [(e["label"], e["starred"]) for e in note["entries"]] == [
                (self.pair_label, True)
            ], note["entries"]
            page.wait_for_function(
                f"document.getElementById({json.dumps('lib-star-backtest-' + b['run_id'])})?.getAttribute('aria-pressed') === 'true'"
            )
            self.open_library()
            found = self.library_search(self.pair_label)
            assert [e["id"] for e in found["entries"]] == [b["run_id"]], found["entries"]
            assert self.library_rows() == [f"lib-backtest-{b['run_id']}"], self.library_rows()
            self.open_library()
            starred_page = self.library_change(lambda: page.locator("#library-starred").check())
            assert all(e["starred"] for e in starred_page["entries"]), starred_page["entries"]
            assert f"lib-backtest-{b['run_id']}" in self.library_rows()
            self.open_library()
            decided = self.library_select("library-decision", "accepted")
            ids = {(e["kind"], e["id"]) for e in decided["entries"]}
            assert {("experiment", self.exp_id), ("study", self.study_id)} <= ids, ids
            self.open_library()
            self.library_kind("backtest")
            by_mar = self.library_select("library-sort", "mar")
            mars = [e["headline"].get("mar") for e in by_mar["entries"]]
            valued = [m for m in mars if m is not None]
            assert valued == sorted(valued, reverse=True), mars[:10]
            assert self.library_rows()[0] == f"lib-backtest-{by_mar['entries'][0]['id']}"
            return (
                f"totals all → backtest → QQQ → 1h → default strategy: {' → '.join(map(str, totals))}; "
                f"label '{self.pair_label}' found by search alone; starred and listed under Starred "
                f"({starred_page['total']}); accepted lists the experiment and the study; MAR sorts descending"
            )

        self.item(71, item71)

        def item72():
            b = self.identical_runs[1]
            before = self.workspace_snapshot()
            self.open_library()
            self.library_search(self.pair_label)
            self.library_open("backtest", b["run_id"])
            page.wait_for_function(
                "/\\d[\\d,]* bars · \\d[\\d,]* markers/.test(document.querySelector('#library-chart .legend')?.innerText ?? '')",
                timeout=90_000,
            )
            legend = self.js("document.querySelector('#library-chart .legend').innerText")
            markers = int(re.search(r"([\d,]+) markers", legend).group(1).replace(",", ""))
            assert markers == len(b["markers"]) > 0, (markers, len(b["markers"]))
            header = self.js("document.querySelector('#library-view .library-view-head').innerText")
            assert b["result_hash"][:12] in header and "raw archive" in header, header
            net = self.js(
                "[...document.querySelectorAll('#library-view #summary-metrics tbody tr')]"
                ".find(r => r.cells[0].innerText === 'Net P&L')?.cells[3].innerText ?? ''"
            )
            assert net not in ("", DASH), net
            temporal = self.js(
                "document.querySelectorAll('#library-view #temporal-breakdown tbody tr').length"
            )
            assert temporal > 0, "no temporal breakdown"
            page.locator("#library-tab-trades").click()
            trades = self.js(
                "document.querySelectorAll('#library-view .results-table tbody tr').length"
            )
            assert trades > 0, "no trades listed"
            page.locator("#library-tab-equity").click()
            assert self.js(
                "document.querySelectorAll('#library-view svg[aria-label=\"equity curve\"] path').length"
            ), "no equity curve"
            after = self.workspace_snapshot()
            assert after == before, (before, after)
            self.open_library()
            self.library_search(self.pair_label)
            self.library_open("backtest", b["run_id"])
            asked: list[str] = []

            def dismiss(dialog):
                asked.append(dialog.message)
                dialog.dismiss()

            def accept(dialog):
                asked.append(dialog.message)
                dialog.accept()

            if before["unsaved"]:
                page.on("dialog", dismiss)
                page.locator("#library-load").click()
                page.wait_for_timeout(500)
                page.remove_listener("dialog", dismiss)
                assert asked and self.js("!!document.getElementById('library-page')"), asked
            page.on("dialog", accept)
            try:
                page.locator("#library-load").click()
                page.wait_for_selector("#chart-mount", timeout=30_000)
            finally:
                page.remove_listener("dialog", accept)
            loaded = self.workspace_snapshot()
            assert loaded["run"].startswith(f"run {b['run_id'][:8]}"), loaded
            assert loaded["instrument"].startswith("QQQ · 1h"), loaded
            return (
                f"run {b['run_id'][:8]} read-only: {legend.strip()}, Net P&L {net}, {temporal} temporal rows, "
                f"{trades} trades; the workspace before and after equal ({before['run'] or 'no run'}); "
                + (
                    "Load asked first over unsaved edits (dismissed: nothing changed), then loaded it"
                    if before["unsaved"]
                    else "no unsaved edits, so Load loaded it without asking"
                )
            )

        self.item(72, item72)

        def item73():
            self.open_library()
            self.library_kind("optimization")
            self.library_open("optimization", self.opt_job_id)
            page.wait_for_function(
                "document.querySelectorAll('#library-view #optimization-cells-long tbody tr').length === 40",
                timeout=60_000,
            )
            filled = self.js(
                f"[...document.querySelectorAll('#library-view .heat-grid .cell:not(.h)')].filter(c => c.innerText !== '{DASH}').length"
            )
            assert filled == 40, filled
            assert self.js("document.getElementById('library-load').disabled")
            page.locator("#library-view #optimization-cells-long tbody tr").first.click()
            page.wait_for_function("!document.getElementById('library-load').disabled")
            self.library_kind("optimization")
            self.library_kind("walkforward")
            self.library_open("walkforward", self.wf_status["job_id"])
            page.wait_for_function(
                "document.querySelectorAll('#library-view #walkforward-windows-long tbody tr').length === 6",
                timeout=60_000,
            )
            stitched = self.js("document.getElementById('walkforward-stitched-long').innerText")
            stability = self.js("document.getElementById('walkforward-stability-long').innerText")
            assert "Net P&L" in stitched and "Stability" in stability, (stitched, stability)
            assert "final window" in self.js("document.getElementById('library-load').innerText")
            self.library_kind("walkforward")
            self.library_kind("experiment")
            self.library_open("experiment", self.exp_id)
            page.locator("#library-open").click()
            page.wait_for_selector(f'[id="exp-{self.exp_id}"].selected', timeout=60_000)
            self.open_library()
            self.library_kind("study")
            self.library_open("study", self.study_id)
            page.locator("#library-open").click()
            page.wait_for_selector(f'[id="study-row-{self.study_id}"].selected', timeout=60_000)
            assert self.js(f"!!document.querySelector('[id=\"exp-{self.exp_id}\"].selected')")
            return (
                f"optimization {self.opt_job_id[:8]}: 40 matrix cells and 40 rows, a pick enables Load; "
                f"walk-forward {self.wf_status['job_id'][:8]}: 6 windows, stitched and stability; "
                f"experiment {self.exp_id} and study {self.study_id} open selected on the Experiments page"
            )

        self.item(73, item73)

        def item74():
            a, b = self.identical_runs
            self.open_library()
            self.pair_filters()
            self.compare_ticked(a["run_id"], b["run_id"])
            notes = self.js("document.getElementById('compare-notes').innerText")
            assert "identical result" in notes and "same data" in notes, notes
            assert "Same strategy and settings." in self.js(
                "document.getElementById('compare-differences').innerText"
            )
            marks = self.js(
                "[...document.querySelectorAll('#compare-metrics-combined tbody tr')].map(r => r.cells[4].innerText)"
            )
            assert marks and all(m == "" for m in marks), marks
            page.locator("#compare-close").click()
            first, centre = self.lab_run, self.centre_run
            self.open_library()
            self.library_kind("backtest")
            self.library_select("library-strategy", self.lab["id"])
            self.compare_ticked(first["run_id"], centre["run_id"])
            expected = self.api(f"library/compare?a={first['run_id']}&b={centre['run_id']}")
            shown = self.js(
                "[...document.querySelectorAll('#compare-differences tbody tr')].map(r => [...r.cells].map(c => c.innerText))"
            )
            paths = [row[0] for row in shown]
            assert paths and paths == [d["path"] for d in expected["differences"]], (
                paths,
                expected,
            )
            surface = {p for p, *_ in EXPERIMENT_SURFACE}
            assert set(paths) <= surface, paths

            def at(envelope, path):
                side, _, ident, field = path.split(".")
                spec = next(i for i in envelope["strategy"][side]["indicators"] if i["id"] == ident)
                return spec[field]

            for path, a_text, b_text in shown:
                assert (json.loads(a_text), json.loads(b_text)) == (
                    at(first, path),
                    at(centre, path),
                ), path
            marks = self.js(
                "[...document.querySelectorAll('#compare-metrics-combined tbody tr')].map(r => r.cells[4].innerText)"
            )
            assert any("▲" in m or "▼" in m for m in marks), marks
            curves = self.js(
                "document.querySelectorAll('#compare-chart svg')[0].querySelectorAll('path').length"
            )
            assert curves == 2, curves
            unit = self.js("document.querySelector('#compare-unit .chip.active')?.innerText ?? ''")
            assert "%" in unit, unit
            page.locator("#compare-close").click()
            return (
                f"item 22's pair: {notes.strip()}; item 39 ({first['run_id'][:8]}) vs item 54 "
                f"({centre['run_id'][:8]}): "
                + ", ".join(f"{p} {x} → {y}" for p, x, y in shown)
                + f"; marks {sum(1 for m in marks if m)} of {len(marks)}; two curves on one axis in % return"
            )

        self.item(74, item74)

        def item75():
            checks = []

            def refused(response, needle, label):
                assert response.status == 409 and needle in response.text(), (
                    label,
                    response.status,
                    response.text()[:300],
                )
                checks.append(f"{label} → 409")

            body = {
                "strategy": self.api("strategy/default"),
                "data": {
                    "symbol": "QQQ",
                    "timeframe": "1h",
                    "start": "2024-01-01",
                    "end": "2024-03-31",
                },
                "settings": {"initial_capital": 100000, "allocation_fraction": 1},
            }
            created = self.post("backtest", body)
            assert created.ok, created.text()
            run = created.json()
            rid = run["run_id"]
            self.open_library()
            self.library_kind("backtest")
            self.library_open("backtest", rid)
            asked: list[str] = []

            def accept(dialog):
                asked.append(dialog.message)
                dialog.accept()

            page.on("dialog", accept)
            try:
                with page.expect_response(
                    lambda r: r.request.method == "DELETE" and f"/library/backtest/{rid}" in r.url,
                    timeout=30_000,
                ) as deleted:
                    page.locator("#library-delete").click()
            finally:
                page.remove_listener("dialog", accept)
            assert deleted.value.ok and asked and "Recently deleted" in asked[0], asked
            page.wait_for_selector(f'[id="lib-backtest-{rid}"]', state="detached", timeout=30_000)
            self.library_change(lambda: page.locator("#library-deleted").check())
            row = self.library_row("backtest", rid)
            assert "deleted" in row.inner_text(), row.inner_text()
            row.click()
            with page.expect_response(
                lambda r: r.url.endswith(f"/library/backtest/{rid}/restore"), timeout=30_000
            ) as restored:
                page.locator("#library-restore").click()
            assert restored.value.ok, restored.value.text()
            back = self.api(f"runs/{rid}")
            assert back["result_hash"] == run["result_hash"], (
                back["result_hash"],
                run["result_hash"],
            )
            checks.append(
                f"backtest {rid[:8]} deleted, listed in Recently deleted, restored with hash {run['result_hash'][:12]}"
            )
            refused(
                page.request.delete(self.base + f"api/library/experiment/{self.exp_id}"),
                "has studies",
                "the item-63 study's parent experiment",
            )
            # a running study: QQQ alone on the 252-cell experiment runs for about a minute (item 67's)
            running = self.post(
                "studies",
                {**self.study_body(), "symbols": ["QQQ"], "name": f"running {self.stamp}"},
            )
            assert running.status == 202, running.text()
            running_id = running.json()["study_id"]
            refused(
                page.request.delete(self.base + f"api/library/study/{running_id}"),
                "cancel it first",
                "a running study",
            )
            assert self.post(f"studies/{running_id}/cancel", {}).ok
            self.wait_study(running_id, ("cancelled", "done"), 900)
            assert page.request.delete(self.base + f"api/library/study/{running_id}").ok
            # a throwaway pair: a 9-cell experiment and a study of it, both finished in seconds
            started = self.post(
                "experiments",
                self.experiment_body(
                    THROWAWAY_SURFACE, objective="net_pnl", name=f"throwaway pair {self.stamp}"
                ),
            )
            assert started.status == 202, started.text()
            tid = started.json()["experiment_id"]
            assert self.wait_until(
                lambda: self.experiment(tid)["status"] in ("done", "failed", "cancelled"), 900, 1
            )
            assert self.experiment(tid)["status"] == "done", self.experiment(tid).get("error")
            study = self.post(
                "studies",
                {
                    **self.study_body(),
                    "experiment_id": tid,
                    "symbols": ["QQQ"],
                    "name": f"throwaway study {self.stamp}",
                },
            )
            assert study.status == 202, study.text()
            sid = study.json()["study_id"]
            self.wait_study(sid, ("done", "failed", "cancelled"), 900)
            assert page.request.delete(self.base + f"api/library/study/{sid}").ok
            assert page.request.delete(self.base + f"api/library/experiment/{tid}").ok
            refused(
                self.post(f"library/study/{sid}/restore", {}),
                "restored first",
                "a restore of a study whose parent is trashed",
            )
            assert self.post(f"library/experiment/{tid}/restore", {}).ok
            assert self.post(f"library/study/{sid}/restore", {}).ok
            assert page.request.delete(self.base + f"api/library/study/{sid}").ok
            assert page.request.delete(self.base + f"api/library/experiment/{tid}").ok
            self.throwaway = {"run": rid, "experiment": tid, "study": sid, "running": running_id}
            return (
                "; ".join(checks)
                + f"; the throwaway pair {tid} / {sid} restored in order, then left in Recently deleted"
            )

        self.item(75, item75)

        def item76():
            import subprocess

            def git(*args) -> str:
                return subprocess.run(
                    ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
                ).stdout

            status = page.request.get("http://127.0.0.1:8000/aegis/api/status").json()
            assert status["mode"] == "human_directed" and status["exchange"] == "CLOSED", status
            schedule = page.request.get("http://127.0.0.1:8000/triad/api/daily-schedule").json()
            assert schedule["enabled"] is False and schedule["id"].startswith("c99fa831"), schedule
            paths = ["app/trading_core", "app/platform_host", "app/products/triad"]
            committed = git("diff", "--name-only", MISSION9_BASE, "HEAD", "--", *paths).strip()
            pending = git("status", "--porcelain", "--", *paths).strip()
            assert committed == "" and pending == "", (committed, pending)
            earlier = [r for r in self.results if r["item"] <= 69]
            failed = [r["item"] for r in earlier if r["status"] != "PASS"]
            assert len(earlier) == 69 and not failed, failed
            trash = {e["id"] for e in self.api("library?deleted=true&limit=200")["entries"]}
            throwaway = getattr(self, "throwaway", {})
            kept = {throwaway[k] for k in ("experiment", "study", "running") if k in throwaway}
            assert kept <= trash, (kept, trash)
            return (
                f"aegis {status['mode']} / {status['exchange']}; DailySchedule {schedule['id'][:8]} "
                f"enabled={schedule['enabled']}; no change under {', '.join(paths)} since {MISSION9_BASE}; "
                f"items 1–69 PASS; Recently deleted holds {len(trash)} item(s), never emptied"
            )

        self.item(76, item76)

    # -- the limits change: plumbing ------------------------------------------------------------
    def limits_body(self, ranges, timeframe="1h", start="2023-01-01", end="2024-12-31") -> dict:
        """The walk's breakout document with an EMA exit, so three parameters matter on one side."""
        spec = self.api(f"strategies/{self.lab['id']}")["spec"]
        side = spec["long_side"]
        side["indicators"] = [i for i in side["indicators"] if i["id"] != "ema"] + [
            {"id": "ema", "kind": "EMA", "length": 50, "source": "close", "overlay": True}
        ]
        side["exit"] = {
            "left": "price.close",
            "operator": "crosses_below",
            "right": "ema",
            "timing": "bar_close",
        }
        side["optimization"] = [
            {"path": p, "enabled": True, "start": a, "stop": b, "step": s} for p, a, b, s in ranges
        ]
        spec["name"] = f"limits {self.stamp}"
        return {
            "strategy": spec,
            "side": "long",
            "data": {"symbol": "QQQ", "timeframe": timeframe, "start": start, "end": end},
            "objective": "mar",
        }

    def run_optimization(self, body: dict, timeout: float = 900) -> dict:
        started = self.post("optimize", body)
        assert started.status == 202, started.text()
        job_id = started.json()["job_id"]
        assert self.wait_until(
            lambda: self.api(f"optimize/{job_id}")["status"] in ("done", "failed", "cancelled"),
            timeout,
            1,
        )
        job = self.api(f"optimize/{job_id}")
        assert job["status"] == "done", job.get("error")
        return job

    def heat_cells(self) -> int:
        return self.js("document.querySelectorAll('#library-view .heat-grid .cell:not(.h)').length")

    # -- the limits change: items 77-81 -------------------------------------------------------------
    def limits(self):
        page = self.page

        def item77():
            page.locator("#nav-charts").click()
            page.wait_for_selector("#chart-mount", timeout=30_000)
            self.select("Symbol", "QQQ")
            page.get_by_label("Start date").fill(STUDY_RANGE[0])
            page.get_by_label("End date").fill(STUDY_RANGE[1])
            self.select("Timeframe", "15m")
            page.wait_for_function(
                "(document.querySelector('.chart-header')?.innerText ?? '').startsWith('QQQ · 15m')"
            )
            started = time.perf_counter()
            page.wait_for_function(
                f"(document.querySelector('.chart-header .ohlc')?.innerText ?? '').includes('{STUDY_RANGE[0]}')",
                timeout=180_000,
            )
            bars = self.wait_bars(timeout=180_000)
            chart_s = round(time.perf_counter() - started, 1)
            assert 50_000 < bars <= 2_000_000, bars  # Mission 10: the cap is a memory guard
            # A 26 MB envelope is more than the browser's inspector keeps, so the run is read back
            # from the worker rather than from the page's response.
            previous = self.run_state()
            page.locator("#run-backtest").click()
            page.wait_for_function(
                "(s => s.startsWith('run ') && s !== "
                + json.dumps(previous)
                + ")(document.getElementById('run-state')?.innerText ?? '')",
                timeout=600_000,
            )
            prefix = self.run_state().split()[1]
            run_id = next(r["run_id"] for r in self.api("runs") if r["run_id"].startswith(prefix))
            envelope = self.api(f"runs/{run_id}")
            self.hashes.append(envelope["result_hash"])
            assert envelope["data"]["bar_count"] == bars, (envelope["data"].get("bar_count"), bars)
            assert envelope["data"]["start"] == STUDY_RANGE[0] and envelope["markers"], envelope[
                "data"
            ]
            self.timings["ten_year_15m"] = {
                "bars": bars,
                "chart_s": chart_s,
                "backtest_server_ms": envelope["elapsed_ms"],
            }
            return (
                f"QQQ 15m {STUDY_RANGE[0]} → {STUDY_RANGE[1]}: {bars:,} bars charted in {chart_s} s "
                f"(the old cap was 50,000); run {envelope['run_id'][:8]} in {envelope['elapsed_ms']} ms, "
                f"{envelope['result']['combined']['metrics']['trade_count']} trades, "
                f"{len(envelope['markers'])} markers"
            )

        self.item(77, item77)

        def item78():
            body = self.limits_body(THREE_PARAMETERS)
            planned = self.post("optimize/plan", body).json()
            assert planned["total_cells"] == 560 and planned["pooled"] is True, planned
            started = time.perf_counter()
            job = self.run_optimization(body)
            seconds = round(time.perf_counter() - started, 1)
            assert job["cells_done"] == 560 and job["pooled"] is True, job.get("cells_done")
            self.open_library()
            self.library_kind("optimization")
            self.library_open("optimization", job["job_id"])
            page.wait_for_function(
                "document.querySelectorAll('#library-view .heat-grid .cell:not(.h)').length === 28",
                timeout=60_000,
            )
            page.locator("#matrix-cols-long").select_option("indicators.ema.length")
            page.wait_for_function(
                "document.querySelectorAll('#library-view .heat-grid .cell:not(.h)').length === 140",
                timeout=60_000,
            )
            rows, cols = "indicators.donchian.length", "indicators.ema.length"
            matrix = self.api(f"optimize/{job['job_id']}/matrix?rows={rows}&cols={cols}")
            values = matrix["metrics"]["mar"]["values"]
            r, c = max(
                ((r, c) for r in range(len(values)) for c in range(len(values[r]))),
                key=lambda rc: values[rc[0]][rc[1]] if values[rc[0]][rc[1]] is not None else -1e9,
            )
            best = matrix["cells"][matrix["metrics"]["mar"]["cells"][r][c]]
            square = page.locator("#library-view .heat-grid .cell:not(.h)").nth(
                r * len(matrix["cols"]) + c
            )
            title = square.get_attribute("title") or ""
            assert f"best of {matrix['counts'][r][c]}" in title and "MAR" in title, title
            square.click()
            page.wait_for_function("!document.getElementById('library-load').disabled")
            asked: list[str] = []

            def accept(dialog):
                asked.append(dialog.message)
                dialog.accept()

            page.on("dialog", accept)
            try:
                page.locator("#library-load").click()
                page.wait_for_selector("#chart-mount", timeout=30_000)
            finally:
                page.remove_listener("dialog", accept)
            self.wait_bars()
            envelope = self.run_backtest()
            long_side = envelope["strategy"]["long_side"]
            lengths = {f"indicators.{i['id']}.length": i["length"] for i in long_side["indicators"]}
            assert all(lengths[p] == v for p, v in best["params"].items()), (
                lengths,
                best["params"],
            )
            ran = envelope["result"]["long"]["metrics"]["mar"]
            assert abs(ran - best["metrics"]["mar"]) < 1e-9, (ran, best["metrics"]["mar"])
            self.limits_job = job["job_id"]
            return (
                f"560 cells planned on the pool ({planned['workers']} workers, ≈ "
                f"{planned['estimated_seconds']:.1f} s) and run in {seconds} s; matrix Donchian × RSI "
                f"(28 squares), switched to Donchian × EMA (140); '{title.split(' · ')[-1]}'; the best "
                f"square loaded {best['params']} and its backtest's long MAR {ran:.4f} equals the cell's"
            )

        self.item(78, item78)

        def item79():
            body = self.limits_body(PAGED_PARAMETERS)
            started = time.perf_counter()
            job = self.run_optimization(body)
            seconds = round(time.perf_counter() - started, 1)
            assert (job["cells_done"], job["cells_shown"], len(job["cells"])) == (2560, 1000, 1000)
            mars = [cell["metrics"]["mar"] for cell in job["cells"]]
            defined = [m for m in mars if m is not None]
            assert defined == sorted(defined, reverse=True), "the best 1,000 are not in MAR order"
            rest = self.api(f"optimize/{job['job_id']}/cells?offset=1000&limit=1000")
            assert rest["total"] == 2560 and len(rest["rows"]) == 1000
            assert (rest["rows"][0]["metrics"]["mar"] or -1e9) <= defined[-1]
            saved = json.loads(
                (ROOT / "data" / "aegis" / "optimizations" / f"{job['job_id']}.json").read_text(
                    encoding="utf-8"
                )
            )
            assert len(saved["cells"]) == 2560
            self.open_library()
            self.library_kind("optimization")
            self.library_open("optimization", job["job_id"])
            page.wait_for_function(
                "(document.getElementById('optimization-cells-pages-long')?.innerText ?? '').includes('the best 1,000 of 2,560')",
                timeout=60_000,
            )
            page.locator("#optimization-cells-next-long").click()
            page.wait_for_function(
                "(document.getElementById('optimization-cells-pages-long')?.innerText ?? '').includes('1,001–2,000')",
                timeout=60_000,
            )
            page.wait_for_function(  # the next page arrives after its label changes
                "document.querySelectorAll('#library-view #optimization-cells-long tbody tr').length === 1000",
                timeout=60_000,
            )
            return (
                f"2,560 cells in {seconds} s; the status sends the best 1,000 in MAR order, the next "
                "page continues below them, the saved job keeps all 2,560; the table reads 'the best "
                "1,000 of 2,560' and pages to 1,001–2,000"
            )

        self.item(79, item79)

        def item80():
            checks = []
            bars = page.request.get(
                self.base
                + f"api/data/bars?symbol=QQQ&timeframe=1m&start={STUDY_RANGE[0]}&end={STUDY_RANGE[1]}"
                + "&max_bars=20000"
            )
            assert bars.ok and bars.json()["count"] == TEN_YEARS_1M, bars.text()[:200]
            checks.append(f"ten years of 1m now select: {TEN_YEARS_1M:,} bars")
            huge = self.limits_body(
                [
                    ("indicators.donchian.length", 2, 401, 1),
                    ("indicators.rsi.length", 2, 301, 1),
                    ("indicators.ema.length", 10, 11, 1),
                ]
            )
            refused = self.post("optimize/plan", huge)
            assert refused.status == 422 and "over cap 100000" in refused.text(), refused.text()[
                :200
            ]
            assert "experiment" in refused.text()
            checks.append("240,000 cells → 422 over cap 100000, pointing to an experiment")
            body = self.limits_body(QUESTION_PARAMETERS, "15m", *STUDY_RANGE)
            planned = self.post("optimize/plan", body).json()
            assert planned["estimated_seconds"] > 600, planned
            # the page: the same plan from the workspace asks before it starts
            page.locator("#nav-charts").click()
            page.wait_for_selector("#chart-mount", timeout=30_000)
            page.get_by_label("Start date").fill(STUDY_RANGE[0])
            page.get_by_label("End date").fill(STUDY_RANGE[1])
            self.select("Timeframe", "15m")
            self.wait_bars(timeout=180_000)
            for path, start, stop, step in QUESTION_PARAMETERS:
                for field, value in (("start", start), ("stop", stop), ("step", step)):
                    page.get_by_label(f"long {path} {field}").fill(str(value))
            before = self.api("optimize")[0]["job_id"]
            if not self.js("!!document.querySelector('.popover')"):
                page.locator("#optimize").click()
            page.locator("#grid-mode").click()
            page.wait_for_function(
                "/on the pool/.test(document.getElementById('optimize-plan')?.innerText ?? '')",
                timeout=120_000,
            )
            line = self.js("document.getElementById('optimize-plan').innerText")
            asked: list[str] = []

            def dismiss(dialog):
                asked.append(dialog.message)
                dialog.dismiss()

            page.on("dialog", dismiss)
            try:
                page.locator("#start-optimization").click()
                page.wait_for_timeout(1500)
            finally:
                page.remove_listener("dialog", dismiss)
            assert asked and "Start it?" in asked[0] and "cells" in asked[0], asked
            assert self.api("optimize")[0]["job_id"] == before, "a job started anyway"
            if self.js("!!document.querySelector('.popover')"):
                page.locator(".popover .actions button", has_text="Close").click()
            checks.append(
                f"plan '{line.strip()}' asked '{asked[0]}' and, dismissed, started nothing"
            )
            return "; ".join(checks)

        self.item(80, item80)

        def item81():
            import subprocess

            def git(*args) -> str:
                return subprocess.run(
                    ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
                ).stdout

            status = page.request.get("http://127.0.0.1:8000/aegis/api/status").json()
            assert status["mode"] == "human_directed" and status["exchange"] == "CLOSED", status
            schedule = page.request.get("http://127.0.0.1:8000/triad/api/daily-schedule").json()
            assert schedule["enabled"] is False and schedule["id"].startswith("c99fa831"), schedule
            paths = ["app/trading_core", "app/platform_host", "app/products/triad"]
            committed = git("diff", "--name-only", LIMITS_BASE, "HEAD", "--", *paths).strip()
            pending = git("status", "--porcelain", "--", *paths).strip()
            assert committed == "" and pending == "", (committed, pending)
            earlier = [r for r in self.results if r["item"] <= 76]
            failed = [r["item"] for r in earlier if r["status"] != "PASS"]
            assert len(earlier) == 76 and not failed, failed
            return (
                f"aegis {status['mode']} / {status['exchange']}; DailySchedule {schedule['id'][:8]} "
                f"enabled={schedule['enabled']}; no change under {', '.join(paths)} since "
                f"{LIMITS_BASE}; items 1–76 PASS"
            )

        self.item(81, item81)

    # -- Mission 10 plumbing: no limit -------------------------------------------------------------
    def worker_memory(self) -> dict:
        """The worker's working set now and at its peak, from the OS (PowerShell Get-Process)."""
        import subprocess

        script = (
            "$c = Get-NetTCPConnection -LocalPort 8102 -State Listen | Select-Object -First 1; "
            "Get-Process -Id $c.OwningProcess | Select-Object Id, WorkingSet64, PeakWorkingSet64 "
            "| ConvertTo-Json -Compress"
        )
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
        info = json.loads(out)
        return {
            "pid": info["Id"],
            "working_set_mb": round(info["WorkingSet64"] / 1e6),
            "peak_working_set_mb": round(info["PeakWorkingSet64"] / 1e6),
        }

    def run_file(self, run_id: str) -> Path:
        return ROOT / "data" / "aegis" / "runs" / f"{run_id}.json"

    def library_equity(self) -> str:
        self.page.locator("#library-tab-equity").click()
        self.page.wait_for_selector("#library-view svg[aria-label='equity curve']", timeout=30_000)
        return self.js("document.querySelector('#library-view .result-body')?.innerText ?? ''")

    def chart_badge(self) -> str:
        """The header's "shown as" badge ('' for native candles), read with the mouse off the chart:
        over it the crosshair readout replaces the header (QA O1)."""
        self.page.mouse.move(5, 5)
        self.page.wait_for_timeout(300)
        return self.js("document.getElementById('chart-shown-as')?.innerText ?? ''")

    def wheel_until(self, delta: int, done, batches: int = 15) -> bool:
        """Wheel over the chart in batches of four notches until `done()` holds."""
        box = self.page.locator("#chart-mount").bounding_box()
        for _ in range(batches):
            self.page.mouse.move(box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.4)
            for _ in range(4):
                self.page.mouse.wheel(0, delta)
                self.page.wait_for_timeout(120)
            self.page.wait_for_timeout(1200)
            if done():
                return True
        return False

    # -- Mission 10 items 82-86 ---------------------------------------------------------------------
    def no_limit(self):
        page = self.page

        def item82():
            a = self.identical_runs[0]
            path = self.run_file(a["run_id"])
            stored = json.loads(path.read_text(encoding="utf-8"))
            size = path.stat().st_size
            sides = ("long", "short")
            assert "series" not in stored and all(
                "series" not in stored["result"][x] for x in sides
            )
            assert stored["stored"]["format"] == 2, stored.get("stored")
            points = {x: len(stored["result"][x]["equity"]) for x in sides}
            assert all(n <= 2_000 for n in points.values()), points
            assert size < 1_000_000, size
            assert stored["result_hash"] == RECORDED_IDENTICAL_HASH, stored["result_hash"]
            # The Library lists 50 rows a page, newest first: narrow to item 22's pair first.
            self.open_library()
            self.pair_filters()
            self.library_open("backtest", a["run_id"])
            slim = self.library_equity()
            per_bar = stored["stored"]["equity_points"]["long"]
            assert f"drawn from 2,000 of {per_bar:,} points" in slim, slim
            runs = self.api("runs")
            named = {}
            for r in runs:
                name = (r.get("strategy") or {}).get("name")
                named[name] = named.get(name, 0) + 1
            older = [
                r
                for r in runs
                if r.get("created_at", "") < MISSION10_STARTED
                and (r.get("data") or {}).get("timeframe") == "1h"
                and r.get("kept") is not False
                and (r.get("strategy") or {}).get("name")
            ]
            assert older, "no run saved before Mission 10 to open"
            # the one whose strategy has the fewest runs, found by searching that strategy's name
            old = min(older, key=lambda r: named[r["strategy"]["name"]])
            old_envelope = self.api(f"runs/{old['run_id']}")
            assert "stored" not in old_envelope and "series" in old_envelope, sorted(old_envelope)
            full = len(old_envelope["result"]["long"]["equity"])
            self.open_library()
            self.library_kind("backtest")
            self.library_search(old["strategy"]["name"])
            self.library_open("backtest", old["run_id"])
            shown = self.library_equity()
            assert f"long ({full})" in shown and "drawn from" not in shown, shown
            return (
                f"item 22's run {a['run_id'][:8]}: {size:,} bytes, format 2, side equity {points} "
                f"of {per_bar:,} bars, hash {stored['result_hash'][:12]}… unchanged; format-1 run "
                f"{old['run_id'][:8]} ({old['created_at'][:16]}) opens with its {full:,}-point equity"
            )

        self.item(82, item82)

        def item83():
            page.locator("#nav-charts").click()
            page.wait_for_selector("#chart-mount", timeout=30_000)
            self.select("Symbol", "QQQ")
            page.get_by_label("Start date").fill(STUDY_RANGE[0])
            page.get_by_label("End date").fill(STUDY_RANGE[1])
            self.select("Timeframe", "1m")
            page.wait_for_function(
                "(document.querySelector('.chart-header')?.innerText ?? '').startsWith('QQQ · 1m')"
            )
            started = time.perf_counter()
            page.wait_for_function(
                f"(document.querySelector('.chart-header .ohlc')?.innerText ?? '').includes('{STUDY_RANGE[0]}')",
                timeout=180_000,
            )
            bars = self.wait_bars(timeout=180_000)
            chart_s = round(time.perf_counter() - started, 1)
            assert bars == TEN_YEARS_1M, bars
            first = self.chart_badge()
            assert first.startswith("shown as "), first
            query = f"symbol=QQQ&timeframe=1m&start={STUDY_RANGE[0]}&end={STUDY_RANGE[1]}&max_bars=20000"
            view = self.api("data/bars?" + query)
            assert view["count"] == bars and view["shown"] <= 20_000, (view["count"], view["shown"])
            assert view["display_timeframe"] in first, (view["display_timeframe"], first)
            series = self.post(
                "indicators",
                {
                    "symbol": "QQQ",
                    "timeframe": "1m",
                    "start": STUDY_RANGE[0],
                    "end": STUDY_RANGE[1],
                    "indicators": [
                        {"id": "ema", "kind": "EMA", "length": 9},
                        {"id": "sma", "kind": "SMA", "length": 30},
                    ],
                    "max_bars": 20_000,
                },
            ).json()
            candles = [b["time"] for b in view["bars"]]
            assert series["times"] == candles and len(series["series"]["ema"]) == len(candles)
            # The zoom is read from the worker's answers, not only the badge (QA O1): a wheel-in
            # must bring native 1m candles, a wheel-out back to aggregated ones (QA D1).
            answers: list[str] = []

            def on_bars(response):
                if "/aegis/api/data/bars?" in response.url and "from_ms=" in response.url:
                    try:
                        answers.append(response.json()["display_timeframe"])
                    except Exception:  # noqa: BLE001, S110 - a body still streaming is skipped
                        pass

            page.on("response", on_bars)
            try:
                assert self.wheel_until(-400, lambda: "1m" in answers and self.chart_badge() == "")
                zoomed = f"native 1m candles (answers {answers})"
                del answers[:]
                assert self.wheel_until(400, lambda: self.chart_badge().startswith("shown as")), (
                    answers
                )
                unzoomed = f"{self.chart_badge()} (answers {answers})"
            finally:
                page.remove_listener("response", on_bars)
            before = self.worker_memory()
            previous = self.run_state()
            ran = time.perf_counter()
            page.locator("#run-backtest").click()
            page.wait_for_function(
                "(s => s.startsWith('run ') && s !== "
                + json.dumps(previous)
                + ")(document.getElementById('run-state')?.innerText ?? '')",
                timeout=900_000,
            )
            wall_s = round(time.perf_counter() - ran, 1)
            after = self.worker_memory()
            prefix = self.run_state().split()[1]
            run_id = next(r["run_id"] for r in self.api("runs") if r["run_id"].startswith(prefix))
            envelope = self.api(f"runs/{run_id}")
            self.hashes.append(envelope["result_hash"])
            assert envelope["data"]["bar_count"] == bars and envelope["saved"] is True
            markers = len(envelope["markers"])
            legend = self.js("document.querySelector('.chart-header .legend')?.innerText ?? ''")
            assert f"{markers} markers" in legend, legend
            size = self.run_file(run_id).stat().st_size
            self.ten_year_run = envelope
            self.timings["ten_year_1m"] = {
                "bars": bars,
                "chart_s": chart_s,
                "shown": view["shown"],
                "display_timeframe": view["display_timeframe"],
                "zoomed": zoomed,
                "unzoomed": unzoomed,
                "backtest_server_ms": envelope["elapsed_ms"],
                "backtest_wall_s": wall_s,
                "run_file_bytes": size,
                "markers": markers,
                "worker_before": before,
                "worker_after": after,
            }
            return (
                f"QQQ 1m {STUDY_RANGE[0]} → {STUDY_RANGE[1]}: {bars:,} bars in {chart_s} s, "
                f"{first} ({view['shown']:,} candles); zoom in → {zoomed}; out → {unzoomed}; "
                f"indicators on the same "
                f"{len(candles):,} candles; run {run_id[:8]} in {envelope['elapsed_ms']:,} ms server / "
                f"{wall_s} s wall, {markers:,} markers in the legend, file {size / 1e6:.1f} MB; worker "
                f"working set {before['working_set_mb']:,} → {after['working_set_mb']:,} MB, peak "
                f"{before['peak_working_set_mb']:,} → {after['peak_working_set_mb']:,} MB"
            )

        self.item(83, item83)

        def item84():
            run, b = self.ten_year_run, self.identical_runs[1]
            self.open_library()
            self.library_open("backtest", run["run_id"])
            page.wait_for_function(
                "/947,519 bars/.test(document.querySelector('#library-chart .chart-header')?.innerText ?? '')",
                timeout=180_000,
            )
            header = self.js("document.querySelector('#library-chart .chart-header').innerText")
            assert "shown as" in header, header
            star = page.locator(f'[id="lib-star-backtest-{run["run_id"]}"]')
            if star.get_attribute("aria-pressed") != "true":
                with page.expect_response(
                    lambda r: r.url.endswith("/annotation"), timeout=30_000
                ) as starred:
                    star.click()
                assert starred.value.ok, starred.value.text()
            try:
                self.open_library()
                self.library_kind("backtest")
                self.library_change(lambda: page.locator("#library-starred").check())
                self.compare_ticked(run["run_id"], b["run_id"])
                notes = self.js("document.getElementById('compare-notes').innerText")
                curves = self.js(
                    "document.querySelectorAll('#compare-chart svg')[0].querySelectorAll('path').length"
                )
                assert curves == 2, curves
                page.locator("#compare-close").click()
            finally:
                self.open_library()
                self.library_kind("backtest")
                unstar = page.locator(f'[id="lib-star-backtest-{run["run_id"]}"]')
                if unstar.count() and unstar.get_attribute("aria-pressed") == "true":
                    with page.expect_response(
                        lambda r: r.url.endswith("/annotation"), timeout=30_000
                    ):
                        unstar.click()
            return (
                f"run {run['run_id'][:8]} opens in the Library ('{header.splitlines()[-1].strip()}'); "
                f"compared with item 22's run {b['run_id'][:8]}: {notes.strip()[:160]}; 2 curves"
            )

        self.item(84, item84)

        def item85():
            page.locator("#nav-charts").click()
            page.wait_for_selector("#chart-mount", timeout=30_000)
            page.get_by_label("Start date").fill("2023-01-01")
            page.get_by_label("End date").fill("2024-12-31")
            self.select("Timeframe", "1h")
            page.wait_for_function(
                "(document.querySelector('.chart-header')?.innerText ?? '').startsWith('QQQ · 1h')"
                " && (document.querySelector('.chart-header')?.innerText ?? '').includes('2023-01-01 → 2024-12-31')",
                timeout=90_000,
            )
            self.wait_bars()
            try:
                page.locator("#save-mode").select_option("kept")
                assert self.wait_until(lambda: self.api("preferences")["save_runs"] == "kept", 10)
                envelope = self.run_backtest()
                run_id = envelope["run_id"]
                assert envelope["saved"] is False, envelope.get("saved")
                assert "NOT KEPT" in self.run_state(), self.run_state()
                listed = [r for r in self.api("runs") if r["run_id"] == run_id]
                assert listed and listed[0].get("kept") is False, listed

                def in_library() -> bool:
                    entries = self.api("library?kind=backtest")["entries"]
                    return run_id in [e["id"] for e in entries]

                assert not in_library()
                with page.expect_response(
                    lambda r: r.url.endswith("/keep"), timeout=30_000
                ) as kept:
                    page.locator("#keep-run").click()
                assert kept.value.ok and kept.value.json() == {"saved": run_id}, kept.value.text()
                assert self.wait_until(in_library, 10), "kept run not in the Library"
                assert "NOT KEPT" not in self.run_state(), self.run_state()
            finally:
                page.locator("#save-mode").select_option("every")
                assert self.wait_until(lambda: self.api("preferences")["save_runs"] == "every", 10)
            return (
                f"in 'Save only what I keep' run {run_id[:8]} answered saved=false, listed kept=false "
                "and stayed out of the Library; Keep saved it and the Library lists it; the mode is "
                "back to 'Save every backtest'"
            )

        self.item(85, item85)

        def item86():
            import subprocess

            def git(*args) -> str:
                return subprocess.run(
                    ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
                ).stdout

            status = page.request.get("http://127.0.0.1:8000/aegis/api/status").json()
            assert status["mode"] == "human_directed" and status["exchange"] == "CLOSED", status
            schedule = page.request.get("http://127.0.0.1:8000/triad/api/daily-schedule").json()
            assert schedule["enabled"] is False and schedule["id"].startswith("c99fa831"), schedule
            paths = ["app/trading_core", "app/platform_host", "app/products/triad"]
            committed = git("diff", "--name-only", NO_LIMIT_BASE, "HEAD", "--", *paths).strip()
            pending = git("status", "--porcelain", "--", *paths).strip()
            assert committed == "" and pending == "", (committed, pending)
            earlier = [r for r in self.results if r["item"] <= 81]
            failed = [r["item"] for r in earlier if r["status"] != "PASS"]
            assert len(earlier) == 81 and not failed, failed
            return (
                f"aegis {status['mode']} / {status['exchange']}; DailySchedule {schedule['id'][:8]} "
                f"enabled={schedule['enabled']}; no change under {', '.join(paths)} since "
                f"{NO_LIMIT_BASE}; items 1–81 PASS"
            )

        self.item(86, item86)


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
        "experiment_id": getattr(acceptance, "exp_id", None),
        "refined_experiment_id": getattr(acceptance, "child_id", None),
        "study_id": getattr(acceptance, "study_id", None),
        "identical_study_id": getattr(acceptance, "twin_id", None),
        "library_throwaway": getattr(acceptance, "throwaway", None),
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
