"""Day 3 contracts, transport mapping and host Git protections."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError

import pytest
from pydantic import ValidationError
from triad.day3.adapters import HttpProvider, ProviderError, compile_prompt, strict_schema
from triad.day3.changes import GitChanges
from triad.day3.contracts import AgentRunRequest, AgentRunResult, FileChange, Limits
from triad.day3.scheduler import tick
from triad.day3.security import ensure_no_secret, redact
from triad.settings import ROOT


def request(**changes):
    return AgentRunRequest(
        agent_id="CODEX",
        work_item_id="test-work",
        mission_id="test-mission",
        context_packet={"observation": "fixture"},
        role="PROPOSE",
        objective="Bounded fixture",
        allowed_paths=("docs/improvements",),
        acceptance_criteria=("Verify source",),
        policy_decision={"decision": "ALLOW"},
        required_output_schema=AgentRunResult.model_json_schema(),
        **changes,
    )


def test_runtime_validates_unknown_fields_and_delegation():
    with pytest.raises(ValidationError):
        request(unrestricted_shell=True)
    with pytest.raises(ValidationError):
        request(delegation_depth=2)
    with pytest.raises(ValidationError):
        request(delegation_depth=1)
    with pytest.raises(ValidationError):
        AgentRunResult(run_id="id", status="SUCCESS", summary="not a permitted status")
    with pytest.raises(ValidationError):
        Limits(max_migrations=1)


def test_secret_redaction(monkeypatch):
    secret = "fixture-credential-do-not-record-12345"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    assert secret not in json.dumps(
        redact({"nested": [secret], "error": "Bearer abcdefghijklmnop"})
    )
    with pytest.raises(PermissionError):
        ensure_no_secret({"text": secret})
    with pytest.raises(PermissionError):
        compile_prompt(request().model_copy(update={"objective": secret}))


@pytest.mark.parametrize("agent", ["CODEX", "CLAUDE", "GROK", "LOCAL_QWEN"])
def test_unavailable_or_offline_provider_is_not_simulated(agent, monkeypatch):
    config = json.loads((ROOT / "agents/day3.json").read_text())["providers"][agent]
    adapter = HttpProvider(agent, config, values={})
    monkeypatch.setattr(
        adapter,
        "transport",
        lambda *a, **k: (_ for _ in ()).throw(ProviderError("UNAVAILABLE", "Offline")),
    )
    result = adapter.health_check()
    assert result.status == "UNAVAILABLE" and result.mode == "UNAVAILABLE"


@pytest.mark.parametrize(
    "agent,code,expected",
    [("CODEX", 429, "RATE_LIMITED"), ("CLAUDE", 503, "DEGRADED"), ("GROK", 401, "AUTH_FAILED")],
)
def test_transport_failure_does_not_leak_response_or_key(agent, code, expected, monkeypatch):
    config = json.loads((ROOT / "agents/day3.json").read_text())["providers"][agent]
    adapter = HttpProvider(
        agent,
        config,
        values={config["key_env"]: "fixture-secret", config["model_env"]: "fixture-model"},
    )

    def fail(*a, **k):
        raise HTTPError("https://example.invalid", code, "fixture-secret", {}, None)

    monkeypatch.setattr("triad.day3.adapters.urllib.request.urlopen", fail)
    with pytest.raises(ProviderError) as raised:
        adapter.transport("/models")
    assert raised.value.status == expected and "fixture-secret" not in str(raised.value)


@pytest.mark.parametrize("agent", ["CODEX", "CLAUDE", "GROK"])
def test_vendor_formats_preserve_envelope_and_validate_result(agent, monkeypatch):
    config = json.loads((ROOT / "agents/day3.json").read_text())["providers"][agent]
    adapter = HttpProvider(
        agent,
        config,
        values={config["key_env"]: "fixture-key", config["model_env"]: "fixture-model"},
    )
    req = request()
    output = AgentRunResult(
        run_id=req.run_id,
        status="NO_CHANGE_JUSTIFIED",
        summary="Evidence does not justify a change",
    ).model_dump_json()
    payloads = []

    def transport(path, body, timeout):
        payloads.append(body)
        if agent == "CODEX":
            return {
                "status": "completed",
                "output": [{"content": [{"type": "output_text", "text": output}]}],
                "usage": {"input_tokens": 20, "output_tokens": 40},
            }
        if agent == "CLAUDE":
            return {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": output}],
                "usage": {"input_tokens": 20, "output_tokens": 40},
            }
        return {
            "choices": [{"finish_reason": "stop", "message": {"content": output}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 40},
        }

    monkeypatch.setattr(adapter, "transport", transport)
    result, inputs, outputs = adapter.execute(req)
    assert result.status == "NO_CHANGE_JUSTIFIED" and (inputs, outputs) == (20, 40)
    text = payloads[0].get("input") or payloads[0]["messages"][-1]["content"]
    canonical = json.loads(text)
    assert canonical["allowed_paths"] == list(req.allowed_paths)
    assert canonical["policy_decision"] == req.policy_decision
    assert "fixture-key" not in json.dumps(payloads)


def test_invalid_json_and_incomplete_provider_response_fail(monkeypatch):
    config = json.loads((ROOT / "agents/day3.json").read_text())["providers"]["CODEX"]
    adapter = HttpProvider(
        "CODEX", config, values={"OPENAI_MODEL": "fixture", "OPENAI_API_KEY": "fixture"}
    )
    monkeypatch.setattr(
        adapter,
        "transport",
        lambda *a: {
            "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": "not json"}]}],
        },
    )
    with pytest.raises(ProviderError, match="Malformed"):
        adapter.execute(request())
    monkeypatch.setattr(adapter, "transport", lambda *a: {"status": "incomplete"})
    with pytest.raises(ProviderError, match="Incomplete"):
        adapter.execute(request())


def test_pricing_requires_explicit_rates():
    config = json.loads((ROOT / "agents/day3.json").read_text())["providers"]["CODEX"]
    with pytest.raises(ProviderError, match="PricingNotConfigured"):
        HttpProvider("CODEX", config, values={}).estimate_cost(100, 100)
    provider = HttpProvider(
        "CODEX",
        config,
        values={"OPENAI_INPUT_USD_PER_MILLION": "1", "OPENAI_OUTPUT_USD_PER_MILLION": "5"},
    )
    assert provider.estimate_cost(1000, 1000) == 0.006


@pytest.fixture
def git_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "test@localhost")
    git("config", "user.name", "Triad Test")
    (root / "README.md").write_text("# Fixture\n")
    git("add", ".")
    git("commit", "-m", "baseline")
    return GitChanges(root, tmp_path / "worktrees")


def test_branch_isolation_review_before_merge_and_exact_rollback(git_repo):
    broker = git_repo
    metadata = broker.isolate("test-work", "CODEX")
    change = FileChange(
        path="docs/improvements/note.md", content="# Checked note\n\nEvidence retained.\n"
    )
    checks = broker.apply(metadata, (change,), Limits())
    assert checks["passed"]
    assert not (broker.root / change.path).exists()
    broker.commit(metadata, "CODEX")
    with pytest.raises(PermissionError):
        broker.merge(metadata, {"decision": "REJECT"}, Limits())
    with pytest.raises(PermissionError):
        broker.merge(
            metadata,
            {
                "decision": "APPROVE",
                "change_commit": metadata["change_commit"],
                "reviewer": "CODEX",
                "worker": "CODEX",
            },
            Limits(),
        )
    broker.review_commit(metadata, "independent-review", "APPROVE")
    review = {
        "review_id": "independent-review",
        "reviewer": "CLAUDE",
        "worker": "CODEX",
        "decision": "APPROVE",
        "change_commit": metadata["change_commit"],
    }
    broker.merge(metadata, review, Limits())
    assert (broker.root / change.path).exists()
    rollback = broker.prepare_revert(metadata, "test-rollback", "GROK")
    assert not (Path(rollback["worktree"]) / change.path).exists()
    broker.verify(rollback, Limits())
    broker.review_commit(rollback, "rollback-review", "APPROVE")
    broker.merge(
        rollback,
        {
            "review_id": "rollback-review",
            "reviewer": "CODEX",
            "worker": "GROK",
            "decision": "APPROVE",
            "change_commit": rollback["change_commit"],
        },
        Limits(),
    )
    assert not (broker.root / change.path).exists()
    assert broker.git("status", "--porcelain") == ""
    assert rollback["reverts_commit"] == metadata["change_commit"] and rollback["merge_commit"]


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "../escape.md",
        "app/triad/control.py",
        "docs/improvements/evil.py",
        "docs/improvements/.hidden.md",
        "C:/escape.md",
        "docs/improvements/a.md:stream",
    ],
)
def test_change_scope_blocks_secret_governance_and_executable_paths(git_repo, path):
    metadata = git_repo.isolate("test-scope", "CODEX")
    with pytest.raises(PermissionError):
        git_repo.apply(metadata, (FileChange(path=path, content="# no\n"),), Limits())


def test_change_limits_and_stale_hash(git_repo):
    metadata = git_repo.isolate("test-limits", "CODEX")
    with pytest.raises(PermissionError):
        git_repo.apply(
            metadata,
            (FileChange(path="docs/improvements/a.md", content="# heading\n" * 200),),
            Limits(),
        )
    with pytest.raises(PermissionError):
        git_repo.apply(
            metadata,
            (
                FileChange(
                    path="docs/improvements/a.md", content="# heading\n", original_sha256="fake"
                ),
            ),
            Limits(),
        )


def test_schedule_configurable_and_disabled():
    assert tick(config={"enabled": False})["status"] == "DISABLED"

    class Engine:
        class L:
            def control(self):
                return {"paused": False, "killed": False}

        ledger = L()

        def run(self, **args):
            return {"status": "CALLED", "day": self.day, **args}

    config = {"enabled": True, "timezone": "UTC", "time": "17:30", "mode": "REAL"}
    assert tick(Engine(), datetime(2026, 1, 1, 17, 29, tzinfo=UTC), config)["status"] == "NOT_DUE"
    assert tick(Engine(), datetime(2026, 1, 1, 17, 30, tzinfo=UTC), config)["day"] == "2026-01-01"


def test_json_schema_requires_all_properties():
    schema = strict_schema(AgentRunResult.model_json_schema())
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False
