"""Live dependency probes; errors are not green placeholders."""

import json
import subprocess
import urllib.request
from datetime import UTC, datetime

from triad.brain import Brain
from triad.settings import ROOT
from triad.store import Store


def system_status(store: Store) -> dict:
    result = {"backend": {"status": "up"}, "checked_at": datetime.now(UTC).isoformat()}
    try:
        with store.connect() as conn:
            conn.execute("SELECT 1").fetchone()
            extension = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname='timescaledb'"
            ).fetchone()
        result["postgres"] = {"status": "up"}
        result["timescale"] = {
            "status": "up" if extension else "down",
            "version": extension["extversion"] if extension else None,
        }
    except Exception as exc:  # noqa: BLE001 - redacted probe boundary
        result["postgres"] = {"status": "down", "error": type(exc).__name__}
        result["timescale"] = {"status": "unknown"}
    try:
        with Brain(store).driver() as driver:
            driver.verify_connectivity()
        result["neo4j"] = {"status": "up"}
    except Exception as exc:  # noqa: BLE001
        result["neo4j"] = {"status": "down", "error": type(exc).__name__}
    try:
        with urllib.request.urlopen(store.settings.ollama_url + "/api/tags", timeout=3) as response:
            models = [m["name"] for m in json.load(response)["models"]]
        result["ollama"] = {"status": "up", "models": models}
    except Exception as exc:  # noqa: BLE001
        result["ollama"] = {"status": "down", "error": type(exc).__name__}
    try:
        branch = subprocess.check_output(
            ["git", "-C", str(ROOT), "branch", "--show-current"], text=True, timeout=3
        ).strip()
        commit = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True, timeout=3
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(ROOT), "status", "--porcelain"], text=True, timeout=3
        ).strip()
        result["git"] = {
            "status": "up",
            "branch": branch,
            "commit": commit,
            "clean": not bool(dirty),
        }
    except Exception as exc:  # noqa: BLE001
        result["git"] = {"status": "down", "error": type(exc).__name__}
    return result
