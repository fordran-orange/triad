"""Backtests not saved (Mission 10 spec §8): in "kept" mode the worker holds the last runs in
memory only, so Load, the Runs drawer and GET /runs/{id} still work for them until the operator
keeps one or the worker restarts. They never enter the Library and never hold a strategy.

At most LIMIT runs and about MAX_BYTES of them (review I2): a ten-year 1m run holds ~111 MB as
Python objects (measured: 185,245 trades, markers and equity points, 599 B each), so twenty such
runs would hold more than this laptop's free memory. The oldest go first; the newest is always
held."""

from __future__ import annotations

import threading
from collections import OrderedDict

from products.aegis.runs import _summary

LIMIT = 20
MAX_BYTES = 512_000_000
BYTES_PER_ITEM = 640  # resident bytes per trade, marker or equity point (599 measured), rounded up
_SCOPES = ("long", "short", "combined")


def weight(envelope: dict) -> int:
    """A run's estimated resident size: its trades, markers and equity points."""
    result = envelope.get("result") or {}
    items = len(envelope.get("markers") or [])
    for scope in _SCOPES:
        side = result.get(scope) or {}
        items += len(side.get("trades") or []) + len(side.get("equity") or [])
    return items * BYTES_PER_ITEM


class UnsavedRuns:
    def __init__(self, limit: int = LIMIT, max_bytes: int = MAX_BYTES):
        self.limit = limit
        self.max_bytes = max_bytes
        self._runs: OrderedDict[str, dict] = OrderedDict()
        self._weights: dict[str, int] = {}
        self._lock = threading.Lock()

    def add(self, envelope: dict) -> None:
        run_id = envelope["run_id"]
        with self._lock:
            self._runs[run_id] = envelope
            self._runs.move_to_end(run_id)
            self._weights[run_id] = weight(envelope)
            while len(self._runs) > 1 and (
                len(self._runs) > self.limit or sum(self._weights.values()) > self.max_bytes
            ):
                oldest, _ = self._runs.popitem(last=False)
                self._weights.pop(oldest, None)

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
            run = self._runs.pop(run_id)
            self._weights.pop(run_id, None)
            return run


__all__ = ["BYTES_PER_ITEM", "LIMIT", "MAX_BYTES", "UnsavedRuns", "weight"]
