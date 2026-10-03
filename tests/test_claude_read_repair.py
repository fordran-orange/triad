"""Protocol continuations retain evidence, usage, verdict independence and authority."""

from contextlib import nullcontext
from types import SimpleNamespace as NS

import pytest
from trading_core.contracts import AgentRunRequest, AgentRunResult
from trading_core.providers import native_agents as native
from trading_core.runtime import ProviderError


def setup(monkeypatch, *, complete=True, invalid=False, stop=False):
    request = AgentRunRequest(
        run_id="fixture",
        agent_id="CLAUDE",
        work_item_id="work",
        mission_id="mission",
        role="REVIEW",
        objective="Independently assess original evidence",
        context_packet={
            "evidence_delivery": "files-v1",
            "product_planning": {
                "history": {
                    "ProductProposal": [{"id": "optional-history", "proposal": {"title": "Old"}}]
                }
            },
        },
        allowed_tools=("read_file",),
        allowed_paths=("one.py", "two.py"),
        acceptance_criteria=("Assess sources",),
        execution_permissions=("read",),
        policy_decision={},
        required_output_schema=AgentRunResult.model_json_schema(),
    )
    run = native.ClaudeRun(["fixture"], lambda: None)

    class Wire:
        def __init__(self):
            self.sent, self.results, self.closed = [], 0, False

        def send(self, message):
            self.sent.append(message)

        def receive(self, **kw):
            kw["guard"]()
            if self.results == 0:
                self.results += 1
                return {
                    "type": "system",
                    "subtype": "init",
                    "model": "fixture-model",
                    "tools": ["mcp__triad__read_file", "StructuredOutput"],
                }
            self.results += 1
            required = sorted(run.required_reads)
            if self.results == 2:
                run.broker.calls.append({"tool": "read_file", "path": required[0]})
            elif complete:
                run.broker.calls.append({"tool": "read_file", "path": required[1]})
            result = AgentRunResult(
                run_id="fixture",
                status="NO_CHANGE_JUSTIFIED",
                summary="Independent result",
                review_decision="APPROVE" if self.results == 2 else "REJECT",
                commands_executed=("invalid command claim",) if invalid else (),
            ).model_dump(mode="json")
            if stop:
                run.cancel()
            return {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "structured_output": result,
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 30,
                    "output_tokens": 5,
                },
            }

        def close(self):
            self.closed = True

    wire = Wire()
    monkeypatch.setattr(native, "LineProcess", lambda *a, **k: wire)
    monkeypatch.setattr(native, "claude_initialize", lambda *a: None)
    monkeypatch.setattr(native, "ToolServer", lambda _: nullcontext(NS(url="fixture")))
    return run, request, wire


def test_missing_reads_resume_same_session_and_allow_revised_verdict(monkeypatch):
    run, request, wire = setup(monkeypatch)
    result, inputs, outputs = run.execute(request, {"one.py": "first", "two.py": "second"})
    assert result.review_decision == "REJECT"  # Early approval never becomes an accepted result.
    assert (inputs, outputs) == (120, 10)
    assert len(wire.sent) == 2 and wire.closed
    repair = wire.sent[1]["message"]["content"]
    required = sorted(run.required_reads)
    assert required[1] in repair and required[0] not in repair
    optional = set(run.broker.original) - run.required_reads
    assert optional and not any(path in repair for path in optional)
    assert run.evidence["read_evidence_repairs"] == [{"attempt": 1, "missing_paths": [required[1]]}]


def test_persistent_missing_reads_fail_closed_with_whole_session_usage(monkeypatch):
    run, request, wire = setup(monkeypatch, complete=False)
    with pytest.raises(ProviderError, match="NativeReadEvidenceMissing"):
        run.execute(request, {"one.py": "first", "two.py": "second"})
    assert len(wire.sent) == 3 and wire.closed
    assert run.evidence["input_tokens"] == 180 and run.evidence["output_tokens"] == 15


def test_invalid_result_is_not_repaired_by_read_continuation(monkeypatch):
    run, request, wire = setup(monkeypatch, invalid=True)
    with pytest.raises(ProviderError, match="NativeResultViolation"):
        run.execute(request, {"one.py": "first", "two.py": "second"})
    assert len(wire.sent) == 1 and wire.closed


def test_cancel_before_read_continuation_sends_no_extra_prompt(monkeypatch):
    run, request, wire = setup(monkeypatch, stop=True)
    with pytest.raises(ProviderError, match="DeadlineExceeded"):
        run.execute(request, {"one.py": "first", "two.py": "second"})
    assert len(wire.sent) == 1 and wire.closed
