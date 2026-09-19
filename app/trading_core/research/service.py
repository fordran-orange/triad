from trading_core.resources import resource

"""Authoritative laboratory records, artifact broker, reproducibility and review."""

import itertools
import json
import platform
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from trading_core.brain import Brain
from trading_core.execution import ExecutionServices
from trading_core.research.contracts import (
    BacktestRun,
    Costs,
    DatasetManifest,
    Experiment,
    Hypothesis,
    LabLimits,
    Partition,
    Slippage,
)
from trading_core.research.data import Archive, FixtureProvider, digest, quality, save_json
from trading_core.research.engine import run_engine
from trading_core.settings import ROOT
from trading_core.work import Handoff, Review, State, WorkItem, WorkResult, now, uid


def source_hash(directory=None):
    files = sorted((directory or Path(__file__).parent).glob("*.py"))
    return digest(b"".join(p.name.encode() + p.read_bytes().replace(b"\r\n", b"\n") for p in files))


def write_run_status(path, run):
    """Replace only mutable run status; completed result artifacts remain untouched."""
    for target, payload in (
        (
            path / "logs/events.json",
            {
                "run_id": run.run_id,
                "status": run.status,
                "content_hash": run.content_hash,
                "errors": run.errors,
            },
        ),
        (path / "manifest.json", run.model_dump(mode="json")),
    ):
        temporary = target.with_name(target.name + ".tmp-" + uid())
        save_json(temporary, payload)
        temporary.replace(target)


class Laboratory:
    def __init__(self, cycles=None, root=ROOT, limits=None):
        self.cycles = cycles or ExecutionServices()
        self.ledger = self.cycles.ledger
        self.host = self.cycles.host
        self.root = Path(root)
        self.limits = limits or LabLimits.model_validate(
            json.loads(resource("config/core/research.json").read_text())
        )
        self.archive = Archive(root, self.limits)

    def put(self, kind, payload, identifier=None, work_id=None, conn=None):
        return self.ledger.put(kind, payload, identifier=identifier, work_id=work_id, conn=conn)

    def model(self, kind, identifier, cls):
        row = self.ledger.get(identifier)
        if row["kind"] != kind:
            raise ValueError("Wrong record kind")
        return cls.model_validate({k: v for k, v in row.items() if k in cls.model_fields})

    def catalog(self, symbol=None):
        rows = self.ledger.records("DatasetManifest", 1000)
        return [r for r in rows if symbol is None or symbol in r["symbols"]]

    def ingest(self, symbol, start, end, provider=None):
        provider = provider or FixtureProvider()
        epoch = self.ledger.guard()["epoch"]
        job_id = uid()
        job = {
            "job_id": job_id,
            "status": "REQUESTED",
            "mode": provider.mode,
            "symbol": symbol,
            "stages": [],
            "limits": self.limits.model_dump(),
        }
        self.put("IngestionJob", job, job_id)
        try:
            with self.host.store.lease("lab-ingestion"):
                raw = provider.fetch_bars(symbol, start, end)
                self.ledger.guard(epoch=epoch)
                metadata = self.archive.preserve(raw, provider, symbol, start, end, job_id)
                self.put("RawDataset", metadata, job_id + "-raw")
                job.update(status="RAW_PRESERVED", raw=metadata)
                job["stages"].append("raw_preserved")
                self.put("IngestionJob", job, job_id)
                rows = self.archive.normalize(raw, metadata)
                report, bars = quality(rows, symbol, start, end)
                report_id = self.put("QualityReport", {**report, "job_id": job_id})
                job.update(quality_report=report_id)
                if report["status"] != "PASS":
                    raise ValueError("DATA_QUALITY_FAILURE")
                self.ledger.guard(epoch=epoch)
                manifest = self.archive.publish(bars, metadata, report)
                self.put("DatasetManifest", manifest.model_dump(mode="json"), manifest.dataset_id)
                job.update(status="COMPLETED", dataset_id=manifest.dataset_id)
                job["stages"] += [
                    "normalized",
                    "quality_passed",
                    "canonical_written",
                    "manifest_written",
                    "catalog_registered",
                ]
                self.put("IngestionJob", job, job_id)
                Brain(self.host.store).flush()
                return manifest
        except Exception as exc:
            job.update(status="FAILED", error_class=type(exc).__name__)
            self.put("IngestionJob", job, job_id)
            raise

    def recover_ingestion(self, job_id):
        """Only reprocess retained raw; preserve failed originals, publish a new version."""
        job = self.ledger.get(job_id)
        if job["kind"] != "IngestionJob" or job["status"] == "COMPLETED" or "raw" not in job:
            raise ValueError("Recovery requires an incomplete job with preserved raw")
        metadata = job["raw"]
        path = (self.root / metadata["path"]).resolve()
        if not path.is_relative_to((self.root / "data/raw").resolve()):
            raise PermissionError("Invalid raw path")
        raw = path.read_bytes()
        if digest(raw) != metadata["checksum"]:
            raise ValueError("Raw checksum mismatch")

        class Retained:
            name, mode = metadata["provider"], metadata["mode"]

            def fetch_bars(self, *args):
                return raw

        request = metadata["request"]
        result = self.ingest(
            request["symbol"],
            datetime.fromisoformat(request["start"]),
            datetime.fromisoformat(request["end"]),
            Retained(),
        )
        self.put(
            "RecoveryRecord",
            {
                "original_job": job_id,
                "dataset_id": result.dataset_id,
                "method": "reprocess preserved raw without mutation",
            },
        )
        return result

    def derive(self, identifier, resolution):
        epoch = self.ledger.guard()["epoch"]
        with self.host.store.lease("lab-ingestion"):
            manifest = self.model("DatasetManifest", identifier, DatasetManifest)
            derived = self.archive.derive(manifest, resolution)
            self.ledger.guard(epoch=epoch)
            self.put("DatasetManifest", derived.model_dump(mode="json"), derived.dataset_id)
            Brain(self.host.store).flush()
            return derived

    def create_experiment(self, dataset_id, config=None):
        self.ledger.guard()
        dataset = self.model("DatasetManifest", dataset_id, DatasetManifest)
        if dataset.quality_status != "PASS":
            raise ValueError("Quality failed")
        hypothesis = Hypothesis(
            statement="Identical deterministic inputs reproduce identical research artifacts.",
            rationale="Validate the laboratory architecture, not investment returns",
            expected_behavior="Trade, equity, decision and metric content hashes match",
            falsification_condition="Any deterministic content differs with unchanged dataset, code, parameters and seed",
        )
        self.put("Hypothesis", hypothesis.model_dump(mode="json"), hypothesis.hypothesis_id)
        experiment = Experiment(
            name="Fixture reproducibility",
            description="Architecture validation only; no alpha or strategy endorsement",
            hypothesis=hypothesis.hypothesis_id,
            dataset_id=dataset_id,
            dataset_version=dataset.dataset_version,
            symbols=dataset.symbols,
            timeframe=dataset.resolution,
            start_time=dataset.start_time,
            end_time=dataset.end_time,
            code_commit=self.cycles.git.git("rev-parse", "HEAD"),
            environment={
                "python": platform.python_version(),
                "pandas": pd.__version__,
                "pyarrow": pa.__version__,
                "lab_source_sha256": source_hash(),
                "lab_source_hash_format": "lf-v1",
            },
            acceptance_criteria=(
                "Identical deterministic content hash on rerun",
                "No future data or same-bar fill",
                "Costs and directions separately recorded",
            ),
            partitions=(Partition(name="test", start=dataset.start_time, end=dataset.end_time),),
            fees_model=Costs(fixed=0.05, per_share=0.001, bps=0.2),
            slippage_model=Slippage(bps=1, spread_bps=2),
        )
        if config:
            allowed = {
                "name",
                "description",
                "parameters",
                "directions",
                "fees_model",
                "slippage_model",
                "position_sizing_model",
                "partitions",
                "selected_partition",
                "strategy_version",
                "random_seed",
            }
            if not set(config) <= allowed:
                raise PermissionError("Experiment configuration exceeds allowed fields")
            experiment = Experiment.model_validate({**experiment.model_dump(), **config})
        self.put("Experiment", experiment.model_dump(mode="json"), experiment.experiment_id)
        path = self.root / f"research/experiments/{experiment.experiment_id}"
        save_json(path / "manifest.json", experiment.model_dump(mode="json"))
        save_json(path / "parameters.json", experiment.parameters)
        return experiment

    def run(self, experiment_id, parameters=None, *, run_id=None):
        with self.host.store.lease("lab-backtest"):
            result = self._run(experiment_id, parameters, run_id=run_id)
        Brain(self.host.store).flush()
        return result

    def _run(self, experiment_id, parameters=None, *, run_id=None):
        experiment = self.model("Experiment", experiment_id, Experiment)
        if parameters is not None:
            experiment = Experiment.model_validate(
                {**experiment.model_dump(), "parameters": parameters}
            )
        if experiment.environment["lab_source_sha256"] != source_hash():
            raise ValueError("CODE_VERSION_MISMATCH: use original code before rerun")
        dataset = self.model("DatasetManifest", experiment.dataset_id, DatasetManifest)
        if (
            dataset.dataset_version != experiment.dataset_version
            or dataset.resolution != experiment.timeframe
        ):
            raise ValueError("Dataset version/timeframe mismatch")
        epoch = self.ledger.guard()["epoch"]
        work = self.host.create(
            WorkItem(
                title="Bounded fixture backtest",
                description=experiment.description,
                mission_id=experiment.experiment_id,
                work_type="research_artifact",
                assigned_agent="CODEX",
                authority_tier=1,
                allowed_paths=("data/canonical", "research/experiments"),
                expected_outputs=("Portable backtest artifacts",),
                acceptance_criteria=experiment.acceptance_criteria,
            )
        )
        work, _policy = self.cycles.start_work(work, epoch)
        run = BacktestRun(
            run_id=run_id or uid(),
            experiment_id=experiment.experiment_id,
            parameters=experiment.parameters,
            start_time=experiment.start_time,
            end_time=experiment.end_time,
            code_commit=experiment.code_commit,
            dataset_version=dataset.dataset_version,
            work_item_id=work.work_item_id,
        )
        self.put("BacktestRun", run.model_dump(mode="json"), run.run_id, work.work_item_id)
        start = time.monotonic()
        path = self.root / f"research/experiments/{experiment_id}/runs/{run.run_id}"
        tracemalloc.start()
        try:
            path.mkdir(parents=True, exist_ok=False)
            write_run_status(path, run)
            frame = self.archive.load(dataset)

            def guard():
                self.ledger.guard(work.assigned_agent, work.work_item_id, epoch)
                if tracemalloc.get_traced_memory()[1] > self.limits.memory_mb * 1024 * 1024:
                    raise MemoryError("Research allocation ceiling")

            result = run_engine(frame, experiment, self.limits, guard=guard)
            guard()
            artifacts = {}
            # IDs are added to storage; deterministic content excludes incidental run UUID/time.
            for name in ("trades", "equity", "decisions"):
                table = pa.Table.from_pylist(
                    [{**row, "run_id": run.run_id} for row in result[name]]
                )
                if name == "trades" and not result[name]:
                    text_fields = (
                        "trade_id",
                        "run_id",
                        "symbol",
                        "direction",
                        "entry_reason",
                        "exit_reason",
                    )
                    time_fields = ("signal_time", "entry_time", "exit_signal_time", "exit_time")
                    numbers = (
                        "entry_price",
                        "exit_price",
                        "quantity",
                        "gross_pnl",
                        "fees",
                        "slippage",
                        "net_pnl",
                        "return",
                        "mae",
                        "mfe",
                        "holding_period_minutes",
                        "time_to_profit_minutes",
                        "time_to_failure_minutes",
                    )
                    table = pa.Table.from_pylist(
                        [],
                        schema=pa.schema(
                            [(f, pa.string()) for f in text_fields]
                            + [(f, pa.timestamp("us", tz="UTC")) for f in time_fields]
                            + [(f, pa.float64()) for f in numbers]
                        ),
                    )
                target = path / f"{name}.parquet"
                pq.write_table(table, target, compression="zstd")
                artifacts[name] = {
                    "path": target.relative_to(self.root).as_posix(),
                    "sha256": digest(target.read_bytes()),
                }
            save_json(path / "metrics.json", result["metrics"])
            save_json(path / "parameters.json", experiment.model_dump(mode="json"))
            for name in ("metrics", "parameters"):
                target = path / f"{name}.json"
                artifacts[name] = {
                    "path": target.relative_to(self.root).as_posix(),
                    "sha256": digest(target.read_bytes()),
                }
            peak = tracemalloc.get_traced_memory()[1]
            finished = run.model_copy(
                update={
                    "status": "COMPLETED",
                    "completed_at": now(),
                    "runtime": time.monotonic() - start,
                    "peak_memory_bytes": peak,
                    "storage_bytes": sum(p.stat().st_size for p in path.iterdir() if p.is_file()),
                    "result_artifacts": artifacts,
                    "metrics": result["metrics"],
                    "content_hash": result["content_hash"],
                    "logs": (
                        "FIXTURE; trusted deterministic engine; no remote model called",
                        "CLOSE_SIGNAL_NEXT_OPEN; separate direction portfolios; final-open forced liquidation",
                    ),
                }
            )
            evidence = tuple(a["sha256"] for a in artifacts.values())
            journal = self.host.journal(
                work,
                kind="creation",
                result="Fixture research artifacts generated; no trading conclusion",
                evidence=evidence,
                tests=("deterministic host validation",),
                mode="FIXTURE_HOST",
            )
            handoff = Handoff(
                from_agent=work.assigned_agent,
                to_agent=work.reviewer,
                work_item_id=work.work_item_id,
                completed_work="Inspect hypothesis, dataset quality, original code, costs, fills and portable artifacts",
                files_changed=tuple(a["path"] for a in artifacts.values()),
                tests_performed=("schema and checksum validation",),
                evidence=evidence,
                recommended_checks=experiment.acceptance_criteria,
                git_commit=experiment.code_commit,
                review_request="Independent research-method review required; profitability is not a correctness verdict",
            )
            guard()
            with (
                self.ledger.gate(work.assigned_agent, work.work_item_id, epoch),
                self.host.store.connect() as conn,
            ):
                self.put(
                    "BacktestRun",
                    finished.model_dump(mode="json"),
                    run.run_id,
                    work.work_item_id,
                    conn=conn,
                )
                self.host.advance(
                    work,
                    State.AWAITING_REVIEW,
                    "Research artifacts ready for independent review",
                    records=(journal, handoff),
                    conn=conn,
                    result=WorkResult(
                        summary="Fixture backtest complete; method review pending",
                        evidence=evidence,
                        execution_mode="deterministic_demo",
                    ),
                )
                write_run_status(path, finished)
            return finished
        except Exception as exc:
            failed = run.model_copy(
                update={
                    "status": "FAILED",
                    "errors": (type(exc).__name__,),
                    "completed_at": now(),
                    "runtime": time.monotonic() - start,
                }
            )
            try:
                write_run_status(path, failed)
            except OSError:
                # A full/unavailable disk must not suppress the authoritative failure record.
                failed = failed.model_copy(
                    update={"errors": (*failed.errors, "StatusPublicationError")}
                )
            self.put("BacktestRun", failed.model_dump(mode="json"), run.run_id, work.work_item_id)
            current = self.host.store.get(work.work_item_id)
            if current.status == State.IN_PROGRESS:
                journal = self.host.journal(
                    current,
                    kind="failure",
                    result="Research run failed",
                    failures=(type(exc).__name__,),
                    mode="FIXTURE_HOST",
                )
                self.host.advance(
                    current,
                    State.FAILED,
                    "Research failure preserved",
                    records=(journal,),
                    failure_reason=type(exc).__name__,
                )
            raise
        finally:
            tracemalloc.stop()

    def commit_review(self, work, review, record, epoch):
        journal = self.host.journal(
            work,
            kind="review",
            result=record["decision"],
            evidence=review.evidence_checked,
            tests=review.tests_repeated,
            mode=review.execution_mode,
        )
        with (
            self.ledger.gate(work.reviewer, work.work_item_id, epoch),
            self.host.store.connect() as conn,
        ):
            accepted = review.decision == "APPROVE"
            work = self.host.advance(
                work,
                State.APPROVED_BY_REVIEWER if accepted else State.CHANGES_REQUESTED,
                "Research method review",
                records=(review, journal),
                review=review,
                conn=conn,
            )
            self.put("ResearchReview", record, review.review_id, work.work_item_id, conn=conn)
            if accepted:
                self.host.advance(
                    work, State.COMPLETED, "Research method accepted", review=review, conn=conn
                )

    def review(self, run_id):
        """A distinct host verifier reruns original evidence; NOT a cloud-model review."""
        run = self.model("BacktestRun", run_id, BacktestRun)
        work = self.host.store.get(run.work_item_id)
        epoch = self.ledger.guard(work.reviewer, work.work_item_id)["epoch"]
        if work.status != State.AWAITING_REVIEW:
            raise ValueError("Research work is not awaiting review")
        self.host.store.receive_handoff(work.work_item_id, work.reviewer)
        experiment = self.model("Experiment", run.experiment_id, Experiment)
        experiment = Experiment.model_validate(
            {**experiment.model_dump(), "parameters": run.parameters}
        )
        dataset = self.model("DatasetManifest", experiment.dataset_id, DatasetManifest)
        decision, findings = "ACCEPT_RESULT", []
        try:
            if source_hash() != experiment.environment["lab_source_sha256"]:
                raise ValueError("Code changed")
            dataset = self.model("DatasetManifest", experiment.dataset_id, DatasetManifest)
            frame = self.archive.load(dataset)
            with self.host.store.lease("lab-backtest"):
                repeated = run_engine(
                    frame,
                    experiment,
                    self.limits,
                    guard=lambda: self.ledger.guard(work.reviewer, work.work_item_id, epoch),
                )
            if repeated["content_hash"] != run.content_hash:
                decision = "REQUEST_RERUN"
            for artifact in run.result_artifacts.values():
                target = (self.root / artifact["path"]).resolve()
                if (
                    not target.is_relative_to((self.root / "research/experiments").resolve())
                    or digest(target.read_bytes()) != artifact["sha256"]
                ):
                    decision = "DATA_QUALITY_FAILURE"
            findings = [
                "Original dataset checksums and deterministic results independently recomputed",
                "No alpha claim; verification cannot establish general strategy quality",
            ]
        except (ValueError, OSError):
            decision, findings = (
                "DATA_QUALITY_FAILURE",
                ["Dataset/artifact or code verification failed"],
            )
        review = Review(
            reviewer=work.reviewer,
            work_item_id=work.work_item_id,
            decision="APPROVE" if decision == "ACCEPT_RESULT" else "REQUEST_CHANGES",
            findings=tuple(findings),
            severity="NONE" if decision == "ACCEPT_RESULT" else "HIGH",
            evidence_checked=(run.content_hash,),
            tests_repeated=("independent deterministic rerun", "artifact and dataset hashes"),
            execution_mode="HOST_VERIFIER_NOT_MODEL",
        )
        record = {
            "review_id": review.review_id,
            "run_id": run_id,
            "experiment_id": run.experiment_id,
            "decision": decision,
            "reviewer": work.reviewer,
            "mode": "HOST_VERIFIER_NOT_MODEL",
            "findings": findings,
            "review_packet": {
                "experiment": experiment.model_dump(mode="json"),
                "dataset": dataset.model_dump(mode="json"),
                "run": run.model_dump(mode="json"),
            },
        }
        self.commit_review(work, review, record, epoch)
        review_path = (
            self.root / f"research/experiments/{run.experiment_id}/runs/{run_id}/review.md"
        )
        review_path.write_text(
            "# Research review\n\n"
            + decision
            + "\n\nMode: HOST_VERIFIER_NOT_MODEL\n\n"
            + "\n".join(findings),
            encoding="utf-8",
        )
        Brain(self.host.store).flush()
        return record

    def sweep(self, experiment_id, ranges):
        experiment = self.model("Experiment", experiment_id, Experiment)
        if experiment.selected_partition == "test":
            raise PermissionError("Parameter search on test partition is forbidden")
        if set(ranges) != {"period", "hold"} or any(
            not isinstance(v, list) or not v for v in ranges.values()
        ):
            raise ValueError("Explicit period and hold ranges required")
        combinations = len(ranges["period"]) * len(ranges["hold"])
        if combinations > self.limits.max_combinations:
            raise ValueError("Sweep combination ceiling")
        identifier = uid()
        record = {
            "sweep_id": identifier,
            "experiment_id": experiment_id,
            "parameter_count": 2,
            "ranges": ranges,
            "variants_planned": combinations,
            "tests_attempted": 0,
            "attempts": [],
            "runs": [],
            "status": "RUNNING",
            "selection_method": "NONE; all variants retained",
            "out_of_sample_result": None,
            "parallelization": 1,
            "runtime_budget_seconds": self.limits.runtime_seconds,
        }
        start = time.monotonic()
        try:
            for period, hold in itertools.product(ranges["period"], ranges["hold"]):
                if time.monotonic() - start > self.limits.runtime_seconds:
                    raise TimeoutError("Sweep runtime ceiling")
                attempt = {
                    "attempt_id": uid(),
                    "parameters": {"period": period, "hold": hold},
                    "run_id": None,
                    "status": "STARTING",
                }
                reserved_run_id = uid()
                record["attempts"].append(attempt)
                record["tests_attempted"] += 1
                self.put("ParameterSweep", record, identifier)
                try:
                    self.run(experiment_id, attempt["parameters"], run_id=reserved_run_id)
                except Exception as exc:
                    attempt["error_class"] = type(exc).__name__
                    raise
                finally:
                    try:
                        actual = self.ledger.get(reserved_run_id)
                    except KeyError:
                        attempt["status"] = "NOT_STARTED"
                    else:
                        attempt.update(run_id=reserved_run_id, status=actual["status"])
                        record["runs"].append(reserved_run_id)
                    self.put("ParameterSweep", record, identifier)
            record["status"] = "COMPLETED"
        except Exception as exc:
            record.update(status="BLOCKED", error_class=type(exc).__name__)
            raise
        finally:
            self.put("ParameterSweep", record, identifier)
        return record

    def demo(self):
        data = self.ingest(
            "LABTEST",
            datetime(2026, 9, 14, 13, 30, tzinfo=UTC),
            datetime(2026, 9, 16, 20, tzinfo=UTC),
        )
        derived = [
            self.derive(data.dataset_id, resolution)
            for resolution in ("5m", "15m", "30m", "1h", "1d")
        ]
        experiment = self.create_experiment(data.dataset_id)
        first, second = self.run(experiment.experiment_id), self.run(experiment.experiment_id)
        assert first.content_hash == second.content_hash
        reviews = [self.review(first.run_id), self.review(second.run_id)]
        finding_id = self.put(
            "ResearchFinding",
            {
                "statement": "This fixture reproduced identical deterministic results in two runs; no investment implication",
                "hypothesis_id": experiment.hypothesis,
                "experiment_id": experiment.experiment_id,
                "supported_by": [first.run_id, second.run_id],
                "contradicted_by": [],
                "status": "SUPPORTED_FOR_THIS_FIXTURE",
                "content_hash": first.content_hash,
            },
        )
        hypothesis = self.model("Hypothesis", experiment.hypothesis, Hypothesis).model_copy(
            update={"status": "SUPPORTED", "evidence_for": (first.run_id, second.run_id)}
        )
        self.put("Hypothesis", hypothesis.model_dump(mode="json"), hypothesis.hypothesis_id)
        Brain(self.host.store).flush()
        return {
            "dataset": data.model_dump(mode="json"),
            "derived": [d.model_dump(mode="json") for d in derived],
            "experiment": experiment.model_dump(mode="json"),
            "runs": [first.model_dump(mode="json"), second.model_dump(mode="json")],
            "reviews": [r["review_id"] for r in reviews],
            "finding": finding_id,
            "reproducible": True,
        }
