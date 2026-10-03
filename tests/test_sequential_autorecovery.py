from types import SimpleNamespace as NS

import pytest
from trading_core.resource_policy import ResourceBlocked, ResourceType
from trading_core.runtime import ProviderError

from products.triad import sequential_autorecovery as recovery


def stopped(error=None):
    error = error or ProviderError("DEGRADED", "CodexTurnFailed")
    error.provider_stopped = True
    error.run_id = "failed-run"
    error.work_item_id = "failed-work"
    return error


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setattr(recovery.time, "sleep", lambda _: None)
    rows = []
    service = NS(
        rows=lambda kind, mission: rows,
        record=lambda kind, mission, **payload: rows.append(payload),
        git=NS(clean_baseline=lambda: "base"),
    )
    return NS(s=service, guard=lambda mission: None, events=rows)


def run(flow, operation):
    return recovery.read_with_recovery(flow, "cycle", "CODEX", "review", {}, (), operation)


def test_retry_keeps_same_assignment_and_failed_evidence(flow):
    calls = []

    def operation():
        calls.append(1)
        if len(calls) == 1:
            raise stopped()
        return None, None, None, {"run_id": "success"}

    assert run(flow, operation)[3]["run_id"] == "success"
    assert [r["status"] for r in flow.events] == ["RETRYING", "RECOVERED"]
    assert flow.events[0]["previous_run_id"] == "failed-run"
    assert len(calls) == 2


def test_read_only_result_mismatch_retries_only_after_provider_stop(flow):
    error = ProviderError("DEGRADED", "NativeProposalEvidenceMismatch")
    assert not recovery.recoverable(error)
    calls = []

    def operation():
        calls.append(1)
        if len(calls) == 1:
            raise stopped(error)
        return None, None, None, {"run_id": "new-assessment"}

    assert run(flow, operation)[3]["run_id"] == "new-assessment"
    assert len(calls) == 2
    assert flow.events[0]["status"] == "RETRYING"


def test_retries_exhaust_and_stay_exhausted_after_new_wrapper(flow):
    calls = []

    def operation():
        calls.append(1)
        raise stopped()

    with pytest.raises(ProviderError):
        run(flow, operation)
    assert len(calls) == 3
    with pytest.raises(ProviderError):
        run(flow, operation)
    assert len(calls) == 4  # no new retries after reentry
    assert sum(r["status"] == "RETRYING" for r in flow.events) == 2
    assert flow.events[-1]["status"] == "NEEDS_ATTENTION"


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("Reviewer rejected"),
        stopped(ProviderError("UNAVAILABLE", "ExecutableChangedDuringOperation")),
        stopped(ProviderError("UNAVAILABLE", "AuthenticationRequired")),
        stopped(ProviderError("UNAVAILABLE", "OuterBoundaryUnavailable")),
        stopped(
            ResourceBlocked(
                {
                    "resource_type": ResourceType.INPUT,
                    "reason": "No new progress; repeated evidence cannot extend a run",
                }
            )
        ),
        ProviderError("DEGRADED", "CodexTurnFailed"),
    ],
)
def test_unsafe_failures_never_retry(flow, error):
    calls = []

    def operation():
        calls.append(1)
        raise error

    with pytest.raises(type(error)):
        run(flow, operation)
    assert len(calls) == 1 and flow.events[-1]["status"] == "NEEDS_ATTENTION"


def test_time_progress_stall_is_recoverable_only_after_stop():
    error = ResourceBlocked(
        {
            "resource_type": ResourceType.TIME,
            "reason": "No new progress; repeated evidence cannot extend a run",
        }
    )
    assert not recovery.recoverable(error)
    assert recovery.recoverable(stopped(error))


def test_cycle_cap_cannot_be_reset_by_changing_stage(flow):
    flow.events.extend({"stage_key": str(i), "status": "RETRYING"} for i in range(6))

    def operation():
        raise stopped()

    with pytest.raises(ProviderError):
        run(flow, operation)
    assert len(flow.events) == 7 and flow.events[-1]["status"] == "NEEDS_ATTENTION"


def test_baseline_move_prevents_retry(flow):
    head = ["base"]
    flow.s.git.clean_baseline = lambda: head[0]

    def operation():
        head[0] = "other"
        raise stopped()

    with pytest.raises(PermissionError, match="Source changed"):
        run(flow, operation)
    assert not flow.events


def test_kill_switch_interrupts_backoff(flow, monkeypatch):
    revoked = [False]
    monkeypatch.setattr(recovery.time, "sleep", lambda _: revoked.__setitem__(0, True))

    def guard(_):
        if revoked[0]:
            raise PermissionError("Epoch revoked")

    flow.guard = guard

    def operation():
        raise stopped()

    with pytest.raises(PermissionError, match="Epoch revoked"):
        run(flow, operation)
    assert [r["status"] for r in flow.events] == ["RETRYING", "NEEDS_ATTENTION"]


@pytest.fixture
def checkpoint():
    from trading_core.work import State, now

    prior = {"created_at": now().isoformat(), "parent_work_item_id": "parent", "control_epoch": 1}
    proposal = {
        "outcome": "NO_CHANGE",
        "title": "Wait for evidence",
        "problem": "Evidence unavailable",
        "change": "No unsupported implementation",
        "files": [],
        "acceptance": [],
        "evidence": ["Recorded gap"],
    }
    records = []

    def add(kind, **payload):
        records.append(
            {
                "kind": kind,
                "payload": payload,
                "work_item_id": "author-work" if payload["run_id"] == "author" else "review-work",
            }
        )

    add(
        "AgentRunRequest",
        run_id="author",
        work_item_id="author-work",
        mission_id="cycle",
        agent_id="GROK",
        role="REVIEW",
        execution_permissions=["read"],
        allowed_tools=["read_file"],
        control_epoch=1,
    )
    add("AgentRunResult", run_id="author", analysis_artifacts=[proposal])
    add(
        "AgentRunRequest",
        run_id="failed",
        work_item_id="review-work",
        mission_id="cycle",
        agent_id="CODEX",
        role="REVIEW",
        execution_permissions=["read"],
        allowed_tools=["read_file"],
        control_epoch=1,
    )
    add(
        "ResourceExtensionDecision",
        run_id="failed",
        work_item_id="review-work",
        agent_id="CODEX",
        decision="DENY",
        resource_type="MORE_TIME",
        reason="No new progress; repeated evidence cannot extend a run",
    )
    add(
        "TransportRun",
        run_id="failed",
        status="BLOCKED_RESOURCE_LIMIT",
        work_item_id="review-work",
        agent="CODEX",
        provider="openai",
        transport="codex_cli",
    )
    works = {
        "author-work": NS(
            status=State.COMPLETED,
            authority_tier=0,
            owner="triad",
            mission_id="cycle",
            assigned_agent="GROK",
            parent_work_item_id="parent",
        ),
        "review-work": NS(
            status=State.BLOCKED,
            owner="triad",
            mission_id="cycle",
            work_item_id="review-work",
            work_type="review",
            authority_tier=0,
            assigned_agent="CODEX",
            parent_work_item_id="parent",
        ),
    }
    proposals = [
        {
            "id": "proposal-record",
            "mission_id": "cycle",
            "proposer": "GROK",
            "proposal": proposal,
            "attempt": 1,
        }
    ]
    cycles = []
    product = NS(
        get=lambda *a, **kw: {
            "selected": {"agent_id": "CODEX", "provider": "openai", "transport": "codex_cli"}
        },
        list=lambda kind, **kw: proposals if kind == "ProductProposal" else cycles,
        store=NS(get=lambda key, **kw: works[key]),
    )
    flow = NS(s=NS(daily=NS(product=product)))
    conn = NS(execute=lambda *a: NS(fetchall=lambda: records))
    return NS(flow=flow, conn=conn, prior=prior, records=records, works=works, cycles=cycles)


def test_saved_read_checkpoint_preserves_original_author(checkpoint):
    b = checkpoint
    saved = recovery.retained_selection(b.flow, "cycle", "GROK", b.prior, b.conn)
    assert saved["author_run_id"] == "author" and saved["author_work_id"] == "author-work"


@pytest.mark.parametrize(
    "tamper", [None, "running", "result", "writes", "denial", "cleanup", "error", "transport"]
)
def test_saved_missing_read_checkpoint_requires_canonical_cleanup(checkpoint, tamper):
    from trading_core.work import State, now

    b = checkpoint
    b.prior.update(
        failure_code="ProviderError", failures=[{"message": "NativeReadEvidenceMissing"}]
    )
    b.works["review-work"].status = State.FAILED
    transport = b.records[-1]["payload"]
    transport.update(
        status="DEGRADED", error_class="NativeReadEvidenceMissing", completed_at=now().isoformat()
    )
    native = {
        "run_id": "failed",
        "event": "native_executor_evidence",
        "boundary": "DOCKER_OFFLINE_TOOLS",
        "denials": 0,
        "calls": [{"tool": "read_file", "path": "evidence/part.txt"}],
    }
    failure = {
        "run_id": "failed",
        "event": "provider_failed",
        "error_class": "NativeReadEvidenceMissing",
    }
    for event in (native, failure):
        b.records.append({"kind": "Event", "payload": event, "work_item_id": "review-work"})
    if tamper == "running":
        b.works["review-work"].status = State.IN_PROGRESS
    elif tamper == "result":
        b.records.append(
            {
                "kind": "AgentRunResult",
                "payload": {"run_id": "failed"},
                "work_item_id": "review-work",
            }
        )
    elif tamper == "writes":
        native["calls"].append({"tool": "write_file", "path": "app.py"})
    elif tamper == "denial":
        native["denials"] = 1
    elif tamper == "cleanup":
        b.records.remove(next(r for r in b.records if r["payload"] is native))
    elif tamper == "error":
        failure["error_class"] = "DifferentError"
    elif tamper == "transport":
        transport.pop("completed_at")
    if tamper:
        with pytest.raises(PermissionError):
            recovery.retained_selection(b.flow, "cycle", "GROK", b.prior, b.conn)
    else:
        saved = recovery.retained_selection(b.flow, "cycle", "GROK", b.prior, b.conn)
        assert saved["author_run_id"] == "author" and saved["failed_run_id"] == "failed"


@pytest.mark.parametrize(
    "tamper",
    [
        "stale",
        "newer",
        "running",
        "writes",
        "epoch",
        "reviewer",
        "result",
        "non_time",
        "transport",
        "author",
    ],
)
def test_saved_read_checkpoint_refuses_ambiguous_or_unsafe_state(checkpoint, tamper):
    from datetime import timedelta

    from trading_core.work import State, now

    b = checkpoint
    request = b.records[2]["payload"]
    if tamper == "stale":
        b.prior["created_at"] = (now() - timedelta(days=3)).isoformat()
    elif tamper == "newer":
        b.cycles.append(
            {
                "cycle_type": "DAILY_PRODUCT",
                "cycle_id": "other",
                "created_at": (now() + timedelta(seconds=1)).isoformat(),
            }
        )
    elif tamper == "running":
        b.works["review-work"].status = State.IN_PROGRESS
    elif tamper == "writes":
        request["execution_permissions"] = ["read", "write_code"]
    elif tamper == "epoch":
        request["control_epoch"] = 2
    elif tamper == "reviewer":
        b.works["review-work"].assigned_agent = "GROK"
    elif tamper == "result":
        b.records.append(
            {
                "kind": "AgentRunResult",
                "payload": {"run_id": "failed"},
                "work_item_id": "review-work",
            }
        )
    elif tamper == "non_time":
        b.records[3]["payload"]["resource_type"] = "MORE_TOKENS"
    elif tamper == "transport":
        b.records[4]["payload"]["status"] = "RUNNING"
    elif tamper == "author":
        b.records[1]["payload"]["analysis_artifacts"] = []
    with pytest.raises(PermissionError):
        recovery.retained_selection(b.flow, "cycle", "GROK", b.prior, b.conn)


@pytest.mark.parametrize(
    "tamper",
    [
        "failed_agent",
        "failed_role",
        "failed_work_column",
        "transport_work",
        "resource_work",
        "author_result_work",
        "provider",
        "author_epoch",
        "resource_decision",
    ],
)
def test_retained_checkpoint_binds_record_lineage(checkpoint, tamper):
    b = checkpoint
    if tamper == "failed_agent":
        b.records[2]["payload"]["agent_id"] = "CLAUDE"
    elif tamper == "failed_role":
        b.records[2]["payload"]["role"] = "IMPLEMENT"
    elif tamper == "failed_work_column":
        b.records[2]["work_item_id"] = "foreign-work"
    elif tamper == "transport_work":
        b.records[4]["work_item_id"] = "foreign-work"
    elif tamper == "resource_work":
        b.records[3]["work_item_id"] = "foreign-work"
    elif tamper == "author_result_work":
        b.records[1]["work_item_id"] = "foreign-work"
    elif tamper == "provider":
        b.records[4]["payload"]["provider"] = "foreign-provider"
    elif tamper == "author_epoch":
        b.records[0]["payload"]["control_epoch"] = 2
    elif tamper == "resource_decision":
        b.records[3]["payload"]["decision"] = "ALLOW"
    with pytest.raises(PermissionError):
        recovery.retained_selection(b.flow, "cycle", "GROK", b.prior, b.conn)


@pytest.mark.parametrize("decision", ["REQUEST_CHANGES", "REJECT"])
def test_saved_proposal_rejection_revises_without_reentering_selecting(monkeypatch, decision):
    from products.triad.daily import NEXT

    from products.triad import sequential

    state = ["INSPECTING"]
    attempts = []
    proposal = NS(model_dump=lambda **kw: {"title": "saved"})
    flow = object.__new__(sequential.SequentialCycle)
    flow.saved_selection = {
        "proposal": proposal,
        "attempt": 1,
        "author_work_id": "author",
        "author_run_id": "run",
    }

    def transition(mission, target, evidence):
        assert target in NEXT[state[0]], "Duplicate or invalid state transition"
        state[0] = target

    flow.s = NS(rows=lambda *a: [], transition=transition, git=NS(clean_baseline=lambda: "base"))
    flow.inventory = list
    monkeypatch.setattr(sequential, "planning_context", lambda *a: {})
    flow.review_proposal = lambda *a: (
        proposal,
        None,
        {"decision": decision, "summary": "Correct math", "findings": []},
    )

    def attempt(mission, agent, feedback, number):
        attempts.append(number)
        if number == 1:
            transition(mission, "SELECTING", [])
        assert feedback[-1]["summary"] == "Correct math"
        return proposal, "fresh-independent-approval", {"decision": "APPROVE"}

    flow.proposal_attempt = attempt
    assert flow.propose("cycle", "GROK")[1] == "fresh-independent-approval"
    assert attempts == [2] and state[0] == "SELECTING"


@pytest.fixture
def saved_revision(checkpoint):
    b = checkpoint
    b.records[:] = b.records[:2]
    b.prior.update(
        failure_code="PermissionError",
        failures=[{"message": "Invalid or terminal cycle transition"}],
    )
    saved = b.flow.s.daily.product.list("ProductProposal")[0]
    saved["recorded_at"] = "2026-10-02T12:52:00+00:00"
    reviews = [
        {
            "mission_id": "cycle",
            "proposer": "GROK",
            "decision": "REQUEST_CHANGES",
            "proposal": {"title": "original"},
            "recorded_at": "2026-10-02T12:46:00+00:00",
        }
    ]
    original = b.flow.s.daily.product.list
    b.flow.s.daily.product.list = lambda kind, **kw: (
        reviews if kind == "ProductProposalReview" else original(kind, **kw)
    )
    b.saved, b.reviews = saved, reviews
    return b


def test_completed_revised_proposal_checkpoint_resumes_review_only(saved_revision):
    b = saved_revision
    saved = recovery.retained_selection(b.flow, "cycle", "GROK", b.prior, b.conn)
    assert saved["failed_work_id"] is None and saved["checkpoint_id"] == "proposal-record"
    assert saved["author_run_id"] == "author"


@pytest.mark.parametrize(
    "tamper",
    [
        "later_work",
        "already_reviewed",
        "no_correction",
        "future_review",
        "missing_author",
        "author_write",
    ],
)
def test_invalid_saved_revision_checkpoint_never_resumes(saved_revision, tamper):
    b = saved_revision
    if tamper == "later_work":
        b.records.append(
            {
                "kind": "AgentRunRequest",
                "work_item_id": "later",
                "payload": {"mission_id": "cycle", "run_id": "later"},
            }
        )
    elif tamper == "already_reviewed":
        b.reviews[0]["proposal"] = b.saved["proposal"]
    elif tamper == "no_correction":
        b.reviews[0]["decision"] = "APPROVE"
    elif tamper == "future_review":
        b.reviews[0]["recorded_at"] = "2026-10-03T00:00:00+00:00"
    elif tamper == "missing_author":
        b.records[1]["payload"]["analysis_artifacts"] = []
    elif tamper == "author_write":
        b.works["author-work"].authority_tier = 2
    with pytest.raises(PermissionError):
        recovery.retained_selection(b.flow, "cycle", "GROK", b.prior, b.conn)
