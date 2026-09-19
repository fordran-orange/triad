"""Operator-authored method reviews, separate from the deterministic run engine."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from trading_core.brain import Brain
from trading_core.research.contracts import BacktestRun, DatasetManifest, Experiment
from trading_core.research.service import Laboratory
from trading_core.work import Review, State


class MethodReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal[
        "ACCEPT_RESULT",
        "REQUEST_RERUN",
        "REJECT_METHOD",
        "DATA_QUALITY_FAILURE",
        "LOOKAHEAD_RISK",
        "INCONCLUSIVE",
    ]
    findings: tuple[str, ...] = Field(min_length=1, max_length=30)
    evidence_checked: tuple[str, ...] = Field(min_length=1, max_length=30)
    tests_repeated: tuple[str, ...] = Field(max_length=30)


def record_method_review(lab: Laboratory, identifier: str, body: MethodReview):
    """Human review uses assigned review authority; never impersonates model inference."""
    run = lab.model("BacktestRun", identifier, BacktestRun)
    work = lab.host.store.get(run.work_item_id)
    epoch = lab.ledger.guard(work.reviewer, work.work_item_id)["epoch"]
    if work.status != State.AWAITING_REVIEW:
        raise ValueError("Research work is not awaiting review")
    experiment = lab.model("Experiment", run.experiment_id, Experiment)
    dataset = lab.model("DatasetManifest", experiment.dataset_id, DatasetManifest)
    accepted = body.decision == "ACCEPT_RESULT"
    review = Review(
        reviewer=work.reviewer,
        work_item_id=work.work_item_id,
        decision="APPROVE" if accepted else "REQUEST_CHANGES",
        findings=body.findings,
        severity="NONE" if accepted else "HIGH",
        evidence_checked=body.evidence_checked,
        tests_repeated=body.tests_repeated,
        execution_mode="HUMAN_OPERATOR_METHOD_REVIEW",
    )
    record = {
        "review_id": review.review_id,
        "run_id": identifier,
        "experiment_id": experiment.experiment_id,
        "decision": body.decision,
        "reviewer": work.reviewer,
        "author": "HUMAN_OPERATOR",
        "mode": review.execution_mode,
        "findings": body.findings,
        "evidence_checked": body.evidence_checked,
        "tests_repeated": body.tests_repeated,
        "review_packet": {
            "experiment": experiment.model_dump(mode="json"),
            "dataset": dataset.model_dump(mode="json"),
            "run": run.model_dump(mode="json"),
        },
    }
    lab.commit_review(work, review, record, epoch)
    target = lab.root / f"research/experiments/{run.experiment_id}/runs/{identifier}/review.md"
    target.write_text(
        "# Research review\n\n"
        + body.decision
        + "\n\nMode: "
        + review.execution_mode
        + "\n\n"
        + "\n".join(body.findings),
        encoding="utf-8",
    )
    Brain(lab.host.store).flush()
    return record
