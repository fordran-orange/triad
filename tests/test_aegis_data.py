import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from products.aegis.data import (
    BAR_CAP,
    TIMEFRAMES,
    ArchiveStore,
    BarsTooLarge,
    SourceUnavailable,
    discover_archives,
    to_records,
)

pytestmark = pytest.mark.aegis

# 2026-10-30 is in EDT (UTC-4); 2026-11-02 is the first trading day in EST (UTC-5).
DAYS = [date(2026, 10, 30), date(2026, 11, 2)]


def session_minutes(day: date):
    start = datetime(day.year, day.month, day.day, 9, 30)  # noqa: DTZ001 - archive is naive ET
    return [start + timedelta(minutes=i) for i in range(390)]  # 09:30 .. 15:59 naive ET


def write_archive(root: Path, vintage: str, symbol: str, days=DAYS, price=100.0, missing=0):
    folder = root / "data" / "raw" / "HFDataLibrary" / vintage
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for day in days:
        minutes = session_minutes(day)[: 390 - missing]
        for i, stamp in enumerate(minutes):
            px = price + i * 0.01
            rows.append(
                {
                    "datetime": stamp,
                    "Open": px,
                    "High": px + 0.5,
                    "Low": px - 0.5,
                    "Close": px + 0.25,
                    "Volume": 100 + i,
                    "source": "iex" if day >= date(2022, 3, 7) else "pitrading",
                }
            )
    frame = pd.DataFrame(rows)
    frame["Volume"] = frame["Volume"].astype("int64")
    frame.to_parquet(folder / f"{symbol}_1m_10y.parquet", index=False)
    with (folder / f"{symbol}-daily-coverage.csv").open("w", encoding="utf-8") as f:
        f.write("date,observed_rows,regular_rows,expected_regular,missing_regular\n")
        for day in days:
            f.write(f"{day},{390 - missing},{390 - missing},390,{missing}\n")
    (folder / "report.json").write_text(
        json.dumps({"run_id": vintage, "source": "HFDataLibrary", "datasets": []}), encoding="utf-8"
    )
    return folder


@pytest.fixture
def root(tmp_path):
    write_archive(tmp_path, "20260101T000000000000Z", "QQQ", price=100.0)
    write_archive(tmp_path, "20260301T000000000000Z", "QQQ", price=200.0, missing=10)
    write_archive(tmp_path, "20260301T000000000000Z", "SPY", price=400.0)
    return tmp_path


def test_discovery_prefers_newest_vintage_and_reads_coverage(root):
    sources = {s.symbol: s for s in discover_archives(root)}
    assert set(sources) == {"QQQ", "SPY"}
    qqq = sources["QQQ"]
    assert qqq.vintage == "20260301T000000000000Z"
    assert qqq.source == "raw_archive" and qqq.research_eligible is False
    assert qqq.relative_path == "data/raw/HFDataLibrary/20260301T000000000000Z/QQQ_1m_10y.parquet"
    assert qqq.row_count == 2 * 380
    assert qqq.coverage_pct == pytest.approx(380 / 390 * 100)
    assert qqq.vendor_sources == ["iex"]
    assert qqq.first_bar.startswith("2026-10-30T09:30") and qqq.last_bar.startswith("2026-11-02")
    expected_sha = hashlib.sha256((root / qqq.relative_path).read_bytes()).hexdigest()
    assert qqq.sha256 == expected_sha


def test_discovery_skips_symbols_with_missing_parquet(root):
    folder = root / "data/raw/HFDataLibrary/20260301T000000000000Z"
    (folder / "ITOT-daily-coverage.csv").write_text("date,observed_rows\n", encoding="utf-8")
    (folder / "SPY_1m_10y.parquet").unlink()
    assert [s.symbol for s in discover_archives(root)] == ["QQQ"]


def test_1m_passthrough_and_hourly_bars_anchor_at_0930(root):
    store = ArchiveStore(root)
    minute, pinned = store.bars("SPY", "1m", "2026-10-30", "2026-10-30")
    assert len(minute) == 390 and pinned.timeframe == "1m"
    first = minute.iloc[0]["timestamp"]
    assert first == pd.Timestamp("2026-10-30 13:30", tz="UTC")  # 09:30 EDT
    hourly, _ = store.bars("SPY", "1h", "2026-10-30", "2026-11-02")
    local = hourly["timestamp"].dt.tz_convert("America/New_York")
    assert local.iloc[0].strftime("%H:%M") == "09:30"
    assert local.iloc[6].strftime("%H:%M") == "15:30"  # the closing stub bucket
    assert len(hourly) == 14
    assert local.iloc[7] == pd.Timestamp("2026-11-02 09:30", tz="America/New_York")
    assert hourly["timestamp"].iloc[7] == pd.Timestamp("2026-11-02 14:30", tz="UTC")  # EST


def test_daily_bars_aggregate_the_session(root):
    store = ArchiveStore(root)
    daily, _ = store.bars("SPY", "1D", "2026-10-30", "2026-11-02")
    minute, _ = store.bars("SPY", "1m", "2026-10-30", "2026-10-30")
    assert len(daily) == 2
    day = daily.iloc[0]
    assert day["open"] == minute.iloc[0]["open"]
    assert day["high"] == minute["high"].max()
    assert day["low"] == minute["low"].min()
    assert day["close"] == minute.iloc[-1]["close"]
    assert day["volume"] == minute["volume"].sum()
    assert day["timestamp"].tz_convert("America/New_York").strftime("%H:%M") == "09:30"


def test_bars_over_cap_returns_422_with_hint(root, monkeypatch):
    import products.aegis.data as module

    monkeypatch.setattr(module, "BAR_CAP", 100)
    store = ArchiveStore(root)
    with pytest.raises(BarsTooLarge) as info:
        store.bars("SPY", "1m", "2026-10-30", "2026-11-02")
    assert info.value.count == 780 and info.value.cap == 100
    assert "narrow the range" in str(info.value)
    assert BAR_CAP == 200_000 and TIMEFRAMES == ("1m", "15m", "30m", "1h", "1D")


def test_pinned_source_has_file_sha_and_data_hash(root):
    store = ArchiveStore(root)
    frame, pinned = store.bars("QQQ", "30m", "2026-10-30", "2026-11-02")
    assert pinned.symbol == "QQQ" and pinned.vintage == "20260301T000000000000Z"
    assert pinned.timeframe == "30m" and pinned.start == date(2026, 10, 30)
    assert pinned.resampling_policy == "rth-anchored-v1"
    assert len(pinned.sha256) == 64 and len(pinned.data_hash) == 64
    assert pinned.bar_count == len(frame)
    _, pinned_again = store.bars("QQQ", "30m", "2026-10-30", "2026-11-02")
    assert pinned_again.data_hash == pinned.data_hash
    _, other = store.bars("QQQ", "30m", "2026-10-30", "2026-10-30")
    assert other.data_hash != pinned.data_hash
    records = to_records(frame)
    assert set(records[0]) == {"time", "open", "high", "low", "close", "volume"}
    assert records[0]["time"] == int(frame.iloc[0]["timestamp"].value // 1_000_000)


def test_load_pinned_detects_changed_file(root):
    store = ArchiveStore(root)
    frame, pinned = store.bars("QQQ", "1h", "2026-10-30", "2026-11-02")
    reloaded = ArchiveStore(root).load_pinned(pinned)
    assert reloaded.equals(frame)
    write_archive(root, "20260301T000000000000Z", "QQQ", price=300.0)  # same path, new bytes
    with pytest.raises(SourceUnavailable, match="sha256"):
        ArchiveStore(root).load_pinned(pinned)
    (root / pinned.relative_path).unlink()
    with pytest.raises(SourceUnavailable, match="missing"):
        ArchiveStore(root).load_pinned(pinned)


def test_cache_computes_each_timeframe_once(root):
    store = ArchiveStore(root)
    store.bars("SPY", "1h", "2026-10-30", "2026-10-30")
    store.bars("SPY", "1h", "2026-11-02", "2026-11-02")
    assert store.resample_count == 1
    store.warm(["SPY"])
    assert store.resample_count == len(TIMEFRAMES)
    store.bars("SPY", "1D", "2026-10-30", "2026-11-02")
    assert store.resample_count == len(TIMEFRAMES)


# --- Mission 10: ten years in one process ------------------------------------------------------------


def test_the_store_holds_one_minute_copy(root):
    store = ArchiveStore(root)
    store.bars("QQQ", "1m", "2026-10-30", "2026-11-02")
    archive = store.source("QQQ")
    assert (
        store._frame(archive, "1m")
        is store._frames[(archive.vintage, archive.symbol, "__minutes__")]
    )


def test_selection_by_local_dates_is_unchanged(root):
    store = ArchiveStore(root)
    spans = (
        ("2026-10-30", "2026-10-30"),
        ("2026-10-31", "2026-11-02"),
        ("2026-10-30", "2026-11-02"),
    )
    for timeframe in TIMEFRAMES:
        full = store._frame(store.source("QQQ"), timeframe)
        dates = full["timestamp"].dt.tz_convert("America/New_York").dt.date
        for start, end in spans:
            frame, _ = store.bars("QQQ", timeframe, start, end)
            keep = (dates >= date.fromisoformat(start)) & (dates <= date.fromisoformat(end))
            assert frame.equals(full[keep].reset_index(drop=True)), (timeframe, start, end)


def test_archive_frame_equals_the_rows_path(root):
    from products.aegis.backtest import (
        BacktestSettings,
        _data_key,
        _prepare_frame,
        prepare_archive_frame,
        prepared_request,
        run_prepared,
    )
    from products.aegis.optimize import engine_rows
    from products.aegis.results import canonical_payload, result_hash
    from products.aegis.strategy import default_strategy

    frame, pinned = ArchiveStore(root).bars("QQQ", "1m", "2026-10-30", "2026-11-02")
    direct = prepare_archive_frame(frame, "QQQ")
    via_rows = _prepare_frame(engine_rows(frame, "QQQ"))
    assert direct.equals(via_rows) and list(direct.columns) == list(via_rows.columns)
    assert _data_key(direct) == _data_key(via_rows)
    request = prepared_request(default_strategy(), BacktestSettings())
    identity = pinned.model_dump(mode="json")
    hashes = {
        result_hash(
            canonical_payload(run_prepared(request, f, _data_key(f)), default_strategy(), identity)
        )
        for f in (direct, via_rows)
    }
    assert len(hashes) == 1
    from test_aegis_walkforward import wave_bars

    wave = pd.DataFrame(wave_bars(n=300))
    assert prepare_archive_frame(wave, "QQQ").equals(_prepare_frame(engine_rows(wave, "QQQ")))
