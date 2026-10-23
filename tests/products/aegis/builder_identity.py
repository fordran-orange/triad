"""Mission 13: real-archive identity for strategies without stops, and the saved strategies' hashes.

    .venv-aegis\\Scripts\\python.exe tests\\products\\aegis\\builder_identity.py capture OUT.json
    .venv-aegis\\Scripts\\python.exe tests\\products\\aegis\\builder_identity.py compare OUT.json
    .venv-aegis\\Scripts\\python.exe tests\\products\\aegis\\builder_identity.py hashes

`capture` runs, on QQQ 1h 2016-01-01 → 2026-09-18, backtests of the reference strategy and the
newest saved "Donchian RSI breakout" (both engines), a 9-cell experiment of the breakout and one
walk-forward, and writes their canonical output; `compare` runs them again and prints the first
difference or "identical". `hashes` recomputes every saved strategy document's hash (read-only).
Nothing is written to the operator's store.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for path in (ROOT / "app", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

SYMBOL, TIMEFRAME = "QQQ", "1h"
START, END = date(2016, 1, 1), date(2026, 9, 18)


def _plain(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _library():
    from products.aegis.runs import JsonRunRepository
    from products.aegis.strategies import StrategyLibrary

    return StrategyLibrary(JsonRunRepository(ROOT / "data" / "aegis"))


def _breakout(identifier: str | None = None):
    """A saved Donchian RSI breakout (what the walk's item 37 builds): the one named, or at a
    capture the newest; a compare reuses the capture's, since later walks save newer ones."""
    library = _library()
    if identifier is None:
        rows = [
            r for r in library.list() if str(r.get("name", "")).startswith("Donchian RSI breakout")
        ]
        identifier = max(rows, key=lambda r: r.get("created_at") or "")["id"]
    return library.get(identifier).spec


def outputs(breakout_id: str | None = None) -> dict:
    from products.aegis.backtest import (
        BacktestSettings,
        DataReference,
        _data_key,
        prepare_archive_frame,
        prepared_request,
        run_metrics,
        run_prepared,
    )
    from products.aegis.data import ArchiveStore
    from products.aegis.indicators import IndicatorCache
    from products.aegis.results import canonical_payload, result_hash
    from products.aegis.strategy import OptimizationParameter, StrategySide, default_strategy
    from products.aegis.surface import Parameter, Surface, build_grid
    from products.aegis.walkforward import WalkForwardJob, WalkForwardRequest

    store = ArchiveStore()
    raw, pinned = store.bars(SYMBOL, TIMEFRAME, START, END)
    frame = prepare_archive_frame(raw, SYMBOL)
    key, cache = _data_key(frame), IndicatorCache()
    identity = {"source": "raw_archive", "bar_count": len(frame)}
    breakout = _breakout(breakout_id)
    out: dict = {"bars": len(frame), "breakout_id": breakout.id}
    for name, strategy in (("reference", default_strategy()), ("breakout", breakout)):
        for engine in ("reference", "kernel"):
            request = prepared_request(strategy, BacktestSettings(), engine)
            result = run_prepared(request, frame, key, cache)
            payload = canonical_payload(result, strategy, identity)
            out[f"backtest/{name}/{engine}"] = _plain(
                {"result_hash": result_hash(payload), "payload": payload}
            )
    surface = Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=10, stop=30, step=10),
            Parameter(path="long_side.indicators.rsi.length", start=7, stop=21, step=7),
        ]
    )
    grid = build_grid(breakout, surface, len(frame))
    out["experiment"] = _plain(
        [
            run_metrics(
                prepared_request(
                    grid.apply_cell(breakout, grid.cell_values(i)), BacktestSettings()
                ),
                frame,
                key,
                cache,
                True,
            )
            for i in grid.valid_indices_iter()
        ]
    )
    side = breakout.long_side.model_dump(mode="json")
    side["optimization"] = [
        OptimizationParameter(
            path="indicators.donchian.length", start=10, stop=30, step=10
        ).model_dump(mode="json")
    ]
    strategy = breakout.model_copy(update={"long_side": StrategySide.model_validate(side)})
    request = WalkForwardRequest(
        strategy=strategy,
        side="long",
        data=DataReference(symbol=SYMBOL, timeframe=TIMEFRAME, start=START, end=END),
        in_sample_bars=4_000,
        out_of_sample_bars=2_000,
    )
    job = WalkForwardJob(request, raw, pinned)
    for unit in range(job.total_units):
        job.commit(unit, job.run_unit(unit))
    job.finalize("done")
    out["walkforward"] = _plain(job.snapshot())
    return out


def _first_difference(a, b, path=""):
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}/{key}: present on one side only"
            found = _first_difference(a[key], b[key], f"{path}/{key}")
            if found:
                return found
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} items != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            found = _first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"


def hashes() -> None:
    from products.aegis.results import strategy_hash

    library = _library()
    changed, count = [], 0
    for row in library.list():
        if row.get("builtin"):
            continue
        document = library.get(row["id"])
        count += 1
        if strategy_hash(document.spec) != document.strategy_hash:
            changed.append(document.id)
    print(f"{count} strategies, {len(changed)} changed" + (f": {changed}" if changed else ""))


def main(argv: list[str]) -> None:
    mode = argv[0] if argv else ""
    if mode == "hashes":
        hashes()
        return
    if mode not in ("capture", "compare") or len(argv) != 2:
        raise SystemExit("usage: builder_identity.py capture|compare OUT.json | hashes")
    target = Path(argv[1])
    captured = json.loads(target.read_text(encoding="utf-8")) if mode == "compare" else None
    breakout_id = None
    if captured is not None:  # captures before breakout_id existed name it in the payload
        breakout_id = (
            captured.get("breakout_id")
            or captured["backtest/breakout/kernel"]["payload"]["strategy"]["id"]
        )
        captured.setdefault("breakout_id", breakout_id)
    started = time.perf_counter()
    current = outputs(breakout_id)
    seconds = time.perf_counter() - started
    if mode == "capture":
        target.write_text(json.dumps(current, sort_keys=True), encoding="utf-8")
        print(f"captured {current['bars']:,} bars in {seconds:.1f} s -> {target}")
        return
    found = _first_difference(current, captured)
    print(f"{current['bars']:,} bars in {seconds:.1f} s: " + (found or "identical"))


if __name__ == "__main__":
    main(sys.argv[1:])
