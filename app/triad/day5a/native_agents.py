"""Pinned Claude MCP and Grok ACP integrations with host-owned isolated tools.

Vendor harnesses remain trusted authentication/inference processes. Models have
no host tools: Claude has only this run's MCP catalog; Grok file tools use ACP
callbacks. Capability drift aborts the run rather than enabling a local fallback.
"""

import json
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import PureWindowsPath

from triad.day3.adapters import ProviderError, strict_schema
from triad.day3.contracts import AgentRunResult
from triad.day5a.bounded_tools import BoundedTools, ToolServer
from triad.day5a.codex_executor import LineProcess
from triad.day5a.isolation import safe_path
from triad.day5a.process import ManagedProcess, clean_environment

VERSIONS = {"CLAUDE": "2.1.276", "GROK": "1.0.34"}


@contextmanager
def native_workspace(prefix):
    temporary = tempfile.TemporaryDirectory(prefix=prefix)
    try:
        yield temporary.name
    finally:
        # Windows job termination is asynchronous for descendants. The root
        # process may have exited before the leader releases its working dir.
        for attempt in range(20):
            try:
                temporary.cleanup()
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.1)


def token_count(value):
    if type(value) is not int or value < 0:
        raise ProviderError("DEGRADED", "NativeUsageMissing")
    return value


class NativeRun:
    def __init__(self, command, guard, max_tool_calls=30):
        self.command, self.guard = command, guard
        self.max_tool_calls = max_tool_calls
        self.cancelled = threading.Event()
        self.actual_model = None
        self.evidence = {}
        self.broker = None
        self.deadline = time.monotonic() + 110

    def check(self):
        if self.cancelled.is_set() or time.monotonic() >= self.deadline:
            raise ProviderError("DEGRADED", "DeadlineExceeded")
        self.guard()

    def cancel(self):
        self.cancelled.set()
        if self.broker:
            self.broker.cancel()

    def prompt(self, request, files):
        return (
            "Execute this Triad assignment using only the supplied isolated file tools. "
            "Read every supplied file before reviewing it. File writes are proposals, not host changes. "
            "Return the requested JSON result with this run_id. Keep claims, commands_executed, "
            "actions_taken, tests_run and permission_requests empty; the host records tool evidence. "
            "For a review keep files_changed empty. For implementation report staged file contents. "
            "Never invoke a slash command, plugin, skill, network tool or another agent.\n"
            + "Supplied files: "
            + json.dumps(list(files))
            + "\n"
            + request.model_dump_json(exclude={"required_output_schema"})
        )

    def finish(self, raw, inputs, outputs):
        self.evidence.update(
            boundary="DOCKER_OFFLINE_TOOLS",
            model=self.actual_model,
            calls=self.broker.calls,
            denials=self.broker.denials,
            input_tokens=token_count(inputs),
            output_tokens=token_count(outputs),
        )
        result = AgentRunResult.model_validate(raw)
        if (
            result.commands_executed
            or result.permission_requests
            or result.claims
            or result.actions_taken
            or result.tests_run
        ):
            raise ProviderError("DEGRADED", "NativeResultViolation")
        observed = {c["path"] for c in self.broker.calls if c["tool"] == "read_file"}
        if not set(self.broker.original) <= observed:
            self.evidence["rejected_result_summary"] = result.summary[:1000]
            raise ProviderError("DEGRADED", "NativeReadEvidenceMissing")
        changes = self.broker.changes()
        if {c.path: c.content for c in result.files_changed} != {
            c.path: c.content for c in changes
        }:
            raise ProviderError("DEGRADED", "NativeProposalEvidenceMismatch")
        self.check()
        return result, inputs, outputs


class GrokSession:
    def __init__(self, command, cwd, guard=lambda: None, broker=None):
        self.cwd, self.guard, self.broker = cwd, guard, broker
        self.serial = 0
        self.session_id = None
        self.tools = None
        self.expected_tools = {"read_file"}
        if broker and broker.writable:
            self.expected_tools.add("search_replace")
        self.text = ""
        env = clean_environment()
        env.update(
            GROK_DISABLE_API_KEY_AUTH="1",
            GROK_MEMORY="0",
            GROK_WORKFLOWS="0",
            GROK_LOGIN_ENV="0",
            GROK_AGENT_DASHBOARD="0",
        )
        self.process = LineProcess(
            command
            + [
                "--no-auto-update",
                "--disable-web-search",
                "--leader-socket",
                cwd + "/leader.sock",
                "agent",
                "stdio",
            ],
            cwd=cwd,
            env=env,
        )

    def close(self):
        self.process.close()

    def relative(self, path):
        if not isinstance(path, str):
            raise PermissionError("Invalid path")
        # ACP uses absolute Windows paths; only the dedicated empty cwd is mapped.
        candidate = PureWindowsPath(path)
        if candidate.is_absolute():
            path = candidate.relative_to(PureWindowsPath(self.cwd)).as_posix()
        elif "\\" in path:
            raise PermissionError("Ambiguous relative path")
        return safe_path(path)

    def observe(self, message):
        self.guard()
        method, params = message.get("method"), message.get("params", {})
        if method == "session/update":
            update = params.get("update", {})
            tools = update.get("_meta", {}).get("tools")
            if tools is not None:
                if not isinstance(tools, list) or set(tools) != self.expected_tools:
                    raise ProviderError("UNAVAILABLE", "NativeToolCatalogMismatch")
                self.tools = tools
            if update.get("sessionUpdate") == "agent_message_chunk":
                self.text += update.get("content", {}).get("text", "")
                if len(self.text) > 48000:
                    raise ProviderError("DEGRADED", "NativeOutputLimit")
        if "id" not in message or not method:
            return
        reply = {"jsonrpc": "2.0", "id": message["id"]}
        try:
            if not self.broker or params.get("sessionId") != self.session_id:
                raise PermissionError("Wrong session")
            if method == "fs/read_text_file":
                path = self.relative(params.get("path"))
                content = self.broker.call("read_file", {"path": path})
                line, limit = params.get("line", 1), params.get("limit")
                if (
                    type(line) is not int
                    or line < 1
                    or (limit is not None and (type(limit) is not int or limit < 0))
                ):
                    raise ValueError("Invalid line range")
                if line != 1 or limit is not None:
                    content = "".join(
                        content.splitlines(keepends=True)[
                            line - 1 : None if limit is None else line - 1 + limit
                        ]
                    )
                reply["result"] = {"content": content}
            elif method == "fs/write_text_file":
                self.broker.call(
                    "propose_file_change",
                    {"path": self.relative(params.get("path")), "content": params.get("content")},
                )
                reply["result"] = {}
            else:
                # Includes terminal, arbitrary MCP, approval, escalation and host extensions.
                raise PermissionError("Unsupported operation")
        except Exception:  # noqa: BLE001 - never expose host exception details
            reply["error"] = {"code": -32602, "message": "Operation denied by Triad"}
        self.process.send(reply)

    def call(self, method, params):
        self.serial += 1
        identifier = self.serial
        self.guard()
        self.process.send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        # ACP may emit several notifications per generated token. Keep a fixed
        # frame ceiling without truncating ordinary multi-file reads; wall time,
        # per-frame size, total text and tool-call limits remain independent.
        for _ in range(4096):
            message = self.process.receive(timeout=110, guard=self.guard)
            if message.get("id") == identifier and "method" not in message:
                if "error" in message:
                    raise ProviderError("UNAVAILABLE", "GrokProtocolRejected")
                return message.get("result", {})
            self.observe(message)
        raise ProviderError("DEGRADED", "NativeFrameLimit")

    def authenticate(self):
        init = self.call(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": True,
                },
            },
        )
        if init.get("_meta", {}).get("agentVersion") != VERSIONS["GROK"]:
            raise ProviderError("UNAVAILABLE", "NativeVersionUnsupported")
        if "cached_token" not in {m.get("id") for m in init.get("authMethods", [])}:
            raise ProviderError("AUTH_FAILED", "AuthenticationRequired")
        auth = self.call("authenticate", {"methodId": "cached_token", "_meta": {"headless": True}})
        meta = auth.get("_meta", {})
        if (
            meta.get("auth_mode") != "Oidc"
            or meta.get("backend_billed") is not False
            or not meta.get("subscription_tier")
        ):
            raise ProviderError("AUTH_FAILED", "SubscriptionAuthenticationRequired")
        return {"auth_state": "AUTHENTICATED", "billing_source": "SUBSCRIPTION"}

    def start(self, model="Auto"):
        profile = {
            "name": "triad-isolated",
            "description": "Triad isolated text tools",
            "tools": ["Read", "Edit"] if "search_replace" in self.expected_tools else ["Read"],
            "disallowedTools": ["search_tool", "use_tool"],
            "discoverSkills": False,
            "inheritSkills": False,
            "agentsMd": False,
            "injectDefaultTools": False,
            "maxTurns": 4,
            "permissionMode": "dontAsk",
            "mcpInheritance": "none",
        }
        result = self.call(
            "session/new",
            {
                "cwd": self.cwd,
                "mcpServers": [],
                "_meta": {"agentProfile": profile, "askUserQuestion": False},
            },
        )
        self.session_id = result["sessionId"]
        if self.tools is None:
            raise ProviderError("UNAVAILABLE", "NativeToolCatalogMissing")
        selected = result.get("models", {}).get("currentModelId")
        if model != "Auto":
            self.call("session/set_model", {"sessionId": self.session_id, "modelId": model})
            selected = model
        if not selected:
            raise ProviderError("UNAVAILABLE", "NativeModelMissing")
        self.call(
            "session/set_config_option",
            {"sessionId": self.session_id, "configId": "reasoning_effort", "value": "low"},
        )
        return selected


def grok_authentication(command):
    deadline = time.monotonic() + 20

    def guard():
        if time.monotonic() > deadline:
            raise TimeoutError("Auth check timed out")

    with tempfile.TemporaryDirectory(prefix="triad-grok-auth-") as cwd:
        session = GrokSession(command, cwd, guard)
        try:
            return session.authenticate()
        finally:
            session.close()


def grok_preflight(command, cwd):
    # Use the vendor's public configuration inventory, not its auth files.
    # Do not persist/return raw configuration (which may contain user values).
    result = ManagedProcess().run(
        command + ["--no-auto-update", "inspect", "--json"], cwd=cwd, timeout=15
    )
    if result.exit_code or result.status != "EXITED":
        raise ProviderError("UNAVAILABLE", "NativeConfigurationUnverified")
    report = json.loads(result.stdout)
    for key in ("hooks", "plugins", "mcpServers", "lspServers"):
        if not isinstance(report.get(key), list) or any(
            not row.get("disabled", False) for row in report[key]
        ):
            raise ProviderError("UNAVAILABLE", "NativeCustomizationsPresent")


class GrokRun(NativeRun):
    def execute(self, request, files, model="Auto", writable=()):
        self.broker = BoundedTools(
            files, writable=writable, guard=self.check, max_calls=self.max_tool_calls
        )
        with native_workspace(prefix="triad-grok-run-") as cwd:
            grok_preflight(self.command, cwd)
            session = GrokSession(self.command, cwd, self.check, self.broker)
            try:
                session.authenticate()
                self.actual_model = session.start(model)

                def meter(response):
                    meta = response.get("_meta", {})
                    usage = meta.get("usage", {})
                    models = usage.get("modelUsage", {})
                    if not models or usage.get("usageIsIncomplete"):
                        raise ProviderError("DEGRADED", "NativeUsageMissing")
                    for field in ("input", "output"):
                        key = field + "_tokens"
                        amount = sum(token_count(v.get(field + "Tokens")) for v in models.values())
                        self.evidence[key] = self.evidence.get(key, 0) + amount
                    if response.get("stopReason") != "end_turn":
                        raise ProviderError("DEGRADED", "GrokTurnIncomplete")

                if files:
                    # Grok can finish a schema-constrained prompt with a progress
                    # message instead of calling tools. Read first without a
                    # response schema, verify actual callbacks, then request the
                    # structured verdict in the same isolated session.
                    reading = session.call(
                        "session/prompt",
                        {
                            "sessionId": session.session_id,
                            "prompt": [
                                {
                                    "type": "text",
                                    "text": "Use the read_file tool to read every one of these supplied files now: "
                                    + json.dumps(list(files))
                                    + ". These are available through the isolated client file tools. "
                                    "Do not merely announce an intention. After all tool reads finish, reply READY. "
                                    "No writing, shell commands, plugins, network tools or other agents.",
                                }
                            ],
                        },
                    )
                    meter(reading)
                    observed = {c["path"] for c in self.broker.calls if c["tool"] == "read_file"}
                    if not set(files) <= observed:
                        raise ProviderError("DEGRADED", "NativeReadEvidenceMissing")
                    session.text = ""
                result = session.call(
                    "session/prompt",
                    {
                        "sessionId": session.session_id,
                        "prompt": [
                            {
                                "type": "text",
                                "text": self.prompt(request, files)
                                + (
                                    "\nThe host verified that both/all supplied files were already read in this session. Use those contents; do not repeat reads. Return the completed assessment now, not a progress message."
                                    if files
                                    else ""
                                ),
                            }
                        ],
                        "_meta": {"outputSchema": strict_schema(request.required_output_schema)},
                    },
                )
                self.evidence.update(
                    stop_reason=result.get("stopReason"),
                    result_meta_keys=sorted(result.get("_meta", {})),
                    usage_keys=sorted(result.get("_meta", {}).get("usage", {})),
                )
                meter(result)
                meta = result.get("_meta", {})
                inputs, outputs = self.evidence["input_tokens"], self.evidence["output_tokens"]
                if not isinstance(meta.get("modelId"), str) or not meta["modelId"]:
                    raise ProviderError("DEGRADED", "NativeModelMissing")
                self.actual_model = meta["modelId"]
                raw = meta.get("structuredOutput")
                if raw is None:
                    raw = json.loads(session.text)
                return self.finish(raw, inputs, outputs)
            except Exception as exc:
                self.evidence["failure"] = (
                    exc.error_class if isinstance(exc, ProviderError) else type(exc).__name__
                )
                if isinstance(exc, RuntimeError):
                    self.evidence["reader_status"] = session.process.failure_reason
                raise
            finally:
                self.evidence.update(calls=self.broker.calls, denials=self.broker.denials)
                session.close()


def claude_arguments(url, writable=False, model="Auto", schema=None):
    config = {"mcpServers": {"triad": {"type": "http", "url": url}}}
    settings = {
        "disableAllHooks": True,
        "enabledPlugins": {},
        "autoMemoryEnabled": False,
        "forceLoginMethod": "claudeai",
    }
    args = [
        "--print",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        json.dumps(config),
        "--setting-sources",
        "",
        "--settings",
        json.dumps(settings),
        "--disable-slash-commands",
        "--no-chrome",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        "mcp__triad__read_file",
    ]
    if writable:
        args += ["mcp__triad__propose_file_change"]
    args += ["--effort", "low"]
    if schema is not None:
        args += ["--json-schema", json.dumps(strict_schema(schema))]
    if model != "Auto":
        args += ["--model", model]
    return args


def claude_initialize(app, guard, expected):
    for identifier, request in (
        ("initialize", {"subtype": "initialize"}),
        ("mcp", {"subtype": "mcp_status"}),
    ):
        app.send({"type": "control_request", "request_id": identifier, "request": request})
        for _ in range(64):
            msg = app.receive(timeout=20, guard=guard)
            if msg.get("type") != "control_response":
                raise ProviderError("UNAVAILABLE", "ClaudeHandshakeUnexpected")
            response = msg.get("response", {})
            if response.get("request_id") != identifier or response.get("subtype") != "success":
                raise ProviderError("UNAVAILABLE", "ClaudeHandshakeFailed")
            if identifier == "mcp":
                servers = response.get("response", {}).get("mcpServers", [])
                if (
                    len(servers) != 1
                    or servers[0].get("name") != "triad"
                    or servers[0].get("status") != "connected"
                    or {t.get("name") for t in servers[0].get("tools", [])} != expected
                ):
                    raise ProviderError("UNAVAILABLE", "NativeToolCatalogMismatch")
            break


class ClaudeRun(NativeRun):
    def execute(self, request, files, model="Auto", writable=()):
        self.broker = BoundedTools(
            files, writable=writable, guard=self.check, max_calls=self.max_tool_calls
        )
        with (
            native_workspace(prefix="triad-claude-run-") as cwd,
            ToolServer(self.broker) as server,
        ):
            argv = self.command + claude_arguments(
                server.url, bool(writable), model, request.required_output_schema
            )
            app = LineProcess(argv, cwd=cwd)
            expected = {"mcp__triad__" + t["name"] for t in self.broker.definitions()}
            initialized = False
            try:
                claude_initialize(app, self.check, {t["name"] for t in self.broker.definitions()})
                app.send(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": self.prompt(request, files)},
                    }
                )
                for _ in range(512):
                    message = app.receive(timeout=110, guard=self.check)
                    if message.get("type") == "system" and message.get("subtype") == "init":
                        # StructuredOutput is a vendor result formatter, not an OS tool.
                        tools = set(message.get("tools", [])) - {"StructuredOutput"}
                        if tools != expected:
                            raise ProviderError("UNAVAILABLE", "NativeToolCatalogMismatch")
                        self.actual_model = message.get("model")
                        initialized = bool(self.actual_model)
                    if message.get("type") == "control_request":
                        app.send(
                            {
                                "type": "control_response",
                                "response": {
                                    "subtype": "error",
                                    "request_id": message.get("request_id"),
                                    "error": "Triad denies additional permissions",
                                },
                            }
                        )
                    if message.get("type") == "result":
                        if (
                            not initialized
                            or message.get("is_error")
                            or message.get("subtype") != "success"
                        ):
                            raise ProviderError("DEGRADED", "ClaudeTurnIncomplete")
                        usage = message.get("usage", {})
                        token_count(usage.get("input_tokens"))
                        inputs = sum(
                            token_count(usage.get(k, 0))
                            for k in (
                                "input_tokens",
                                "cache_read_input_tokens",
                                "cache_creation_input_tokens",
                            )
                        )
                        outputs = token_count(usage.get("output_tokens"))
                        return self.finish(message.get("structured_output"), inputs, outputs)
                raise ProviderError("DEGRADED", "NativeFrameLimit")
            finally:
                self.evidence.update(calls=self.broker.calls, denials=self.broker.denials)
                app.close()
