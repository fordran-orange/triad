"""Windowless scheduled entry point; keep PowerShell and all children off the desktop."""

import os
import subprocess
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
            return result.returncode
        except OSError as exc:
            output.write(("Supervisor could not start: " + type(exc).__name__ + "\n").encode())
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
