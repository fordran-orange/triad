"""Aegis market data: raw archives read directly, resampled, cached, and pinned.

Discovery picks the newest vintage directory for NEW experiments. Every run pins the exact
file (path, SHA-256, first/last bar, row count) and the exact resampled data hash; reloading
a run never substitutes a newer archive (spec §2b.3). Nothing here touches Core's canonical
store or manifests, and every response says `source: raw_archive, research_eligible: false`.
"""

from __future__ import annotations

import csv
import hashlib
import threading
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict

DATA_ROOT = Path(__file__).resolve().parents[3]
ARCHIVE_DIR = Path("data") / "raw" / "HFDataLibrary"
TIMEFRAMES = ("1m", "15m", "30m", "1h", "1D")
BAR_CAP = 200_000  # operator, 2026-10-20: ten years of 15m fit; the goal is no limit
RESAMPLING_POLICY = "rth-anchored-v1"
TIMEZONE = "America/New_York"
SESSION_OPEN = "09:30"
_MINUTES = {"15m": 15, "30m": 30, "1h": 60}
_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class BarsTooLarge(ValueError):
    def __init__(self, count: int, cap: int):
        self.count, self.cap = count, cap
        super().__init__(f"range too large: {count} bars over cap {cap}; narrow the range")


class SourceUnavailable(RuntimeError):
    """The pinned archive is missing or its bytes changed; never fall forward silently."""


class ArchiveSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    source: str = "raw_archive"
    vintage: str
    relative_path: str
    sha256: str
    first_bar: str
    last_bar: str
    row_count: int
    vendor_sources: list[str]
    coverage_pct: float | None = None
    research_eligible: bool = False


class PinnedSource(ArchiveSource):
    timeframe: str
    start: date
    end: date
    resampling_policy: str = RESAMPLING_POLICY
    data_hash: str
    bar_count: int


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coverage(folder: Path, symbol: str) -> float | None:
    path = folder / f"{symbol}-daily-coverage.csv"
    if not path.is_file():
        return None
    regular = expected = 0
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                regular += int(row["regular_rows"])
                expected += int(row["expected_regular"])
            except (KeyError, ValueError):
                return None
    return regular / expected * 100 if expected else None


def _describe(root: Path, folder: Path, path: Path) -> ArchiveSource:
    table = pq.read_table(path, columns=["datetime", "source"])
    stamps = table.column("datetime").to_pandas()
    local = pd.DatetimeIndex(stamps).tz_localize(
        TIMEZONE, ambiguous="NaT", nonexistent="shift_forward"
    )
    local = local[~local.isna()]
    return ArchiveSource(
        symbol=path.name.split("_")[0],
        vintage=folder.name,
        relative_path=path.relative_to(root).as_posix(),
        sha256=_file_sha256(path),
        first_bar=local.min().isoformat(),
        last_bar=local.max().isoformat(),
        row_count=table.num_rows,
        vendor_sources=sorted(set(table.column("source").to_pylist())),
        coverage_pct=_coverage(folder, path.name.split("_")[0]),
    )


def discover_archives(root: Path = DATA_ROOT) -> list[ArchiveSource]:
    """Archives in the newest vintage directory; symbols without a parquet file are skipped."""
    base = root / ARCHIVE_DIR
    vintages = (
        sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name)
        if base.is_dir()
        else []
    )
    if not vintages:
        return []
    folder = vintages[-1]
    return [_describe(root, folder, path) for path in sorted(folder.glob("*_1m_10y.parquet"))]


def _load_minutes(path: Path) -> pd.DataFrame:
    frame = pq.read_table(path).to_pandas()
    frame = frame.rename(
        columns={
            "datetime": "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )[_COLUMNS]
    local = pd.DatetimeIndex(frame["timestamp"]).tz_localize(
        TIMEZONE, ambiguous="NaT", nonexistent="shift_forward"
    )
    frame = frame.assign(timestamp=local.tz_convert("UTC"))
    frame = frame[frame["timestamp"].notna()].sort_values("timestamp").reset_index(drop=True)
    frame["volume"] = frame["volume"].astype("int64")
    return frame


def _resample(minutes: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Policy rth-anchored-v1: intraday buckets anchored at 09:30 local; 1D per session day."""
    if timeframe == "1m":
        return minutes.copy()
    local = minutes.set_index(minutes["timestamp"].dt.tz_convert(TIMEZONE)).drop(
        columns="timestamp"
    )
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if timeframe == "1D":
        grouped = local.groupby(local.index.date).agg(agg)
        stamps = pd.DatetimeIndex(
            [pd.Timestamp(f"{day} {SESSION_OPEN}", tz=TIMEZONE) for day in grouped.index]
        )
        out = grouped.reset_index(drop=True).assign(timestamp=stamps.tz_convert("UTC"))
    else:
        # Explicit 09:30-anchored buckets (avoids pandas' resample offset path, which warns on
        # NumPy 2 generic timedelta units): bucket = session open + floor(elapsed / rule) * rule.
        # Integer-nanosecond arithmetic: this pandas/NumPy pairing warns on Timedelta objects.
        index = pd.DatetimeIndex(local.index)
        day_open = index.normalize() + pd.DateOffset(hours=9, minutes=30)
        rule_ns = _MINUTES[timeframe] * 60 * 1_000_000_000
        elapsed_ns = index.asi8 - day_open.asi8
        bucket_ns = day_open.asi8 + (elapsed_ns // rule_ns) * rule_ns
        bucket = pd.DatetimeIndex(bucket_ns, tz="UTC").tz_convert(TIMEZONE)
        grouped = local.groupby(bucket).agg(agg).dropna(subset=["open"]).sort_index()
        out = grouped.reset_index().rename(columns={"index": "timestamp"})
        out["timestamp"] = pd.DatetimeIndex(out["timestamp"]).tz_convert("UTC")
    out["volume"] = out["volume"].astype("int64")
    return out[_COLUMNS].reset_index(drop=True)


def _data_hash(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(frame["timestamp"].astype("int64").to_numpy().tobytes())
    for column in ("open", "high", "low", "close"):
        digest.update(frame[column].astype("float64").to_numpy().tobytes())
    digest.update(frame["volume"].astype("int64").to_numpy().tobytes())
    return digest.hexdigest()


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def to_records(frame: pd.DataFrame) -> list[dict]:
    times = (frame["timestamp"].astype("int64") // 1_000_000).tolist()
    return [
        {
            "time": int(t),
            "open": float(o),
            "high": float(h),
            "low": float(lo),
            "close": float(c),
            "volume": int(v),
        }
        for t, o, h, lo, c, v in zip(
            times,
            frame["open"],
            frame["high"],
            frame["low"],
            frame["close"],
            frame["volume"],
            strict=True,
        )
    ]


class ArchiveStore:
    """In-memory cache of resampled archives, keyed by (vintage, symbol, timeframe)."""

    def __init__(self, root: Path = DATA_ROOT):
        self.root = Path(root)
        self._sources: dict[str, ArchiveSource] | None = None
        self._frames: dict[tuple[str, str, str], pd.DataFrame] = {}
        self._lock = threading.RLock()
        self.resample_count = 0

    def symbols(self) -> list[ArchiveSource]:
        with self._lock:
            if self._sources is None:
                self._sources = {s.symbol: s for s in discover_archives(self.root)}
            return list(self._sources.values())

    def source(self, symbol: str) -> ArchiveSource:
        self.symbols()
        assert self._sources is not None
        if symbol not in self._sources:
            raise KeyError(f"unknown symbol {symbol!r}")
        return self._sources[symbol]

    def _frame(self, archive: ArchiveSource, timeframe: str) -> pd.DataFrame:
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"unknown timeframe {timeframe!r}; expected one of {TIMEFRAMES}")
        key = (archive.vintage, archive.symbol, timeframe)
        with self._lock:
            if key not in self._frames:
                minutes_key = (archive.vintage, archive.symbol, "__minutes__")
                if minutes_key not in self._frames:
                    self._frames[minutes_key] = _load_minutes(self.root / archive.relative_path)
                self._frames[key] = _resample(self._frames[minutes_key], timeframe)
                self.resample_count += 1
            return self._frames[key]

    def _select(
        self, archive: ArchiveSource, timeframe: str, start, end
    ) -> tuple[pd.DataFrame, PinnedSource]:
        start_date, end_date = _as_date(start), _as_date(end)
        if end_date < start_date:
            raise ValueError("end date precedes start date")
        full = self._frame(archive, timeframe)
        local_dates = full["timestamp"].dt.tz_convert(TIMEZONE).dt.date
        frame = full[(local_dates >= start_date) & (local_dates <= end_date)].reset_index(drop=True)
        if len(frame) > BAR_CAP:
            raise BarsTooLarge(len(frame), BAR_CAP)
        pinned = PinnedSource(
            **archive.model_dump(),
            timeframe=timeframe,
            start=start_date,
            end=end_date,
            data_hash=_data_hash(frame),
            bar_count=len(frame),
        )
        return frame, pinned

    def bars(self, symbol: str, timeframe: str, start, end) -> tuple[pd.DataFrame, PinnedSource]:
        return self._select(self.source(symbol), timeframe, start, end)

    def load_pinned(self, pinned: PinnedSource) -> pd.DataFrame:
        """Reload exactly the pinned archive; any drift is an explicit source_unavailable."""
        path = self.root / pinned.relative_path
        if not path.is_file():
            raise SourceUnavailable(f"pinned archive missing: {pinned.relative_path}")
        if _file_sha256(path) != pinned.sha256:
            raise SourceUnavailable(f"pinned archive sha256 mismatch: {pinned.relative_path}")
        archive = ArchiveSource(
            **{k: v for k, v in pinned.model_dump().items() if k in ArchiveSource.model_fields}
        )
        frame, fresh = self._select(archive, pinned.timeframe, pinned.start, pinned.end)
        if fresh.data_hash != pinned.data_hash:
            raise SourceUnavailable("pinned data hash mismatch after resampling")
        return frame

    def warm(self, symbols: list[str]) -> None:
        for symbol in symbols:
            try:
                archive = self.source(symbol)
            except KeyError:
                continue
            for timeframe in TIMEFRAMES:
                self._frame(archive, timeframe)
