from datetime import UTC, date, datetime, timedelta

import pytest
from triad.lab.calendar import Calendar
from triad.lab.contracts import Bar, Experiment, Partition
from triad.lab.data import Archive, FixtureProvider, quality
from triad.lab.engine import run_engine, sequence_analysis

pytestmark = pytest.mark.triad

START = datetime(2026, 9, 14, 13, 30, tzinfo=UTC)
END = START + timedelta(hours=1)


def dataset(tmp_path):
    archive = Archive(tmp_path)
    provider = FixtureProvider()
    raw = provider.fetch_bars("LABTEST", START, END)
    metadata = archive.preserve(raw, provider, "LABTEST", START, END, "fixture")
    rows = archive.normalize(raw, metadata)
    report, bars = quality(rows, "LABTEST", START, END)
    manifest = archive.publish(bars, metadata, report)
    return archive, rows, manifest


def experiment(**updates):
    return Experiment(
        name="test",
        description="fixture",
        hypothesis="fixture",
        dataset_id="fixture",
        dataset_version="v1",
        symbols=("LABTEST",),
        start_time=START,
        end_time=END,
        code_commit="fixture",
        environment={},
        acceptance_criteria=("deterministic",),
        partitions=(Partition(name="test", start=START, end=END),),
        **updates,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("high", 1),
        ("low", 999),
        ("open", -1),
        ("volume", -1),
        ("close", float("nan")),
        ("timestamp", "2026-09-14T13:30:00"),
        ("symbol", "../bad"),
    ],
)
def test_invalid_canonical_schema(tmp_path, field, value):
    _, rows, _ = dataset(tmp_path)
    with pytest.raises(ValueError):
        Bar.model_validate({**rows[0], field: value})


def test_quality_duplicates_gaps_order_symbols_timezone(tmp_path):
    _, rows, _ = dataset(tmp_path)
    for modified in (
        [*rows, rows[0]],
        rows[1:],
        rows[::-1],
        [{**rows[0], "symbol": "OTHER"}, *rows[1:]],
        [{**rows[0], "timezone": "wrong"}, *rows[1:]],
    ):
        assert quality(modified, "LABTEST", START, END)[0]["status"] == "FAIL"


def test_calendar_holidays_weekends_early_close_and_dst():
    c = Calendar()
    assert c.bounds(date(2026, 11, 26)) is None
    assert c.bounds(date(2026, 9, 19)) is None
    a, b = c.bounds(date(2026, 11, 27))
    assert len(c.expected(a, b)) == 210
    assert c.classify(datetime(2026, 9, 14, 12, tzinfo=UTC)) == "PRE_MARKET"
    assert c.classify(datetime(2026, 9, 14, 21, tzinfo=UTC)) == "AFTER_HOURS"
    assert c.bounds(date(2026, 1, 2))[0].hour == 14
    assert c.bounds(date(2026, 9, 14))[0].hour == 13
    with pytest.raises(ValueError):
        c.bounds(date(2027, 1, 4))


@pytest.mark.parametrize(
    "resolution,count", [("5m", 12), ("15m", 4), ("30m", 2), ("1h", 1), ("1d", 1)]
)
def test_resampling_and_manifest_lineage(tmp_path, resolution, count):
    archive, _, manifest = dataset(tmp_path)
    derived = archive.derive(manifest, resolution)
    base, frame = archive.load(manifest), archive.load(derived)
    assert len(frame) == count
    assert frame.volume.sum() == base.volume.sum()
    assert frame.iloc[0].open == base.iloc[0].open
    assert frame.iloc[-1].close == base.iloc[-1].close
    assert frame.high.max() == base.high.max()
    assert derived.provenance["parent_dataset"] == manifest.dataset_id
    assert (tmp_path / f"data/manifests/{manifest.dataset_id}.json").exists()


def test_corruption_and_no_raw_overwrite(tmp_path):
    archive, _, manifest = dataset(tmp_path)
    target = tmp_path / manifest.canonical_paths[0]
    target.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="corruption"):
        archive.load(manifest)
    with pytest.raises(FileExistsError):
        archive.preserve(b"[]", FixtureProvider(), "LABTEST", START, END, "fixture")


def test_known_long_short_costs_and_next_bar_fills(tmp_path):
    archive, _, manifest = dataset(tmp_path)
    frame = archive.load(manifest).iloc[:6].copy()
    prices = [100, 101, 103, 102, 104, 101]
    for field in ("open", "high", "low", "close"):
        frame[field] = prices
    exp = experiment(parameters={"period": 2, "hold": 1}, fees_model={"fixed": 1})
    result = run_engine(frame, exp)
    long = [t for t in result["trades"] if t["direction"] == "LONG"]
    short = [t for t in result["trades"] if t["direction"] == "SHORT"]
    assert long[0]["entry_price"] == 101 and long[0]["exit_price"] == 103
    assert long[0]["gross_pnl"] == 20 and long[0]["net_pnl"] == 18
    assert short[0]["net_pnl"] == -22
    assert all(
        t["entry_time"] >= t["signal_time"] and t["entry_time"] > START for t in long + short
    )
    slip = run_engine(
        frame,
        experiment(
            parameters={"period": 2, "hold": 1},
            fees_model={"per_share": 0.01, "bps": 2},
            slippage_model={"bps": 5, "spread_bps": 2},
        ),
    )
    assert slip["trades"][0]["slippage"] > 0
    assert slip["trades"][0]["net_pnl"] < slip["trades"][0]["gross_pnl"]


def test_determinism_future_data_and_direction_separation(tmp_path):
    archive, _, manifest = dataset(tmp_path)
    frame = archive.load(manifest)
    exp = experiment()
    first = run_engine(frame, exp)
    assert first["content_hash"] == run_engine(frame, exp)["content_hash"]
    changed = frame.copy()
    changed.loc[changed.index[-5:], "close"] *= 1.001
    second = run_engine(changed, exp)
    cut = frame.iloc[-6].bar_end
    assert [d for d in first["decisions"] if d["decision_time"] <= cut] == [
        d for d in second["decisions"] if d["decision_time"] <= cut
    ]
    long_only = run_engine(frame, experiment(directions=("LONG",)))
    assert set(long_only["metrics"]) == {"LONG"}
    assert long_only["metrics"]["LONG"] == first["metrics"]["LONG"]
    assert (
        run_engine(frame, experiment(directions=("SHORT",)))["metrics"]["SHORT"]
        == first["metrics"]["SHORT"]
    )


def test_feature_and_corporate_action_columns_not_exposed(tmp_path):
    from triad.lab.engine import FixtureStrategy

    archive, _, manifest = dataset(tmp_path)
    frame = archive.load(manifest)
    frame["future_normalization"] = 999
    frame["future_regime"] = "profit"
    frame["future_split"] = 2

    class Inspect(FixtureStrategy):
        def generate_signal(self, history, direction):
            assert isinstance(history, tuple)
            assert not hasattr(history[-1], "future_regime")
            assert not hasattr(history[-1], "future_normalization")
            assert not hasattr(history[-1], "future_split")
            return super().generate_signal(history, direction)

    assert run_engine(frame, experiment(), strategy=Inspect({"period": 20, "hold": 5}))["trades"]


def test_partitions_and_sequence_risk():
    with pytest.raises(ValueError, match="Overlapping"):
        Experiment.model_validate(
            {
                **experiment().model_dump(),
                "partitions": [
                    {"name": "training", "start": START, "end": END},
                    {"name": "test", "start": START, "end": END},
                ],
            }
        )
    a, b = sequence_analysis([0.2, -0.1, -0.1, 0.2]), sequence_analysis([0.2, -0.1, 0.2, -0.1])
    assert a["compound_return"] == pytest.approx(b["compound_return"])
    assert a["max_drawdown"] != b["max_drawdown"]


def test_incomplete_derived_bucket_rejected_for_backtest(tmp_path):
    archive, _, manifest = dataset(tmp_path)
    derived = archive.derive(manifest, "1d")
    frame = archive.load(derived)
    assert frame.partial_dataset_bucket.all()
    with pytest.raises(ValueError, match="Incomplete"):
        run_engine(frame, experiment())


def test_version_and_corrupt_manifest(tmp_path):
    archive, _, manifest = dataset(tmp_path)
    assert len(manifest.dataset_version) == 64
    with pytest.raises(ValueError, match="checksum"):
        archive.load(manifest.model_copy(update={"checksum": "bad"}))


def test_walk_forward_skeleton_never_claims_validation():
    from triad.lab.planning import walk_forward_windows

    windows = walk_forward_windows(START, START + timedelta(days=30), 10, 5)
    assert len(windows) == 4
    assert all(
        w["training"][1] == w["test"][0] and w["validation_status"] == "NOT_RUN" for w in windows
    )
    with pytest.raises(ValueError):
        walk_forward_windows(START, START + timedelta(days=100), 1, 1, 2)


def test_resource_limits_and_cancellation(tmp_path):
    from triad.lab.contracts import LabLimits

    archive, _, manifest = dataset(tmp_path)
    frame = archive.load(manifest)
    with pytest.raises(ValueError, match="ceiling"):
        run_engine(frame, experiment(), LabLimits(max_rows=10))

    def stopped():
        raise PermissionError("Killed")

    with pytest.raises(PermissionError, match="Killed"):
        run_engine(frame, experiment(), guard=stopped)
