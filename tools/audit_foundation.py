"""Verify the Day 1 filesystem, contracts, dependency lock and tracked secret exclusion."""

import json
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def main():
    folders = [
        "app",
        "agents",
        "control-plane",
        "data/raw",
        "data/canonical",
        "data/derived",
        "data/manifests",
        "data/temp",
        "databases",
        "docs",
        "infrastructure",
        "logs",
        "research",
        "tests",
        "tools",
    ]
    documents = [
        "README.md",
        "docs/ARCHITECTURE.md",
        "docs/DAY1_SETUP.md",
        "docs/AGENT_CONTROL_PLANE.md",
        "docs/DATA_ARCHITECTURE.md",
        "docs/KNOWLEDGE_ARCHITECTURE.md",
        "docs/LOCAL_MODEL.md",
        "docker-compose.yml",
        ".env.example",
        "pyproject.toml",
        "requirements.lock",
    ]
    assert all((ROOT / name).is_dir() for name in folders), "Missing required directory"
    assert all((ROOT / name).is_file() for name in documents), "Missing required deliverable"
    assert sys.prefix != sys.base_prefix, "Not running in a virtual environment"
    assert git("branch", "--show-current") == "main", "Wrong Git branch"
    assert git("check-ignore", ".env") == ".env", "Local credentials not ignored"
    tracked = git("ls-files").splitlines()
    assert tracked, "No tracked/staged project files"
    assert ".env" not in tracked and not any(f.startswith(".venv/") for f in tracked)
    credentials = dotenv_values(ROOT / ".env")
    secrets = [
        credentials[key] for key in ("POSTGRES_PASSWORD", "NEO4J_PASSWORD", "TRIAD_OPERATOR_TOKEN")
    ]
    assert secrets[0] != secrets[1] and all(len(s) >= 32 for s in secrets)
    import os

    provider_secrets = {**credentials, **os.environ}
    secrets.extend(
        provider_secrets[k]
        for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY")
        if provider_secrets.get(k)
    )
    for name in tracked:
        data = (ROOT / name).read_bytes()
        assert all(secret.encode() not in data for secret in secrets), f"Secret found in {name}"
    # Parse every committed JSON contract/example rather than relying on filenames.
    for name in tracked:
        if name.endswith(".json"):
            json.loads((ROOT / name).read_text())
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8-sig").splitlines()
    assert all("==" in line for line in lock if line and not line.startswith("#"))
    print(
        json.dumps(
            {
                "folders": len(folders),
                "required_files": len(documents),
                "tracked_files": len(tracked),
                "branch": "main",
                "secret_exclusion": "passed",
                "lock_pinned": "passed",
                "virtual_environment": "passed",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
