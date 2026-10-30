"""Optimization Lab v2, Phase 2: the trial store (layout 2, compaction, snapshots, reclamation).
Task 4: the layout-2 write path, the additive document fields and the chunk naming (F16).
Task 5: the canonical reader, compaction into parts, snapshots, retention, reclamation and
`decompact`."""

import hashlib
import math
import os
import shutil
import sys
import threading
import time
import types
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from products.aegis import api
from products.aegis import experiments as exp
from products.aegis.analysis import _columns, _paths_of, analyse
from products.aegis.jobs import JobRunner
from products.aegis.lab import identity, policy
from products.aegis.lab import store as lab_store
from products.aegis.pool import METRICS, SCOPES
from products.aegis.runs import ITEM_FOLDERS, JsonRunRepository
from products.aegis.strategies import StrategyLibrary
from products.aegis.surface import KERNEL_MS_PER_BAR, Budget, Parameter, Surface, build_grid
from products.aegis.surface import plan as plan_surface
from test_aegis_api import _experiment_body, _runner, _wait_experiment, client  # noqa: F401
from test_aegis_data import write_archive
from test_aegis_experiments import (  # noqa: F401 - `world` is the shared experiments fixture
    PINNED_DATA,
    ROWS,
    document_of,
    request,
    surface12,
    wait_for,
    world,
)
from test_aegis_surface import pinned

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


def keep_chunks(repository, kept: Path):
    """An `after_unit` hook copying every chunk file the job has written so far into `kept`:
    from Task 5 on, `finalize` merges a `done` experiment's chunks into a part and reclaims them,
    so a test of the chunk files as written reads these copies."""

    def keep(done):
        kept.mkdir(parents=True, exist_ok=True)
        for path in (repository.root / "experiments").glob("*.cells/[0-9]*.parquet"):
            shutil.copy2(path, kept / path.name)

    return keep


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
    return hand_document(repository, document, **overrides)


def hand_document(
    repository,
    document,
    *,
    experiment_id: str | None = None,
    status: str = "queued",
    layout2: bool = False,
    **overrides,
) -> exp.ExperimentDocument:
    """A document built by hand as `create` builds one and saved through
    `repository.save_experiment`, never through `exp.create` (no `init_layout2`, no job): a legacy
    one without the layout-2 keys, or with `layout2` the fields `create` writes (Task 4), for a
    cells folder written beside it by `layout2_dir`."""
    body = request(document, **overrides)
    planned = plan_surface(
        document.spec, body.surface, body.budget, len(ROWS), KERNEL_MS_PER_BAR, 2, None
    )
    chunk = exp.CHUNK_CELLS
    now = "2026-10-20T00:00:00+00:00"
    identifier = experiment_id or exp.ExperimentStore(repository).free_id(body.name)
    extra = {}
    if layout2:
        extra = {
            **exp._layout2_fields(
                document.spec,
                body.surface,
                planned,
                body.seed,
                document.strategy_hash,
                PINNED_DATA,
                None,
            ),
            "lineage": {"parent": None, "root": identifier},
        }
    doc = exp.ExperimentDocument(
        id=identifier,
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
        status=status,
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
        **extra,
    )
    raw = doc.model_dump(mode="json")
    if not layout2:
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
    done = document_of(repository, doc.id)
    assert done.status == "done"
    # Recounted from the readable rows on resume: the torn chunk's cells count once, not twice.
    counts = done.counts
    assert counts["attempted"] == counts["scheduled"] == 12 and counts["pending"] == 0
    assert counts["completed"] + counts["invalid"] + counts["failed"] == counts["attempted"]
    assert listings == [["000000.parquet", "000001.parquet", "000002.parquet"]]
    assert (folder / "000001.parquet").read_bytes() == b"x"  # never merged, never overwritten
    cells = store.cells(doc.id).column("cell").to_pylist()
    assert sorted(cells) == list(range(12))  # chunk 0 plus the rerun of 5-11, each once

    # The name rule itself: both name forms count, nothing else does, the watermark too. The
    # readable chunks 0, 2 and 3 were merged into part-1 and reclaimed at finalize (Task 5); the
    # torn one never is, and the manifest's watermark keeps their indices used.
    assert chunk_names(folder) == ["000001.parquet"] and store.next_chunk_index(doc.id) == 4
    (folder / "000007.parquet.tmp").write_bytes(b"torn")
    assert store.next_chunk_index(doc.id) == 8
    names = ("000012.parquet", "000012.parquet.tmp", "part-1.parquet", "manifest.json", "12.parq")
    assert [lab_store.chunk_index_of(Path(n)) for n in names] == [12, 12, None, None, None]
    manifest = lab_store.read_manifest(folder)
    assert manifest is not None and manifest.chunk_watermark == 3
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
    assert chunk_names(folder) == []  # finalize merged the one chunk into part-1 (Task 5)
    assert "trial_no" in pq.read_schema(folder / "part-1.parquet").names

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


def test_layout2_chunk_schema(world, tmp_path):  # noqa: F811
    repository, library, document = world
    kept = tmp_path / "kept"
    runner = JobRunner(repository, after_unit=keep_chunks(repository, kept))
    doc = finished_layout2(repository, library, document, runner=runner)
    store = exp.ExperimentStore(repository)
    paths = doc.surface.paths()
    grid = build_grid(doc.spec, doc.surface, doc.plan["bars"])
    steps = {p.path: p.step for p in doc.surface.parameters}
    assert [(f.name, f.type) for f in exp._cells_schema_v2(paths)] == expected_v2_fields(paths)

    assert chunk_names(store.cells_dir(doc.id)) == []  # merged and reclaimed at finalize
    folder = kept  # the chunk files as the job wrote them
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
    # Read through the canonical reader: finalize merged the chunks into a part (Task 5).
    table = lab_store.read_latest(store.cells_dir(exhaustive.id), ["trial_no", "cell"]).table
    assert len(table) == 12
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
    table = lab_store.read_latest(store.cells_dir(sampled.id), ["trial_no", "cell", "pass"]).table
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
        assert counts["unique"] == counts["completed"]  # finalize's compaction; no duplicates
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
        "evaluations_done": 0,
        "pending": 12,
        "evaluations": 12,  # scheduled x (K + 1), K = 0 without screening blocks (Phase 3)
    }
    manifest = lab_store.read_manifest(store.cells_dir(pinned.id))
    assert (manifest.layout, manifest.generation, manifest.chunk_watermark) == (2, 0, -1)
    assert (manifest.parts, manifest.merged_chunks, manifest.generations) == ([], [], [])
    assert store.layout(pinned.id) == 2

    bare = exp.create(store, library, request(document, name="bare"), bars=len(ROWS), max_workers=2)
    assert bare.data_pinned is None and document_of(repository, bare.id).data_pinned is None
    assert bare.versions["engine_build"] == identity.engine_build()


def test_create_refuses_more_values_than_a_position_holds(world):  # noqa: F811
    """A layout-2 `pos.<k>` is a uint16: a parameter of 70,001 values is refused at creation,
    before anything is planned or written, never at the first commit."""
    repository, library, document = world
    store = exp.ExperimentStore(repository)
    wide = Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=0, stop=70000, step=1)
        ]
    )
    body = request(document, name="too wide", surface=wide.model_dump())
    with pytest.raises(ValueError, match="65535"):
        exp.create(store, library, body, bars=len(ROWS), max_workers=2, pinned=PINNED_DATA)
    folder = repository.root / "experiments"
    assert not folder.exists() or list(folder.iterdir()) == []


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


# --- Task 5: the reader, compaction, snapshots, retention, reclamation, decompact ------------

EXPERIMENT = "lab-trials"
SPEC = pinned()
SURFACE = surface12()  # donchian 10, 15, 20 x rsi 7, 14, 21, 28: 12 cells, none skipped
GRID = build_grid(SPEC, SURFACE)
PATHS = SURFACE.paths()
STEPS = {p.path: p.step for p in SURFACE.parameters}
WHEN = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
NOW = 1_800_000_000.0  # the `now` handed to compaction and reclamation (merged_at, retention)


PLATEAU = {(1, 2), (0, 2), (2, 2), (1, 1), (1, 3)}  # grid positions around donchian 15, rsi 21


def metrics_of(cell: int) -> dict:
    """Hand-written metrics with a flat top of five neighbouring cells (2d + 1 on this grid), so
    a report over them has main effects and a counting plateau."""
    pnl = 100.0 if GRID.positions(cell) in PLATEAU else 10.0 + 2.0 * cell
    values = {metric: float(cell + 1) for metric in METRICS}
    values.update(net_pnl=pnl, net_return=pnl / 1000.0, trade_count=float(20 + cell))
    return {scope: dict(values) for scope in SCOPES}


def trial_row(cell: int, **extra) -> dict:
    return {
        "cell": cell,
        "valid": True,
        "skip_reason": None,
        "params": GRID.cell_values(cell),
        "metrics": metrics_of(cell),
        "elapsed_ms": 1.0,
        "pass": "grid",
        "engine": "kernel",
        **extra,
    }


def rows_of(cells, **extra) -> list[dict]:
    return [trial_row(cell, **extra) for cell in cells]


def write_trials(cells_dir: Path, index: int, rows: list[dict]) -> Path:
    """One layout-2 chunk numbered by the exhaustive schedule (trial_no == cell on this grid)."""
    table = exp._cells_table_v2(rows, GRID, SPEC, STEPS, exp.Schedule.exhaustive(GRID), index, WHEN)
    path = cells_dir / f"{index:06d}.parquet"
    pq.write_table(table, path)
    return path


def layout2_dir(tmp_path: Path, chunks: list[list[dict]], experiment_id=EXPERIMENT) -> Path:
    """A layout-2 `<id>.cells` folder where the repository of the `world` and `client` fixtures
    keeps it (`tmp_path/aegis`): the generation-0 manifest and one chunk per list of rows, never
    a part (ruling P5: `write_part` is exercised through `compact`)."""
    repository = JsonRunRepository(tmp_path / "aegis")
    exp.ExperimentStore(repository).init_layout2(experiment_id)
    cells_dir = repository.experiment_dir(experiment_id, "cells")
    for index, rows in enumerate(chunks):
        write_trials(cells_dir, index, rows)
    return cells_dir


def experiment_of(cells_dir: Path) -> str:
    return cells_dir.name.removesuffix(".cells")


def test_lab_compaction_torn_is_idempotent(tmp_path):
    """Review Focus 1: a worker dying mid-compaction leaves a folder the reader serves whole,
    and a completed re-run leaves one generation; a chunk overlapping a part is a duplicate."""
    chunks = [rows_of(range(4)), rows_of(range(4, 8)), rows_of(range(8, 12))]
    names = ["000000.parquet", "000001.parquet", "000002.parquet"]
    for stage in ("part_written", "manifest_written"):
        cells_dir = layout2_dir(tmp_path / stage, chunks)
        before = lab_store.read_latest(cells_dir).table

        def tear(at, stage=stage):
            if at == stage:
                raise RuntimeError(f"the worker died at {at}")

        with pytest.raises(RuntimeError, match=stage):
            lab_store.compact(cells_dir, now=NOW, hooks=tear)
        torn = lab_store.read_latest(cells_dir)
        assert torn.table.column("trial_no").to_pylist() == list(range(12))
        assert torn.duplicates == 0
        assert (cells_dir / "part-1.parquet").is_file()

        manifest = lab_store.compact(cells_dir, now=NOW + 1)
        assert manifest.generation == 1 and len(manifest.generations) == 1
        assert [part["file"] for part in manifest.parts] == ["part-1.parquet"]
        assert [entry["file"] for entry in manifest.merged_chunks] == names
        after = lab_store.read_latest(cells_dir)
        assert after.duplicates == 0 and after.table.to_pylist() == before.to_pylist()
        assert lab_store.compact(cells_dir, now=NOW + 2) == manifest  # nothing new: a no-op

    # Overlap: a merged chunk's rows again under a new, unmerged name beside the part.
    cells_dir = layout2_dir(tmp_path / "overlap", chunks)
    before = lab_store.read_latest(cells_dir).table
    manifest = lab_store.compact(cells_dir, now=NOW)
    copy = cells_dir / f"{manifest.chunk_watermark + 1:06d}.parquet"
    shutil.copyfile(cells_dir / "000001.parquet", copy)
    assert lab_store.latest_snapshot(cells_dir)[1] == lab_store.Snapshot(1, 3)
    overlap = lab_store.read_latest(cells_dir)
    assert overlap.duplicates == len(chunks[1])
    assert overlap.table.to_pylist() == before.to_pylist()


def test_reader_dedupes_by_trial_block_attempt(tmp_path):
    rows = rows_of(range(4))
    cells_dir = layout2_dir(tmp_path, [rows, rows_of(range(4, 12))])
    once = lab_store.read_latest(cells_dir)
    assert once.duplicates == 0
    write_trials(cells_dir, 2, rows)  # the same (trial_no, block, attempt) under two more names
    write_trials(cells_dir, 3, rows)
    again = lab_store.read_latest(cells_dir)
    assert again.duplicates == 2 * len(rows)
    assert len(again.table) == len(once.table) == 12
    assert again.table.column("trial_no").to_pylist() == list(range(12))


def test_canonical_attempt_is_highest(tmp_path):
    """§7.3a across files: a failed attempt 0 compacted into a part, then an ok attempt 1 of the
    same (trial_no, block) in a later chunk, is one `ok` trial before and after compaction."""
    failed = trial_row(3, attempt=0, error="boom", metrics=None)
    cells_dir = layout2_dir(tmp_path, [[failed]])
    first = lab_store.compact(cells_dir, now=NOW)
    assert first.generation == 1 and first.unique == 0  # a failed trial is never unique
    assert lab_store.read_latest(cells_dir).table.column("status").to_pylist() == ["failed"]
    write_trials(cells_dir, lab_store.next_chunk_index(cells_dir, first), [trial_row(3, attempt=1)])

    def canonical():
        trials = lab_store.read_latest(cells_dir)
        assert trials.duplicates == 0
        return trials.table.select(["trial_no", "block", "attempt", "status"]).to_pylist()

    one_ok = [{"trial_no": 3, "block": 0, "attempt": 1, "status": "ok"}]
    assert canonical() == one_ok  # across the part and the chunk
    second = lab_store.compact(cells_dir, now=NOW + 1)
    assert second.generation == 2 and second.unique == 1
    assert canonical() == one_ok  # across the two parts


def test_readers_see_one_set_during_compaction(tmp_path):
    """Four request-shaped readers in bounded loops while one compaction and its reclamation run:
    every read sees one whole set, and the writer-preferring lock lets the compaction in (under a
    reader-preferring lock it would starve and this test would hang, hence the deadline)."""
    cells_dir = layout2_dir(tmp_path, [rows_of(range(k, k + 4)) for k in range(0, 12, 4)])
    experiment_id = experiment_of(cells_dir)
    expected = len(lab_store.read_latest(cells_dir).table)

    # The rule itself, deterministically: while a read is held, a waiting writer blocks every
    # new reader until it has run, and the holder's own nested read never waits behind it.
    order: list[str] = []

    def write():
        with lab_store.LOCKS.write(experiment_id):
            order.append("write")

    def read():
        with lab_store.LOCKS.read(experiment_id):
            order.append("read")

    with lab_store.LOCKS.read(experiment_id):
        writer = threading.Thread(target=write)
        writer.start()
        assert wait_for(lambda: lab_store.LOCKS._lock(experiment_id).waiting == 1, timeout=10)
        newcomer = threading.Thread(target=read)
        newcomer.start()
        time.sleep(0.2)
        assert order == []  # the writer waits for this read, the newcomer for the writer
        with lab_store.LOCKS.read(experiment_id):
            order.append("nested")
    writer.join(10)
    newcomer.join(10)
    assert order == ["nested", "write", "read"]

    seen: list[tuple[int, int, int]] = []
    errors: list[BaseException] = []

    def reader():
        try:
            for _ in range(200):
                with lab_store.LOCKS.read(experiment_id):
                    manifest, snapshot = lab_store.latest_snapshot(cells_dir)
                    files = lab_store.file_set(cells_dir, manifest, snapshot)
                    handle = lab_store.REGISTRY.open(experiment_id, snapshot, files)
                    try:
                        trials = lab_store.read_trials(cells_dir, snapshot)
                    finally:
                        lab_store.REGISTRY.release(handle)
                seen.append((len(trials.table), trials.duplicates, snapshot.generation))
        except BaseException as exc:  # noqa: BLE001 - every failure is reported below
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
        thread.start()
    assert wait_for(lambda: len(seen) >= 4 or errors, timeout=30)
    started = time.perf_counter()
    manifest = lab_store.compact(cells_dir, now=NOW)
    elapsed = time.perf_counter() - started
    reads_meanwhile = len(seen)
    removed = lab_store.reclaim(cells_dir, now=manifest.merged_chunks[0]["merged_at"] + 601)
    assert lab_store.compact(cells_dir, now=NOW + 1).generation == 1  # nothing new: a no-op
    for thread in threads:
        thread.join(120)
    assert elapsed < 10, f"the compaction waited {elapsed:.1f} s behind the readers"
    assert reads_meanwhile < 800  # it ran between the readers' reads, not after all of them
    assert not errors, errors
    assert len(seen) == 800
    assert {(rows, duplicates) for rows, duplicates, _ in seen} == {(expected, 0)}
    assert {generation for *_, generation in seen} <= {0, 1}
    assert sorted(path.name for path in removed) == [
        "000000.parquet",
        "000001.parquet",
        "000002.parquet",
    ]
    assert lab_store.REGISTRY.held(experiment_id) == set()


def test_reopen_older_snapshot_after_later_generations(tmp_path):
    """Review Focus 5: files an open snapshot references are never reclaimed and it reopens
    identically; once released and reclaimed it is `snapshot expired`, never served partially."""
    cells_dir = layout2_dir(tmp_path, [rows_of(range(3)), rows_of(range(3, 6))])
    experiment_id = experiment_of(cells_dir)
    lab_store.compact(cells_dir, now=NOW)  # generation 1: chunks 0-1
    write_trials(cells_dir, 2, rows_of(range(6, 9)))
    write_trials(cells_dir, 3, rows_of(range(9, 12)))
    manifest, g1 = lab_store.latest_snapshot(cells_dir)
    assert g1 == lab_store.Snapshot(generation=1, chunk_watermark=3)
    first = lab_store.read_trials(cells_dir, g1)
    assert first.table.column("trial_no").to_pylist() == list(range(12)) and first.snapshot == g1
    files = lab_store.file_set(cells_dir, manifest, g1)
    assert [path.name for path in files] == ["part-1.parquet", "000002.parquet", "000003.parquet"]
    handle = lab_store.REGISTRY.open(experiment_id, g1, files)
    try:
        second = lab_store.compact(cells_dir, now=NOW + 10)  # generation 2: chunks 2-3
        assert second.generation == 2
        merged_at = next(e["merged_at"] for e in second.merged_chunks if e["generation"] == 2)
        removed = lab_store.reclaim(cells_dir, now=merged_at + 601)
        assert set(removed) == {cells_dir / "000000.parquet", cells_dir / "000001.parquet"}
        assert (cells_dir / "000002.parquet").is_file() and (cells_dir / "000003.parquet").is_file()
        again = lab_store.read_trials(cells_dir, g1)
        assert again.table.to_pylist() == first.table.to_pylist() and again.snapshot == g1
    finally:
        lab_store.REGISTRY.release(handle)
    removed = lab_store.reclaim(cells_dir, now=merged_at + 601)
    assert set(removed) == {cells_dir / "000002.parquet", cells_dir / "000003.parquet"}
    with pytest.raises(lab_store.SnapshotExpired):
        lab_store.read_trials(cells_dir, g1)
    latest = lab_store.read_latest(cells_dir)
    assert latest.snapshot == lab_store.Snapshot(2, 3)
    assert latest.table.to_pylist() == first.table.to_pylist()


def test_snapshot_expired_after_registry_loss(tmp_path):
    cells_dir = layout2_dir(tmp_path, [rows_of(range(6)), rows_of(range(6, 8))])
    experiment_id = experiment_of(cells_dir)
    lab_store.compact(cells_dir, now=NOW)
    write_trials(cells_dir, 2, rows_of(range(8, 12)))
    manifest, g1 = lab_store.latest_snapshot(cells_dir)
    files = lab_store.file_set(cells_dir, manifest, g1)
    handle = lab_store.REGISTRY.pin(experiment_id, g1, files)
    try:
        assert lab_store.REGISTRY.held(experiment_id) == set(files)
        lab_store.compact(cells_dir, now=NOW)
        assert lab_store.reclaim(cells_dir, now=NOW + 601) == [
            cells_dir / "000000.parquet",
            cells_dir / "000001.parquet",
        ]
        assert len(lab_store.read_trials(cells_dir, g1).table) == 12  # still pinned
        restarted = lab_store.SnapshotRegistry()  # the registry is in-process: a restart loses it
        assert lab_store.reclaim(cells_dir, now=NOW + 601, registry=restarted) == [
            cells_dir / "000002.parquet"
        ]
        with pytest.raises(lab_store.SnapshotExpired):
            lab_store.read_trials(cells_dir, g1)
    finally:
        lab_store.REGISTRY.unpin(handle)
    assert lab_store.REGISTRY.held(experiment_id) == set()
    assert len(lab_store.read_latest(cells_dir).table) == 12


def test_reclaim_waits_for_retention(tmp_path):
    cells_dir = layout2_dir(tmp_path, [rows_of(range(6)), rows_of(range(6, 12))])
    chunks = [cells_dir / "000000.parquet", cells_dir / "000001.parquet"]
    manifest = lab_store.compact(cells_dir, now=NOW)
    merged_at = manifest.merged_chunks[0]["merged_at"]
    assert merged_at == NOW and {e["merged_at"] for e in manifest.merged_chunks} == {NOW}
    assert lab_store.reclaim(cells_dir, now=merged_at + 599) == []
    assert all(path.is_file() for path in chunks)
    assert lab_store.read_manifest(cells_dir).generations[-1]["reclaim_ms"] is None
    assert lab_store.reclaim(cells_dir, now=merged_at + 601) == chunks
    assert not any(path.exists() for path in chunks)
    after = lab_store.read_manifest(cells_dir)
    assert [e["file"] for e in after.merged_chunks] == [path.name for path in chunks]
    assert {e["reclaimed_at"] for e in after.merged_chunks} == {merged_at + 601}
    assert after.generations[-1]["reclaim_ms"] >= 0
    assert lab_store.reclaim(cells_dir, now=merged_at + 900) == []  # nothing left to reclaim
    assert lab_store.read_latest(cells_dir).table.column("trial_no").to_pylist() == list(range(12))


def test_reclaim_skips_a_held_chunk_without_failing(tmp_path, caplog):
    """A reader holding a merged chunk open outside the registry: Windows refuses the unlink and
    `_retry` gives up after 50 x 10 ms; reclaim leaves the chunk for the next pass and raises
    nothing, so the job never fails over it (POSIX unlinks an open file)."""
    cells_dir = layout2_dir(tmp_path, [rows_of(range(6)), rows_of(range(6, 12))])
    before = lab_store.read_latest(cells_dir).table.to_pylist()
    lab_store.compact(cells_dir, now=NOW)
    held, other = cells_dir / "000000.parquet", cells_dir / "000001.parquet"
    opened, release = threading.Event(), threading.Event()

    def hold():
        with pq.ParquetFile(held):
            opened.set()
            release.wait(30)  # well past _retry's 0.5 s

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert opened.wait(10)
        started = time.perf_counter()
        with caplog.at_level("WARNING", logger="aegis"):
            removed = lab_store.reclaim(cells_dir, now=NOW + 601)
        assert time.perf_counter() - started < 5
        assert lab_store.read_latest(cells_dir).table.to_pylist() == before
        if os.name == "nt":
            assert removed == [other]
            assert held.is_file()
            entry = next(
                e
                for e in lab_store.read_manifest(cells_dir).merged_chunks
                if e["file"] == held.name
            )
            assert entry.get("reclaimed_at") is None  # still listed for the next pass
            assert f"reclaim: {held.name} held open, retried next pass" in caplog.text
    finally:
        release.set()
        thread.join(10)
    again = lab_store.reclaim(cells_dir, now=NOW + 601)
    if os.name == "nt":
        assert again == [held]
    assert not held.exists() and not other.exists()
    assert lab_store.read_latest(cells_dir).table.to_pylist() == before


def test_layout2_store_reads_take_the_read_lock(world, tmp_path, monkeypatch):  # noqa: F811
    repository, _library, document = world
    store = exp.ExperimentStore(repository)
    layout2_dir(tmp_path, [rows_of(range(6)), rows_of(range(6, 12))])
    hand_document(repository, document, experiment_id=EXPERIMENT, status="done", layout2=True)
    legacy = hand_document(repository, document, experiment_id="legacy-reads", status="done")
    for index, cells in enumerate((range(6), range(6, 12))):
        store.write_chunk(legacy.id, index, rows_of(cells), PATHS)  # layout-1 chunks
    assert store.layout(EXPERIMENT) == 2 and store.layout(legacy.id) == 1

    taken: list[str] = []
    read = lab_store.LOCKS.read

    def recording(experiment_id):
        taken.append(experiment_id)
        return read(experiment_id)

    monkeypatch.setattr(lab_store.LOCKS, "read", recording)

    def acquisitions(call) -> int:
        taken.clear()
        call()
        return len(taken)

    assert acquisitions(lambda: store.cells(EXPERIMENT)) >= 1
    assert acquisitions(lambda: store.row(EXPERIMENT, 0)) >= 2  # row's own, then cells' nested
    assert acquisitions(lambda: store.done_cells(EXPERIMENT)) >= 1
    assert acquisitions(lambda: store.trials(EXPERIMENT, None)) >= 1
    assert set(taken) == {EXPERIMENT}
    assert acquisitions(lambda: store.cells(legacy.id)) == 0
    assert acquisitions(lambda: store.row(legacy.id, 0)) == 0
    assert acquisitions(lambda: store.done_cells(legacy.id)) == 0
    assert acquisitions(lambda: store.trials(legacy.id, None)) == 1
    assert store.row(EXPERIMENT, 5)["cell"] == store.row(legacy.id, 5)["cell"] == 5
    assert store.done_cells(EXPERIMENT) == store.done_cells(legacy.id) == set(range(12))
    assert len(store.trials(legacy.id, None).table) == len(store.trials(EXPERIMENT).table) == 12


def test_chunk_index_never_reused_after_reclaim(tmp_path):
    repository = JsonRunRepository(tmp_path / "aegis")
    store = exp.ExperimentStore(repository)
    cells_dir = layout2_dir(tmp_path, [rows_of(range(4)), rows_of(range(4, 8))])
    manifest = lab_store.compact(cells_dir, now=NOW)
    lab_store.reclaim(cells_dir, now=NOW + 601)
    assert chunk_names(cells_dir) == []  # no chunk file remains to count from
    index = store.next_chunk_index(EXPERIMENT)
    assert index == manifest.chunk_watermark + 1 == 2
    rows = [{**trial_row(cell), "trial_no": cell} for cell in range(8, 12)]
    table = exp._cells_table_v2(rows, GRID, SPEC, STEPS, None, index, WHEN)
    store.write_chunk(EXPERIMENT, index, rows, PATHS, table=table)
    assert chunk_names(cells_dir) == ["000002.parquet"]
    assert lab_store.latest_snapshot(cells_dir)[1] == lab_store.Snapshot(1, 2)
    trials = lab_store.read_latest(cells_dir)
    assert trials.table.column("trial_no").to_pylist() == list(range(12))
    assert trials.duplicates == 0


def test_compaction_part_sorted_zstd_rowgroups(tmp_path, monkeypatch):
    chunks = [rows_of([11, 10, 9, 8]), rows_of([3, 2, 1, 0]), rows_of([7, 6, 5, 4])]
    for root, row_group in ((tmp_path / "default", 65_536), (tmp_path / "small", 5)):
        monkeypatch.setattr(policy, "PART_ROW_GROUP", row_group)  # read when the part is written
        cells_dir = layout2_dir(root, chunks)
        manifest = lab_store.compact(cells_dir, now=NOW)
        (part,) = manifest.parts
        path = cells_dir / part["file"]
        assert part["file"] == "part-1.parquet" and part["generation"] == 1
        metadata = pq.read_metadata(path)
        sizes = [metadata.row_group(i).num_rows for i in range(metadata.num_row_groups)]
        assert max(sizes) <= min(row_group, 65_536) and sum(sizes) == 12
        assert sizes == ([12] if row_group > 12 else [5, 5, 2])
        compressions = {
            metadata.row_group(i).column(j).compression
            for i in range(metadata.num_row_groups)
            for j in range(metadata.num_columns)
        }
        assert compressions == {"ZSTD"}
        trial_no = pq.read_table(path, columns=["trial_no"]).column("trial_no").to_pylist()
        assert trial_no == sorted(trial_no) == list(range(12))
        assert part["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert (part["trial_no_min"], part["trial_no_max"], part["rows"]) == (0, 11, 12)
        assert part["compaction_ms"] >= 0
        assert manifest.generations == [
            {
                "generation": 1,
                "at": NOW,
                "rows": 12,
                "compaction_ms": part["compaction_ms"],
                "reclaim_ms": None,
            }
        ]
        assert (manifest.unique, manifest.unique_generation, manifest.chunk_watermark) == (12, 1, 2)


def test_unreadable_chunk_is_skipped_by_read_trials_and_compact(tmp_path):
    cells_dir = layout2_dir(tmp_path, [rows_of(range(6)), rows_of(range(6, 12))])
    torn = cells_dir / "000000.parquet"
    torn.write_bytes(b"x")  # a chunk torn after it landed, under a readable later chunk
    trials = lab_store.read_latest(cells_dir)
    assert trials.table.column("trial_no").to_pylist() == list(range(6, 12))
    assert trials.duplicates == 0
    assert [index for index, _ in lab_store.readable_chunks(cells_dir)] == [1]
    manifest, _ = lab_store.latest_snapshot(cells_dir)
    assert lab_store.unmerged_chunks(manifest, cells_dir) == 1
    manifest = lab_store.compact(cells_dir, now=NOW)
    assert [entry["file"] for entry in manifest.merged_chunks] == ["000001.parquet"]
    assert lab_store.unmerged_chunks(manifest, cells_dir) == 0  # the torn chunk is ignored
    assert lab_store.reclaim(cells_dir, now=NOW + 601) == [cells_dir / "000001.parquet"]
    assert torn.read_bytes() == b"x"  # never merged, reclaimed or overwritten
    assert lab_store.next_chunk_index(cells_dir) == 1  # its name still counts
    assert lab_store.next_chunk_index(cells_dir, lab_store.read_manifest(cells_dir)) == 2
    assert lab_store.read_latest(cells_dir).table.column("trial_no").to_pylist() == list(
        range(6, 12)
    )


def test_legacy_read_equals_cells(tmp_path):
    folder = JsonRunRepository(tmp_path / "aegis").experiment_dir("legacy-cells", "cells")
    folder.mkdir(parents=True)
    skipped = trial_row(3, valid=False, skip_reason="insufficient bars", metrics=None)
    chunks = [
        [*rows_of(range(3)), skipped],
        rows_of(range(4, 8), **{"pass": "sample"}),
        rows_of(range(8, 12), **{"pass": "refine"}),
    ]
    tables = []
    for index, rows in enumerate(chunks):
        table = exp._cells_table(rows, PATHS)  # today's layout-1 chunk
        pq.write_table(table, folder / f"{index:06d}.parquet")
        tables.append(table)
    promoted = lab_store.read_latest(folder, legacy=lab_store.LegacyContext(GRID, PATHS))
    legacy_schema = exp._cells_schema(PATHS)
    assert (
        promoted.table.select(legacy_schema.names).cast(legacy_schema).sort_by("cell").to_pylist()
        == pa.concat_tables(tables).sort_by("cell").to_pylist()
    )
    assert promoted.table.schema.equals(exp._cells_schema_v2(PATHS))
    assert (promoted.layout, promoted.duplicates, promoted.provisional) == (1, 0, False)
    assert promoted.snapshot == lab_store.Snapshot(0, 2)
    rows = promoted.table.to_pylist()
    assert [row["trial_no"] for row in rows] == [row["cell"] for row in rows] == list(range(12))
    assert {row["block"] for row in rows} == {0} and {row["attempt"] for row in rows} == {0}
    designs = {(row["pass"], row["design"]) for row in rows}
    assert designs == {("grid", "uniform"), ("sample", "uniform"), ("refine", "adaptive")}
    for row in rows:
        assert [row[f"pos.{k}"] for k in range(len(PATHS))] == list(GRID.positions(row["cell"]))
        assert row["chunk"] == (0 if row["cell"] < 4 else 1 if row["cell"] < 8 else 2)
        assert row["status"] == ("invalid" if row["cell"] == 3 else "ok")
        assert row["finished_at"] is None and row["combined.sharpe_trade"] is None
        assert row["param_key"] is None and row["error"] is None
    with pytest.raises(ValueError, match="legacy"):
        lab_store.read_latest(folder)  # a layout-1 chunk is promoted only with its context


def test_legacy_promotion_reads_projected_columns_only(tmp_path, monkeypatch):
    """A projected read of a legacy folder loads the promotion's inputs and the wanted columns
    only, never the other metric columns (Global Constraints: projected columns only)."""
    folder = JsonRunRepository(tmp_path / "aegis").experiment_dir("legacy-projected", "cells")
    folder.mkdir(parents=True)
    skipped = trial_row(5, valid=False, skip_reason="insufficient bars", metrics=None)
    chunks = [rows_of(range(5)), [skipped, *rows_of(range(6, 12), **{"pass": "refine"})]]
    for index, rows in enumerate(chunks):
        pq.write_table(exp._cells_table(rows, PATHS), folder / f"{index:06d}.parquet")
    legacy = lab_store.LegacyContext(GRID, PATHS)
    full = lab_store.read_latest(folder, legacy=legacy).table

    recorded: list[list[str] | None] = []
    read = pq.ParquetFile.read

    def recording(self, columns=None, *args, **kwargs):
        recorded.append(None if columns is None else list(columns))
        return read(self, columns, *args, **kwargs)

    monkeypatch.setattr(pq.ParquetFile, "read", recording)
    trials = lab_store.read_latest(folder, ["trial_no", "cell", "long.net_pnl"], legacy=legacy)
    needed = ["cell", "pass", "valid", "skip_reason", "long.net_pnl"]
    assert len(recorded) == 2  # one read per chunk, each projected
    assert all(sorted(columns) == sorted(needed) for columns in recorded)
    table = trials.table
    assert table.column_names == ["trial_no", "cell", "long.net_pnl", "block", "status"]
    assert table.to_pylist() == full.select(table.column_names).to_pylist()
    assert table.column("trial_no").to_pylist() == list(range(12))
    assert table.column("status").to_pylist() == ["invalid" if c == 5 else "ok" for c in range(12)]
    assert full.schema.equals(exp._cells_schema_v2(PATHS))  # None still yields the full set
    rows = full.to_pylist()
    for row in rows:
        assert [row[f"pos.{k}"] for k in range(len(PATHS))] == list(GRID.positions(row["cell"]))
    assert {(row["pass"], row["design"]) for row in rows} == {
        ("grid", "uniform"),
        ("refine", "adaptive"),
    }


def test_read_trials_filters_one_trial(tmp_path, monkeypatch):
    """The trial route's read (Task 8 review): with `trial_no`, each file contributes that
    trial's rows only, through a Parquet predicate whose row groups the statistics prune (a part
    is sorted by trial_no; a legacy chunk's trial number is its cell), and the canonical collapse
    runs on those rows as on the whole set. Without it, nothing changes."""
    monkeypatch.setattr(policy, "PART_ROW_GROUP", 3)  # a part of four row groups
    cells_dir = layout2_dir(tmp_path / "layout2", [rows_of(range(6)), rows_of(range(6, 12))])
    manifest = lab_store.compact(cells_dir, now=NOW)
    assert pq.read_metadata(cells_dir / "part-1.parquet").num_row_groups == 4
    retried = {scope: {**values, "net_pnl": 999.0} for scope, values in metrics_of(4).items()}
    unmerged = [trial_row(4, attempt=1, metrics=retried), trial_row(2)]  # a retry; a copy
    write_trials(cells_dir, lab_store.next_chunk_index(cells_dir, manifest), unmerged)
    columns = ["trial_no", "cell", "long.net_pnl"]
    full = lab_store.read_latest(cells_dir, columns)
    assert full.duplicates == 1 and len(full.table) == 12
    reads: list[tuple[str, list | None]] = []
    read_table = pq.read_table

    def recording(path, *args, **kwargs):
        reads.append((Path(path).name, kwargs.get("filters")))
        return read_table(path, *args, **kwargs)

    monkeypatch.setattr(pq, "read_table", recording)
    for n in (0, 2, 4, 7, 11):
        reads.clear()
        one = lab_store.read_latest(cells_dir, columns, trial_no=n)
        expected = [row for row in full.table.to_pylist() if row["trial_no"] == n]
        assert len(expected) == 1 and one.table.to_pylist() == expected
        assert one.table.schema.equals(full.table.schema) and one.snapshot == full.snapshot
        assert sorted(reads) == [
            ("000002.parquet", [("trial_no", "==", n)]),
            ("part-1.parquet", [("trial_no", "==", n)]),
        ]
    assert lab_store.read_latest(cells_dir, columns, trial_no=2).duplicates == 1
    four = lab_store.read_latest(cells_dir, ["trial_no", "attempt", "long.net_pnl"], trial_no=4)
    assert four.table.to_pylist() == [
        {"trial_no": 4, "attempt": 1, "long.net_pnl": 999.0, "block": 0, "status": "ok"}
    ]
    absent = lab_store.read_latest(cells_dir, columns, trial_no=99)
    assert absent.table.num_rows == 0 and absent.duplicates == 0
    assert absent.table.column_names == ["trial_no", "cell", "long.net_pnl", "block", "status"]
    reads.clear()
    assert lab_store.read_latest(cells_dir, columns).table.equals(full.table)
    assert reads == []  # an unfiltered read is the reader it always was

    folder = JsonRunRepository(tmp_path / "legacy" / "aegis").experiment_dir("legacy-one", "cells")
    folder.mkdir(parents=True)
    for index, rows in enumerate([rows_of(range(6)), rows_of(range(6, 12), **{"pass": "refine"})]):
        pq.write_table(exp._cells_table(rows, PATHS), folder / f"{index:06d}.parquet")
    legacy = lab_store.LegacyContext(GRID, PATHS)
    wanted = ["trial_no", "cell", "pos.0", "design", "long.net_pnl"]
    whole = lab_store.read_latest(folder, wanted, legacy=legacy).table.to_pylist()
    for cell in (3, 8):
        reads.clear()
        promoted = lab_store.read_latest(folder, wanted, legacy=legacy, trial_no=cell)
        assert promoted.layout == 1 and len(promoted.table) == 1
        assert promoted.table.to_pylist() == [row for row in whole if row["cell"] == cell]
        assert sorted(reads) == [
            ("000000.parquet", [("cell", "==", cell)]),
            ("000001.parquet", [("cell", "==", cell)]),
        ]
    nowhere = lab_store.read_latest(folder, wanted, legacy=legacy, trial_no=99)
    assert nowhere.table.num_rows == 0 and nowhere.table.column_names == [
        *wanted,
        "block",
        "status",
    ]


def test_legacy_report_reproduced_identically(world):  # noqa: F811
    repository, _library, document = world
    store = exp.ExperimentStore(repository)
    doc = legacy_document(repository, document, name="legacy report")
    JobRunner(repository).start(exp.ExperimentJob(doc, ROWS, PINNED_DATA, repository))
    assert wait_for(lambda: document_of(repository, doc.id).status in ("done", "failed"))
    done = document_of(repository, doc.id)
    assert done.status == "done", done.error
    assert store.layout(done.id) == 1
    paths = done.surface.paths()
    grid = build_grid(done.spec, done.surface, done.plan["bars"])
    folder = store.cells_dir(done.id)
    promoted = lab_store.read_latest(folder, legacy=lab_store.LegacyContext(grid, paths)).table

    def report(table):
        return analyse(table, grid, "net_pnl", 0.15, "exhaustive", 1, "QQQ")

    ours = report(exp._legacy_projection(promoted, paths))
    today = report(store._legacy_cells(done.id))
    assert list(ours["main_effects"]) == paths
    for key in ("main_effects", "plateaus", "clusters"):
        assert ours[key] == today[key], key
    assert ours == today  # the whole report, peaks, sensitivity and statement included


def test_layout2_report_before_and_after_compaction(world, tmp_path):  # noqa: F811
    repository, _library, document = world
    store = exp.ExperimentStore(repository)
    chunks = [rows_of(range(4)), rows_of(range(4, 8)), rows_of(range(8, 12))]
    cells_dir = layout2_dir(tmp_path, chunks)
    hand_document(repository, document, experiment_id=EXPERIMENT, status="done", layout2=True)
    reports = []

    def recompute():
        _updated, report = exp.recompute_report(store, store.get(EXPERIMENT))
        reports.append(report)

    recompute()  # the chunks
    manifest = lab_store.compact(cells_dir, now=NOW)
    assert len(chunk_names(cells_dir)) == 3  # merged, not yet reclaimed
    recompute()  # the part
    lab_store.reclaim(cells_dir, now=manifest.merged_chunks[0]["merged_at"] + 601)
    assert chunk_names(cells_dir) == []
    recompute()  # the part alone
    first = reports[0]
    assert list(first["main_effects"]) == PATHS and first["plateaus"]
    for report in reports[1:]:
        assert report["main_effects"] == first["main_effects"]
        assert report["plateaus"] == first["plateaus"]
    assert [r["report_id"] for r in reports] == [1, 2, 3]


def test_legacy_job_never_compacts(world, monkeypatch):  # noqa: F811
    """AGENTS.md retained data: a legacy (layout 1) experiment is never compacted, even when its
    chunk count passes COMPACT_EVERY; provable because the fixture never calls `init_layout2`."""
    repository, _library, document = world
    monkeypatch.setattr(policy, "COMPACT_EVERY", 1)
    store = exp.ExperimentStore(repository)
    doc = legacy_document(repository, document, name="legacy never compacts")
    folder = store.cells_dir(doc.id)
    written: dict[str, bytes] = {}

    def keep(done):
        for path in folder.glob("[0-9]*.parquet"):
            written.setdefault(path.name, path.read_bytes())

    job = exp.ExperimentJob(document_of(repository, doc.id), ROWS, PINNED_DATA, repository)
    JobRunner(repository, after_unit=keep).start(job)
    assert wait_for(lambda: document_of(repository, doc.id).status in ("done", "failed"))
    done = document_of(repository, doc.id)
    assert done.status == "done", done.error
    assert not (folder / "manifest.json").exists() and list(folder.glob("part-*")) == []
    assert store.layout(doc.id) == 1 and done.counts is None
    assert sorted(written) == ["000000.parquet", "000001.parquet", "000002.parquet"]
    assert {path.name: path.read_bytes() for path in folder.glob("[0-9]*.parquet")} == written


def test_decompact_restores_chunks_for_layout1_code(client, tmp_path):  # noqa: F811
    c, _, repository = client
    store = exp.ExperimentStore(repository)
    strategy = StrategyLibrary(repository).create("Breakout", pinned())
    cells_dir = layout2_dir(tmp_path, [rows_of(range(4)), rows_of(range(4, 8))])
    hand_document(repository, strategy, experiment_id=EXPERIMENT, status="done", layout2=True)
    before = lab_store.read_latest(cells_dir).table.to_pylist()
    lab_store.compact(cells_dir, now=NOW)
    lab_store.reclaim(cells_dir, now=NOW + 601)
    assert chunk_names(cells_dir) == []

    assert lab_store.decompact(cells_dir) == {"chunks_written": 2, "parts_removed": 1}
    assert sorted(path.name for path in cells_dir.iterdir()) == ["000000.parquet", "000001.parquet"]
    restored = pa.concat_tables([pq.read_table(path) for path in exp._readable(cells_dir)])
    assert sorted(restored.column("trial_no").to_pylist()) == list(range(8))  # each row once
    assert restored.sort_by("trial_no").to_pylist() == before
    assert lab_store.read_manifest(cells_dir) is None
    assert store.layout(EXPERIMENT) == 2  # its chunks carry trial_no: never a layout-1 folder

    response = c.get(f"/aegis/api/experiments/{EXPERIMENT}/cells?limit=50")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 8 and body["columns"] == exp._cells_schema(PATHS).names
    assert _paths_of(_columns(store.cells(EXPERIMENT))) == PATHS  # never trial_no, pos.0, ...

    # A resume keeps writing layout-2 chunks beside the restored ones.
    index = store.next_chunk_index(EXPERIMENT)
    assert index == 2
    rows = rows_of(range(8, 12))
    schedule = exp.Schedule.exhaustive(GRID)
    table = exp._cells_table_v2(rows, GRID, SPEC, STEPS, schedule, index, WHEN)
    store.write_chunk(EXPERIMENT, index, rows, PATHS, table=table)
    table = store.cells(EXPERIMENT)
    assert sorted(table.column("cell").to_pylist()) == list(range(12))
    assert table.schema.equals(exp._cells_schema(PATHS))
    report = analyse(table, GRID, "net_pnl", 0.15, "exhaustive", 1, "QQQ")
    assert list(report["main_effects"]) == PATHS and report["plateaus"]
    assert lab_store.decompact(cells_dir) == {"chunks_written": 0, "parts_removed": 0}


def test_job_compacts_every_fifty_chunks_and_at_finalize(world, monkeypatch):  # noqa: F811
    repository, library, document = world
    monkeypatch.setattr(policy, "COMPACT_EVERY", 2)
    monkeypatch.setattr(exp, "CHUNK_CELLS", 5)
    store = exp.ExperimentStore(repository)
    # 12 RSI lengths on the 260-bar ROWS: only 270 (warm-up 271 bars) is skipped. One group, so
    # exactly one of 12 cells is skipped and never scheduled: 11 trials in units of 5 / 5 / 1.
    surface = Surface(
        parameters=[Parameter(path="long_side.indicators.rsi.length", start=50, stop=270, step=20)]
    )
    body = request(document, name="compacting", surface=surface.model_dump())
    doc = exp.create(store, library, body, bars=len(ROWS), max_workers=2, pinned=PINNED_DATA)
    folder = store.cells_dir(doc.id)
    seen = []

    def observe(done):
        manifest = lab_store.read_manifest(folder)
        merged = [entry["file"] for entry in manifest.merged_chunks]
        seen.append((done, manifest.generation, merged, chunk_names(folder)))

    job = exp.ExperimentJob(doc, ROWS, PINNED_DATA, repository)
    assert job.grid.valid_count == 11 and job.grid.size == 12
    assert [len(unit) for unit in job.units] == [5, 5, 1]
    JobRunner(repository, after_unit=observe).start(job)
    assert wait_for(lambda: document_of(repository, doc.id).status in ("done", "failed"))
    done = document_of(repository, doc.id)
    assert done.status == "done", done.error
    first_two = ["000000.parquet", "000001.parquet"]
    assert seen == [
        (1, 0, [], ["000000.parquet"]),
        (2, 0, [], first_two),
        # compacted at the start of run_unit(2), after after_unit(2): chunk 2 is unmerged
        (3, 1, first_two, [*first_two, "000002.parquet"]),
    ]
    manifest = lab_store.read_manifest(folder)
    assert manifest.generation == 2
    assert [part["file"] for part in manifest.parts] == ["part-1.parquet", "part-2.parquet"]
    assert chunk_names(folder) == []  # finalize reclaimed every merged chunk at once
    counts = done.counts
    assert counts["scheduled"] == counts["attempted"] == counts["completed"] == 11
    assert counts["invalid"] == counts["failed"] == 0
    assert counts["unique"] == counts["completed"] == 11  # not the 12 cells
    assert counts["unique"] <= counts["completed"]  # §6.4
    assert counts["unique_generation"] == manifest.unique_generation == 2
    assert store.done_cells(doc.id) == set(range(11))


# --- Task 6: attachments travel together; resume and materialize through the pinned source ------


def attachment_contents(folder: Path, experiment_id: str) -> dict[str, str]:
    """Every file of an experiment beside its document (the document, its sidecar and each
    attachment folder's files), as its path under `folder` with its bytes' sha256."""
    found = {}
    for piece in sorted(folder.iterdir()):
        if not piece.name.startswith(f"{experiment_id}."):
            continue
        files = [piece] if piece.is_file() else sorted(p for p in piece.rglob("*") if p.is_file())
        for path in files:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            found[path.relative_to(folder).as_posix()] = digest
    return found


def test_experiment_attachments_travel_with_trash_and_restore(tmp_path):
    repository = JsonRunRepository(tmp_path / "aegis")
    store = exp.ExperimentStore(repository)
    strategy = StrategyLibrary(repository).create("Breakout", pinned())
    cells_dir = layout2_dir(tmp_path, [rows_of(range(6)), rows_of(range(6, 12))])
    hand_document(repository, strategy, experiment_id=EXPERIMENT, status="done", layout2=True)
    lab_store.compact(cells_dir, now=NOW)
    lab_store.reclaim(cells_dir, now=NOW + 601)
    assert sorted(path.name for path in cells_dir.iterdir()) == ["manifest.json", "part-1.parquet"]
    folder = repository.root / "experiments"
    named = ("curves", "reports", "replays", "views", "events.jsonl")  # the spec's attachments
    others = [s for s in ITEM_FOLDERS["experiments"] if s != "cells" and s not in named]
    for suffix in (*named, *others):
        path = folder / f"{EXPERIMENT}.{suffix}"
        if suffix.endswith(".jsonl"):
            path.write_text('{"event": "created"}\n{"event": "done"}\n', encoding="utf-8")
            continue
        (path / "nested").mkdir(parents=True)
        (path / "000000.parquet").write_bytes(suffix.encode())
        (path / "nested" / "1.json").write_text(f'{{"{suffix}": 1}}', encoding="utf-8")
    before = lab_store.read_latest(cells_dir)
    contents = attachment_contents(folder, EXPERIMENT)
    pieces = {f"{EXPERIMENT}.{suffix}" for suffix in ("cells", *named, *others)}
    assert {name.split("/")[0] for name in contents} == pieces | {
        f"{EXPERIMENT}.json.gz",
        f"{EXPERIMENT}.summary.json",
    }

    repository.move_to_trash("experiments", EXPERIMENT, {"kind": "experiment", "id": EXPERIMENT})
    assert attachment_contents(folder, EXPERIMENT) == {}  # nothing of it is left live
    trash = repository.root / "trash" / "experiments" / EXPERIMENT
    assert {path.name for path in trash.iterdir()} == pieces | {
        f"{EXPERIMENT}.json.gz",
        f"{EXPERIMENT}.summary.json",
        "trash.json",
    }
    assert attachment_contents(trash, EXPERIMENT) == contents  # moved whole, byte for byte
    assert [item["id"] for item in repository.list_trash()] == [EXPERIMENT]

    repository.restore_from_trash("experiments", EXPERIMENT)
    assert not trash.exists()
    assert attachment_contents(folder, EXPERIMENT) == contents
    after = lab_store.read_latest(cells_dir)
    assert after.table.equals(before.table) and after.snapshot == before.snapshot
    assert after.table.to_pylist() == before.table.to_pylist()
    assert store.layout(EXPERIMENT) == 2 and len(store.cells(EXPERIMENT)) == 12


# -- R3 independent QA (2026-10-29): a move to or from Recently deleted is whole or nothing ------
def compacted_experiment(tmp_path):
    """A finished layout-2 experiment as finalize leaves it (manifest and one part), with every
    attachment folder populated, beside its repository, store and Library."""
    from products.aegis.library import Library

    repository = JsonRunRepository(tmp_path / "aegis")
    store = exp.ExperimentStore(repository)
    strategy = StrategyLibrary(repository).create("Breakout", pinned())
    cells_dir = layout2_dir(tmp_path, [rows_of(range(6)), rows_of(range(6, 12))])
    hand_document(repository, strategy, experiment_id=EXPERIMENT, status="done", layout2=True)
    lab_store.compact(cells_dir, now=NOW)
    lab_store.reclaim(cells_dir, now=NOW, retain_seconds=0)
    folder = repository.root / "experiments"
    for suffix in ITEM_FOLDERS["experiments"]:
        if suffix == "cells":
            continue
        path = folder / f"{EXPERIMENT}.{suffix}"
        if suffix.endswith(".jsonl"):
            path.write_text('{"event": "done"}\n', encoding="utf-8")
        else:
            path.mkdir()
            (path / "000000.parquet").write_bytes(suffix.encode())
    return repository, store, Library(repository, store), cells_dir


def held(path: Path):
    """A thread holding `path` open as a Lab read of a part does (pyarrow's ParquetFile), until
    the returned release() is called."""
    opened, done = threading.Event(), threading.Event()

    def hold():
        with pq.ParquetFile(path) if path.suffix == ".parquet" else open(path, "rb"):
            opened.set()
            done.wait(60)

    thread = threading.Thread(target=hold)
    thread.start()
    assert opened.wait(10)

    def release():
        done.set()
        thread.join(10)

    return release


@pytest.fixture
def quick_moves(monkeypatch):
    """A refused move gives up after a few tries instead of the route's few seconds."""
    from products.aegis import runs

    monkeypatch.setattr(runs, "MOVE_ATTEMPTS", 3)
    monkeypatch.setattr(runs, "MOVE_DELAY", 0.01)


@pytest.mark.skipif(os.name != "nt", reason="only Windows refuses a rename under an open file")
def test_trash_under_a_held_part_moves_nothing_and_says_so(tmp_path, quick_moves):
    from products.aegis.library import Refused

    repository, _store, library, cells_dir = compacted_experiment(tmp_path)
    folder = repository.root / "experiments"
    before = attachment_contents(folder, EXPERIMENT)
    rows = lab_store.read_latest(cells_dir).table
    release = held(cells_dir / "part-1.parquet")
    try:
        with pytest.raises(Refused, match="in use"):
            library.delete("experiment", EXPERIMENT)
        assert attachment_contents(folder, EXPERIMENT) == before  # every piece still live
        assert not (repository.root / "trash" / "experiments" / EXPERIMENT).exists()
        assert lab_store.read_latest(cells_dir).table.equals(rows)
    finally:
        release()
    library.delete("experiment", EXPERIMENT)  # the reader gone, the same delete goes through
    assert attachment_contents(folder, EXPERIMENT) == {}
    library.restore("experiment", EXPERIMENT)
    assert attachment_contents(folder, EXPERIMENT) == before
    assert lab_store.read_latest(cells_dir).table.equals(rows)


@pytest.mark.skipif(os.name != "nt", reason="only Windows refuses a rename under an open file")
def test_restore_under_a_held_file_in_the_trash_moves_nothing(tmp_path, quick_moves):
    from products.aegis.library import Refused

    repository, _store, library, _cells_dir = compacted_experiment(tmp_path)
    folder = repository.root / "experiments"
    before = attachment_contents(folder, EXPERIMENT)
    library.delete("experiment", EXPERIMENT)
    trash = repository.root / "trash" / "experiments" / EXPERIMENT
    trashed = attachment_contents(trash, EXPERIMENT)
    release = held(trash / f"{EXPERIMENT}.cells" / "part-1.parquet")
    try:
        with pytest.raises(Refused, match="in use"):
            library.restore("experiment", EXPERIMENT)
        assert attachment_contents(trash, EXPERIMENT) == trashed  # the item stays deleted, whole
        assert attachment_contents(folder, EXPERIMENT) == {}
    finally:
        release()
    library.restore("experiment", EXPERIMENT)
    assert attachment_contents(folder, EXPERIMENT) == before and not trash.exists()


def test_a_refused_piece_puts_back_every_piece_already_moved(tmp_path, quick_moves, monkeypatch):
    """Portable: the rename of one attachment refused (as Windows refuses it under a reader), the
    pieces moved before it go back and the item is live and whole."""
    from products.aegis import runs
    from products.aegis.library import Refused

    repository, store, library, _cells_dir = compacted_experiment(tmp_path)
    folder = repository.root / "experiments"
    before = attachment_contents(folder, EXPERIMENT)
    real = os.rename

    def rename(source, target):
        if str(source).endswith(f"{EXPERIMENT}.reports"):
            raise PermissionError(13, "held by a reader", str(source))
        return real(source, target)

    monkeypatch.setattr(runs.os, "rename", rename)
    with pytest.raises(Refused, match="in use"):
        library.delete("experiment", EXPERIMENT)
    assert attachment_contents(folder, EXPERIMENT) == before
    assert not (repository.root / "trash" / "experiments" / EXPERIMENT).exists()
    assert repository.list_trash() == []
    assert len(store.cells(EXPERIMENT)) == 12


def test_a_trash_move_waits_for_an_in_process_lab_read(tmp_path):
    """The Library takes the experiment's write lock for the move: a Lab read in this worker
    finishes first, so the move is not refused by our own reader."""
    repository, _store, library, _cells_dir = compacted_experiment(tmp_path)
    reading, finish = threading.Event(), threading.Event()

    def read():
        with lab_store.LOCKS.read(EXPERIMENT):
            reading.set()
            finish.wait(10)

    thread = threading.Thread(target=read)
    thread.start()
    assert reading.wait(10)
    deleted = threading.Event()
    deleter = threading.Thread(
        target=lambda: (library.delete("experiment", EXPERIMENT), deleted.set())
    )
    deleter.start()
    time.sleep(0.3)
    assert not deleted.is_set()  # waiting for the read, not refused and not moving
    finish.set()
    thread.join(10)
    deleter.join(10)
    assert deleted.is_set()
    assert [item["id"] for item in repository.list_trash()] == [EXPERIMENT]


@pytest.mark.skipif(os.name != "nt", reason="only Windows refuses a rename under an open file")
def test_a_hard_delete_under_a_held_part_deletes_nothing_and_says_so(tmp_path, quick_moves):
    """R3 QA D2: the hard delete never leaves a live experiment's folder half erased behind a
    removed document (whose id a new experiment could then take, reading the old trials)."""
    from products.aegis.runs import ItemBusy

    repository, store, _library, cells_dir = compacted_experiment(tmp_path)
    folder = repository.root / "experiments"
    before = attachment_contents(folder, EXPERIMENT)
    release = held(cells_dir / "part-1.parquet")
    try:
        with pytest.raises(ItemBusy, match="in use"):
            repository.delete_experiment(EXPERIMENT)
        assert attachment_contents(folder, EXPERIMENT) == before
        assert store.free_id("lab trials") != EXPERIMENT  # the id stays taken
    finally:
        release()
    repository.delete_experiment(EXPERIMENT)
    assert attachment_contents(folder, EXPERIMENT) == {}
    assert not any((repository.root / ".erasing").glob("*"))


# -- R3 QA observations O1 and O2 (2026-10-29): a refused undo still answers 409 and heals whole ---
def refusing(monkeypatch, refuse):
    """os.rename in runs refuses (as Windows does under a reader) whenever refuse(source, target)."""
    from products.aegis import runs

    real = os.rename

    def rename(source, target):
        if refuse(str(source), str(target)):
            raise PermissionError(13, "held by a reader", str(source))
        return real(source, target)

    monkeypatch.setattr(runs.os, "rename", rename)
    return lambda: monkeypatch.setattr(runs.os, "rename", real)


def without_sidecar(contents: dict) -> dict:
    return {k: v for k, v in contents.items() if not k.endswith(".summary.json")}


def test_a_refused_put_back_still_answers_refused_and_heals_whole(
    tmp_path, quick_moves, monkeypatch
):
    """O2: the forward move of `.curves` refused, then the put-back of `.cells` refused as well: the
    Library answers Refused (409), never a bare PermissionError (500), and says what stays in
    Recently deleted until the next try or a restart puts it back; the rest is put back at once."""
    from products.aegis.library import Refused

    repository, store, library, _cells_dir = compacted_experiment(tmp_path)
    binned = str(repository.root / "trash")  # never a test folder named "trash"
    folder = repository.root / "experiments"
    before = attachment_contents(folder, EXPERIMENT)
    trash = repository.root / "trash" / "experiments" / EXPERIMENT
    restore = refusing(
        monkeypatch,
        lambda s, t: (
            (s.endswith(f"{EXPERIMENT}.curves") and t.startswith(binned))
            or (
                s.endswith(f"{EXPERIMENT}.cells")
                and s.startswith(binned)
                and not t.startswith(binned)
            )
        ),
    )
    with pytest.raises(Refused, match="in use") as refused:
        library.delete("experiment", EXPERIMENT)
    assert f"{EXPERIMENT}.cells" in str(refused.value)  # the one piece not yet put back
    assert sorted(p.name for p in trash.iterdir()) == [f"{EXPERIMENT}.cells", "trash.json"]
    with lab_store.LOCKS.read(EXPERIMENT):
        pass  # the write lock is free again
    restore()
    assert repository.heal_trash() == [f"experiments/{EXPERIMENT}"]
    assert attachment_contents(folder, EXPERIMENT) == before and not trash.exists()
    assert len(store.cells(EXPERIMENT)) == 12


def test_a_stale_trashed_sidecar_is_never_a_clash(tmp_path, quick_moves, monkeypatch):
    """O1: a stranding that leaves the summary sidecar in Recently deleted, then a listing that
    rebuilds it live: the next heal drops the stale trashed copy (it is derived from the live
    document) instead of keeping a folder that refuses every later delete as a clash."""
    repository, _store, library, _cells_dir = compacted_experiment(tmp_path)
    binned = str(repository.root / "trash")  # never a test folder named "trash"
    folder = repository.root / "experiments"
    before = attachment_contents(folder, EXPERIMENT)
    trash = repository.root / "trash" / "experiments" / EXPERIMENT
    restore = refusing(
        monkeypatch,
        lambda s, t: (
            (s.endswith(f"{EXPERIMENT}.curves") and t.startswith(binned))
            or (s.startswith(binned) and not t.startswith(binned))
        ),  # every put-back refused
    )
    with pytest.raises(Exception, match="in use"):
        library.delete("experiment", EXPERIMENT)
    assert (trash / f"{EXPERIMENT}.summary.json").is_file()
    restore()
    assert [item["id"] for item in repository.list_experiments()] == [EXPERIMENT]  # sidecar rebuilt
    assert (folder / f"{EXPERIMENT}.summary.json").is_file()
    assert repository.heal_trash() == [f"experiments/{EXPERIMENT}"]
    assert not trash.exists()
    assert without_sidecar(attachment_contents(folder, EXPERIMENT)) == without_sidecar(before)
    library.delete("experiment", EXPERIMENT)  # no clash: the delete goes through whole
    library.restore("experiment", EXPERIMENT)
    assert without_sidecar(attachment_contents(folder, EXPERIMENT)) == without_sidecar(before)


def test_a_restore_replaces_an_orphan_live_sidecar(tmp_path):
    """O1, restore side: a live sidecar with no live document belongs to nothing (listings would
    show it as an item); the sidecar trashed with the document takes its place."""
    repository, _store, library, _cells_dir = compacted_experiment(tmp_path)
    folder = repository.root / "experiments"
    before = attachment_contents(folder, EXPERIMENT)
    library.delete("experiment", EXPERIMENT)
    (folder / f"{EXPERIMENT}.summary.json").write_text('{"id": "orphan"}', encoding="utf-8")
    library.restore("experiment", EXPERIMENT)
    assert attachment_contents(folder, EXPERIMENT) == before
    assert not (repository.root / "trash" / "experiments" / EXPERIMENT).exists()


def test_heal_trash_never_raises_on_a_held_piece(tmp_path, quick_moves, monkeypatch):
    """At worker start a held piece is skipped and logged, never an error that stops the worker;
    the next heal finishes it."""
    from products.aegis.library import Refused

    repository, _store, library, _cells_dir = compacted_experiment(tmp_path)
    binned = str(repository.root / "trash")  # never a test folder named "trash"
    folder = repository.root / "experiments"
    before = attachment_contents(folder, EXPERIMENT)
    restore = refusing(
        monkeypatch,
        lambda s, t: (
            (s.endswith(f"{EXPERIMENT}.curves") and t.startswith(binned))
            or (
                s.endswith(f"{EXPERIMENT}.cells")
                and s.startswith(binned)
                and not t.startswith(binned)
            )
        ),
    )
    with pytest.raises(Refused):
        library.delete("experiment", EXPERIMENT)
    assert repository.heal_trash() == []  # the put-back still refused: skipped, not raised
    restore()
    assert repository.heal_trash() == [f"experiments/{EXPERIMENT}"]
    assert attachment_contents(folder, EXPERIMENT) == before


def test_an_undone_hard_delete_is_put_back_never_erased(tmp_path, quick_moves, monkeypatch):
    """A hard delete refused part way whose put-back is refused too: the piece left in the staging
    folder belongs to a live experiment, so heal_trash puts it back; it erases only a staging
    folder that holds its document (the delete got past its last move)."""
    from products.aegis.runs import ItemBusy

    repository, store, _library, _cells_dir = compacted_experiment(tmp_path)
    folder = repository.root / "experiments"
    before = attachment_contents(folder, EXPERIMENT)
    restore = refusing(
        monkeypatch,
        lambda s, t: (
            (s.endswith(f"{EXPERIMENT}.curves") and ".erasing" in t)
            or (s.endswith(f"{EXPERIMENT}.cells") and ".erasing" in s)
        ),
    )
    with pytest.raises(ItemBusy, match="in use"):
        store.delete(EXPERIMENT)
    (staging,) = (repository.root / ".erasing").iterdir()
    assert sorted(p.name for p in staging.iterdir()) == [f"{EXPERIMENT}.cells"]
    restore()
    repository.heal_trash()
    assert attachment_contents(folder, EXPERIMENT) == before  # put back, not erased
    assert not any((repository.root / ".erasing").iterdir())
    assert len(store.cells(EXPERIMENT)) == 12


def test_heal_trash_erases_a_staging_folder_that_holds_its_document(tmp_path):
    repository = JsonRunRepository(tmp_path / "aegis")
    staging = repository.root / ".erasing" / "experiments-gone-1a2b3c4d"
    (staging / "gone.cells").mkdir(parents=True)
    (staging / "gone.cells" / "part-1.parquet").write_bytes(b"x")
    (staging / "gone.json.gz").write_bytes(b"x")
    repository.heal_trash()
    assert not staging.exists()


def finished_through_api(c, runner, name: str) -> str:
    """A layout-2 experiment created through `POST /experiments` (so `data_pinned` and `versions`
    are written) and run to `done`. It waits for the runner's own record too: the runner saves the
    document once more after the experiment's finalize, so a test that rewrites the document
    must not race that last save."""
    created = c.post("/aegis/api/experiments", json=_experiment_body(c, name=name))
    assert created.status_code == 202, created.text
    experiment_id, job_id = created.json()["experiment_id"], created.json()["job_id"]
    assert job_id
    done = _wait_experiment(c, experiment_id, ("done", "failed"))
    assert done["status"] == "done", done.get("error")
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")
    return experiment_id


def paused_layout2(c, runner, repository, name: str) -> dict:
    """A finished layout-2 experiment persisted as paused with a dead job, the way
    test_aegis_api.py's paused-experiment test does: a `done` document is refused before any
    drift check, and `/pause` answers 409 unless the document is running with a live job."""
    experiment_id = finished_through_api(c, runner, name)
    document = exp.ExperimentStore(repository).get(experiment_id)
    assert document.cells_layout == 2 and document.data_pinned and document.versions
    paused = {**document.model_dump(mode="json"), "status": "paused", "job_id": "dead"}
    repository.save_experiment(paused)
    return paused


def bars_spy(monkeypatch) -> list[tuple[str, str]]:
    """Record each call of the module-level `_experiment_bars` (the legacy re-selection)."""
    calls = []
    real = api._experiment_bars

    def spy(data, store):
        calls.append((data.symbol, data.timeframe))
        return real(data, store)

    monkeypatch.setattr(api, "_experiment_bars", spy)
    return calls


def test_resume_refuses_vintage_drift(client, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    c, _, repository = client
    runner = _runner(repository)
    paused = paused_layout2(c, runner, repository, "vintage drift")
    write_archive(tmp_path, "20260301T000000000000Z", "QQQ", price=101.0)  # same vintage, new bytes
    response = c.post(f"/aegis/api/experiments/{paused['id']}/resume")
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail.startswith("resume refused: data drift: ") and "sha256 mismatch" in detail
    after = c.get(f"/aegis/api/experiments/{paused['id']}").json()
    assert after["status"] == "paused" and after["data_pinned"] == paused["data_pinned"]
    assert repository.get_experiment(paused["id"]) == paused  # the document is unchanged


def test_resume_refuses_engine_build_drift(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    c, _, repository = client
    runner = _runner(repository)
    paused = paused_layout2(c, runner, repository, "engine drift")
    recorded = paused["versions"]["engine_build"]
    assert recorded == identity.engine_build()
    monkeypatch.setattr(identity, "engine_build", lambda: "0" * 64)
    response = c.post(f"/aegis/api/experiments/{paused['id']}/resume")
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        f"resume refused: engine build drift (document {recorded[:12]}, worker {'0' * 12})"
    )
    after = c.get(f"/aegis/api/experiments/{paused['id']}").json()
    assert after["status"] == "paused" and after["data_pinned"] == paused["data_pinned"]
    assert repository.get_experiment(paused["id"]) == paused


def test_materialize_refuses_vintage_drift(client, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    c, _, repository = client
    runner = _runner(repository)
    store = exp.ExperimentStore(repository)
    # (1) A finished layout-2 experiment: its trial is re-run on the bytes its row came from.
    first = finished_through_api(c, runner, "pinned materialize")
    document = store.get(first)
    url = f"/aegis/api/experiments/{first}/cells/0/materialize"
    ran = c.post(url)
    assert ran.status_code == 200, ran.text
    assert ran.json()["data"]["sha256"] == document.data_pinned["sha256"]
    runs = len(repository.list_runs())
    # (2) The fixture's vintage folder rewritten with new bytes under the same name.
    write_archive(tmp_path, "20260301T000000000000Z", "QQQ", price=101.0)
    # (3) The layout-2 materialize refuses the drift (load_pinned re-hashes the file on disk).
    refused = c.post(url)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"].startswith("materialize refused: data drift: ")
    assert len(repository.list_runs()) == runs  # no new run saved
    # (4) A second experiment, made legacy. The fixture's ArchiveStore cached the sources and the
    # frame before the rewrite, so this one is pinned to the old digest too and its layout-2
    # materialize would be refused the same way: its folder and document become layout 1.
    second = finished_through_api(c, runner, "legacy materialize")
    assert store.get(second).data_pinned["sha256"] == document.data_pinned["sha256"]
    cells_dir = store.cells_dir(second)
    legacy = store.cells(second)  # the layout-1 column set, as `test_legacy_read_equals_cells`
    assert legacy.schema.equals(exp._cells_schema(store.get(second).surface.paths()))
    assert sorted(path.name for path in cells_dir.iterdir()) == ["manifest.json", "part-1.parquet"]
    (cells_dir / "part-1.parquet").unlink()
    (cells_dir / lab_store.MANIFEST).unlink()
    pq.write_table(legacy, cells_dir / "000000.parquet")
    raw = repository.get_experiment(second)
    for key in LAYOUT2_FIELDS:
        raw.pop(key, None)
    repository.save_experiment(raw)
    assert store.layout(second) == 1 and store.get(second).cells_layout == 1
    assert store.get(second).data_pinned is None and store.get(second).versions is None
    # (5) Its materialize takes today's path: the module-level re-selection, once.
    calls = bars_spy(monkeypatch)
    again = c.post(f"/aegis/api/experiments/{second}/cells/0/materialize")
    assert again.status_code == 200, again.text
    assert calls == [("QQQ", "15m")]
    assert len(repository.list_runs()) == runs + 1


def test_legacy_resume_unchanged(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    c, _, repository = client
    runner = _runner(repository)
    store = exp.ExperimentStore(repository)
    body = exp.ExperimentRequest.model_validate(_experiment_body(c, name="legacy resume"))
    doc = exp.create(store, StrategyLibrary(repository), body, bars=52, max_workers=2)
    (store.cells_dir(doc.id) / lab_store.MANIFEST).unlink()  # a cells folder from before layout 2
    raw = {**doc.model_dump(mode="json"), "status": "paused", "job_id": "dead"}
    for key in LAYOUT2_FIELDS:
        del raw[key]
    repository.save_experiment(raw)
    legacy = store.get(doc.id)
    assert legacy.cells_layout == 1 and legacy.data_pinned is None and legacy.versions is None
    assert store.layout(doc.id) == 1
    calls = bars_spy(monkeypatch)
    resumed = c.post(f"/aegis/api/experiments/{doc.id}/resume")
    assert resumed.status_code == 202, resumed.text
    assert calls == [("QQQ", "15m")]  # re-selected once, as before Task 6
    job_id = resumed.json()["job_id"]
    assert wait_for(lambda: runner.status(job_id)["status"] in ("done", "failed", "cancelled"))
    finished = store.get(doc.id)
    assert finished.status == "done", finished.error
    assert finished.progress["cells_done"] == 4
    assert store.layout(doc.id) == 1  # today's path: layout-1 chunks, never compacted
    assert lab_store.read_manifest(store.cells_dir(doc.id)) is None


def test_canonical_skips_the_take_on_identity_order(monkeypatch):
    """A table already strictly increasing in (trial_no, block), as a part and the chunks after
    it are written, is canonical as read: no sort and no `take` (one chunk per column, as the
    take left it); a repeated (trial_no, block) still sorts and dedupes."""
    import pyarrow.compute as pc

    taken: list[str] = []
    original_take, original_sort = pc.take, pc.sort_indices

    def take(data, indices, *args, **kwargs):
        taken.append(type(data).__name__)
        return original_take(data, indices, *args, **kwargs)

    def sort_indices(*args, **kwargs):
        taken.append("sort_indices")
        return original_sort(*args, **kwargs)

    monkeypatch.setattr(pc, "take", take)
    monkeypatch.setattr(pc, "sort_indices", sort_indices)

    def table(rows: list[tuple[int, int, int]]) -> pa.Table:
        trial, block, attempt = zip(*rows, strict=True)
        return pa.table(
            {
                "trial_no": pa.array(trial, pa.int64()),
                "block": pa.array(block, pa.uint8()),
                "attempt": pa.array(attempt, pa.uint8()),
                "status": pa.array(["ok"] * len(rows)).dictionary_encode(),
            }
        )

    blocked = [(0, 0, 0), (0, 1, 0), (0, 2, 1), (1, 0, 0), (1, 2, 0), (4, 0, 2), (4, 1, 0)]
    in_order = pa.concat_tables([table(blocked[:3]), table(blocked[3:])])  # a part, then a chunk
    assert in_order.column("trial_no").num_chunks == 2
    canonical, duplicates = lab_store._canonical(in_order)
    assert taken == [] and duplicates == 0
    assert canonical.equals(in_order)
    assert {canonical.column(name).num_chunks for name in canonical.column_names} == {1}

    repeated = table([(0, 0, 0), (1, 0, 0), (1, 0, 1), (1, 0, 1), (2, 0, 0), (2, 1, 0)])
    canonical, duplicates = lab_store._canonical(repeated)
    assert "Table" in taken and "sort_indices" in taken
    assert duplicates == 1  # the second copy of (1, 0) attempt 1
    kept = canonical.select(["trial_no", "block", "attempt"]).to_pylist()
    assert [tuple(row.values()) for row in kept] == [(0, 0, 0), (1, 0, 1), (2, 0, 0), (2, 1, 0)]
    taken.clear()
    backwards = table([(3, 0, 0), (1, 0, 0)])  # in no order: sorted
    canonical, _ = lab_store._canonical(backwards)
    assert canonical.column("trial_no").to_pylist() == [1, 3] and "Table" in taken


def test_compaction_keeps_the_canonical_rows_at_its_watermark(tmp_path):
    """What Lab Phase 3 Task 6's ruling rests on (two snapshots of one watermark are one evidence):
    merging a watermark's chunks leaves its canonical rows as they were, in every column and in
    order, whatever the chunks hold: a screening block's rows, a retried attempt, a copy of a
    (trial_no, block, attempt) with other metrics (the first read wins, before and after), and an
    unreadable chunk, read by neither. A reclaim then changes nothing, and a compaction with
    nothing new is no generation at all."""
    changed = {**trial_row(3), "metrics": metrics_of(9)}
    chunks = [
        [*rows_of(range(4)), trial_row(0, block=1), trial_row(1, block=1)],
        rows_of(range(4, 6)),
        [changed, trial_row(5, attempt=1, metrics=metrics_of(10))],
        [trial_row(0, attempt=1, block=1, metrics=metrics_of(11)), *rows_of(range(6, 8))],
    ]
    cells_dir = layout2_dir(tmp_path, chunks)
    write_trials(cells_dir, 4, rows_of(range(8, 10)))
    (cells_dir / "000001.parquet").write_bytes(b"x")  # torn after it landed: trials 4 and 5 gone
    _, before_at = lab_store.latest_snapshot(cells_dir)
    assert before_at == lab_store.Snapshot(0, 4)
    before = lab_store.read_trials(cells_dir, before_at)
    assert before.duplicates == 1

    def rows(trials):
        return repr(trials.table.to_pylist())  # repr: NaN and null compare as they read

    manifest = lab_store.compact(cells_dir, now=NOW)
    _, after_at = lab_store.latest_snapshot(cells_dir)
    assert after_at == lab_store.Snapshot(1, 4) and manifest.chunk_watermark == 4
    after = lab_store.read_trials(cells_dir, after_at)
    assert after.table.schema.names == before.table.schema.names
    assert rows(after) == rows(before) and after.duplicates == before.duplicates
    assert rows(lab_store.read_trials(cells_dir, before_at)) == rows(before)
    table = after.table.to_pylist()
    three = next(row for row in table if row["trial_no"] == 3)
    assert three["combined.net_pnl"] == metrics_of(3)["combined"]["net_pnl"]  # the first read
    five = next(row for row in table if row["trial_no"] == 5)
    assert five["attempt"] == 1  # the torn chunk's attempt 0 is gone, the retry stands
    retried = next(row for row in table if (row["trial_no"], row["block"]) == (0, 1))
    assert retried["attempt"] == 1
    assert 4 not in {row["trial_no"] for row in table}
    lab_store.reclaim(cells_dir, now=NOW + 601)
    assert rows(lab_store.read_trials(cells_dir, after_at)) == rows(before)
    assert lab_store.compact(cells_dir, now=NOW + 602).generation == 1  # nothing new
    assert lab_store.latest_snapshot(cells_dir)[1] == after_at
