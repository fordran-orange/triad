"""Trusted post-merge verification; candidate UI code is never run as host code."""

import subprocess
import sys

import httpx
from trading_core.settings import ROOT


def verify(merged):
    if (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        != merged["merge_commit"]
    ):
        raise PermissionError("Merged revision moved before post-merge verification")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise PermissionError("Post-merge verification requires clean source")
    # These are trusted framework tests outside the model's exact UI grant. No
    # arbitrary test IDs, argv or Python files come from proposed changes.
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_readiness.py",
        "tests/test_day8_daily_ui_qa.py",
        "-q",
    ]
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=120, check=False
    )
    routes = (
        "/core",
        "/triad/product",
        "/triad/product/research-readiness",
        "/triad/development",
        "/triad/cycles",
        "/triad/daily-debrief",
        "/aegis",
        "/api/core/integrations",
        "/api/core/research-readiness",
    )
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30, trust_env=False) as client:
        checks = {path: client.get(path).status_code for path in routes}
        providers = client.get("/api/providers").raise_for_status().json()
        status = client.get("/api/status").raise_for_status().json()
        aegis = client.get("/aegis/api/status").raise_for_status().json()
    passed = (
        result.returncode == 0
        and all(v == 200 for v in checks.values())
        and providers["gate"] == "PASS"
        and aegis["exchange"] == "CLOSED"
        and aegis["mode"] == "human_directed"
        and not aegis["work_items"]
        and all(
            status[k]["status"] == "up"
            for k in ("backend", "postgres", "timescale", "neo4j", "ollama", "git")
        )
    )
    return {
        "status": "PASS" if passed else "FAILED",
        "tests": command[3:],
        "test_exit": result.returncode,
        "test_output": result.stdout[-12000:],
        "routes": checks,
        "provider_gate": providers["gate"],
        "evidence": [
            "Exact merged revision",
            "Affected trusted regression",
            "Read-only live service checks",
        ],
    }
