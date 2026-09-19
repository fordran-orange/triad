"""Independent product framework QA; disposable Git/DB, no live inference."""

# ruff: noqa: F811
import hashlib
import json
from pathlib import Path

import pytest
from products.triad.development import INSPECTION_PATHS
from test_day3_integration import engine  # noqa: F401
from test_intelligence_capabilities import build as core_build
from test_intelligence_capabilities import qa as core_qa
from test_intelligence_routing import setup_routing
from test_product_development import proposal, service
from trading_core.contracts import AgentRunResult, FileChange
from trading_core.intelligence.capabilities import Capabilities
from trading_core.intelligence.contracts import Capability
from trading_core.intelligence.quality import Quality
from trading_core.runtime import HttpProvider, ProviderError
from trading_core.work import State, WorkItem, now

pytestmark = pytest.mark.integration


def test_qwen_support_uses_compact_adapter_schema_and_256_generation_cap(engine, monkeypatch):
    dev, _ = ready(engine, monkeypatch)
    adapter = HttpProvider(
        "LOCAL_QWEN", {"provider": "ollama", "model_env": "QA_MODEL"}, {"QA_MODEL": "fixture-model"}
    )
    requests, bodies = [], []

    def transport(path, body, timeout):
        assert path == "/api/generate" and timeout == 480
        bodies.append(body)
        # Behave like a schema-following model; this also demonstrates why the
        # old full AgentRunResult format is incompatible with SUPPORT decoding.
        if set(body["format"]["properties"]) == {"summary", "assumptions"}:
            response = {"summary": "Independent findings summarized.", "assumptions": []}
        else:
            response = AgentRunResult(
                run_id=requests[-1].run_id,
                status="RESEARCH_FINDING",
                summary="Full-schema response",
            ).model_dump(mode="json")
        return {
            "response": json.dumps(response),
            "done_reason": "stop",
            "model": "fixture-model",
            "prompt_eval_count": 100,
            "eval_count": 20,
        }

    monkeypatch.setattr(adapter, "transport", transport)

    def execute(request):
        requests.append(request)
        result, inputs, outputs = adapter.execute(request)
        dev.ledger.put(
            "Usage",
            {
                "run_id": request.run_id,
                "work_item_id": request.work_item_id,
                "provider": "ollama",
                "actual_model": "fixture-model",
                "transport": "ollama",
                "billing_source": "LOCAL",
                "status": "SUCCESS",
                "mode": "INDEPENDENT_QA_FIXTURE",
                "input_tokens": inputs,
                "output_tokens": outputs,
            },
            work_id=request.work_item_id,
        )
        return result

    monkeypatch.setattr(dev.runtime, "execute", execute)
    work, result, _, usage = dev.call(
        "support-codec",
        "LOCAL_QWEN",
        "SUPPORT",
        "Summarize briefly with no assumptions",
        {"findings": [{"agent": "CODEX", "summary": "Fixture evidence"}]},
    )
    assert work.status == State.COMPLETED and work.reasoning_budget == 256
    assert result.summary == "Independent findings summarized." and not result.assumptions
    assert usage["billing_source"] == "LOCAL"
    assert requests[0].execution_permissions == ("read",) and not requests[0].allowed_tools
    assert bodies[0]["options"]["num_predict"] == 256 and bodies[0]["think"] is False
    assert set(bodies[0]["format"]["required"]) == {"summary", "assumptions"}
    assert bodies[0]["format"]["additionalProperties"] is False
    old_request = requests[0].model_copy(
        update={"required_output_schema": AgentRunResult.model_json_schema()}
    )
    with pytest.raises(ProviderError, match="MalformedOrUnsafeResponse"):
        adapter.execute(old_request)


def ready(engine, monkeypatch):
    dev = service(engine)
    router, host = setup_routing(engine)
    cap = Capability(
        capability_id="claude_code_cli:isolated_text_proposal",
        provider="anthropic",
        model="fixture-model",
        transport="claude_code_cli",
        capability="isolated_text_proposal",
        native_or_tool_mediated="tool_mediated",
        status="AVAILABLE",
        verification_status="VERIFIED",
        discovery_source="runtime",
        evidence=("independent disposable fixture",),
        verified_by="QA fixture",
        verified_at=now(),
        permissions_required=("write_docs",),
    )
    registry = Capabilities(host)
    pid = registry.propose(cap, actor="operator")
    implementation = core_build(host, ("capability:" + host.get(pid)["digest"],))
    Quality(host).review(core_qa(implementation))
    registry.approve(pid, implementation.implementation_run_id, implementation.change_commit)
    dev.routing = router
    calls = []

    def execute(request):
        calls.append(request)
        route = router.records.get("route-" + request.work_item_id)["selected"]
        router.validate_execution(
            request, type("Adapter", (), {"transport_id": route["transport"]})
        )
        dev.ledger.put(
            "Usage",
            {
                "run_id": request.run_id,
                "work_item_id": request.work_item_id,
                "provider": route["provider"],
                "actual_model": route["model"],
                "transport": route["transport"],
                "billing_source": "SUBSCRIPTION",
                "status": "SUCCESS",
                "mode": "INDEPENDENT_QA_FIXTURE",
            },
            work_id=request.work_item_id,
        )
        return AgentRunResult(
            run_id=request.run_id,
            status="DOCUMENTATION_CHANGE" if request.role == "IMPLEMENT" else "RESEARCH_FINDING",
            summary="Controlled independent fixture result",
            files_changed=(
                FileChange(
                    path="docs/improvements/fixture-guide.md",
                    content="# Guide\n\nVerified fixture content.\n",
                ),
            )
            if request.role == "IMPLEMENT"
            else (),
            review_decision="APPROVE" if request.role == "REVIEW" else None,
        )

    monkeypatch.setattr(dev.runtime, "execute", execute)
    return dev, calls


def test_actual_readonly_call_completes_and_journals_executor(engine, monkeypatch):
    dev, calls = ready(engine, monkeypatch)
    work, _, _, _ = dev.call("read-probe", "CODEX", "REVIEW", "Inspect provided text", {})
    assert work.status == State.COMPLETED
    journals = [
        r for r in dev.host.store.records(work_id=work.work_item_id) if r["kind"] == "JournalEntry"
    ]
    assert journals and all(r["agent"] == "CODEX" for r in journals)
    assert len(calls) == 1


def test_real_disposable_git_build_qa_and_governed_merge(engine, monkeypatch):
    dev, calls = ready(engine, monkeypatch)
    selected = proposal()
    built = dev.build("full-probe", selected)
    checked = dev.qa("full-probe", selected, built)
    merged = dev.merge("full-probe", selected, built, checked, operator_authorized=True)
    assert dev.git.git("rev-parse", "HEAD") == merged["merge_commit"]
    assert dev.host.store.get(built["work_item_id"]).status == State.COMPLETED
    assert [r.agent_id for r in calls] == ["CLAUDE", "CODEX"]
    assert calls[0].work_item_id != calls[1].work_item_id
    assert calls[1].allowed_paths == INSPECTION_PATHS
    assert calls[1].context_packet["repeated_host_checks"]["hashes"] == built["checks"]["hashes"]
    assert dev.rows("ProductMerge", "full-probe")
    assert dev.artifact("docs/improvements/fixture-guide.md")["content"].startswith("# Guide")


@pytest.mark.parametrize("mutation", ["unstaged", "staged", "untracked"])
def test_dirty_worktree_cannot_be_presented_as_exact_qa_commit(engine, monkeypatch, mutation):
    dev, _ = ready(engine, monkeypatch)
    selected = proposal()
    built = dev.build("tamper-probe", selected)
    target = Path(built["git"]["worktree"]) / "docs/improvements/fixture-guide.md"
    target.write_text("# Different artifact\n\nNot the committed build.\n", encoding="utf-8")
    if mutation == "staged":
        dev.git.git("add", "--", "docs/improvements/fixture-guide.md", cwd=built["git"]["worktree"])
    if mutation == "untracked":
        dev.git.git(
            "restore", "--", "docs/improvements/fixture-guide.md", cwd=built["git"]["worktree"]
        )
        target = Path(built["git"]["worktree"]) / "unreviewed.txt"
        target.write_text("Untracked extra file", encoding="utf-8")
    assert (
        hashlib.sha256(target.read_bytes()).hexdigest()
        != built["checks"]["hashes"]["docs/improvements/fixture-guide.md"]
    )
    monkeypatch.setattr(
        dev,
        "call",
        lambda *a, **k: pytest.fail("Dirty unreviewed bytes reached QA under the original commit"),
    )
    with pytest.raises(PermissionError):
        dev.qa("tamper-probe", selected, built)


def test_tamper_after_passing_qa_cannot_merge(engine, monkeypatch):
    dev, _ = ready(engine, monkeypatch)
    selected = proposal()
    built = dev.build("late-tamper", selected)
    checked = dev.qa("late-tamper", selected, built)
    target = Path(built["git"]["worktree"]) / "docs/improvements/fixture-guide.md"
    target.write_text("# Changed after passing QA\n", encoding="utf-8")
    monkeypatch.setattr(dev.git, "merge", lambda *a, **k: pytest.fail("Late tamper reached merge"))
    with pytest.raises(PermissionError, match="changed|differs"):
        dev.merge("late-tamper", selected, built, checked, operator_authorized=True)
    assert dev.host.store.get(built["work_item_id"]).status == State.AWAITING_REVIEW


def test_correction_has_new_parent_link_and_cannot_reuse_old_qa(engine, monkeypatch):
    dev, _ = ready(engine, monkeypatch)
    execute = dev.runtime.execute
    rejected = False

    def correction_execute(request):
        nonlocal rejected
        result = execute(request)
        if request.role == "REVIEW" and not rejected:
            rejected = True
            return result.model_copy(
                update={"review_decision": "REQUEST_CHANGES", "findings": ("Clarify the guide",)}
            )
        if request.role == "IMPLEMENT" and rejected:
            return result.model_copy(
                update={
                    "files_changed": (
                        FileChange(
                            path="docs/improvements/fixture-guide.md",
                            content="# Guide\n\nCorrected and clarified fixture.\n",
                        ),
                    )
                }
            )
        return result

    monkeypatch.setattr(dev.runtime, "execute", correction_execute)
    selected = proposal()
    original = dev.build("correction-loop", selected)
    old_qa = dev.qa("correction-loop", selected, original)
    assert old_qa.decision == "CHANGES_REQUIRED"
    revised = dev.build("correction-loop", selected, correction=old_qa.required_changes)
    assert (
        dev.host.store.get(revised["work_item_id"]).parent_work_item_id == original["work_item_id"]
    )
    assert revised["git"]["change_commit"] != original["git"]["change_commit"]
    with pytest.raises(PermissionError):
        dev.merge("correction-loop", selected, revised, old_qa, operator_authorized=True)
    new_qa = dev.qa("correction-loop", selected, revised)
    assert new_qa.qa_run_id != old_qa.qa_run_id
    merged = dev.merge("correction-loop", selected, revised, new_qa, operator_authorized=True)
    assert dev.git.git("rev-parse", "HEAD") == merged["merge_commit"]


def test_kill_prevents_build_before_worktree_or_provider(engine, monkeypatch):
    dev, calls = ready(engine, monkeypatch)
    engine.ledger.operate("kill")
    with pytest.raises(PermissionError):
        dev.build("killed-probe", proposal())
    assert not calls and not dev.rows("ProductBuildCheckpoint", "killed-probe")


def test_extra_unverified_proposal_capability_cannot_be_ignored(engine):
    dev = service(engine)
    with pytest.raises(PermissionError):
        dev.approve(
            "extra-capability",
            proposal(
                required_capabilities=(
                    "structured_output",
                    "isolated_text_proposal",
                    "native_x_access",
                )
            ),
        )


@pytest.mark.parametrize("path", ["docs/improvements/guide.md", "docs/improvements/subfolder"])
def test_proposal_scope_must_match_installed_transport_directory_grant(engine, path):
    dev = service(engine)
    with pytest.raises(PermissionError):
        dev.approve("exact-root-grant", proposal(affected_components=(path,)))


@pytest.mark.parametrize(
    "decision,target", [("REQUEST_CHANGES", State.CHANGES_REQUESTED), ("REJECT", State.REJECTED)]
)
def test_negative_qa_updates_builder_state(engine, monkeypatch, decision, target):
    dev, _ = ready(engine, monkeypatch)
    selected = proposal()
    built = dev.build("negative-qa", selected)
    review_work = dev.host.create(
        WorkItem(
            owner="triad",
            assigned_agent="CODEX",
            title="Independent QA fixture",
            description="Inspect exact artifact",
            work_type="review",
            authority_tier=0,
            allowed_tools=("read_file",),
            allowed_paths=(),
            execution_permissions=("read",),
            review_required=False,
            parent_work_item_id=built["work_item_id"],
        )
    )
    review_work, _ = dev.start_work(review_work)
    review_work = dev.host.advance(review_work, State.COMPLETED, "Controlled QA completed")
    result = AgentRunResult(
        run_id="fixture-review",
        status="RESEARCH_FINDING",
        summary="Needs corrections",
        review_decision=decision,
        findings=("Concrete issue",),
    )
    usage = {"provider": "openai", "actual_model": "fixture-model", "run_id": "fixture-review"}
    monkeypatch.setattr(dev, "call", lambda *a, **k: (review_work, result, None, usage))
    checked = dev.qa("negative-qa", selected, built)
    assert checked.decision not in {"PASS", "PASS_WITH_OBSERVATIONS"}
    assert dev.host.store.get(built["work_item_id"]).status == target


def test_failed_provider_build_has_failed_canonical_implementation(engine, monkeypatch):
    dev, _ = ready(engine, monkeypatch)

    def fail(request):
        raise RuntimeError("controlled provider failure")

    monkeypatch.setattr(dev.runtime, "execute", fail)
    with pytest.raises(RuntimeError, match="controlled provider failure"):
        dev.build("failed-probe", proposal())
    checkpoint = dev.rows("ProductBuildCheckpoint", "failed-probe")[-1]
    assert dev.host.store.get(checkpoint["work_item_id"]).status == State.FAILED
    assert any(
        r["work_item_id"] == checkpoint["work_item_id"] and r["status"] == "FAILED"
        for r in dev.canonical.list("ImplementationRun")
    )
