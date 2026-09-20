"""Retain and audit the three operator-supplied archives; never publish failed data.

Run with the project Python. Audit-only calendar dependencies are installed in
data/temp/hf-audit-deps (exchange_calendars==4.13.2, pandas<3). This deliberately
does not change Core's calendar, execution settings, or eligibility policy.
"""

import argparse
import gzip
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "data/temp/hf-audit-deps"))

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from trading_core.research.contracts import DatasetManifest
from trading_core.research.data import digest, encoded, save_json

SYMBOLS = ("SPY", "QQQ", "ITOT")
VERSION = "hf-retention-audit-v1"
EVIDENCE = {
    "dictionary": "https://hfdatalibrary.com/pages/dictionary",
    "methodology": "https://hfdatalibrary.com/pages/docs",
    "versions": "https://hfdatalibrary.com/pages/versions",
    "license": "https://hfdatalibrary.com/pages/terms",
    "upstream": "https://github.com/elkassabgi/hfdatalibrary",
    "calendar": "https://pypi.org/project/exchange_calendars/4.13.2/",
}


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def extract(source, destination, max_bytes=1024**3):
    """Verify gzip CRC through EOF; bound expansion; never replace destination.

    Gzip headers cannot choose a path. Stage in the destination directory and
    exclusively create the final path only after validation. A conflicting
    existing file is an error, including when it appears during publication.
    """
    source, destination = Path(source), Path(destination)
    result = {
        "source_path": str(source),
        "destination_path": str(destination),
        "compressed_size": source.stat().st_size,
        "raw_file_hash": sha(source),
        "uncompressed_size": 0,
        "errors": [],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as out:
            temporary = Path(out.name)
            with gzip.open(source, "rb") as stream:
                while chunk := stream.read(1024**2):
                    result["uncompressed_size"] += len(chunk)
                    if result["uncompressed_size"] > max_bytes:
                        raise ValueError("Uncompressed size ceiling exceeded")
                    out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        result["extracted_file_hash"] = sha(temporary)
        if destination.exists():
            result["existing_destination_hash"] = sha(destination)
            if result["existing_destination_hash"] != result["extracted_file_hash"]:
                raise ValueError(
                    "Existing destination differs from gzip payload; retained unchanged"
                )
            result["action"] = "verified_existing_identical"
        else:
            # Hard link is atomic, same-volume, and refuses an existing target.
            os.link(temporary, destination)
            result["action"] = "decompressed_new"
        if sha(source) != result["raw_file_hash"]:
            raise ValueError("Source changed during decompression")
    except Exception as exc:  # noqa: BLE001 - retain all extraction failures as evidence
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["action"] = "failed"
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return result


def inspect(path, symbol, output):
    import exchange_calendars as xcals

    parquet = pq.ParquetFile(path)
    frame = parquet.read().to_pandas()  # Decode every row group; malformed Parquet fails.
    expected_columns = ["datetime", "Open", "High", "Low", "Close", "Volume", "source"]
    if list(frame.columns) != expected_columns:
        raise ValueError(f"Unexpected schema: {list(frame.columns)}")
    t = frame.datetime
    if not pd.api.types.is_datetime64_ns_dtype(t) or t.dt.tz is not None or t.isna().any():
        raise ValueError("Expected non-null naive timestamp[ns]; do not guess other encodings")
    # Vendor dictionary explicitly specifies Eastern Time. Localization is only
    # an analytical view; raw timestamps and values are never rewritten.
    aware = t.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    utc = pd.DatetimeIndex(aware.dt.tz_convert("UTC"))
    first, last = t.min(), t.max()
    calendar = xcals.get_calendar("XNYS", start=str(first.date()), end=str(last.date()))
    schedule = calendar.schedule
    expected = calendar.minutes  # side=left below is asserted; excludes closing instant.
    assert calendar.side == "left"
    actual = utc.dropna().unique()
    missing = expected.difference(actual)
    regular = utc.isin(expected)
    session_dates = set(schedule.index.strftime("%Y-%m-%d"))
    dates = t.dt.strftime("%Y-%m-%d")
    missing_sessions = sorted(session_dates - set(dates[regular]))
    close_by_day = {str(d.date()): c for d, c in schedule["close"].items()}
    open_by_day = {str(d.date()): o for d, o in schedule["open"].items()}
    opens = pd.to_datetime(dates.map(open_by_day), utc=True)
    closes = pd.to_datetime(dates.map(close_by_day), utc=True)
    minutes = t.dt.hour * 60 + t.dt.minute
    pre = (aware < opens) & (minutes >= 240) & opens.notna()
    post = (aware >= closes) & (minutes < 1200) & closes.notna()
    prices = frame[["Open", "High", "Low", "Close"]]
    bad_ohlc = (frame.High < prices.max(axis=1)) | (frame.Low > prices.min(axis=1))
    malformed = frame.isna().any(axis=1) | ~np.isfinite(frame[expected_columns[1:6]]).all(axis=1)
    checks = {
        "duplicate_timestamps": int(t.duplicated().sum()),
        "out_of_order_records": int((t.diff() < pd.Timedelta(0)).sum()),
        "invalid_ohlc": int(bad_ohlc.sum()),
        "negative_price_rows": int((prices < 0).any(axis=1).sum()),
        "zero_price_rows": int((prices == 0).any(axis=1).sum()),
        "negative_volume": int((frame.Volume < 0).sum()),
        "zero_volume": int((frame.Volume == 0).sum()),
        "malformed_rows": int(malformed.sum()),
        "off_minute_timestamps": int((t != t.dt.floor("min")).sum()),
        "dst_ambiguous_or_nonexistent": int(aware.isna().sum()),
        "unexpected_upstream_source": int((~frame.source.isin(["pitrading", "iex"])).sum()),
        "source_boundary_inconsistencies": int(
            (
                (t.lt("2022-03-07") & frame.source.ne("pitrading"))
                | (t.ge("2022-03-07") & frame.source.ne("iex"))
            ).sum()
        ),
        "missing_expected_bars": len(missing),
        "missing_expected_sessions": len(missing_sessions),
    }
    daily = (
        pd.DataFrame({"date": dates, "regular": regular})
        .groupby("date")
        .agg(observed_rows=("regular", "size"), regular_rows=("regular", "sum"))
    )
    expected_daily = pd.Series(
        expected.tz_convert("America/New_York").strftime("%Y-%m-%d")
    ).value_counts()
    missing_daily = pd.Series(
        missing.tz_convert("America/New_York").strftime("%Y-%m-%d")
    ).value_counts()
    daily = daily.reindex(sorted(set(daily.index) | session_dates), fill_value=0)
    daily["expected_regular"] = expected_daily.reindex(daily.index, fill_value=0)
    daily["missing_regular"] = missing_daily.reindex(daily.index, fill_value=0)
    daily.to_csv(output / f"{symbol}-daily-coverage.csv", index_label="date", mode="x")
    pd.DataFrame({"timestamp_utc": missing}).to_csv(
        output / f"{symbol}-missing-bars.csv", index=False, mode="x"
    )
    anomalous = (
        bad_ohlc
        | malformed
        | t.duplicated(keep=False)
        | (frame.Volume < 0)
        | (prices <= 0).any(axis=1)
    )
    frame.loc[anomalous].to_csv(
        output / f"{symbol}-anomalous-rows.csv", index_label="source_row", mode="x"
    )
    segments = {}
    for source, group in frame.groupby("source"):
        segments[source] = {
            "rows": len(group),
            "first": str(group.datetime.min()),
            "last": str(group.datetime.max()),
        }
    return {
        "symbol": symbol,
        "format": "Parquet",
        "schema": str(parquet.schema_arrow),
        "row_groups": parquet.num_row_groups,
        "rows_decoded": len(frame),
        "metadata_rows_match": len(frame) == parquet.metadata.num_rows,
        "timestamp_format": "Parquet timestamp[ns], naive; display YYYY-MM-DD HH:MM:SS",
        "timezone": "America/New_York per vendor dictionary; absent from file metadata",
        "timezone_consistency_limit": "DST validity and market-hour alignment checked; original offsets cannot be proven from naive timestamps",
        "symbol_convention": "Uppercase US ETF ticker inferred from operator-supplied filename; no symbol column",
        "adjustment": "Vendor documents split/dividend and splice adjustment; exact local vintage/factors unverified",
        "first_timestamp_local": str(first),
        "last_timestamp_local": str(last),
        "first_timestamp_utc": utc.min().isoformat(),
        "last_timestamp_utc": utc.max().isoformat(),
        "total_rows": len(frame),
        "observed_dates": int(dates.nunique()),
        "observed_trading_dates": int(dates[regular].nunique()),
        "expected_sessions": len(schedule),
        "expected_regular_bars": len(expected),
        "actual_unique_regular_bars": int(actual.isin(expected).sum()),
        "regular_coverage_percent": round(100 * actual.isin(expected).sum() / len(expected), 6),
        "regular_rows": int(regular.sum()),
        "pre_market_rows": int(pre.sum()),
        "post_market_rows": int(post.sum()),
        "closed_or_other_rows": int((~regular & ~pre & ~post).sum()),
        "missing_sessions": missing_sessions,
        "checks": checks,
        "upstream_segments": segments,
        "calendar": f"exchange_calendars {xcals.__version__} XNYS side=left",
        "coverage_method": "Full first-to-last calendar dates, holidays/early closes included; [09:30, close). Missing bars may mean no venue trades, not corruption. Extended window descriptive only: 04:00-20:00 ET.",
        "quality_status": "FAIL",
        "publication_blockers": [
            "Core requires UNADJUSTED; vendor documents adjusted prices",
            "Core calendar supports 2026 only and bounded intervals; these archives cover ten years",
            "Core resource ceilings cannot load full archives",
            "Missing expected bars and/or session anomalies; Core requires complete regular sessions",
            "Exact local vendor version, adjustment factors and interval-label convention not authenticated",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--register", action="store_true", help="Register FAIL manifests using Core Ledger"
    )
    args = parser.parse_args()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "data/raw/HFDataLibrary" / run_id
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "run_id": run_id,
        "version": VERSION,
        "source": "HFDataLibrary",
        "evidence_urls": EVIDENCE,
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "implementation_sha256": sha(__file__),
        "datasets": [],
        "canonical_outputs": [],
        "normalization": "NONE; read-only NY localization for analysis only",
        "created_at": datetime.now(UTC).isoformat(),
    }
    for symbol in SYMBOLS:
        source = ROOT / f"{symbol}_1m_10y.parquet.gz"
        entry = {"symbol": symbol, "registration": "NOT_ATTEMPTED"}
        report["datasets"].append(entry)
        try:
            extraction = extract(source, source.with_suffix(""))
            entry["extraction"] = extraction
            if extraction["errors"]:
                continue
            for original in (source, source.with_suffix("")):
                with original.open("rb") as src, (output / original.name).open("xb") as dst:
                    shutil.copyfileobj(src, dst)
                if sha(original) != sha(output / original.name):
                    raise ValueError("Raw retention hash mismatch")
            details = inspect(output / source.with_suffix("").name, symbol, output)
            entry["inspection"] = details
            raw = {
                "provider": "HFDataLibrary",
                "mode": "REAL",
                "path": (output / source.name).relative_to(ROOT).as_posix(),
                "checksum": extraction["raw_file_hash"],
                "extracted_checksum": extraction["extracted_file_hash"],
                "original_path": str(source),
                "original_filename": source.name,
                "downloaded_at": None,
                "retained_at": report["created_at"],
                "request": {"symbol": symbol},
                "license_use_notes": {
                    "notes": "Vendor states CC BY 4.0 with attribution; PiTrading and IEX upstream terms also apply. Local download license/vintage not supplied.",
                    "urls": [EVIDENCE["license"], EVIDENCE["upstream"]],
                },
            }
            identifier = f"hf-{symbol.lower()}-{run_id}"
            manifest = DatasetManifest(
                dataset_id=identifier,
                dataset_version=extraction["raw_file_hash"],
                symbols=(symbol,),
                start_time=datetime.fromisoformat(details["first_timestamp_utc"]),
                end_time=datetime.fromisoformat(details["last_timestamp_utc"]),
                row_count=details["total_rows"],
                source="HFDataLibrary",
                mode="REAL",
                raw_sources=(raw,),
                canonical_paths=(),
                schema_version="hf.raw.parquet.v1",
                checksum=digest(encoded({})),
                file_checksums={},
                quality_status="FAIL",
                known_gaps=tuple(details["publication_blockers"]),
                adjustment_policy=details["adjustment"],
                timezone_policy=details["timezone"],
                calendar_version=details["calendar"],
                size_bytes=0,
                provenance={
                    "provenance_id": identifier,
                    "normalization_version": "none",
                    "audit_version": VERSION,
                    "quality_report": details,
                    "evidence_urls": EVIDENCE,
                    "audit_path": output.relative_to(ROOT).as_posix(),
                    "canonical_file_hash": None,
                    "coverage_end_semantics": "last observed timestamp, inclusive; interval label unverified",
                    "registration_intent": "Retained failed dataset only; not eligible for research execution",
                },
            )
            manifest_path = ROOT / "data/manifests" / f"{identifier}.json"
            save_json(manifest_path, manifest.model_dump(mode="json"))
            entry["manifest_path"] = str(manifest_path)
            if args.register:
                from trading_core.ledger import Ledger

                ledger = Ledger()
                ledger.put("DatasetManifest", manifest.model_dump(mode="json"), identifier)
                retained = ledger.get(identifier)
                assert retained["quality_status"] == "FAIL"
                from trading_core.integrations.data import LocalCanonicalStore

                assert identifier in {m.dataset_id for m in LocalCanonicalStore().manifests()}
                entry["registration"] = "REGISTERED_CORE_FAIL"
        except Exception as exc:  # noqa: BLE001 - continue other symbols and record failure
            entry["error"] = f"{type(exc).__name__}: {exc}"
    save_json(output / "report.json", report)
    print(output / "report.json")
    for entry in report["datasets"]:
        print(
            entry["symbol"],
            entry.get("inspection", {}).get("checks"),
            entry.get("error", entry["registration"]),
        )


if __name__ == "__main__":
    main()
