"""Trusted restart, revision verification and automatic rollback of a reviewed merge."""

import subprocess
import time
from contextlib import nullcontext

import httpx

from trading_core.settings import ROOT


def git(*args):
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=NUL", *args], cwd=ROOT, text=True
    ).strip()


def restart():
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "tools/start_product.ps1"),
            "-Product",
            "triad",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=45,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Product worker restart failed")


def health(revision):
    deadline = time.monotonic() + 30
    with httpx.Client(timeout=5, trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                worker = client.get("http://127.0.0.1:8101/health/live").raise_for_status().json()
                if worker.get("status") == "ok" and worker.get("loaded_revision") == revision:
                    break
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("Product did not load the deployed revision")
        routes = (
            "/core",
            "/triad/product",
            "/triad/product-api/health",
            "/triad/cycles",
            "/triad/daily-debrief",
        )
        checks = {p: client.get("http://127.0.0.1:8000" + p).status_code for p in routes}
        if not all(v == 200 for v in checks.values()):
            raise RuntimeError("Post-deployment route checks failed")
        providers = client.get("http://127.0.0.1:8000/api/providers").raise_for_status().json()
        members = {
            a["agent"]: a for a in providers["agents"] if a["agent"] in {"CODEX", "CLAUDE", "GROK"}
        }
        if len(members) != 3 or any(a["state"] != "ONLINE" for a in members.values()):
            raise RuntimeError("Development provider is not ready")
        return {
            "routes": checks,
            "loaded_revision": revision,
            "development_provider_gate": "PASS",
            "maintenance_required": False,
        }


def verify(merged):
    guard = merged.get("_deployment_guard", lambda: None)
    gate = merged.get("_deployment_gate", nullcontext)
    guard()
    expected = merged["merge_commit"]
    if git("rev-parse", "HEAD") != expected or git("status", "--porcelain"):
        raise PermissionError("Deployment requires the exact clean reviewed merge")
    try:
        guard()
        restart()
        evidence = health(expected)
        if git("rev-parse", "HEAD") != expected or git("status", "--porcelain"):
            raise PermissionError("Source changed during deployment")
        return {
            "status": "PASS",
            **evidence,
            "evidence": [
                "Isolated candidate tests",
                "Independent exact-diff QA",
                "Restart and loaded-revision health check",
            ],
        }
    except Exception as exc:
        if git("rev-parse", "HEAD") != expected or git("status", "--porcelain"):
            raise PermissionError(
                "Deployment failed and concurrent source prevents automatic rollback"
            ) from exc
        result = {"status": "FAILED", "error": str(exc), "rolled_back": False}
        try:
            with gate():
                guard()
                if git("rev-parse", "HEAD") != expected or git("status", "--porcelain"):
                    raise PermissionError("Source changed before rollback")
                git("revert", "--no-edit", "-m", "1", expected)
                result.update(rolled_back=True, rollback_commit=git("rev-parse", "HEAD"))
            if git("diff", "--name-only", merged["base_commit"], "HEAD"):
                raise PermissionError("Rollback tree differs from last healthy baseline")
            guard()
            restart()
            result["rollback_health"] = health(result["rollback_commit"])
        except Exception as rollback_error:  # noqa: BLE001 - preserve both failures for canonical evidence
            result["rollback_error"] = str(rollback_error)
        return result
