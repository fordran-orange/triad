# ruff: noqa: F401, F811
import hashlib
import json

import pytest
from products.triad.development import Development
from products.triad.sequential_correction_plan import CorrectionPlan, author_request
from products.triad.sequential_correction_renewal import PLANNING_DENIED
from products.triad.sequential_planning import token_guidance
from products.triad.sequential_qa_recovery import resume_citation_failure
from psycopg.types.json import Jsonb
from test_candidate_correction_integration import engine, proof, snapshot
from test_correction_renewal_integration import healthy, stopped

pytestmark = [pytest.mark.integration, pytest.mark.triad]


@pytest.fixture
def denied(stopped, monkeypatch):
    p = stopped
    healthy(monkeypatch)
    resume_citation_failure(p.flow, p.mission, substantive=True)
    retained = p.flow._prepared_correction
    p.daily.transition(p.mission, "CORRECTING", [p.qa])
    objective, context = author_request(
        "CODEX", p.proposal, retained, p.flow.s.git.clean_baseline()
    )
    expanded = (
        objective
        + token_guidance("CODEX")
        + (
            "Do not execute commands or claim host tests. Top-level files_changed must be [] and proposal must be null; "
            "the requested Proposal or Patch is data inside analysis_artifacts, not the outer proposal field."
        )
    )
    p.flow.s.call = lambda *a, **kw: Development.call(p.flow.s, *a, **kw)
    work, expected = p.flow.s.call(
        p.mission,
        "CODEX",
        "REVIEW",
        expanded,
        {
            **context,
            "evidence_delivery": "files-v1",
            "response_format_feedback": [],
            "response_envelope": {
                "files_changed": [],
                "proposal": None,
                "analysis_artifacts": "Exactly one JSON object for the requested schema; never encode it as a string",
            },
        },
        paths=p.proposal.files,
        schema=CorrectionPlan,
        parent=p.daily.current(p.mission)["parent_work_item_id"],
        _preview=True,
    )
    p.denial = p.host.append(
        "CapabilityRoutingDecision",
        {
            "decision": "DENY",
            "work_item_id": work.work_item_id,
            "requirements": expected.model_dump(mode="json"),
            "candidates": [
                {
                    "agent_id": "CODEX",
                    "eligible": False,
                    "exclusions": ["Assignment exceeds configured path grant"],
                }
            ],
        },
        owner="triad",
    )
    p.host.append(
        "ProductAutoRecovery",
        {
            "mission_id": p.mission,
            "agent": "CODEX",
            "status": "NEEDS_ATTENTION",
            "failure_class": "PermissionError",
            "previous_run_id": None,
            "stage_key": hashlib.sha256(
                json.dumps(
                    ["CODEX", objective, context, list(p.proposal.files)],
                    sort_keys=True,
                    default=str,
                ).encode()
            ).hexdigest(),
        },
        owner="triad",
    )
    p.daily.transition(
        p.mission,
        "BLOCKED",
        ["PermissionError"],
        failures=({"code": "PermissionError", "message": PLANNING_DENIED},),
    )
    p.denied_work = work.work_item_id
    return p


def test_exact_unstarted_author_denial_recovers_without_replaying_prior_work(denied):
    p = denied
    before = snapshot(p)
    cycle, _, _, _ = resume_citation_failure(p.flow, p.mission, substantive=True)
    assert cycle.status == "AWAITING_QA" and snapshot(p) == before
    assert cycle.recovery_action.endswith(p.denial)
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)


@pytest.mark.parametrize(
    "tamper",
    ["stage", "denial_reason", "duplicate_denial", "execution", "completed_plan", "rollback"],
)
def test_unstarted_denial_requires_exact_stage_and_no_execution(denied, tamper, monkeypatch):
    p = denied
    before = snapshot(p)
    if tamper in {"stage", "denial_reason", "duplicate_denial"}:
        if tamper == "stage":
            p.host.append(
                "ProductAutoRecovery",
                {
                    "mission_id": p.mission,
                    "agent": "CODEX",
                    "status": "NEEDS_ATTENTION",
                    "failure_class": "PermissionError",
                    "stage_key": "wrong",
                },
                owner="triad",
            )
        else:
            row = p.host.get(p.denial)
            if tamper == "denial_reason":
                row["candidates"][0]["exclusions"] = ["Provider unavailable"]
            p.host.append("CapabilityRoutingDecision", row, owner="triad")
    elif tamper == "execution":
        p.host.ledger.put(
            "AgentRunRequest",
            {"run_id": "unknown", "mission_id": p.mission, "role": "REVIEW"},
            work_id=p.denied_work,
        )
    elif tamper == "completed_plan":
        p.host.append("ProductCorrectionPlan", {"mission_id": p.mission}, owner="triad")
    else:
        original = p.daily.host.ledger.put

        def fail(*a, **kw):
            original(*a, **kw)
            raise RuntimeError("Injected post-insert failure")

        monkeypatch.setattr(p.daily.host.ledger, "put", fail)
    with pytest.raises((PermissionError, RuntimeError)):
        resume_citation_failure(p.flow, p.mission, substantive=True)
    assert p.daily.current(p.mission)["status"] == "BLOCKED" and snapshot(p) == before
