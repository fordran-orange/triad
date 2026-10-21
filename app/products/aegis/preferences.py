"""Aegis worker preferences (Mission 10 spec §8).

One small JSON file beside the saved runs (`data/aegis/preferences.json`). `save_runs` says
whether every backtest is saved ("every", the default) or only the runs the operator keeps
("kept"). An unreadable file reads as the defaults; nothing else is stored here.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from products.aegis.data import DATA_ROOT
from products.aegis.runs import _retry

SAVE_MODES = ("every", "kept")
DEFAULTS = {"save_runs": "every"}


class Preferences:
    def __init__(self, root: Path | None = None):
        self.path = (
            Path(root) if root is not None else DATA_ROOT / "data" / "aegis"
        ) / "preferences.json"

    def get(self) -> dict:
        # Windows refuses a read while a write swaps the file in: retry, never fall back to the
        # default mid-write (Mission 11 trial: a read answered "every" in "kept" mode).
        try:
            stored = json.loads(_retry(lambda: self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return dict(DEFAULTS)
        mode = stored.get("save_runs") if isinstance(stored, dict) else None
        return {"save_runs": mode if mode in SAVE_MODES else DEFAULTS["save_runs"]}

    def set(self, save_runs: str) -> dict:
        if save_runs not in SAVE_MODES:
            raise ValueError(f"save_runs must be one of {list(SAVE_MODES)}, not {save_runs!r}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # a temporary file per writer, swapped in with the run store's retry (a held file refused
        # the swap and the PUT answered 500)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"save_runs": save_runs}, sort_keys=True), encoding="utf-8")
        _retry(lambda: tmp.replace(self.path))
        return self.get()


__all__ = ["DEFAULTS", "SAVE_MODES", "Preferences"]
