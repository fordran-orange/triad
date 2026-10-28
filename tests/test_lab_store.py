"""Optimization Lab v2, Phase 2: the trial store (layout 2, compaction, snapshots, reclamation).
Task 4: the layout-2 write path, the additive document fields and the chunk naming (F16)."""

import math
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from products.aegis import experiments as exp
from products.aegis.analysis import _columns, _paths_of, analyse
from products.aegis.jobs import JobRunner
from products.aegis.lab import identity
from products.aegis.lab import store as lab_store
from products.aegis.pool import METRICS, SCOPES
from products.aegis.surface import KERNEL_MS_PER_BAR, Budget, Parameter, Surface, build_grid
from products.aegis.surface import plan as plan_surface
from test_aegis_api import _experiment_body, _runner, _wait_experiment, client  # noqa: F401
from test_aegis_experiments import (  # noqa: F401 - `world` is the shared experiments fixture
    PINNED_DATA,
    ROWS,
    document_of,
    request,
    wait_for,
    world,
)

pytestmark = pytest.mark.aegis

LAYOUT2_FIELDS = (
    "cells_layout",
    "search_space",
    "sampler",
    "versions",
    "data_pinned",
    "execution",
    "counts",
    "lineage",
)


def chunk_names(folder: Path) -> list[str]:
    return [path.name for path in sorted(folder.glob("[0-9]*.parquet"))]


def finished_layout2(repository, library, document, runner=None, **overrides):
    """A new (layout-2) experiment created with its pinned data and run to `done`."""
    store = exp.ExperimentStore(repository)
    doc = exp.create(
        store,
        library,
        request(document, **overrides),
        bars=len(ROWS),
        max_workers=2,
        pinned=PINNED_DATA,
    )
    (runner or JobRunner(repository)).start(exp.ExperimentJob(doc, ROWS, PINNED_DATA, repository))
    assert wait_for(lambda: document_of(repository, doc.id).status in ("done", "failed"))
    done = document_of(repository, doc.id)
    assert done.status == "done", done.error
    return done


def stub_analysis(monkeypatch):
    """The first-pass analysis of test_aegis_experiments.py:257-271: the first five run cells are
    the plateau, so the refinement spends its budget on their neighbours."""

    def analyse_stub(table, grid, objective, tolerance, mode, seed, data_label):
        run = sorted(table.column("cell").to_pylist())
        return {
            "objective": objective,
            "tolerance": tolerance,
            "plateaus": [{"id": 1, "cells": run[:5], "centre": {"cell": run[0]}}],
            "recommendation": None,
            "statement": "stub",
            "cells_named": [],
        }

    stub = types.ModuleType("products.aegis.analysis")
    stub.analyse = analyse_stub
    stub.render_markdown = lambda report: "# stub"
    monkeypatch.setitem(sys.modules, "products.aegis.analysis", stub)


def sampled_overrides(name: str) -> dict:
    """The 20 x 20 surface under a 30-run budget: 20 first-pass and 10 refinement cells."""
    surface = Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=10, stop=29, step=1),
            Parameter(path="long_side.indicators.rsi.length", start=5, stop=24, step=1),
        ]
    )
    return {"name": name, "surface": surface.model_dump(), "budget": Budget(runs=30).model_dump()}


def legacy_document(repository, document, **overrides) -> exp.ExperimentDocument:
    """A document as `create` built one before layout 2 (experiments.py:381-408), saved without
    the layout-2 keys, as every document saved before this task is: never through `exp.create`,
    whose `init_layout2` would already have written the manifest."""
    body = request(document, **overrides)
    planned = plan_surface(
        document.spec, body.surface, body.budget, len(ROWS), KERNEL_MS_PER_BAR, 2, None
    )
    chunk = exp.CHUNK_CELLS
    now = "2026-10-20T00:00:00+00:00"
    doc = exp.ExperimentDocument(
        id=exp.ExperimentStore(repository).free_id(body.name),
        name=body.name,
        strategy_id=document.id,
        strategy_hash=document.strategy_hash,
        spec=document.spec,
        data=body.data,
        settings=body.settings,
        objective=body.objective,
        surface=body.surface,
        budget=body.budget,
        tolerance=body.tolerance,
        seed=body.seed,
        plan=planned.model_dump(mode="json"),
        status="queued",
        progress={
            "cells_done": 0,
            "cells_planned": planned.planned_runs,
            "chunks_done": 0,
            "chunks_total": math.ceil(planned.first_pass / chunk)
            + math.ceil(planned.refinement / chunk),
        },
        engine="kernel",
        created_at=now,
        updated_at=now,
        workers=2,
        chunk_cells=chunk,
    )
    raw = doc.model_dump(mode="json")
    for key in LAYOUT2_FIELDS:
        del raw[key]
    repository.save_experiment(raw)
    return doc


def write_recommendation(store, doc, plateau: list[int]) -> None:
    """Report 1 recommending `plateau`, as test_refine_creates_a_queued_child_from_the_recommended
    _plateau writes it."""
    report = {
        "recommendation": {
            "plateau": 1,
            "centre": {"cell": plateau[0]},
            "supported_peak": None,
            "fragile_peaks": [],
            "statement": "x",
        },
        "plateaus": [{"id": 1, "cells": plateau, "centre": {"cell": plateau[0]}}],
    }
    store.write_report(doc.id, 1, report, "# Recommendation — x\n")


def expected_v2_fields(paths: list[str]) -> list[tuple[str, pa.DataType]]:
    """The layout-2 chunk columns in order, with their Arrow types, written out literally."""
    words = pa.dictionary(pa.int32(), pa.string())
    return [
        ("trial_no", pa.int64()),
        ("cell", pa.int64()),
        *[(f"pos.{k}", pa.uint16()) for k in range(len(paths))],
        *[(path, pa.float64()) for path in paths],
        ("param_key", pa.binary(16)),
        ("pass", words),
        ("design", words),
        ("block", pa.uint8()),
        ("reused_from", pa.struct([("experiment", pa.string()), ("trial_no", pa.int64())])),
        ("status", words),
        ("valid", pa.bool_()),
        ("skip_reason", pa.string()),
        ("error", pa.string()),
        ("attempt", pa.uint8()),
        *[(f"{scope}.{metric}", pa.float64()) for scope in SCOPES for metric in METRICS],
        *[(f"{scope}.sharpe_trade", pa.float64()) for scope in SCOPES],
        ("elapsed_ms", pa.float64()),
        ("engine", words),
        ("chunk", pa.int32()),
        ("finished_at", pa.timestamp("ms", tz="UTC")),
    ]


def test_unreadable_chunk_never_overwritten(world):  # noqa: F811
    """F16: the next chunk is named by the highest index on disk + 1, so a chunk that landed and
    was later torn is never overwritten by the resumed run; its cells rerun under a new name."""
    repository, library, document = world
    store = exp.ExperimentStore(repository)
    gate = {"paused": False}

    def pause_at_two(done):
        if done == 2 and not gate["paused"]:
            gate["paused"] = True
            runner.cancel(job_id)

    runner = JobRunner(repository, after_unit=pause_at_two)
    doc = exp.create(store, library, request(document), bars=len(ROWS), max_workers=2)
    job = exp.ExperimentJob(doc, ROWS, PINNED_DATA, repository)
    job.pause_requested = True  # what POST /pause sets before cancelling
    job_id = runner.start(job)
    assert wait_for(lambda: document_of(repository, doc.id).status == "paused")
    folder = store.cells_dir(doc.id)
    assert chunk_names(folder) == ["000000.parquet", "000001.parquet"]
    (folder / "000001.parquet").write_bytes(b"x")  # a chunk torn after it landed

    listings: list[list[str]] = []

    def after_first(done):
        if done == 1:  # before finalize, which reclaims a done experiment's chunks from Task 5
            listings.append(chunk_names(folder))

    resumed = exp.ExperimentJob(document_of(repository, doc.id), ROWS, PINNED_DATA, repository)
    assert sorted(resumed.pending_cells()) == list(range(5, 12))
    JobRunner(repository, after_unit=after_first).start(resumed)
    assert wait_for(lambda: document_of(repository, doc.id).status in ("done", "failed"))
    assert document_of(repository, doc.id).status == "done"
    assert listings == [["000000.parquet", "000001.parquet", "000002.parquet"]]
    assert (folder / "000001.parquet").read_bytes() == b"x"  # never merged, never overwritten
    cells = store.cells(doc.id).column("cell").to_pylist()
    assert sorted(cells) == list(range(12))  # chunk 0 plus the rerun of 5-11, each once

    # The name rule itself: both name forms count, nothing else does, the watermark too.
    assert chunk_names(folder)[-1] == "000003.parquet" and store.next_chunk_index(doc.id) == 4
    (folder / "000007.parquet.tmp").write_bytes(b"torn")
    assert store.next_chunk_index(doc.id) == 8
    names = ("000012.parquet", "000012.parquet.tmp", "part-1.parquet", "manifest.json", "12.parq")
    assert [lab_store.chunk_index_of(Path(n)) for n in names] == [12, 12, None, None, None]
    manifest = lab_store.read_manifest(folder)
    assert manifest is not None and manifest.chunk_watermark == -1
    assert lab_store.next_chunk_index(folder, manifest) == 8
    manifest.chunk_watermark = 41  # a reclaimed chunk's index is never reused
    assert lab_store.next_chunk_index(folder, manifest) == 42
    assert lab_store.next_chunk_index(folder / "absent") == 0


def test_layout2_cells_projection_matches_legacy_columns(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    c, _, repository = client
    _runner(repository)
    created = c.post("/aegis/api/experiments", json=_experiment_body(c, name="projected"))
    assert created.status_code == 202, created.text
    experiment_id = created.json()["experiment_id"]
    done = _wait_experiment(c, experiment_id, ("done", "failed"))
    assert done["status"] == "done", done.get("error")
    store = exp.ExperimentStore(repository)
    document = store.get(experiment_id)
    paths = document.surface.paths()
    assert document.cells_layout == 2 and store.layout(experiment_id) == 2
    folder = store.cells_dir(experiment_id)
    assert "trial_no" in pq.read_schema(folder / chunk_names(folder)[0]).names

    table = store.cells(experiment_id)
    assert table.schema.equals(exp._cells_schema(paths)) and len(table) == 4
    assert _paths_of(_columns(table)) == paths  # never trial_no, pos.0, param_key, design, ...
    grid = build_grid(document.spec, document.surface, document.plan["bars"])
    report = analyse(table, grid, "net_pnl", 0.15, "exhaustive", 1, "QQQ")
    assert list(report["main_effects"]) == paths

    response = c.get(f"/aegis/api/experiments/{experiment_id}/cells?limit=10")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 4 and body["columns"] == exp._cells_schema(paths).names
    assert all(list(row) == body["columns"] for row in body["rows"])


def test_layout2_chunk_schema(world):  # noqa: F811
    repository, library, document = world
    doc = finished_layout2(repository, library, document)
    store = exp.ExperimentStore(repository)
    paths = doc.surface.paths()
    grid = build_grid(doc.spec, doc.surface, doc.plan["bars"])
    steps = {p.path: p.step for p in doc.surface.parameters}
    assert [(f.name, f.type) for f in exp._cells_schema_v2(paths)] == expected_v2_fields(paths)

    folder = store.cells_dir(doc.id)
    names = chunk_names(folder)
    assert names == ["000000.parquet", "000001.parquet", "000002.parquet"]
    cells = []
    for index, name in enumerate(names):
        path = folder / name
        table = pq.read_table(path)
        assert [(f.name, f.type) for f in table.schema] == expected_v2_fields(paths)
        assert float(pq.read_metadata(path).metadata[b"aegis.write_ms"]) >= 0.0
        for row in table.to_pylist():
            cell = row["cell"]
            cells.append(cell)
            values = grid.cell_values(cell)
            assert [row[f"pos.{k}"] for k in range(len(paths))] == list(grid.positions(cell))
            assert {path: row[path] for path in paths} == values
            assert len(row["param_key"]) == 16
            assert row["param_key"] == identity.param_key(doc.spec, values, steps)
            assert (row["pass"], row["design"], row["block"], row["attempt"]) == (
                "grid",
                "uniform",
                0,
                0,
            )
            assert (row["status"], row["valid"], row["skip_reason"], row["error"]) == (
                "ok",
                True,
                None,
                None,
            )
            assert row["reused_from"] is None and row["engine"] == "kernel"
            assert row["chunk"] == index and row["finished_at"].tzinfo is not None
            assert row["combined.net_pnl"] is not None and row["elapsed_ms"] > 0
    assert sorted(cells) == list(range(12))

    # Rows as tests and fixtures write them (no Schedule: each row carries its trial_no): the
    # status follows error, then skip_reason; the trade Sharpe is null when absent.
    def row_of(cell, **extra):
        return {
            "cell": cell,
            "trial_no": 100 + cell,
            "valid": True,
            "skip_reason": None,
            "params": grid.cell_values(cell),
            "metrics": None,
            "elapsed_ms": 1.0,
            "pass": "refine",
            **extra,
        }

    lab = {scope: {"sharpe_trade": 0.5, "trade_count": 30, "low_n": False} for scope in SCOPES}
    rows = [
        row_of(0, lab_metrics=lab),
        row_of(1, valid=False, skip_reason="insufficient bars"),
        row_of(2, error="boom"),
        row_of(2, attempt=1, lab_metrics={"combined": {"sharpe_trade": None}}),
    ]
    when = datetime(2026, 10, 28, 12, 0, 0, 123456, tzinfo=UTC)
    table = exp._cells_table_v2(rows, grid, doc.spec, steps, None, 7, when)
    assert table.schema.equals(exp._cells_schema_v2(paths))
    got = table.to_pylist()
    assert [r["trial_no"] for r in got] == [100, 101, 102, 102]
    assert [r["status"] for r in got] == ["ok", "invalid", "failed", "ok"]
    assert [r["valid"] for r in got] == [True, False, False, True]
    assert [r["attempt"] for r in got] == [0, 0, 0, 1] and got[2]["error"] == "boom"
    assert [r["combined.sharpe_trade"] for r in got] == [0.5, None, None, None]
    assert [r["design"] for r in got] == ["adaptive"] * 4
    assert {r["chunk"] for r in got} == {7}
    assert got[0]["finished_at"] == datetime(2026, 10, 28, 12, 0, 0, 123000, tzinfo=UTC)


def test_layout2_trial_numbers_follow_the_schedule(world, monkeypatch):  # noqa: F811
    repository, library, document = world
    store = exp.ExperimentStore(repository)
    exhaustive = finished_layout2(repository, library, document, name="exhaustive")
    for name in chunk_names(store.cells_dir(exhaustive.id)):
        table = pq.read_table(store.cells_dir(exhaustive.id) / name, columns=["trial_no", "cell"])
        assert table.column("trial_no").to_pylist() == table.column("cell").to_pylist()

    # Exhaustive with skips: the rank among the valid cells; sampled: the position in the list.
    beyond = Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=10, stop=310, step=50)
        ]
    )
    grid = build_grid(document.spec, beyond, len(ROWS))
    valid = list(grid.valid_indices_iter())
    assert grid.skipped_count >= 1
    ranks = exp.Schedule.exhaustive(grid)
    assert [ranks.trial_no_of(cell) for cell in valid] == list(range(len(valid)))
    with pytest.raises(KeyError):
        ranks.trial_no_of(grid.size - 1)  # the longest donchian is skipped on 260 bars
    listed = exp.Schedule.of([9, 2, 5])
    assert [listed.trial_no_of(cell) for cell in (9, 2, 5)] == [0, 1, 2]
    with pytest.raises(KeyError):
        listed.trial_no_of(3)

    # Sampled: refinement rows continue after the first pass, and every chunk lands only after
    # the document on disk lists the cells it numbers.
    stub_analysis(monkeypatch)
    monkeypatch.setattr(exp, "CHUNK_CELLS", 10)
    seen: list[tuple[str, list[int] | None, list[int] | None, list[int]]] = []
    write_chunk = exp.ExperimentStore.write_chunk

    def spy(self, experiment_id, chunk_index, rows, paths, table=None):
        stored = document_of(repository, experiment_id)
        label = rows[0]["pass"]
        cells = [r["cell"] for r in rows]
        seen.append((label, stored.first_pass_cells, stored.refinement_cells, cells))
        return write_chunk(self, experiment_id, chunk_index, rows, paths, table)

    monkeypatch.setattr(exp.ExperimentStore, "write_chunk", spy)
    sampled = finished_layout2(repository, library, document, **sampled_overrides("sampled"))
    first, refinement = sampled.first_pass_cells, sampled.refinement_cells
    assert len(first) == 20 and len(refinement) == 10
    assert [label for label, *_ in seen] == ["sample", "sample", "refine"]
    for label, stored_first, stored_refinement, cells in seen:
        listed_cells = stored_first if label == "sample" else stored_refinement
        assert listed_cells is not None and set(cells) <= set(listed_cells)
    schedule = exp.Schedule.from_document(sampled)
    numbers: dict[str, list[int]] = {"sample": [], "refine": []}
    for name in chunk_names(store.cells_dir(sampled.id)):
        table = pq.read_table(store.cells_dir(sampled.id) / name)
        for row in table.select(["trial_no", "cell", "pass"]).to_pylist():
            numbers[row["pass"]].append(row["trial_no"])
            assert row["trial_no"] == schedule.trial_no_of(row["cell"])
            if row["pass"] == "sample":
                assert row["trial_no"] == first.index(row["cell"])
            else:
                assert row["trial_no"] == len(first) + refinement.index(row["cell"])
    assert sorted(numbers["sample"]) == list(range(20))
    assert sorted(numbers["refine"]) == list(range(20, 30))


def test_layout2_document_fields_survive_commit_and_decide(world, monkeypatch):  # noqa: F811
    repository, library, document = world
    store = exp.ExperimentStore(repository)
    exhaustive = finished_layout2(repository, library, document, name="exhaustive")
    stub_analysis(monkeypatch)  # the sampled run's first-pass analysis, and its later reports
    monkeypatch.setattr(exp, "CHUNK_CELLS", 10)
    sampled = finished_layout2(repository, library, document, **sampled_overrides("sampled"))

    for done in (exhaustive, sampled):
        assert done.cells_layout == 2 and all(getattr(done, key) for key in LAYOUT2_FIELDS)
        assert done.search_space == identity.search_space(done.spec, done.surface)
        assert done.sampler == identity.sampler(done.plan, done.seed)
        assert done.versions == identity.versions(done.strategy_hash)
        assert done.data_pinned == PINNED_DATA
        assert done.execution == {
            "commission_per_side": done.spec.execution.commission_per_side,
            "slippage_bps": done.spec.execution.slippage_bps,
        }
        assert done.lineage == {"parent": None, "root": done.id}
        counts = done.counts
        assert counts["attempted"] == counts["completed"] + counts["invalid"] + counts["failed"]
        assert counts["attempted"] == counts["scheduled"] and counts["pending"] == 0
        assert counts["budget_total"] == done.plan["planned_runs"]
        assert counts["budget_total"] - counts["scheduled"] >= 0
        assert counts["unique"] is None  # set by compaction (Task 5)
        assert lab_store.Counters.from_document(done).as_dict() == counts

        fields = {key: getattr(done, key) for key in LAYOUT2_FIELDS}
        decided = exp.decide(store, done, "accepted", "")
        stored = document_of(repository, done.id)
        assert {key: getattr(decided, key) for key in LAYOUT2_FIELDS} == fields
        assert {key: getattr(stored, key) for key in LAYOUT2_FIELDS} == fields
        exp.recompute_report(store, stored)
        stored = document_of(repository, done.id)
        assert stored.latest_report == 2
        assert {key: getattr(stored, key) for key in LAYOUT2_FIELDS} == fields

    grid = build_grid(exhaustive.spec, exhaustive.surface, exhaustive.plan["bars"])
    assert exhaustive.counts["scheduled"] == grid.valid_count == 12
    assert exhaustive.sampler["method"] == "grid" and sampled.sampler["method"] == "lhs+refine"
    scheduled = len(sampled.first_pass_cells) + len(sampled.refinement_cells)
    assert sampled.counts["scheduled"] == scheduled == 30  # never the 400 valid cells


def test_refine_child_is_layout2_with_its_own_identity(world):  # noqa: F811
    repository, library, document = world
    store = exp.ExperimentStore(repository)
    parent = finished_layout2(repository, library, document, name="parent")
    legacy = legacy_document(repository, document, name="legacy parent")
    repository.save_experiment(
        {**repository.get_experiment(legacy.id), "status": "done", "latest_report": 1}
    )
    legacy = document_of(repository, legacy.id)
    assert legacy.cells_layout == 1 and legacy.search_space is None and legacy.lineage is None

    grid = build_grid(document.spec, parent.surface)
    plateau = [
        grid.index_of(
            {"long_side.indicators.donchian.length": 10, "long_side.indicators.rsi.length": r}
        )
        for r in (7, 14)
    ]
    for source in (parent, legacy):
        write_recommendation(store, source, plateau)
        child = exp.refine(store, source, bars=len(ROWS), max_workers=2, pinned=PINNED_DATA)
        assert child.parent == source.id and child.surface != source.surface
        before = source.search_space or identity.search_space(source.spec, source.surface)
        assert child.search_space == identity.search_space(child.spec, child.surface)
        assert child.search_space["hash"] != before["hash"]
        assert child.sampler == identity.sampler(child.plan, child.seed)
        assert child.versions == identity.versions(child.strategy_hash)
        assert child.lineage == {"parent": source.id, "root": source.id}
        assert child.data_pinned == PINNED_DATA and child.counts["attempted"] == 0
        stored = document_of(repository, child.id)
        assert stored.cells_layout == 2 and store.layout(child.id) == 2
        assert {key: getattr(stored, key) for key in LAYOUT2_FIELDS} == {
            key: getattr(child, key) for key in LAYOUT2_FIELDS
        }


def test_data_pinned_written_at_creation(world):  # noqa: F811
    repository, library, document = world
    store = exp.ExperimentStore(repository)
    pinned = exp.create(
        store,
        library,
        request(document, name="pinned"),
        bars=len(ROWS),
        max_workers=2,
        pinned=PINNED_DATA,
        engine_build="e" * 64,
    )
    assert pinned.data_pinned == PINNED_DATA
    assert document_of(repository, pinned.id).data_pinned == PINNED_DATA
    assert pinned.versions["engine_build"] == "e" * 64  # the worker's, handed in by the route
    assert pinned.counts == {
        "attempted": 0,
        "completed": 0,
        "invalid": 0,
        "failed": 0,
        "scheduled": 12,
        "budget_total": 12,
        "unique": None,
        "unique_generation": None,
        "pending": 12,
    }
    manifest = lab_store.read_manifest(store.cells_dir(pinned.id))
    assert (manifest.layout, manifest.generation, manifest.chunk_watermark) == (2, 0, -1)
    assert (manifest.parts, manifest.merged_chunks, manifest.generations) == ([], [], [])
    assert store.layout(pinned.id) == 2

    bare = exp.create(store, library, request(document, name="bare"), bars=len(ROWS), max_workers=2)
    assert bare.data_pinned is None and document_of(repository, bare.id).data_pinned is None
    assert bare.versions["engine_build"] == identity.engine_build()


def test_legacy_document_stays_layout_1(world):  # noqa: F811
    repository, _library, document = world
    store = exp.ExperimentStore(repository)
    doc = legacy_document(repository, document)
    raw = repository.get_experiment(doc.id)
    assert not set(LAYOUT2_FIELDS) & set(raw)
    stored = document_of(repository, doc.id)
    assert stored.cells_layout == 1
    assert all(getattr(stored, key) is None for key in LAYOUT2_FIELDS[1:])
    folder = store.cells_dir(doc.id)
    assert store.layout(doc.id) == 1 and not (folder / "manifest.json").exists()

    # Its job writes layout-1 chunks and never the layout-2 fields.
    JobRunner(repository).start(exp.ExperimentJob(stored, ROWS, PINNED_DATA, repository))
    assert wait_for(lambda: document_of(repository, doc.id).status in ("done", "failed"))
    done = document_of(repository, doc.id)
    assert done.status == "done", done.error
    assert done.cells_layout == 1 and done.counts is None and done.versions is None
    assert store.layout(doc.id) == 1 and not (folder / "manifest.json").exists()
    paths = done.surface.paths()
    names = chunk_names(folder)
    assert names == ["000000.parquet", "000001.parquet", "000002.parquet"]
    assert all(pq.read_schema(folder / name).equals(exp._cells_schema(paths)) for name in names)
    assert sorted(store.cells(doc.id).column("cell").to_pylist()) == list(range(12))
