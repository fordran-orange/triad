"""Autonomous subscription-CLI execution inside a Core-created Git worktree.

This is not a security sandbox. The hard boundary is the disposable run worktree plus
Core's protected-path/secret/test merge gate. Provider login remains vendor-managed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trading_core.contracts import AgentRunResult
from trading_core.providers.process import ManagedProcess
from trading_core.runtime import ProviderError
from trading_core.security import ensure_no_secret
from trading_core.settings import ROOT


WORKTREE_ROOT = (ROOT / "data" / "temp" / "day3-worktrees").resolve()


def _workspace(value: str | Path) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(WORKTREE_ROOT) or not path.exists():
        raise PermissionError("Autonomous execution requires a Core-created run worktree")
    return path


def _prompt(request) -> str:
    protected = (
        "Core governance is machine protected. Do not edit governance policy, kill switch, "
        "spend/trading authority, ledger/provenance integrity, credential service, capability-"
        "evidence semantics, or the merge gate. Do not merge to main or push remote branches. "
        "Work only in the current run worktree. You may inspect/edit the repository, run tests "
        "and local shell/git commands, and use network research when useful. "
    )
    output = (
        "When finished, return ONLY one JSON object matching AgentRunResult. "
        f"run_id must be {request.run_id!r}. Do not include chain of thought. "
        "Use claims only for hypotheses/recommendations; Core verifies facts/tests independently. "
        "permission_requests must be empty because normal Triad work has no human approval gate."
    )
    payload = {
        "objective": request.objective,
        "acceptance_criteria": request.acceptance_criteria,
        "context": request.context_packet,
        "output_schema": AgentRunResult.model_json_schema(),
    }
    text = protected + output + "\n\nTASK PACKET:\n" + json.dumps(payload, default=str)
    ensure_no_secret(text)
    return text


def _objects(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _objects(item)


def _extract_result(text: str, run_id: str) -> AgentRunResult:
    candidates: list[dict] = []
    stripped = text.strip()
    try:
        root = json.loads(stripped)
        candidates.extend(_objects(root))
    except json.JSONDecodeError:
        # Codex/Grok streaming modes may emit JSONL. Parse each event independently.
        for line in stripped.splitlines():
            try:
                candidates.extend(_objects(json.loads(line)))
            except json.JSONDecodeError:
                continue
    for candidate in reversed(candidates):
        if candidate.get("run_id") == run_id:
            try:
                return AgentRunResult.model_validate(candidate)
            except Exception:
                continue
        for key in ("structured_output", "result", "output", "text", "message"):
            nested = candidate.get(key)
            if isinstance(nested, str):
                try:
                    parsed = json.loads(nested)
                    if isinstance(parsed, dict) and parsed.get("run_id") == run_id:
                        return AgentRunResult.model_validate(parsed)
                except (json.JSONDecodeError, ValueError):
                    pass
    raise ProviderError("DEGRADED", "InvalidAutonomousStructuredResult")


def _usage(value: Any) -> tuple[int | None, int | None]:
    inputs = outputs = None
    for item in _objects(value):
        for key in ("input_tokens", "inputTokens", "prompt_tokens"):
            if isinstance(item.get(key), int):
                inputs = item[key]
        for key in ("output_tokens", "outputTokens", "completion_tokens"):
            if isinstance(item.get(key), int):
                outputs = item[key]
    return inputs, outputs


class AutonomousCLIRun:
    """Run a configured subscription CLI non-interactively in an isolated worktree."""

    def __init__(self, command, agent, *, guard=lambda: None, resources=None):
        self.command = list(command)
        self.agent = agent
        self.guard = guard
        self.resources = resources
        self.runner = ManagedProcess()
        self.actual_model = None
        self.evidence: dict[str, Any] = {}

    def cancel(self):
        self.runner.cancel()

    def argv(self, workspace: Path, model: str, prompt: str) -> tuple[list[str], str]:
        selected = [] if not model or model == "Auto" else ["--model", model]
        if self.agent == "CLAUDE":
            # Official Claude Code non-interactive mode; bypass prompts only inside the
            # disposable run worktree. Core still owns the merge boundary.
            return (
                self.command
                + [
                    "--dangerously-skip-permissions",
                    "--print",
                    "--output-format",
                    "json",
                    "--no-session-persistence",
                    *selected,
                    prompt,
                ],
                "",
            )
        if self.agent == "GROK":
            return (
                self.command
                + [
                    "--no-auto-update",
                    "--always-approve",
                    "--cwd",
                    str(workspace),
                    "--output-format",
                    "json",
                    "--no-plan",
                    *selected,
                    "-p",
                    prompt,
                ],
                "",
            )
        if self.agent == "CODEX":
            # Keep Codex bounded to the run worktree while allowing network use and no
            # interactive approvals. Core's merge gate is the authority boundary.
            args = self.command + [
                "exec",
                "--json",
                "-c",
                'approval_policy="never"',
                "-c",
                'sandbox_mode="workspace-write"',
                "-c",
                "sandbox_workspace_write.network_access=true",
            ]
            if selected:
                args += selected
            args.append(prompt)
            return args, ""
        raise ValueError("Autonomous worktree mode requires a frontier CLI agent")

    def execute(self, request, workspace, model):
        root = _workspace(workspace)
        prompt = _prompt(request)
        argv, stdin = self.argv(root, model, prompt)
        timeout = self.resources.remaining_time() if self.resources else 480
        result = self.runner.run(
            argv,
            cwd=root,
            timeout=max(1, min(int(timeout), 86400)),
            stdin=stdin,
            guard=self.guard,
        )
        raw = result.stdout
        if result.status != "EXITED" or result.exit_code != 0:
            detail = (result.stderr or result.stdout)[-4000:]
            from trading_core.providers.transports import classify_failure

            status = classify_failure(detail)
            raise ProviderError(
                status if status != "ERROR" else "UNAVAILABLE",
                status if status != "ERROR" else "AutonomousCLIError",
            )
        parsed: Any = None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = []
            for line in raw.splitlines():
                try:
                    parsed.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        for item in _objects(parsed):
            candidate = item.get("model") or item.get("model_id") or item.get("modelId")
            if isinstance(candidate, str) and candidate:
                self.actual_model = candidate
        if not self.actual_model and model and model != "Auto":
            self.actual_model = model
        inputs, outputs = _usage(parsed)
        structured = _extract_result(raw, request.run_id)
        self.evidence = {
            "boundary": "CORE_RUN_WORKTREE",
            "workspace": str(root),
            "exit_code": result.exit_code,
            "duration": result.duration,
            "input_tokens": inputs if inputs is not None else "UNKNOWN",
            "output_tokens": outputs if outputs is not None else "UNKNOWN",
        }
        return structured, inputs, outputs
