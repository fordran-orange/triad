"""Explicit real product proof using the existing governed development lifecycle.

Provider inspection, selection, isolated build and independent QA retain their
canonical WorkItems and observed usage. This is a bounded product cycle, not proof
that arbitrary host shell execution has been isolated or authorized.
"""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from products.triad.development import Development
from trading_core.contracts import Limits
from trading_core.work import now, uid


def core_live(url="http://127.0.0.1:8000/health/live"):
    try:
        with urlopen(url, timeout=3) as response:
            body = json.loads(response.read().decode())
            return isinstance(body, dict) and body.get("status") == "ok"
    except (URLError, TimeoutError, ValueError, OSError):
        return False


def restart_services(root):
    if os.name != "nt":
        return False
    for script, args in (
        ("ensure_core.ps1", ["-Restart"]),
        ("start_product.ps1", ["-Product", "triad"]),
    ):
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-File", str(Path(root) / "tools" / script), *args],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=360,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode:
            return False
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if core_live() and core_live("http://127.0.0.1:8101/health/live"):
            return True
        time.sleep(1)
    return False


class ProofDevelopment(Development):
    def __init__(self, *, no_merge=False):
        super().__init__()
        self.no_merge = no_merge

    def merge(self, mission, proposal, build, qa, *, operator_authorized=False):
        if not self.no_merge:
            return super().merge(
                mission, proposal, build, qa, operator_authorized=operator_authorized
            )
        accepted = self.quality.require_pass(
            build["implementation_id"], build["git"]["change_commit"]
        )
        if accepted["id"] != qa.qa_run_id:
            raise PermissionError("Diagnostic proof requires the current independent review")
        limits = Limits.model_validate(self.ledger.control()["limits"]).model_copy(
            update={"allowed_directories": proposal.affected_components}
        )
        self.exact_checks(build, limits)
        return {**build["git"], "proof_status": "REVIEWED_NOT_MERGED"}


def recover_merge(dev, merged):
    """Restore the prior tree with an auditable revert, never a destructive reset."""
    with dev.host.store.lease("triad-product-development"):
        dev.ledger.guard()
        if dev.git.clean_baseline() != merged["merge_commit"]:
            raise PermissionError("Source moved; automatic recovery requires reconciliation")
        parents = dev.git.git("rev-list", "--parents", "-n", "1", merged["merge_commit"]).split()
        if len(parents) != 3 or parents[1] != merged["base_commit"]:
            raise PermissionError("Recovery requires the exact reviewed two-parent merge")
        dev.git.git("revert", "--no-edit", "-m", "1", merged["merge_commit"])
        reverted = dev.git.git("rev-parse", "HEAD")
        if dev.git.git("rev-parse", "HEAD^{tree}") != dev.git.git(
            "rev-parse", merged["base_commit"] + "^{tree}"
        ):
            raise PermissionError("Recovery tree differs from the accepted baseline")
        return reverted


def run_proof(dev, *, restart=restart_services):
    mission = "m1-" + uid()
    base = dev.git.clean_baseline()
    record = {
        "mission_id": mission,
        "base_commit": base,
        "started_at": now().isoformat(),
        "status": "RUNNING",
        "scope": "Existing isolated product development and independent QA; no broad host tools",
    }
    dev.record("Milestone1Rotation", mission, **{k: v for k, v in record.items() if k != "mission_id"})
    try:
        merged = dev.run(mission)
        record.update(merged)
        if merged.get("merge_commit"):
            dev.ledger.guard()
            try:
                healthy = restart(dev.git.root)
            except (OSError, subprocess.TimeoutExpired):
                healthy = False
            if not healthy:
                record["revert_commit"] = recover_merge(dev, merged)
                try:
                    record["recovery_healthy"] = restart(dev.git.root)
                except (OSError, subprocess.TimeoutExpired):
                    record["recovery_healthy"] = False
                raise RuntimeError("PostMergeHealthFailed")
            record["status"] = "MERGED_AND_HEALTHY"
        else:
            record["status"] = "REVIEWED_NOT_MERGED"
        return record
    except Exception as exc:
        record.update(status="FAILED", error_class=type(exc).__name__)
        raise
    finally:
        record["finished_at"] = now().isoformat()
        dev.record("Milestone1Rotation", mission, **{k: v for k, v in record.items() if k != "mission_id"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-merge", action="store_true", help="Retain independently reviewed candidate")
    args = parser.parse_args()
    print(json.dumps(run_proof(ProofDevelopment(no_merge=args.no_merge)), indent=2, default=str))


if __name__ == "__main__":
    main()
