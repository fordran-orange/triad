from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError
from triad.market import SCHEMA, Candle1m, write_candles

pytestmark = pytest.mark.triad


def candle(**changes):
    row = {
        "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
        "symbol": "SYNTHETIC:TEST",
        "open": "1.123456789012",
        "high": "2",
        "low": "1",
        "close": "1.5",
        "volume": "10",
        "source": "synthetic_fixture",
        "ingested_at": datetime(2026, 1, 2, tzinfo=UTC),
        "data_version": "fixture-v1",
        "provenance_id": "fixture-001",
    }
    return Candle1m(**(row | changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"timestamp": datetime(2026, 1, 1)},  # noqa: DTZ001 - deliberately invalid input
        {"timestamp": datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)},
        {"high": "1"},
        {"low": "1.9"},
        {"volume": "-1"},
        {"close": "NaN"},
        {"ingested_at": datetime(2025, 1, 1, tzinfo=UTC)},
        {"source": ""},
        {"open": "1.1234567890123"},
    ],
)
def test_invalid_candles(changes):
    with pytest.raises(ValidationError):
        candle(**changes)


def test_parquet_roundtrip_and_no_overwrite(tmp_path):
    path = tmp_path / "candles.parquet"
    write_candles(path, [candle()])
    table = pq.read_table(path)
    assert table.schema == SCHEMA
    assert table.to_pylist()[0]["open"] == Decimal("1.123456789012")
    assert Candle1m(**table.to_pylist()[0]) == candle()
    with pytest.raises(FileExistsError):
        write_candles(path, [candle()])


def test_duplicate_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        write_candles(tmp_path / "duplicate.parquet", [candle(), candle()])


def test_offset_normalized_to_utc():
    row = candle(timestamp=datetime(2026, 1, 1, 1, tzinfo=timezone(timedelta(hours=1))))
    assert row.timestamp == datetime(2026, 1, 1, tzinfo=UTC)
