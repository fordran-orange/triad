"""The experiment process pool (Mission 6 spec §4.3).

Each worker process holds the bars (prepared once), its own indicator cache and the compiled
kernel, and runs cells through the metrics-only path; it returns rows, never envelopes. The
pool measures the workers' own cost per cell-bar, which is comparable to the single-threaded
optimizer's rate (plan ruling P2).
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor
from itertools import repeat

from pydantic import ValidationError

SCOPES = ("combined", "long", "short")
METRICS = (
    "net_pnl",
    "net_return",
    "cagr",
    "max_drawdown",
    "mar",
    "win_rate",
    "expectancy",
    "profit_factor",
    "trade_count",
    "exposure",
)
CURVE_POINTS = 128

# Worker-process state, set once by the initializer.
_FRAME = None
_DATA_KEY = None
_SPEC = None
_SETTINGS = None
_CACHE = None
_ROWS = None
_WINDOW = None  # (bounds, frame, data key) of the window slice the worker last ran


def default_workers() -> int:
    configured = os.environ.get("AEGIS_POOL_WORKERS")
    if configured:
        return max(1, int(configured))
    return max(1, (os.cpu_count() or 2) - 2)


def resample_curve(points: list[float], n: int = CURVE_POINTS) -> list[float]:
    """`n` points by index: the first and last are kept, short series are padded by repetition."""
    if not points:
        return [0.0] * n
    if len(points) == 1:
        return [float(points[0])] * n
    last = len(points) - 1
    return [float(points[(k * last) // (n - 1)]) for k in range(n)]


def _init_worker(
    rows: list[dict], symbol: str, spec: dict, settings: dict, keep_rows: bool = True
) -> None:
    global _FRAME, _DATA_KEY, _SPEC, _SETTINGS, _CACHE, _ROWS, _WINDOW
    from products.aegis.backtest import BacktestSettings, _data_key, _prepare_frame
    from products.aegis.indicators import IndicatorCache
    from products.aegis.strategy import StrategySpec

    for row in rows:
        row.setdefault("symbol", symbol)
    _ROWS = rows
    _WINDOW = None
    _FRAME = _prepare_frame(rows)
    _DATA_KEY = _data_key(_FRAME)
    _SPEC = StrategySpec.model_validate(spec)
    _SETTINGS = BacktestSettings.model_validate(settings)
    _CACHE = IndicatorCache()
    if not keep_rows:
        _ROWS = None  # a grid never slices windows: one prepared frame per worker is enough


def _window_frame(window: tuple[int, int] | None):
    """The frame and data key a cell runs on: the whole bars, or one window's slice prepared
    as its own bars (Mission 8: a study maps each window in-sample only)."""
    global _WINDOW
    if window is None:
        return _FRAME, _DATA_KEY
    if _ROWS is None:
        raise RuntimeError("this pool was started without rows; a window needs them")
    from products.aegis.backtest import _data_key, _prepare_frame

    bounds = (int(window[0]), int(window[1]))
    if _WINDOW is None or _WINDOW[0] != bounds:
        frame = _prepare_frame(_ROWS[bounds[0] : bounds[1]])
        _WINDOW = (bounds, frame, _data_key(frame))
    return _WINDOW[1], _WINDOW[2]


def _run_cell(
    index: int, params: dict[str, float], want_curve: bool, window: tuple[int, int] | None = None
) -> dict:
    from products.aegis.backtest import BacktestRequest, run_metrics
    from products.aegis.surface import apply_params, skip_reason_of

    started = time.perf_counter()
    row = {
        "cell": index,
        "valid": True,
        "skip_reason": None,
        "params": dict(params),
        "metrics": None,
        "elapsed_ms": 0.0,
        "curve": None,
        "first_time": None,
        "last_time": None,
        "engine": None,
    }
    try:
        strategy = apply_params(_SPEC, params)
    except ValidationError as exc:
        row.update(valid=False, skip_reason=skip_reason_of(exc))
        row["elapsed_ms"] = (time.perf_counter() - started) * 1000
        return row
    except ValueError as exc:
        row.update(valid=False, skip_reason=str(exc))
        row["elapsed_ms"] = (time.perf_counter() - started) * 1000
        return row
    request = BacktestRequest.model_construct(
        strategy=strategy, data=None, bars=[], events=[], settings=_SETTINGS, engine="kernel"
    )
    try:
        frame, data_key = _window_frame(window)
        result = run_metrics(request, frame, data_key, _CACHE, want_curve)
    except ValueError as exc:  # the engine's own refusal (a warm-up longer than the data)
        message = str(exc)
        reason = "insufficient bars" if message.startswith("insufficient bars") else message
        row.update(valid=False, skip_reason=reason)
        row["elapsed_ms"] = (time.perf_counter() - started) * 1000
        return row
    row.update(
        metrics={scope: result[scope] for scope in SCOPES},
        curve=resample_curve(result["curve"]) if want_curve else None,
        first_time=result["first_time"],
        last_time=result["last_time"],
        engine=result["engine"],
    )
    row["elapsed_ms"] = (time.perf_counter() - started) * 1000
    return row


class Pool:
    """A process pool bound to one set of bars, one pinned spec and one settings object."""

    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = max_workers or default_workers()
        self._executor: ProcessPoolExecutor | None = None
        self._bars = 0
        self._cell_ms_total = 0.0
        self._cell_bars_total = 0

    def start(
        self, rows: list[dict], symbol: str, spec: dict, settings: dict, keep_rows: bool = True
    ) -> None:
        self._bars = len(rows)
        self._executor = ProcessPoolExecutor(
            max_workers=self.max_workers,
            initializer=_init_worker,
            initargs=(rows, symbol, spec, settings, keep_rows),
        )

    @property
    def mean_ms_per_cell_bar(self) -> float | None:
        if not self._cell_bars_total:
            return None
        return self._cell_ms_total / self._cell_bars_total

    def run_chunk(
        self,
        cells: list[tuple[int, dict[str, float]]],
        want_curve: bool,
        window: tuple[int, int] | None = None,
    ) -> list[dict]:
        """Run cells on the whole bars, or with `window` = (start, end) on that slice only."""
        if self._executor is None:
            raise RuntimeError("pool not started")
        bars = self._bars if window is None else window[1] - window[0]
        indices = [index for index, _ in cells]
        params = [values for _, values in cells]
        chunksize = max(1, len(cells) // (self.max_workers * 4))
        rows = list(
            self._executor.map(
                _run_cell,
                indices,
                params,
                repeat(want_curve),
                repeat(window),
                chunksize=chunksize,
            )
        )
        for row in rows:
            if row["valid"]:
                self._cell_ms_total += row["elapsed_ms"]
                self._cell_bars_total += bars
        return rows

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None


__all__ = ["CURVE_POINTS", "METRICS", "SCOPES", "Pool", "default_workers", "resample_curve"]
