"""Independent workflow integration seams; offline vendors and disposable state."""
# ruff: noqa: F811

import json
from types import SimpleNamespace

import pytest
from test_daily_lifecycle import draft
from test_day3_integration import engine  # noqa: F401
from test_product_development import proposal
from trading_core.contracts import AgentRunResult, FileChange
from trading_core.engineering import EngineeringGit
from trading_core.store import Store

from products.triad import daily_development as module
from products.triad import daily_verification

pytestmark = pytest.mark.triad


def wire(engine, monkeypatch, *, fail_build=False, reject_first=False, debrief_rejections=0):
    dev = module.DailyDevelopment(Store(engine.host.store.settings, scope="triad"), engine.git)
    # This orchestration fixture's tiny Git repository has no Core source tree.
    # Exact real-source references are covered by test_day8_qa_reference.py.
    monkeypatch.setattr(dev, "qa_references", lambda build: {})
    calls = []
    routing = []
    checks = []
    monkeypatch.setattr(
        module,
        "Readiness",
        lambda: SimpleNamespace(
            catalog=lambda: {"sources": [], "datasets": [], "limitations": ["offline fixture only"]}
        ),
    )
    monkeypatch.setattr(
        module,
        "EngineeringGit",
        lambda grant: EngineeringGit(grant, engine.git.root, engine.git.worktrees),
    )

    def route(work, requirements):
        routing.append((work, requirements))
        assigned = work.model_copy(update={"assigned_agent": requirements.preferred_agent})
        dev.host.store.create(assigned)
        dev.canonical.append(
            "RouteDecision",
            {
                "selected": {
                    "provider": "fixture",
                    "model": "fixture-model",
                    "transport": "offline-fixture",
                }
            },
            owner="triad",
            identifier="route-" + assigned.work_item_id,
        )
        return assigned

    monkeypatch.setattr(dev.routing, "create", route)
    monkeypatch.setattr(dev.routing.agents, "list", list)

    def check(grant, files, script, *, guard, **kwargs):
        guard()
        assert script == module.CHECK_SCRIPT and set(files) == set(module.FILES)
        checks.append(grant.work_item_id)
        return {
            "status": "PASS",
            "test_id": grant.test_id,
            "test_sha256": grant.test_sha256,
            "evidence": "Mocked offline checker: orchestration seam only",
        }

    monkeypatch.setattr(module, "run_approved_checks", check)
    reviews = 0
    debrief_reviews = 0

    def execute(request):
        nonlocal reviews, debrief_reviews
        calls.append(request)
        assert dev.daily.current(request.mission_id)["status"] != "COMPLETED"
        dev.ledger.put(
            "Usage",
            {
                "run_id": request.run_id,
                "work_item_id": request.work_item_id,
                "agent": request.agent_id,
                "provider": "fixture",
                "actual_model": "fixture-model",
                "transport": "offline-fixture",
                "billing_source": "LOCAL" if request.agent_id == "LOCAL_QWEN" else "SUBSCRIPTION",
                "status": "SUCCESS",
                "mode": "INDEPENDENT_QA_FIXTURE",
                "input_tokens": 10,
                "output_tokens": 5,
            },
            work_id=request.work_item_id,
        )
        if request.role == "IMPLEMENT":
            if fail_build:
                raise RuntimeError("Independent injected provider failure")
            dev.canonical.append(
                "ResourceExtensionRequest",
                {
                    "work_item_id": request.work_item_id,
                    "resource": "MORE_TIME",
                    "reason": "independent fixture progress",
                    "evidence": ["fixture-extension"],
                },
                owner="triad",
            )
            return AgentRunResult(
                run_id=request.run_id,
                status="CODE_CHANGE",
                summary="Fixture assets",
                files_changed=tuple(
                    FileChange(
                        path=p,
                        content=(
                            "<!doctype html><title>Fixture</title>\n"
                            if p.endswith(".html")
                            else f"// Fixture candidate {len(calls)}\n"
                        ),
                    )
                    for p in module.FILES
                ),
            )
        context = request.context_packet
        if request.objective.startswith("Independently inspect current Triad"):
            assert "findings" not in context and "inspections" not in context
            payload = {
                "areas": [
                    {
                        "capability": "fixture",
                        "state": "MISSING",
                        "user_value": "fixture",
                        "dependencies": [],
                        "limitations": [],
                        "technical_debt": [],
                        "evidence": ["fixture"],
                        "candidate_improvements": ["Fixture readiness"],
                    }
                ],
                "candidates": [
                    {
                        "candidate_id": request.agent_id + "-candidate",
                        "title": "Fixture readiness",
                        "problem": "Missing",
                        "product_area": "Research",
                        "evidence": ["fixture"],
                        "expected_user_value": "Clarity",
                        "technical_value": "Checks",
                        "risk": "LOW",
                        "effort": "small",
                        "dependencies": [],
                        "reversibility": "Git",
                        "origin": request.agent_id,
                    }
                ],
            }
        elif request.objective.startswith("Select exactly"):
            payload = proposal(
                candidate_id=context["candidates"][0]["candidate_id"],
                affected_components=module.FILES,
                required_capabilities=module.CAPS,
                permissions_required=("write_code",),
            ).model_dump(mode="json")
        elif request.objective.startswith("Write a candid"):
            cycle = dev.daily.current(request.mission_id)
            payload = draft(SimpleNamespace(**cycle)).model_dump(mode="json")
        elif request.objective.startswith("Independently challenge"):
            debrief_reviews += 1
            payload = {
                "classification": "LOW",
                "reason": "Independent fixture downgrade",
                "action": "DOWNGRADE",
            }
            if debrief_reviews <= debrief_rejections:
                return AgentRunResult(
                    run_id=request.run_id,
                    status="RESEARCH_FINDING",
                    summary="Fixture debrief requires correction",
                    review_decision="REQUEST_CHANGES",
                    findings=("Correct unsupported debrief attribution",),
                    analysis_artifacts=(json.dumps(payload),),
                )
        elif request.objective.startswith("Independently QA"):
            reviews += 1
            return AgentRunResult(
                run_id=request.run_id,
                status="RESEARCH_FINDING",
                summary="Fixture QA",
                review_decision="REQUEST_CHANGES" if reject_first and reviews == 1 else "APPROVE",
                findings=("Correct fixture asset",) if reject_first and reviews == 1 else (),
            )
        else:
            assert request.agent_id == "LOCAL_QWEN" and request.role == "SUPPORT"
            payload = None
        return AgentRunResult(
            run_id=request.run_id,
            status="RESEARCH_FINDING",
            summary="Fixture evidence",
            analysis_artifacts=(json.dumps(payload),) if payload else (),
            review_decision="APPROVE" if request.agent_id == "CODEX" else None,
        )

    monkeypatch.setattr(dev.runtime, "execute", execute)
    return dev, calls, routing, checks


@pytest.mark.integration
def test_actual_daily_pipeline_preserves_work_usage_and_resource_evidence(engine, monkeypatch):
    dev, calls, routing, checks = wire(engine, monkeypatch)
    cycle = dev.run_daily(
        verify=lambda merged: {"status": "PASS", "evidence": ["fixture-only verifier"]}
    )
    assert cycle["status"] == "COMPLETED"
    assert dev.rows("ProductMerge", cycle["cycle_id"])
    assert len(checks) >= 5  # Initial build, both QA sides, both merge checks.
    writes = [(w, r) for w, r in routing if r.role == "IMPLEMENT"]
    assert len(writes) == 1 and writes[0][0].allowed_paths == module.FILES
    assert set(writes[0][1].capabilities) == set(module.CAPS)
    assert (
        writes[0][0].reasoning_budget == 8192 and writes[0][0].compute_budget.timeout_seconds == 480
    )
    assert cycle["work_items"], "Canonical completed cycle must retain actual WorkItems"
    assert cycle["provider_runs"] and cycle["agents_run"] and cycle["billing_sources"]
    assert {r["run_id"] for r in cycle["provider_runs"]} == {c.run_id for c in calls}
    assert set(cycle["agents_run"]) == {"CODEX", "CLAUDE", "GROK", "LOCAL_QWEN"}
    assert set(cycle["billing_sources"]) == {"LOCAL", "SUBSCRIPTION"}
    debrief_call = next(c for c in calls if c.objective.startswith("Write a candid"))
    assert debrief_call.context_packet["resource_extensions"], (
        "Actual recorded extension omitted from debrief QA evidence"
    )


@pytest.mark.integration
def test_actual_daily_correction_rechecks_and_merges_only_new_qa(engine, monkeypatch):
    dev, _calls, _, checks = wire(engine, monkeypatch, reject_first=True)
    cycle = dev.run_daily(verify=lambda merged: {"status": "PASS", "evidence": ["fixture only"]})
    assert cycle["status"] == "COMPLETED"
    builds = dev.rows("ProductBuild", cycle["cycle_id"])
    qa = dev.rows("ProductQA", cycle["cycle_id"])
    assert len(builds) == len(qa) == 2 and len(checks) >= 8
    assert qa[0]["decision"] == "CHANGES_REQUIRED" and qa[1]["decision"] == "PASS"
    assert qa[0]["implementation_id"] != qa[1]["implementation_id"]
    merge = dev.rows("ProductMerge", cycle["cycle_id"])[0]
    assert (
        merge["implementation_id"] == builds[1]["implementation_id"]
        and merge["qa_id"] == qa[1]["qa_id"]
    )
    assert builds[1]["correction"] == ["Correct fixture asset"]
    assert cycle["correction_runs"], "Canonical correction history must not disappear at completion"
    assert {
        r["implementation_id"] for r in cycle["implementation_runs"] if "implementation_id" in r
    } >= {b["implementation_id"] for b in builds}


@pytest.mark.integration
def test_actual_daily_provider_failure_preserves_blocked_record_no_merge(engine, monkeypatch):
    dev, _, _, _ = wire(engine, monkeypatch, fail_build=True)
    with pytest.raises(RuntimeError, match="injected provider failure"):
        dev.run_daily(cycle_id="workflow-failure", verify=lambda m: {"status": "PASS"})
    cycle = dev.daily.current("workflow-failure")
    assert cycle["status"] == "BLOCKED" and cycle["finished_at"]
    assert cycle["failures"] and dev.rows("ProductBuildFailure", "workflow-failure")
    assert not dev.rows("ProductMerge", "workflow-failure") and not dev.daily.debriefs()


@pytest.mark.integration
@pytest.mark.parametrize("rejections", [1, 3])
def test_debrief_rejection_requires_fresh_review_before_completion(engine, monkeypatch, rejections):
    dev, calls, _, _ = wire(engine, monkeypatch, debrief_rejections=rejections)
    cycle_id = "debrief-correction"
    if rejections == 3:
        with pytest.raises(PermissionError, match="Debrief independent review did not pass"):
            dev.run_daily(cycle_id=cycle_id, verify=lambda _: {"status": "PASS"})
        assert dev.daily.current(cycle_id)["status"] == "BLOCKED"
        assert not dev.daily.debriefs()
    else:
        result = dev.run_daily(cycle_id=cycle_id, verify=lambda _: {"status": "PASS"})
        assert result["status"] == "COMPLETED"
        published = dev.daily.debriefs()
        assert len(published) == 1
        assert published[0]["classification"] == "LOW"
    drafts = [c for c in calls if c.objective.startswith("Write a candid")]
    reviews = [c for c in calls if c.objective.startswith("Independently challenge")]
    assert len(drafts) == len(reviews) == min(rejections + 1, 3)
    assert len({c.context_packet["debrief"]["debrief_id"] for c in reviews}) == len(reviews)
    assert "Correct unsupported debrief attribution" in str(drafts[1].context_packet)


@pytest.mark.integration
def test_failed_postmerge_verification_never_publishes_or_completes(engine, monkeypatch):
    dev, calls, _, _ = wire(engine, monkeypatch)

    def fail_verification(_):
        before = dev.daily.current("verification-failed")
        assert before["status"] == "VERIFYING" and before["finished_at"] is None
        with pytest.raises(PermissionError, match="Daily evidence"):
            dev.daily.history.capture("verification-failed", status="COMPLETED")
        dev.daily.refresh("verification-failed")
        after = dev.daily.current("verification-failed")
        for key in ("status", "finished_at", "parent_work_item_id", "control_epoch", "created_at"):
            assert after[key] == before[key]
        return {"status": "FAILED"}

    with pytest.raises(PermissionError, match="Post-merge verification failed"):
        dev.run_daily(cycle_id="verification-failed", verify=fail_verification)
    assert dev.daily.current("verification-failed")["status"] == "BLOCKED"
    assert dev.rows("ProductMerge", "verification-failed")
    assert not dev.daily.debriefs()
    assert not any(c.objective.startswith("Write a candid") for c in calls)


def verification_stubs(monkeypatch, *, change_during_test=False, test_exit=0):
    state = {"head": "reviewed", "dirty": False}

    def output(args, **kwargs):
        return (
            state["head"] if args[1] == "rev-parse" else (" M feature.js" if state["dirty"] else "")
        )

    def run(args, **kwargs):
        assert args[1:3] == ["-m", "pytest"] and kwargs["timeout"] == 120
        if change_during_test:
            state.update(head="unreviewed", dirty=True)
        return SimpleNamespace(returncode=test_exit, stdout="offline fixture result")

    monkeypatch.setattr(daily_verification.subprocess, "check_output", output)
    monkeypatch.setattr(daily_verification.subprocess, "run", run)

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, path):
            payload = (
                {"gate": "PASS"}
                if path == "/api/providers"
                else {"exchange": "CLOSED", "mode": "human_directed", "work_items": []}
                if path == "/aegis/api/status"
                else {
                    k: {"status": "up"}
                    for k in ["backend", "postgres", "timescale", "neo4j", "ollama", "git"]
                }
            )
            return SimpleNamespace(
                status_code=200, raise_for_status=lambda: SimpleNamespace(json=lambda: payload)
            )

    monkeypatch.setattr(daily_verification.httpx, "Client", Client)


def test_postmerge_verification_rechecks_head_and_cleanliness_after_tests(monkeypatch):
    verification_stubs(monkeypatch, change_during_test=True)
    try:
        result = daily_verification.verify({"merge_commit": "reviewed"})
    except PermissionError:
        return
    assert result["status"] != "PASS", (
        "Verification certified a revision that moved during its own checks"
    )


@pytest.mark.parametrize("test_exit", [0, 1])
def test_postmerge_verification_uses_trusted_tests_and_honest_exit(monkeypatch, test_exit):
    verification_stubs(monkeypatch, test_exit=test_exit)
    result = daily_verification.verify({"merge_commit": "reviewed"})
    assert result["status"] == ("PASS" if test_exit == 0 else "FAILED")


def test_daily_cycle_runner_scopes_its_trusted_verification_to_triad(monkeypatch):
    """Mission 7: the runner's post-merge verification runs pytest in a subprocess; it must carry
    the Triad scope, or the scope guard refuses it and the cycle blocks."""
    import importlib.util
    import os
    import sys

    from trading_core.settings import ROOT

    path = ROOT / "tools" / "run_daily_product_cycle.py"
    spec = importlib.util.spec_from_file_location("run_daily_product_cycle", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    seen = {}

    class Development:
        def run_daily(self, **kwargs):
            seen["scope"] = os.environ.get("TRIAD_PYTEST_SCOPE")
            return {"status": "stub"}

    monkeypatch.setattr(runner, "DailyDevelopment", Development)
    monkeypatch.delenv("TRIAD_PYTEST_SCOPE", raising=False)
    monkeypatch.setattr(sys, "argv", ["run_daily_product_cycle.py", "--operator-authorized"])
    runner.main()
    assert seen["scope"] == "triad"
