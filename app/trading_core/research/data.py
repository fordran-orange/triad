"""Provider-neutral fixture ingestion, deterministic quality, immutable portable files."""

import hashlib
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import Protocol

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from trading_core.research.calendar import NY, Calendar
from trading_core.research.contracts import Bar, DatasetManifest, LabLimits
from trading_core.work import now, uid


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
    ).encode()


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(encoded(data))


class MarketDataProvider(Protocol):
    name: str
    mode: str

    def fetch_bars(self, symbol, start, end): ...
    def get_capabilities(self): ...
    def supported_resolutions(self): ...
    def supported_asset_classes(self): ...
    def health_check(self): ...


class FixtureProvider:
    name = "local-engine-fixture-v1"
    mode = "FIXTURE"

    def get_capabilities(self):
        return {
            "mode": self.mode,
            "name": self.name,
            "symbols": ["LABTEST"],
            "purpose": "engine validation only",
        }

    def supported_resolutions(self):
        return ("1m",)

    def supported_asset_classes(self):
        return ("equity",)

    def health_check(self):
        return {"status": "AVAILABLE", "mode": "FIXTURE"}

    def fetch_bars(self, symbol, start, end):
        if symbol != "LABTEST":
            raise ValueError("Only explicitly synthetic LABTEST is available")
        times = Calendar().expected(start, end)
        if len(times) > LabLimits().max_rows:
            raise ValueError("Fixture row ceiling")
        rows = []
        for i, timestamp in enumerate(times):
            price = round(100 + 0.003 * i + math.sin(i / 9), 6)
            close = round(price + 0.08 * math.cos(i / 3), 6)
            rows.append(
                {
                    "timestamp": timestamp.astimezone(NY).isoformat(),
                    "symbol": symbol,
                    "open": price,
                    "high": max(price, close) + 0.15,
                    "low": min(price, close) - 0.15,
                    "close": close,
                    "volume": 1000 + i % 100,
                }
            )
        return encoded(rows)


def quality(rows, symbol, start, end, calendar=None):
    calendar = calendar or Calendar()
    issues = []
    times = []
    canonical = []
    raw_hashes = [digest(encoded(r)) for r in rows]
    if len(raw_hashes) != len(set(raw_hashes)):
        issues.append(
            {"check": "duplicate_source_records", "count": len(raw_hashes) - len(set(raw_hashes))}
        )
    for index, row in enumerate(rows):
        try:
            item = Bar.model_validate(row)
            if item.symbol != symbol or item.source_symbol != symbol:
                raise ValueError("symbol inconsistency")
            if item.timezone != "America/New_York" or item.exchange != "XNYS":
                raise ValueError("timezone/exchange inconsistency")
            if calendar.classify(item.timestamp) != "REGULAR":
                raise ValueError("unexpected session")
            canonical.append(item)
            times.append(item.timestamp)
        except (ValueError, TypeError):
            issues.append({"check": "schema_ohlc_timezone_symbol_session", "row": index})
    if len(times) != len(set(times)):
        issues.append({"check": "duplicate_timestamps", "count": len(times) - len(set(times))})
    if times != sorted(times):
        issues.append({"check": "out_of_order_records"})
    expected = set(calendar.expected(start, end))
    gaps = sorted(expected - set(times))
    extra = sorted(set(times) - expected)
    if gaps:
        issues.append(
            {
                "check": "missing_expected_timestamps",
                "count": len(gaps),
                "sample": [t.isoformat() for t in gaps[:50]],
            }
        )
    if extra:
        issues.append({"check": "unexpected_timestamps", "count": len(extra)})
    return {
        "status": "FAIL" if issues else "PASS",
        "issues": issues,
        "expected_bars": len(expected),
        "rows": len(rows),
        "gaps": [t.isoformat() for t in gaps],
        "calendar": calendar.version,
        "transformations": [
            "UTC timestamp normalization only; no repairs, deduplication, sorting or filling"
        ],
    }, canonical


class Archive:
    def __init__(self, root, limits=None):
        self.root = Path(root).resolve()
        self.limits = limits or LabLimits()

    def preserve(self, raw, provider, symbol, start, end, job_id):
        if len(raw) > self.limits.max_bytes:
            raise ValueError("Raw byte ceiling exceeded")
        path = self.root / "data/raw" / job_id / "source.json"
        path.parent.mkdir(parents=True, exist_ok=False)
        with path.open("xb") as handle:
            handle.write(raw)
        metadata = {
            "raw_id": job_id,
            "provider": provider.name,
            "mode": provider.mode,
            "request": {
                "symbol": symbol,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "resolution": "1m",
            },
            "downloaded_at": now().isoformat(),
            "original_filename": "source.json",
            "checksum": digest(raw),
            "path": path.relative_to(self.root).as_posix(),
        }
        save_json(path.with_name("metadata.json"), metadata)
        return metadata

    def normalize(self, raw, metadata):
        if digest(raw) != metadata["checksum"]:
            raise ValueError("Raw corruption")
        rows = json.loads(raw)
        if not isinstance(rows, list) or not 0 < len(rows) <= self.limits.max_rows:
            raise ValueError("Invalid or oversized row collection")
        version = digest(
            encoded(
                {"raw": metadata["checksum"], "ingested": metadata["downloaded_at"], "schema": "v2"}
            )
        )
        return [
            {
                **r,
                "source": metadata["provider"],
                "source_symbol": metadata["request"]["symbol"],
                "timezone": "America/New_York",
                "ingested_at": metadata["downloaded_at"],
                "dataset_version": version,
                "provenance_id": metadata["raw_id"],
            }
            for r in rows
        ]

    def publish(self, bars, metadata, quality_report, parent=None, resolution="1m"):
        if quality_report["status"] != "PASS":
            raise ValueError("Failed quality cannot enter canonical archive")
        rows = [b.model_dump() if isinstance(b, Bar) else dict(b) for b in bars]
        frame = pd.DataFrame(rows)
        identifier = uid()
        version = digest(encoded(rows))
        frame["dataset_version"] = version
        if "bar_end" not in frame:
            frame["bar_end"] = [t + timedelta(minutes=1) for t in frame.timestamp]

        paths = []
        checksums = {}
        for (symbol, year, month), group in frame.groupby(
            ["symbol", frame.timestamp.dt.year, frame.timestamp.dt.month], sort=True
        ):
            path = (
                self.root
                / f"data/canonical/asset_class=equity/symbol={symbol}/year={year}/month={month:02}/{identifier}/{resolution}.parquet"
            )
            path.parent.mkdir(parents=True, exist_ok=False)
            table = pa.Table.from_pandas(group.reset_index(drop=True), preserve_index=False)
            table = table.replace_schema_metadata(
                {
                    b"contract": b"triad.ohlcv.v2",
                    b"timestamp_semantics": b"UTC interval start, bar_end exclusive",
                    b"mode": metadata["mode"].encode(),
                }
            )
            with path.open("xb") as handle:
                pq.write_table(table, handle, compression="zstd")
            relative = path.relative_to(self.root).as_posix()
            paths.append(relative)
            checksums[relative] = digest(path.read_bytes())
        manifest = DatasetManifest(
            dataset_id=identifier,
            dataset_version=version,
            symbols=tuple(sorted(frame.symbol.unique())),
            resolution=resolution,
            start_time=frame.timestamp.min().to_pydatetime(),
            end_time=frame.bar_end.max().to_pydatetime(),
            row_count=len(frame),
            source=metadata["provider"],
            mode=metadata["mode"],
            raw_sources=(metadata,),
            canonical_paths=tuple(paths),
            checksum=digest(encoded(checksums)),
            file_checksums=checksums,
            quality_status="PASS",
            provenance={
                "raw_id": metadata["raw_id"],
                "parent_dataset": parent,
                "quality_report": quality_report,
            },
            transformations=tuple(quality_report["transformations"]),
            size_bytes=sum((self.root / p).stat().st_size for p in paths),
        )
        save_json(self.root / f"data/manifests/{identifier}.json", manifest.model_dump(mode="json"))
        return manifest

    def load(self, manifest):
        if manifest.row_count > self.limits.max_rows or manifest.size_bytes > self.limits.max_bytes:
            raise ValueError("Dataset exceeds configured resource ceiling")
        if digest(encoded(manifest.file_checksums)) != manifest.checksum:
            raise ValueError("Manifest checksum mismatch")
        frames = []
        for path in manifest.canonical_paths:
            target = (self.root / path).resolve()
            if not target.is_relative_to(self.root / "data/canonical"):
                raise PermissionError("Untrusted archive path")
            if (
                target.stat().st_size > self.limits.max_bytes
                or digest(target.read_bytes()) != manifest.file_checksums[path]
            ):
                raise ValueError("Canonical file corruption")
            parquet = pq.ParquetFile(target)
            if parquet.metadata.num_rows > self.limits.max_rows:
                raise ValueError("Parquet metadata exceeds row limit")
            frames.append(parquet.read().to_pandas())
        frame = pd.concat(frames, ignore_index=True).sort_values(["timestamp", "symbol"])
        if (
            len(frame) != manifest.row_count
            or not (frame.dataset_version == manifest.dataset_version).all()
        ):
            raise ValueError("Manifest/data mismatch")
        return frame

    def derive(self, manifest, resolution):
        if manifest.resolution != "1m" or resolution not in {"5m", "15m", "30m", "1h", "1d"}:
            raise ValueError("Derive supported timeframes directly from canonical 1m")
        frame = self.load(manifest)
        minutes = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}[resolution]
        groups = {}
        for row in frame.to_dict("records"):
            day = row["timestamp"].astimezone(NY).date()
            opening, closing = Calendar().bounds(day)
            bucket = int((row["timestamp"] - opening).total_seconds() // 60) // minutes
            groups.setdefault((row["symbol"], day, bucket), []).append(row)
        output = []
        for (_, day, bucket), rows in groups.items():
            opening, closing = Calendar().bounds(day)
            start = opening + timedelta(minutes=bucket * minutes)
            end = min(start + timedelta(minutes=minutes), closing)
            output.append(
                {
                    **rows[0],
                    "timestamp": rows[0]["timestamp"],
                    "bar_end": min(end, rows[-1]["bar_end"]),
                    "partial_dataset_bucket": len(rows) != int((end - start).total_seconds() / 60),
                    "open": rows[0]["open"],
                    "high": max(r["high"] for r in rows),
                    "low": min(r["low"] for r in rows),
                    "close": rows[-1]["close"],
                    "volume": sum(r["volume"] for r in rows),
                    "trade_count": sum(r["trade_count"] for r in rows)
                    if all(pd.notna(r.get("trade_count")) for r in rows)
                    else None,
                    "vwap": sum(r["vwap"] * r["volume"] for r in rows if r["volume"] > 0)
                    / sum(r["volume"] for r in rows)
                    if sum(r["volume"] for r in rows) > 0
                    and all(pd.notna(r.get("vwap")) for r in rows if r["volume"] > 0)
                    else None,
                    "base_bar_count": len(rows),
                    "partial_session_bucket": (end - start).total_seconds() < minutes * 60,
                }
            )
        report = {
            "status": "PASS",
            "issues": [],
            "gaps": [],
            "transformations": [
                f"{resolution}: regular-session anchored, left-closed/right-open; terminal bucket retained; first/max/min/last/sum"
            ],
        }
        return self.publish(
            output,
            manifest.raw_sources[0],
            report,
            parent=manifest.dataset_id,
            resolution=resolution,
        )
