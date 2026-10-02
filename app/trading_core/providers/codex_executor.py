"""Codex remote executor bridge. No provider credentials enter the executor.

Experimental protocol support is version-pinned and must pass acceptance before
CLITransport enables it. This module never starts a model turn by itself.
"""

import json
import os
import queue
import secrets
import shlex
import signal
import subprocess
import threading
import time
from uuid import uuid4

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

from trading_core.contracts import AgentRunResult
from trading_core.providers.isolation import SEED, OfflineSandbox, safe_path
from trading_core.providers.process import WindowsJob, clean_environment
from trading_core.runtime import ProviderError, strict_schema
from trading_core.security import ensure_no_secret
from trading_core.settings import ROOT

VERSION = "0.155.0-alpha.2.6"
TAG = "triad-codex-executor:" + VERSION


class LineProcess:
    """Bounded JSON-line process with tree cleanup, used only by the host."""

    def __init__(self, argv, *, cwd=ROOT, env=None):
        self.messages = queue.Queue(maxsize=128)
        self.failed = threading.Event()
        self.closing = threading.Event()
        self.failure_reason = "Executor protocol disconnected"
        self.job = WindowsJob() if os.name == "nt" else None
        self.process = None
        try:
            self.process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=clean_environment() if env is None else env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=(0x08000000 | 0x4) if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            if self.job:
                self.job.attach_and_resume(self.process)
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            while not self.closing.is_set() and (line := self.process.stdout.readline(1048577)):
                if len(line) > 1048576:
                    raise ValueError("Protocol frame exceeds limit")
                message = json.loads(line)
                # A live agent can emit many token updates while a file tool is
                # running. Backpressure bounds memory without dropping frames.
                while not self.closing.is_set():
                    try:
                        self.messages.put(message, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        except (ValueError, OSError) as exc:
            self.failure_reason = "Executor protocol reader failed: " + type(exc).__name__
            self.failed.set()
        finally:
            self.failed.set()

    def send(self, message):
        data = json.dumps(message).encode() + b"\n"
        if len(data) > 1048576:
            raise ValueError("Protocol request exceeds limit")
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def receive(self, timeout=20, guard=lambda: None):
        deadline = time.monotonic() + timeout if timeout is not None else None
        while deadline is None or time.monotonic() < deadline:
            guard()
            try:
                return self.messages.get(timeout=0.1)
            except queue.Empty:
                if self.failed.is_set():
                    raise RuntimeError(self.failure_reason) from None
        raise TimeoutError("Executor protocol deadline exceeded")

    def close(self):
        self.closing.set()
        if self.job:
            self.job.close()
        if self.process:
            if self.process.poll() is None:
                if os.name != "nt":
                    os.killpg(self.process.pid, signal.SIGKILL)
                else:
                    self.process.kill()
            self.process.wait(timeout=5)
            for stream in (self.process.stdin, self.process.stdout):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass


class CodexExecutor:
    """An offline exec-server reached via an authenticated loopback relay.

    WebSocket bytes are forwarded over docker exec stdio, so the container itself
    keeps network=none. App-server remains outside, owning its vendor login.
    Only the trusted orchestration process receives the unpredictable relay URL.
    """

    def __init__(self, files, *, guard, writable=(), max_tool_calls=30, resources=None):
        self.files = {safe_path(k): v for k, v in files.items()}
        if writable:
            raise PermissionError("The Codex executor is currently read-only")
        self.writable = ()
        if len(files) > 2048 or len(writable) > 5:
            raise ValueError("Executor snapshot exceeds limit")
        if sum(len(v.encode()) for v in files.values()) > 1000000:
            raise ValueError("Executor input too large")
        ensure_no_secret(files)
        self.guard = guard
        if not 1 <= max_tool_calls <= 1000:
            raise ValueError("Invalid executor tool-call budget")
        self.max_tool_calls = max_tool_calls
        self.resources = resources
        self.tool_calls = 0
        self.name = "triad-tools-" + uuid4().hex
        self.environment_id = "triad-" + uuid4().hex
        self.path = "/" + secrets.token_urlsafe(32)
        self.server = self.process = self.connection = None
        self.connected = threading.Event()
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.methods = []
        self.requests = []
        self.denials = 0
        self.responses = []
        self.frame_count = 0

    def mediate(self, message):
        """Read-only native tools: the host owns the allowed operations."""
        method = message.get("method")
        params = message.get("params", {})
        if method is None:
            return message
        ensure_no_secret(params)
        if method in {"process/start", "fs/readFile", "fs/getMetadata", "fs/readDirectory"}:
            self.tool_calls += 1
            if self.resources:
                self.resources.consume_tool()
            elif self.tool_calls > self.max_tool_calls:
                raise PermissionError("WorkItem tool budget exhausted")
        if method in {
            "initialize",
            "initialized",
            "environment/info",
            "environment/status",
            "environmentConfig/read",
            "fs/getMetadata",
            "fs/readDirectory",
            "process/terminate",
        }:
            return message
        if method == "fs/readFile":
            path = params.get("path", "").removeprefix("file://").removeprefix("/workspace/")
            if path in self.files:
                return message
        if method == "process/start":
            argv = params.get("argv", [])
            if len(argv) == 3 and argv[0] in {"/bin/bash", "/usr/bin/bash", "/bin/sh"}:
                if argv[1] not in {"-lc", "-c"}:
                    raise PermissionError("Unsupported shell invocation")
                argv = shlex.split(argv[2])
            if argv and argv[0] == "cat":
                paths = argv[1:]
                if paths and paths[0] == "--":
                    paths = paths[1:]
                paths = [p.removeprefix("/workspace/") for p in paths]
                if paths and all(p in self.files for p in paths):
                    # Rebuild rather than execute shell syntax, environment or
                    # working-directory changes supplied by the agent harness.
                    params = {
                        **params,
                        "argv": ["cat", "--", *paths],
                        "cwd": "file:///workspace",
                        "env": {},
                        "sandbox": None,
                        "arg0": None,
                        "enforceManagedNetwork": False,
                        "managedNetwork": None,
                        "envPolicy": {
                            "inherit": "none",
                            "ignoreDefaultExcludes": False,
                            "set": {},
                            "exclude": [],
                            "includeOnly": [],
                        },
                        "tty": False,
                        "pipeStdin": False,
                    }
                    return {**message, "params": params}
        raise PermissionError("Only reading supplied files is granted")

    def __enter__(self):
        try:
            self.guard()
            image = OfflineSandbox._docker(["image", "inspect", TAG, "--format", "{{.Id}}"])
            if not image.startswith("sha256:"):
                raise RuntimeError("Executor image unavailable")
            OfflineSandbox._docker(OfflineSandbox.create_options(self.name, image))
            OfflineSandbox._docker(["start", self.name])
            OfflineSandbox._docker(
                ["exec", "-i", self.name, "python", "-I", "-c", SEED],
                stdin=json.dumps({"files": self.files, "writable": self.writable}),
            )
            self.process = LineProcess(
                [
                    "docker",
                    "exec",
                    "-i",
                    "--user=10001:10001",
                    self.name,
                    "codex",
                    "exec-server",
                    "--listen",
                    "stdio",
                ]
            )
            self.server = serve(
                self._relay,
                "127.0.0.1",
                0,
                max_size=1048576,
                max_queue=16,
                compression=None,
                open_timeout=5,
                close_timeout=2,
            )
            self.url = f"ws://127.0.0.1:{self.server.socket.getsockname()[1]}{self.path}"
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
            return self
        except BaseException:
            self.close()
            raise

    def _relay(self, socket):
        with self.lock:
            if socket.request.path != self.path or self.connected.is_set():
                socket.close(1008, "Unauthorized executor connection")
                return
            self.connected.set()
            self.connection = socket

        def outbound():
            try:
                while not self.stopped.is_set():
                    message = self.process.receive(timeout=None, guard=self.guard)
                    if "error" in message:
                        self.responses.append(message["error"])
                    socket.send(json.dumps(message))
            except (OSError, RuntimeError, TimeoutError, PermissionError):
                socket.close()

        threading.Thread(target=outbound, daemon=True).start()
        try:
            for raw in socket:
                self.guard()
                self.frame_count += 1
                if self.frame_count > 8192:
                    raise PermissionError("Executor protocol budget exhausted")
                message = json.loads(raw)
                try:
                    message = self.mediate(message)
                except (PermissionError, ValueError):
                    self.denials += 1
                    if "id" in message:
                        socket.send(
                            json.dumps(
                                {
                                    "id": message["id"],
                                    "error": {
                                        "code": -32602,
                                        "message": "Triad read-only grant: use cat on supplied files only",
                                    },
                                }
                            )
                        )
                    continue
                if "method" in message:
                    self.methods.append(message["method"])
                    if message["method"] == "process/start":
                        self.requests.append(message)
                self.process.send(message)
        except (ConnectionClosed, OSError, ValueError, PermissionError):
            socket.close()
        finally:
            self.stopped.set()

    def close(self):
        self.stopped.set()
        if self.connection:
            self.connection.close()
        if self.server:
            self.server.shutdown()
        try:
            if self.process:
                self.process.close()
        finally:
            OfflineSandbox._docker(["rm", "--force", self.name])

    def __exit__(self, *_):
        self.close()


class CodexReadOnlyRun:
    """Version-pinned read-only Codex native execution and structured results."""

    def __init__(self, command, guard, max_tool_calls=30, *, resources=None):
        self.command = command
        self.guard = guard
        self.max_tool_calls = max_tool_calls
        self.cancelled = threading.Event()
        self.actual_model = None
        self.commands = ()
        self.evidence = {}
        self.resources = resources

    def cancel(self):
        self.cancelled.set()
        if getattr(self, "workspace", None) is not None:
            self.workspace.cancel()

    def execute(self, request, files, model="Auto", *, workspace=None):
        self.workspace = workspace
        required_reads, delivery_proof = set(files), {}
        if workspace is None:
            from trading_core.evidence_delivery import prepare
            request, files, required_reads, delivery_proof = prepare(request, files)
        deadline = time.monotonic() + 110

        def check():
            if self.cancelled.is_set():
                raise ProviderError("DEGRADED", "DeadlineExceeded")
            if self.resources:
                self.resources.check_time()
            elif time.monotonic() >= deadline:
                raise ProviderError("DEGRADED", "DeadlineExceeded")
            self.guard()

        with CodexExecutor(
            files, guard=check, max_tool_calls=self.max_tool_calls, resources=self.resources
        ) as executor:
            # Empty MCP table and disabled local integrations prevent unrelated
            # user-configured integrations entering this dedicated subprocess.
            app = LineProcess(
                self.command
                + [
                    "app-server",
                    "--stdio",
                    "-c",
                    "mcp_servers={}",
                    "-c",
                    "features.hooks=false",
                    "-c",
                    "features.plugins=false",
                ]
            )
            serial = 0
            dynamic_thread = None
            dynamic_results = {}
            usage = None
            commands = []
            final = None

            def observe(msg):
                nonlocal usage, final
                method = msg.get("method")
                params = msg.get("params", {})
                if "id" in msg and method:
                    if workspace is not None and method == "item/tool/call":
                        check()
                        if (
                            params.get("threadId") != dynamic_thread
                            or not dynamic_thread
                            or params.get("namespace")
                        ):
                            raise ProviderError("UNAVAILABLE", "ProductToolSessionMismatch")
                        call_id = params.get("callId")
                        if not isinstance(call_id, str) or not call_id:
                            raise ProviderError("UNAVAILABLE", "ProductToolSessionMismatch")
                        signature = json.dumps(
                            [params.get("tool"), params.get("arguments")], sort_keys=True
                        )
                        if call_id in dynamic_results:
                            previous, reply = dynamic_results[call_id]
                            if signature != previous:
                                raise ProviderError("UNAVAILABLE", "ProductToolReplayMismatch")
                        else:
                            try:
                                text = workspace.call(params.get("tool"), params.get("arguments"))
                                reply = {
                                    "success": True,
                                    "contentItems": [{"type": "inputText", "text": text}],
                                }
                            except (ValueError, TypeError, KeyError, PermissionError, RuntimeError):
                                check()
                                reply = {
                                    "success": False,
                                    "contentItems": [
                                        {
                                            "type": "inputText",
                                            "text": "Development operation failed or was denied; inspect the supplied paths and arguments.",
                                        }
                                    ],
                                }
                            dynamic_results[call_id] = signature, reply
                        app.send({"id": msg["id"], "result": reply})
                        return False, params
                    # No approval, escalation or external tool can be granted by a model.
                    app.send(
                        {
                            "id": msg["id"],
                            "error": {
                                "code": -32601,
                                "message": "Unsupported operation under Triad read-only grant",
                            },
                        }
                    )
                if method == "thread/tokenUsage/updated":
                    usage = params["tokenUsage"]["total"]
                if method == "item/completed":
                    item = params["item"]
                    if item["type"] == "commandExecution" and item.get("exitCode") == 0:
                        commands.append(item["command"])
                    if item["type"] == "agentMessage" and item.get("phase") == "final_answer":
                        final = item["text"]
                return method == "turn/completed", params

            def call(method, params):
                nonlocal serial
                check()
                serial += 1
                app.send({"id": serial, "method": method, "params": params})
                while True:
                    msg = app.receive(timeout=20, guard=check)
                    if msg.get("id") == serial and "method" not in msg:
                        if "error" in msg:
                            raise ProviderError("UNAVAILABLE", "CodexProtocolRejected")
                        return msg.get("result")
                    observe(msg)

            try:
                call(
                    "initialize",
                    {
                        "clientInfo": {"name": "triad", "version": "0.1"},
                        "capabilities": {"experimentalApi": True},
                    },
                )
                app.send({"method": "initialized", "params": {}})
                call(
                    "environment/add",
                    {
                        "environmentId": executor.environment_id,
                        "execServerUrl": executor.url,
                        "connectTimeoutMs": 10000,
                    },
                )
                info = call("environment/info", {"environmentId": executor.environment_id})
                if info.get("cwd") != "file:///workspace":
                    raise ProviderError("UNAVAILABLE", "ExecutorEnvironmentMismatch")
                models = call("model/list", {"includeHidden": False})["data"]
                if model == "Auto":
                    model = next(m["id"] for m in models if m.get("isDefault"))
                if model not in {m["id"] for m in models}:
                    raise ProviderError("UNAVAILABLE", "CodexModelUnavailable")
                configuration = {"web_search": "disabled", "mcp_servers": {}}
                for name in (
                    "apps",
                    "plugins",
                    "multi_agent",
                    "browser_use",
                    "in_app_browser",
                    "image_generation",
                    "hooks",
                    "memories",
                    "workspace_dependencies",
                ):
                    configuration["features." + name] = False
                thread = call(
                    "thread/start",
                    {
                        "model": model,
                        "ephemeral": True,
                        "approvalPolicy": "never",
                        "sandbox": "read-only",
                        "config": configuration,
                        "environments": [
                            {
                                "environmentId": executor.environment_id,
                                "cwd": "/workspace",
                                "runtimeWorkspaceRoots": ["/workspace"],
                            }
                        ],
                        **(
                            {
                                "dynamicTools": [
                                    {**tool, "type": "function"} for tool in workspace.definitions()
                                ]
                            }
                            if workspace is not None
                            else {}
                        ),
                        "developerInstructions": (
                            "Use the supplied dynamic development tools to inspect, edit and test product files. "
                            "Tools operate in an isolated workspace. Use run_command for shell and tests. "
                            "Built-in shell/environment tools have no product workspace. Return the requested JSON. "
                            "Keep files_changed, analysis_artifacts, commands_executed, claims and tests_run empty; "
                            "Core exports exact observed changes and tool evidence. "
                            if workspace is not None
                            else "Triad grants read-only access to the supplied files. "
                            "Use cat FILENAME through the remote shell to inspect them. Other commands "
                            "are denied. Never request another environment or tool. Return the requested "
                            "JSON result. Leave commands_executed and claims empty; the host records evidence."
                        ),
                    },
                )
                self.actual_model = thread["model"]
                dynamic_thread = thread["thread"]["id"]
                prompt = request.model_dump_json(exclude={"required_output_schema"})
                call(
                    "turn/start",
                    {
                        "threadId": thread["thread"]["id"],
                        "input": [{"type": "text", "text": prompt}],
                        "effort": "low",
                        "outputSchema": strict_schema(request.required_output_schema),
                        "sandboxPolicy": {"type": "externalSandbox", "networkAccess": "restricted"},
                    },
                )
                while True:
                    done, params = observe(app.receive(timeout=None, guard=check))
                    if done:
                        if params["turn"]["status"] != "completed":
                            raise ProviderError("DEGRADED", "CodexTurnFailed")
                        break
                if final is None or usage is None:
                    raise ProviderError("DEGRADED", "CodexExecutionEvidenceMissing")
                result = AgentRunResult.model_validate_json(final)
                if result.commands_executed or result.files_changed or result.permission_requests:
                    raise ProviderError("DEGRADED", "ReadOnlyResultViolation")
                self.evidence = {
                    "methods": executor.methods,
                    "denials": executor.denials,
                    "protocol_errors": executor.responses,
                    "commands": commands,
                    "input_tokens": usage["inputTokens"],
                    "output_tokens": usage["outputTokens"],
                }
                observed = {path for r in executor.requests for path in r["params"]["argv"][2:]}
                if files and (
                    not required_reads <= observed or len(commands) != len(executor.requests)
                ):
                    raise ProviderError("DEGRADED", "NativeReadEvidenceMissing")
                self.commands = tuple(commands)
                self.evidence = {
                    "boundary": "DOCKER_REMOTE_EXECUTOR_READ_ONLY",
                    "evidence_delivery": delivery_proof,
                    "methods": executor.methods,
                    "denied_operations": executor.denials,
                    "commands": commands,
                    "model": self.actual_model,
                    "input_tokens": usage["inputTokens"],
                    "output_tokens": usage["outputTokens"],
                    "executed_argv": [r["params"]["argv"] for r in executor.requests],
                }
                if workspace is not None:
                    if (
                        result.analysis_artifacts
                        or result.tests_run
                        or result.actions_taken
                        or result.claims
                    ):
                        raise ProviderError("DEGRADED", "ProductToolResultViolation")
                    check()
                    self.evidence.update(
                        boundary="DOCKER_PRODUCT_WORKSPACE",
                        calls=workspace.calls,
                        denied_operations=workspace.denials,
                    )
                    result = result.model_copy(
                        update={
                            "analysis_artifacts": (
                                json.dumps(
                                    {
                                        "files": [
                                            c.model_dump(mode="json") for c in workspace.changes()
                                        ]
                                    }
                                ),
                            )
                        }
                    )
                return result, usage["inputTokens"], usage["outputTokens"]
            finally:
                app.close()
