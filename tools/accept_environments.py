"""Mission 7 acceptance (spec §2, plan Task 5): one Core codebase and runtime, three dependency
environments, each worker on its own interpreter, and no pytest run that can show a misleading
partial green. Run from Core's environment:

    .venv\\Scripts\\python.exe tools\\accept_environments.py

Writes logs/environments-acceptance-<stamp>.json with PASS/FAIL and the evidence per item.
Items that need Core (8000) check it first and fail with the reason instead of acting: the
supervisor item never stops a worker it could not bring back.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MISSION7_BASE = "9fb3d2f"  # the plan commit; Core, the platform host and both products frozen since
ENVIRONMENTS = {"core": ".venv", "triad": ".venv-triad", "aegis": ".venv-aegis"}
PORTS = {"triad": 8101, "aegis": 8102}
PROTECTED = ["app/trading_core", "app/platform_host", "app/products/triad", "app/products/aegis"]
GREEN = "all three scopes green"


def python(scope: str) -> Path:
    return ROOT / ENVIRONMENTS[scope] / "Scripts" / "python.exe"


def run(args, env=None, timeout=600, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(a) for a in args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        **kwargs,
    )


def scoped(scope: str | None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TRIAD_PYTEST_")}
    if scope:
        env["TRIAD_PYTEST_SCOPE"] = scope
    return env


def powershell(command: str, timeout=120) -> subprocess.CompletedProcess:
    return run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], None, timeout)


def get(url: str, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read() or b"null")


def core_up() -> bool:
    try:
        return get("http://127.0.0.1:8000/health/live").get("status") == "ok"
    except Exception:  # noqa: BLE001 - down is an answer
        return False


def listener(port: int) -> int | None:
    out = powershell(
        f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue"
        " | Select-Object -First 1).OwningProcess"
    ).stdout.strip()
    return int(out) if out.isdigit() else None


def process_evidence(pid: int) -> dict:
    """The listener's parent (the environment's launcher stub) and the site-packages roots of the
    extension modules the listener has loaded (spec §2 item 3, Task 3 ruling)."""
    script = (
        f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; "
        '$parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($p.ParentProcessId)"; '
        f"$mods = (Get-Process -Id {pid}).Modules | ForEach-Object {{ $_.FileName }}; "
        "[ordered]@{ executable = $p.ExecutablePath; parent = $parent.ExecutablePath; "
        "modules = @($mods) } | ConvertTo-Json -Depth 3 -Compress"
    )
    data = json.loads(powershell(script).stdout)
    roots = sorted(
        {m.split("\\Lib\\site-packages")[0] for m in data["modules"] if "site-packages" in m}
    )
    llvmlite = any("llvmlite" in m.lower() for m in data["modules"])
    return {
        "executable": data["executable"],
        "parent": data["parent"],
        "roots": roots,
        "llvmlite": llvmlite,
    }


def wait_for_listener(port: int, old: int | None, seconds=90) -> int:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pid = listener(port)
        if pid is not None and pid != old:
            try:
                if get(f"http://127.0.0.1:{port}/health/live", timeout=3).get("status") == "ok":
                    return pid
            except Exception:  # noqa: BLE001, S110 - still starting
                pass
        time.sleep(1)
    raise AssertionError(f"no healthy new listener on {port} within {seconds} s (was {old})")


def assert_environment(product: str, evidence: dict) -> None:
    expected = str(python(product)).lower()
    assert (evidence["parent"] or "").lower() == expected, (evidence["parent"], expected)
    assert evidence["roots"] == [str(ROOT / ENVIRONMENTS[product])], evidence["roots"]
    assert evidence["llvmlite"] is (product == "aegis"), evidence["llvmlite"]


class Acceptance:
    def __init__(self, stamp: str):
        self.stamp = stamp
        self.results: list[dict] = []

    def item(self, number: int, title: str, check) -> None:
        started = time.perf_counter()
        try:
            detail, status = check(), "PASS"
        except Exception as exc:  # noqa: BLE001 - every item is reported, never hidden
            detail, status = f"{type(exc).__name__}: {exc}", "FAIL"
        ms = int((time.perf_counter() - started) * 1000)
        self.results.append(
            {"item": number, "title": title, "status": status, "detail": detail, "ms": ms}
        )
        print(f"[{status}] {number:>2}. {title} -- {detail}", flush=True)

    # -- items ------------------------------------------------------------------------------
    def environments(self):
        notes = []
        for scope in ENVIRONMENTS:
            assert python(scope).is_file(), f"missing {python(scope)}"
            check = run([python(scope), "-m", "pip", "check"])
            assert check.returncode == 0, (scope, check.stdout, check.stderr)
            lock = powershell(
                f"& '{ROOT / 'tools' / 'lock.ps1'}' -Product {scope} -Check; exit $LASTEXITCODE"
            )
            assert lock.returncode == 0, (scope, lock.stdout, lock.stderr)
            notes.append(lock.stdout.strip())
        return "; ".join(notes) + "; pip check clean in all three"

    def import_probes(self):
        probe = "import importlib.util as u, sys; s = u.find_spec('numba'); print(s is not None)"
        seen = {}
        for scope in ENVIRONMENTS:
            seen[scope] = run([python(scope), "-c", probe]).stdout.strip()
        assert seen == {"core": "False", "triad": "False", "aegis": "True"}, seen
        version = run([python("aegis"), "-c", "import numba; print(numba.__version__)"])
        assert version.stdout.strip() == "0.68.0", version.stdout
        return f"numba importable: {seen}; .venv-aegis has numba {version.stdout.strip()}"

    def refusals(self):
        notes = []
        for scope, environment in ENVIRONMENTS.items():
            plain = run(
                [python(scope), "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                scoped(None),
            )
            assert plain.returncode == 4, (scope, plain.returncode, plain.stderr[-300:])
            assert "TRIAD_PYTEST_SCOPE is not set: no tests were run." in plain.stderr
            assert " passed" not in plain.stdout, plain.stdout[-300:]
            notes.append(f"bare pytest on {environment} -> exit 4")
        wrong = run(
            [python("core"), "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
            scoped("aegis"),
        )
        assert wrong.returncode == 4 and "it needs .venv-aegis" in wrong.stderr, wrong.stderr
        notes.append("scope aegis on .venv -> exit 4 'it needs .venv-aegis'")
        return "; ".join(notes)

    def inventory(self):
        collected = run(
            [python("core"), "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
            scoped("inventory"),
        )
        assert collected.returncode == 0, collected.stderr[-300:]
        line = re.search(r"^inventory: .*$", collected.stdout, re.MULTILINE).group(0)
        owned = {k: int(v) for k, v in re.findall(r"(core|triad|aegis) (\d+)", line)}
        total = int(re.search(r"total (\d+)", line).group(1))
        whole = int(re.search(r"(\d+) tests? collected", collected.stdout).group(1))
        assert sum(owned.values()) == total == whole, (owned, total, whole)
        for scope in ENVIRONMENTS:
            out = run(
                [python(scope), "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                scoped(scope),
            ).stdout
            selected, deselected = map(
                int, re.search(r"scope \w+: (\d+) selected; (\d+) deselected", out).groups()
            )
            assert selected == owned[scope] and selected + deselected == total, (scope, out[-200:])
        self.owned = owned
        return f"{line}; collected {whole}; each scope selects exactly what it owns"

    def verify(self, inject: bool = False):
        log = (
            ROOT
            / "logs"
            / f"environments-acceptance-{self.stamp}-verify{'-red' if inject else ''}.log"
        )
        injected = ROOT / "tests" / "test_zz_injected_failure.py"
        if inject:
            injected.write_text(
                "import pytest\n\npytestmark = pytest.mark.core\n\n\n"
                "def test_fails():\n    assert False, 'injected by the acceptance'\n",
                encoding="utf-8",
            )
        try:
            with log.open("w", encoding="utf-8", errors="replace") as out:
                code = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(ROOT / "tools" / "verify.ps1"),
                    ],
                    cwd=ROOT,
                    env=scoped(None),
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    timeout=3600,
                    check=False,
                ).returncode
        finally:
            if inject:
                injected.unlink(missing_ok=True)
        text = log.read_text(encoding="utf-8", errors="replace")
        last = [line for line in text.splitlines() if line.strip()][-1] if text.strip() else ""
        if inject:
            assert code != 0 and GREEN not in text, (code, last)
            assert "test_zz_injected_failure.py::test_fails" in text, last
            status = run(["git", "status", "--porcelain", "tests"]).stdout.strip()
            assert status == "", status
            return (
                f"one red module -> exit {code}, no '{GREEN}' line, module removed; log {log.name}"
            )
        assert code == 0 and last.endswith(GREEN), (code, last[-300:])
        return f"{last}; log {log.name}"

    def restarts(self):
        notes = []
        for product, port in PORTS.items():
            old = listener(port)
            powershell(
                "Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
                "@{CommandLine='powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden "
                f"-ExecutionPolicy Bypass -File {ROOT}\\tools\\start_product.ps1 -Product {product}'; "
                f"CurrentDirectory='{ROOT}'}} | Out-Null"
            )
            new = wait_for_listener(port, old)
            evidence = process_evidence(new)
            assert_environment(product, evidence)
            notes.append(
                f"{product}: listener {old} -> {new}, parent {evidence['parent']}, "
                f"site-packages {evidence['roots'][0]}, llvmlite {evidence['llvmlite']}"
            )
        return "; ".join(notes)

    def supervisor(self):
        if not core_up():
            raise AssertionError(
                "Core (8000) is not healthy, so the supervisor defers product recovery; no worker "
                "was stopped (Docker Desktop, which runs Core's databases, is down on this host)"
            )
        notes = []
        for product, port in PORTS.items():
            old = listener(port)
            stub = process_evidence(old)
            powershell(
                f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId = {old}'; "
                f"Stop-Process -Id {old} -Force; Stop-Process -Id $p.ParentProcessId -Force "
                "-ErrorAction SilentlyContinue"
            )
            deadline = time.monotonic() + 30
            while listener(port) is not None and time.monotonic() < deadline:
                time.sleep(1)
            recovered = run(
                [python("core"), ROOT / "tools" / "ensure_product_worker.py", "--product", product],
                timeout=180,
            )
            log = (ROOT / "logs" / f"{product}-supervisor.log").read_text(encoding="utf-8")
            event = json.loads(log.strip().splitlines()[-1])
            assert recovered.returncode == 0 and event["status"] == "RECOVERED", event
            new = wait_for_listener(port, old, seconds=30)
            evidence = process_evidence(new)
            assert_environment(product, evidence)
            notes.append(
                f"{product}: stopped {old} (parent {stub['parent']}), supervisor {event['status']}, "
                f"new listener {new} on {evidence['parent']}"
            )
        return "; ".join(notes)

    def governance(self):
        changed = run(["git", "diff", "--name-only", MISSION7_BASE, "HEAD", "--", *PROTECTED])
        pending = run(["git", "status", "--porcelain", "--", *PROTECTED])
        assert changed.stdout.strip() == "" and pending.stdout.strip() == "", (
            changed.stdout,
            pending.stdout,
        )
        notes = [f"no change under {', '.join(PROTECTED)} since {MISSION7_BASE}"]
        if not core_up():
            raise AssertionError(
                notes[0] + "; but Core (8000) is down, so the governance status and the schedule "
                "record cannot be read (Docker Desktop is down on this host)"
            )
        status = get("http://127.0.0.1:8000/aegis/api/status", timeout=30)
        schedule = get("http://127.0.0.1:8000/triad/api/daily-schedule", timeout=30)
        assert status["mode"] == "human_directed" and status["exchange"] == "CLOSED", status
        assert schedule["enabled"] is False and schedule["id"].startswith("c99fa831"), schedule
        notes.append(
            f"aegis {status['mode']} / {status['exchange']}, kernel {status.get('kernel_available')}; "
            f"DailySchedule {schedule['id'][:8]} enabled={schedule['enabled']}"
        )
        return "; ".join(notes)

    def triad_verification(self):
        result = run(
            [
                python("triad"),
                "-m",
                "pytest",
                "tests/test_readiness.py",
                "tests/test_day8_daily_ui_qa.py",
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            scoped("triad"),
        )
        summary = re.search(r"scope triad: (\d+) selected; (\d+) deselected", result.stdout)
        assert result.returncode == 0 and summary and summary.group(2) == "0", result.stdout[-400:]
        return (
            f"Triad's trusted post-merge command under the Triad scope: {summary.group(1)} selected, "
            "0 deselected, passed"
        )

    def browser(self):
        if not core_up():
            raise AssertionError(
                "Core (8000) is down; the Mission 6 walk reads the gateway (items 23, 36, 47, 60), "
                "so it was not started (Docker Desktop is down on this host)"
            )
        result = run(
            [python("core"), ROOT / "tests" / "products" / "aegis" / "browser_workstation.py"],
            timeout=1800,
        )
        tail = [line for line in result.stdout.splitlines() if "PASS," in line]
        assert result.returncode == 0 and tail and tail[-1].startswith("60/60 PASS"), tail
        return tail[-1]

    def run(self):
        self.item(
            1, "three environments built from their locks, pip check clean", self.environments
        )
        self.item(2, "numba only in .venv-aegis", self.import_probes)
        self.item(3, "a bare or mismatched pytest refuses before running anything", self.refusals)
        self.item(
            4, "every collected test owned; each scope selects exactly its own", self.inventory
        )
        self.item(5, "tools\\verify.ps1 green across the three scopes", self.verify)
        self.item(6, "both workers relaunched on their own interpreters", self.restarts)
        self.item(
            7, "the supervisor's recovery path relaunches each on its interpreter", self.supervisor
        )
        self.item(8, "one red scope cannot end green (Review Focus 5)", lambda: self.verify(True))
        self.item(9, "governance and the frozen trees", self.governance)
        self.item(10, "the Mission 6 browser acceptance on .venv-aegis", self.browser)
        self.item(
            11, "Triad's trusted verification runs whole under its scope", self.triad_verification
        )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (ROOT / "logs").mkdir(exist_ok=True)
    started = time.perf_counter()
    acceptance = Acceptance(stamp)
    acceptance.run()
    passed = sum(r["status"] == "PASS" for r in acceptance.results)
    report = {
        "stamp": stamp,
        "total_ms": int((time.perf_counter() - started) * 1000),
        "passed": passed,
        "failed": len(acceptance.results) - passed,
        "items": acceptance.results,
    }
    out = ROOT / "logs" / f"environments-acceptance-{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(acceptance.results)} PASS -> {out}")
    return 0 if passed == len(acceptance.results) else 1


if __name__ == "__main__":
    sys.exit(main())
