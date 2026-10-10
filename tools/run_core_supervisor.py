"""Windowless scheduled entry point; keep PowerShell and all children off the desktop."""

import os
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / "supervisor-launcher.log").open("ab") as output:
        try:
            result = subprocess.run(
                [
                    str(powershell),
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(root / "tools/ensure_core.ps1"),
                ],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=output,
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
            if result.returncode:
                return result.returncode
            # Both products are checked every pass; the first failure is the exit code.
            code = 0
            for product in ("triad", "aegis"):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(root / "tools/ensure_product_worker.py"),
                        "--product",
                        product,
                    ],
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=output,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    check=False,
                    timeout=100,
                )
                code = code or result.returncode
            return code
        except (OSError, subprocess.TimeoutExpired) as exc:
            output.write(("Supervisor could not start: " + type(exc).__name__ + "\n").encode())
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
