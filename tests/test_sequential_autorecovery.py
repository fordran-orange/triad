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
        records.append({"kind": kind, "payload": payload})

    add(
        "AgentRunRequest",
        run_id="author",
        work_item_id="author-work",
        mission_id="cycle",
        agent_id="GROK",
        role="REVIEW",
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
        resource_type="MORE_TIME",
        reason="No new progress; repeated evidence cannot extend a run",
    )
    add("TransportRun", run_id="failed", status="BLOCKED_RESOURCE_LIMIT")
    works = {
        "author-work": NS(status=State.COMPLETED, authority_tier=0),
        "review-work": NS(
            status=State.BLOCKED,
            work_type="review",
            authority_tier=0,
            assigned_agent="CODEX",
            parent_work_item_id="parent",
        ),
    }
    proposals = [{"mission_id": "cycle", "proposer": "GROK", "proposal": proposal, "attempt": 1}]
    cycles = []
    product = NS(
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
        b.records.append({"kind": "AgentRunResult", "payload": {"run_id": "failed"}})
    elif tamper == "non_time":
        b.records[3]["payload"]["resource_type"] = "MORE_TOKENS"
    elif tamper == "transport":
        b.records[4]["payload"]["status"] = "RUNNING"
    elif tamper == "author":
        b.records[1]["payload"]["analysis_artifacts"] = []
    with pytest.raises(PermissionError):
        recovery.retained_selection(b.flow, "cycle", "GROK", b.prior, b.conn)
