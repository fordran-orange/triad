"""Backtests not saved (Mission 10 spec §8): in "kept" mode the worker holds the last runs in
memory only, so Load, the Runs drawer and GET /runs/{id} still work for them until the operator
keeps one or the worker restarts. They never enter the Library and never hold a strategy."""

from __future__ import annotations

import threading
from collections import OrderedDict

from products.aegis.runs import _summary

LIMIT = 20


class UnsavedRuns:
    def __init__(self, limit: int = LIMIT):
        self.limit = limit
        self._runs: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, envelope: dict) -> None:
        with self._lock:
            self._runs[envelope["run_id"]] = envelope
            self._runs.move_to_end(envelope["run_id"])
            while len(self._runs) > self.limit:
                self._runs.popitem(last=False)

    def get(self, run_id: str) -> dict:
        """The run (a shallow copy: callers annotate what they serve); KeyError when forgotten."""
        with self._lock:
            return dict(self._runs[run_id])

    def list(self) -> list[dict]:
        """Summaries, newest first, each marked `kept: False`."""
        with self._lock:
            return [{**_summary(run), "kept": False} for run in reversed(self._runs.values())]

    def pop(self, run_id: str) -> dict:
        with self._lock:
            return self._runs.pop(run_id)


__all__ = ["LIMIT", "UnsavedRuns"]
