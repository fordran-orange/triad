"""Print the existing Ollama executable selected by Core's shared resolver."""

import subprocess

from trading_core.providers.discovery import candidates


def main():
    for command in candidates("ollama"):
        try:
            result = subprocess.run(
                command + ["--version"], capture_output=True, text=True, timeout=10, check=False
            )
            if result.returncode == 0 and "ollama" in (result.stdout + result.stderr).lower():
                print(command[0])
                return
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise SystemExit("No responsive Ollama installation found; configure TRIAD_OLLAMA_EXECUTABLE")


if __name__ == "__main__":
    main()
