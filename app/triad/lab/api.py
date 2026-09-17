from datetime import UTC, datetime

import pyarrow.parquet as pq
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from triad.api import require_operator
from triad.lab.contracts import BacktestRun, Experiment
from triad.lab.service import Laboratory

router = APIRouter(prefix="/api/research")


def laboratory():
    return Laboratory()


DEP = Depends(laboratory)
AUTH = [Depends(require_operator)]


class DatasetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str
    config: dict = Field(default_factory=dict)


@router.get("/dashboard")
def dashboard(lab: Laboratory = DEP):
    return {
        "datasets": lab.catalog(),
        "experiments": lab.ledger.records("Experiment"),
        "runs": lab.ledger.records("BacktestRun"),
        "reviews": lab.ledger.records("ResearchReview"),
        "quality": lab.ledger.records("QualityReport"),
        "hypotheses": lab.ledger.records("Hypothesis"),
        "findings": lab.ledger.records("ResearchFinding"),
        "limits": lab.limits.model_dump(),
        "provider": {
            "name": "local-engine-fixture-v1",
            "mode": "FIXTURE",
            "real_market_provider": "UNAVAILABLE",
        },
    }


@router.get("/datasets")
def datasets(symbol: str | None = None, lab: Laboratory = DEP):
    return lab.catalog(symbol)


@router.post("/fixture", dependencies=AUTH)
def fixture(lab: Laboratory = DEP):
    return lab.ingest(
        "LABTEST", datetime(2026, 9, 14, 13, 30, tzinfo=UTC), datetime(2026, 9, 16, 20, tzinfo=UTC)
    )


@router.post("/experiments", dependencies=AUTH)
def create(body: DatasetInput, lab: Laboratory = DEP):
    return lab.create_experiment(body.dataset_id, body.config)


@router.post("/experiments/{identifier}/run", dependencies=AUTH)
def run(identifier: str, lab: Laboratory = DEP):
    return lab.run(identifier)


@router.post("/runs/{identifier}/review", dependencies=AUTH)
def review(identifier: str, lab: Laboratory = DEP):
    return lab.review(identifier)


@router.get("/runs/{identifier}")
def detail(identifier: str, lab: Laboratory = DEP):
    run = lab.model("BacktestRun", identifier, BacktestRun)
    experiment = lab.model("Experiment", run.experiment_id, Experiment)
    output = {"run": run.model_dump(mode="json"), "experiment": experiment.model_dump(mode="json")}
    for kind in ("trades", "equity", "decisions"):
        artifact = run.result_artifacts.get(kind)
        if not artifact:
            output[kind] = []
            continue
        path = (lab.root / artifact["path"]).resolve()
        if not path.is_relative_to((lab.root / "research/experiments").resolve()):
            raise PermissionError("Invalid artifact path")
        from triad.lab.data import digest

        if digest(path.read_bytes()) != artifact["sha256"]:
            raise ValueError("Artifact checksum mismatch")
        output[kind] = pq.ParquetFile(path).read().to_pylist()
    output["reviews"] = [
        r for r in lab.ledger.records("ResearchReview") if r["run_id"] == identifier
    ]
    output["dataset"] = lab.ledger.get(experiment.dataset_id)
    output["hypothesis"] = lab.ledger.get(experiment.hypothesis)
    return output


@router.post("/runs/{identifier}/support", dependencies=AUTH)
def research_support(identifier: str, lab: Laboratory = DEP):
    from triad.day3.support import support

    run = lab.model("BacktestRun", identifier, BacktestRun)
    return support(
        lab.cycles,
        run.work_item_id,
        "CODEX",
        "SUMMARY",
        f"Research run {run.run_id} is a FIXTURE engine test. Status {run.status}. Deterministic content hash {run.content_hash}. Summarize only this operational observation; do not declare a trading strategy successful.",
    )
