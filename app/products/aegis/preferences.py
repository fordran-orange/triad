"""Aegis worker preferences (Mission 10 spec §8).

One small JSON file beside the saved runs (`data/aegis/preferences.json`). `save_runs` says
whether every backtest is saved ("every", the default) or only the runs the operator keeps
("kept"). An unreadable file reads as the defaults; nothing else is stored here.
"""

from __future__ import annotations

import json
from pathlib import Path

from products.aegis.data import DATA_ROOT

SAVE_MODES = ("every", "kept")
DEFAULTS = {"save_runs": "every"}


class Preferences:
    def __init__(self, root: Path | None = None):
        self.path = (
            Path(root) if root is not None else DATA_ROOT / "data" / "aegis"
        ) / "preferences.json"

    def get(self) -> dict:
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return dict(DEFAULTS)
        mode = stored.get("save_runs") if isinstance(stored, dict) else None
        return {"save_runs": mode if mode in SAVE_MODES else DEFAULTS["save_runs"]}

    def set(self, save_runs: str) -> dict:
        if save_runs not in SAVE_MODES:
            raise ValueError(f"save_runs must be one of {list(SAVE_MODES)}, not {save_runs!r}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"save_runs": save_runs}, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
        return self.get()


__all__ = ["DEFAULTS", "SAVE_MODES", "Preferences"]
