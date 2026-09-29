from trading_core.resources import resource

"""Vendor status adapters. Unverified native isolation fails closed before inference."""

import json
from pathlib import Path

from trading_core.contracts import ProviderHealth
from trading_core.providers.contracts import SPECS
from trading_core.providers.process import ManagedProcess
from trading_core.runtime import HttpProvider, ProviderError
from trading_core.settings import ROOT
from trading_core.work import now


def classify_failure(text):
    """Normalize provider failures without conflating install, auth, quota, and availability."""
    lower = text.lower()
    for words, code in [
        (("usage limit", "quota exceeded", "limit reached", "quota exhausted"), "QUOTA_EXHAUSTED"),
        (("rate limit", "429"), "RATE_LIMITED"),
        (("expired", "not logged in", "login required", "not authenticated"), "NOT_AUTHENTICATED"),
        (("unauthorized", "401", "invalid api key"), "NOT_AUTHENTICATED"),
        (("not found", "no such file", "is not recognized"), "NOT_FOUND"),
        (("version mismatch", "unsupported version"), "VERSION_MISMATCH"),
    ]:
        if any(word in lower for word in words):
            return code
    return "ERROR"


class BaseTransport:
    def __init__(self, transport_id, control):
        self.transport_id = transport_id
        self.control = control
        self.spec = SPECS[transport_id]
        self.agent_id = self.agent = self.spec["agent"]
        self.provider = self.spec["provider"]
        self.transport_type = self.spec["type"]
        settings = getattr(
            getattr(getattr(control, "ledger", None), "store", None), "settings", None
        )
        self.model = control.policy(self.agent).models.get(
            transport_id,
            getattr(settings, "ollama_model", "qwen3:4b") if transport_id == "ollama" else "Auto",
        )
        self.actual_model = None

    def install_status(self):
        return self.detect()

    def provider_metadata(self):
        return {"agent": self.agent, "provider": self.provider, "model": self.model, "mode": "REAL"}

    def provenance(self):
        return {
            "transport": self.transport_id,
            "billing_source": self.billing_source(),
            "requested_model": self.model,
            "actual_model": self.actual_model,
            "runtime_identity": getattr(self, "verified_runtime_identity", None),
        }

    def identity_data(self):
        from trading_core.providers.discovery import runtime_identity

        if self.transport_type == "CLI":
            self.assert_identity()
            return runtime_identity(self.detect(), self.transport_id)
        if self.transport_type == "LOCAL":
            adapter = self.adapter()
            tags = self.list_models()
            digest = next(
                (m.get("digest") for m in tags.get("installed", []) if m.get("name") == self.model),
                None,
            )
            version = adapter.transport("/api/version").get("version")
            if not digest or not version:
                raise ProviderError("UNAVAILABLE", "LocalIdentityUnavailable")
            return {"endpoint": adapter.base, "local_version": version, "model_digest": digest}
        return None

    def usage(self):
        return [
            r
            for r in self.control.ledger.records("Usage", 1000)
            if r.get("transport") == self.transport_id
        ]

    def supported_capabilities(self):
        return ("SUPPORT",) if self.agent == "LOCAL_QWEN" else ("PROPOSE", "IMPLEMENT", "REVIEW")

    def cancel(self):
        pass


class CLITransport(BaseTransport):
    def __init__(self, transport_id, control):
        super().__init__(transport_id, control)
        self.runner = ManagedProcess()

    def cli_ready(self):
        """Pinned executable + exact version + subscription authentication; no inference."""
        detected = self.detect()
        if detected.get("install_status") != "INSTALLED" or detected.get(
            "compatibility_status"
        ) not in {"VERIFIED", "CANDIDATE"}:
            return False
        return self.authentication_status().get("auth_state") == "AUTHENTICATED"

    def readonly_ready(self):
        from trading_core.providers.codex_executor import TAG, VERSION
        from trading_core.providers.isolation import OfflineSandbox

        if hasattr(self, "_readonly_ready"):
            return self._readonly_ready
        self._readonly_ready = False
        if not self.command():
            return False
        self.assert_identity()
        try:
            if self.agent == "CODEX":
                image_version = OfflineSandbox._docker(
                    [
                        "image",
                        "inspect",
                        TAG,
                        "--format",
                        '{{index .Config.Labels "triad.executor.version"}}',
                    ]
                )
                self._readonly_ready = image_version == VERSION
            else:
                self._readonly_ready = OfflineSandbox.available()
        except (OSError, RuntimeError):
            pass
        return self._readonly_ready

    def command(self):
        # An adapter instance keeps one resolved installation for its whole operation.
        if not hasattr(self, "_resolved_command"):
            self.detect()
        return self._resolved_command

    def detect(self):
        from trading_core.providers.discovery import candidates, compatible, identity

        if hasattr(self, "_detection"):
            return dict(self._detection)
        data = {
            "transport": self.transport_id,
            "detected_at": now().isoformat(),
            "cli_name": self.spec["cli"],
            "executable": None,
            "cli_version": None,
            "minimum_supported_version": "Isolated protocol compatibility required",
            "compatibility_status": "NOT_VERIFIED",
            "install_status": "NOT_FOUND",
            "installation_instructions": self.spec["docs"],
            "discovery_failures": [],
        }
        self._resolved_command = None
        for command in candidates(self.spec["cli"]):
            try:
                result = ManagedProcess().run(command + ["--version"], cwd=ROOT)
                version = result.stdout.strip()[:200]
                if result.exit_code != 0 or result.status != "EXITED":
                    reason = "Executable did not respond"
                elif not compatible(self.agent, version):
                    reason = "Unsupported protocol family"
                else:
                    self._resolved_command = command
                    self._launch_identity = identity(command)
                    data.update(
                        executable=command,
                        cli_version=version,
                        executable_identity=self._launch_identity,
                        install_status="INSTALLED",
                        compatibility_status="CANDIDATE",
                    )
                    break
            except (OSError, RuntimeError):
                reason = "Executable unavailable"
            data["discovery_failures"].append({"command": command, "reason": reason})
        if not self._resolved_command and data["discovery_failures"]:
            data.update(install_status="UNAVAILABLE", compatibility_status="VERSION_MISMATCH")
        self._detection = data
        return dict(data)

    def assert_identity(self):
        from trading_core.providers.discovery import identity

        command = self.command()
        if not command:
            raise ProviderError("UNAVAILABLE", "OuterBoundaryUnavailable")
        if identity(command) != self._launch_identity:
            raise ProviderError("UNAVAILABLE", "ExecutableChangedDuringOperation")

    def authentication_status(self):
        command = self.command()
        if not command:
            return {"auth_state": "NOT_FOUND", "billing_source": "UNKNOWN"}
        self.assert_identity()
        if self.agent == "GROK":
            from trading_core.providers.native_agents import grok_authentication

            try:
                return grok_authentication(command)
            except (OSError, RuntimeError, TimeoutError, ProviderError):
                return {
                    "auth_state": "UNKNOWN",
                    "billing_source": "UNKNOWN",
                    "auth_detail": "Triad could not verify Grok's subscription session. "
                    "A successful browser login does not need to be repeated automatically.",
                }
        args = ["login", "status"] if self.agent == "CODEX" else ["auth", "status", "--json"]
        result = ManagedProcess().run(command + args, cwd=ROOT)
        auth = {"auth_state": "NOT_AUTHENTICATED", "billing_source": "UNKNOWN"}
        if result.exit_code != 0 or result.status != "EXITED":
            return auth
        if self.agent == "CODEX":
            if "logged in using chatgpt" in (result.stdout + result.stderr).lower():
                auth.update(auth_state="AUTHENTICATED", billing_source="SUBSCRIPTION")
        else:
            try:
                data = json.loads(result.stdout)
                if data.get("loggedIn") and data.get("authMethod") == "claude.ai":
                    auth.update(auth_state="AUTHENTICATED", billing_source="SUBSCRIPTION")
            except (ValueError, TypeError):
                auth["auth_state"] = "AUTH_FAILED"
        return auth

    def authenticate(self):
        return self._auth_action(False)

    def logout(self):
        return self._auth_action(True)

    def _auth_action(self, logout):
        command = self.command()
        detected = self.detect()
        if detected.get("compatibility_status") == "VERSION_MISMATCH":
            raise ValueError("CLI version mismatch: supported protocol verification is required")
        if not command or detected["install_status"] != "INSTALLED":
            raise ValueError(
                "Install the supported CLI with tools/install_provider_clis.ps1 before signing in"
            )
        if detected.get("compatibility_status") not in {"VERIFIED", "CANDIDATE"}:
            raise ValueError(
                "CLI version mismatch; install the pinned supported version before signing in"
            )
        args = (["auth"] if self.agent == "CLAUDE" else []) + ["logout" if logout else "login"]
        if not logout and self.agent == "CLAUDE":
            args.append("--claudeai")
        if not logout and self.agent == "GROK":
            args.append("--oauth")
        # No model prompt, credential parsing, copied session files, or API key input.
        result = self.runner.run(command + args, cwd=ROOT, timeout=180)
        return {
            "exit_code": result.exit_code,
            "status": result.status,
            "success": result.exit_code == 0 and result.status == "EXITED",
        }

    def health_check(self):
        detected = self.detect()
        if detected["install_status"] == "NOT_FOUND":
            return ProviderHealth(
                agent=self.agent,
                provider=self.provider,
                model=self.model,
                status="NOT_FOUND",
                error_class="NOT_FOUND",
            )
        if detected.get("compatibility_status") == "VERSION_MISMATCH":
            return ProviderHealth(
                agent=self.agent,
                provider=self.provider,
                model=self.model,
                status="VERSION_MISMATCH",
                error_class="VERSION_MISMATCH",
            )

        if detected.get("install_status") != "INSTALLED" or detected.get(
            "compatibility_status"
        ) not in {"VERIFIED", "CANDIDATE"}:
            return ProviderHealth(
                agent=self.agent,
                provider=self.provider,
                model=self.model,
                status="UNAVAILABLE",
                error_class="CLICompatibilityUnverified",
            )
        auth = self.authentication_status()
        if auth["auth_state"] == "NOT_AUTHENTICATED":
            return ProviderHealth(
                agent=self.agent,
                provider=self.provider,
                model=self.model,
                status="NOT_AUTHENTICATED",
                error_class="NOT_AUTHENTICATED",
            )
        if auth["auth_state"] == "UNKNOWN":
            return ProviderHealth(
                agent=self.agent,
                provider=self.provider,
                model=self.model,
                status="UNAVAILABLE",
                error_class="UNAVAILABLE",
            )
        if self.readonly_ready() and auth["auth_state"] == "AUTHENTICATED":
            return ProviderHealth(
                agent=self.agent,
                provider=self.provider,
                model=self.model,
                status="AVAILABLE",
                mode="REAL",
            )
        return ProviderHealth(
            agent=self.agent,
            provider=self.provider,
            model=self.model,
            status="UNAVAILABLE",
            error_class="UNAVAILABLE",
        )

    def list_models(self):
        return {
            "models": ["Auto"],
            "discovery": "NOT_SUPPORTED",
            "detail": "Explicit model IDs may be selected; actual model requires run evidence",
        }

    def billing_source(self):
        if hasattr(self, "_verified_billing_source"):
            return self._verified_billing_source
        return self.control.snapshot(self.transport_id).get("billing_source", "UNKNOWN")

    def capabilities(self):
        if self.agent in {"CLAUDE", "GROK"} and self.readonly_ready():
            return {
                "native": ["file_read", "file_proposals", "structured_output"],
                "granted": ["read_supplied_files", "stage_reviewed_text_proposals"],
                "outer_boundary": "DOCKER_OFFLINE_TOOLS",
                "execution_blocker": None,
                "limitation": "Explicit text snapshots and reviewed proposals only; no host shell, Git or network tools",
            }
        if self.agent == "CODEX" and self.readonly_ready():
            return {
                "native": ["file_read", "structured_output"],
                "granted": ["read_supplied_files"],
                "outer_boundary": "DOCKER_REMOTE_EXECUTOR_READ_ONLY",
                "execution_blocker": None,
                "limitation": "Read-only reviews only; shell is restricted to cat on supplied files",
            }
        return {
            "native": [],
            "granted": [],
            "outer_boundary": "NOT_IMPLEMENTED",
            "execution_blocker": "OuterBoundaryUnavailable",
        }

    def estimate_cost(self, input_tokens, output_tokens):
        return 0.0  # reservation only; subscription monetary usage remains null

    def execute(self, request):
        self.assert_identity()
        if self.agent in {"CLAUDE", "GROK"}:
            return self._execute_isolated(request)
        if (
            self.agent != "CODEX"
            or getattr(request, "role", None) != "REVIEW"
            or not self.readonly_ready()
        ):
            raise ProviderError("UNAVAILABLE", "OuterBoundaryUnavailable")
        from trading_core.gateway import ToolGateway
        from trading_core.providers.codex_executor import CodexReadOnlyRun

        work = self.control.ledger.store.get(request.work_item_id)
        if request.execution_permissions != ("read",) or set(request.allowed_tools) - {"read_file"}:
            raise PermissionError("Codex currently supports read-only review only")
        resources = getattr(self, "resources", None)
        gateway = ToolGateway(work, resources=resources)
        files = {}
        # Exact file grants only; never recursively expose a host directory.
        if "read_file" in request.allowed_tools:
            for path in request.allowed_paths:
                if (ROOT / path).is_file():
                    files[path] = gateway.read(path)
        guard = lambda: self.control.ledger.guard(
            request.agent_id, request.work_item_id, request.control_epoch
        )
        self.native_run = CodexReadOnlyRun(
            self.command(), guard, work.compute_budget.max_tool_calls, resources=resources
        )
        try:
            result = self.native_run.execute(request, files, self.model)
            self.actual_model = self.native_run.actual_model
            return result
        finally:
            self.control.ledger.event(
                "native_executor_evidence",
                request.work_item_id,
                run_id=request.run_id,
                source_hashes=gateway.evidence,
                **self.native_run.evidence,
            )

    def _execute_isolated(self, request):
        from trading_core.gateway import ToolGateway
        from trading_core.providers.native_agents import ClaudeRun, GrokRun

        if not self.readonly_ready() or request.role not in {"REVIEW", "PROPOSE", "IMPLEMENT"}:
            raise ProviderError("UNAVAILABLE", "OuterBoundaryUnavailable")
        work = self.control.ledger.store.get(request.work_item_id)
        resources = getattr(self, "resources", None)
        gateway = ToolGateway(work, resources=resources)
        files, writable, engineering = {}, (), None
        if request.role == "REVIEW":
            if request.execution_permissions != ("read",) or set(request.allowed_tools) - {
                "read_file"
            }:
                raise PermissionError("Review must be read-only")
            if "read_file" in request.allowed_tools:
                for path in request.allowed_paths:
                    # Exact file grants only. No recursive directory snapshots.
                    if (ROOT / path).is_file():
                        files[path] = gateway.read(path)
        else:
            if request.execution_permissions == ("write_code",):
                from trading_core.engineering import grant_for

                engineering = grant_for(self.control.ledger, request)
                for path in engineering.writable_files:
                    if (ROOT / path).is_file():
                        files[path] = gateway.read(path)
                writable = tuple(
                    sorted(
                        {str(Path(p).parent).replace("\\", "/") for p in engineering.writable_files}
                    )
                )
            elif request.execution_permissions != ("write_docs",):
                raise PermissionError("Implementation supports reviewed text proposals only")
            if set(request.allowed_tools) != {"propose_file_change"}:
                raise PermissionError("Only staging tools are granted")
            limits = self.control.ledger.guard(request.agent_id)["limits"]
            if not engineering and not set(request.allowed_paths) <= set(
                limits["allowed_directories"]
            ):
                raise PermissionError("Proposal directories must be explicitly governed")
            if not engineering:
                writable = request.allowed_paths
        guard = lambda: self.control.ledger.guard(
            request.agent_id, request.work_item_id, request.control_epoch
        )
        runner = ClaudeRun if self.agent == "CLAUDE" else GrokRun
        self.native_run = runner(
            self.command(), guard, work.compute_budget.max_tool_calls, resources=resources
        )
        try:
            if engineering:
                result = self.native_run.execute(
                    request, files, self.model, writable, exact_files=engineering.writable_files
                )
            else:
                result = self.native_run.execute(request, files, self.model, writable)
            self.actual_model = self.native_run.actual_model
            return result
        finally:
            self.control.ledger.event(
                "native_executor_evidence",
                request.work_item_id,
                run_id=request.run_id,
                source_hashes=gateway.evidence,
                **self.native_run.evidence,
            )

    def cancel(self):
        self.runner.cancel()
        if hasattr(self, "native_run"):
            self.native_run.cancel()


class HTTPTransport(BaseTransport):
    def adapter(self):
        config = json.loads(resource("config/core/runtime.json").read_text())["providers"][
            self.agent
        ]
        values = {config["model_env"]: "" if self.model == "Auto" else self.model}
        if self.transport_type == "API":
            p = self.control.policy(self.agent)
            values.update(
                {
                    config["key_env"]: self.control.secrets.get_secret(self.transport_id) or "",
                    config["input_rate_env"]: str(p.input_price_per_million),
                    config["output_rate_env"]: str(p.output_price_per_million),
                }
            )
        else:
            # Local endpoint is host-owned. UI cannot redirect keys or prompts.
            from urllib.parse import urlsplit

            settings = getattr(
                getattr(getattr(self.control, "ledger", None), "store", None), "settings", None
            )
            endpoint = getattr(settings, "ollama_url", "http://127.0.0.1:11434")
            parsed = urlsplit(endpoint)
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ProviderError("UNAVAILABLE", "LocalEndpointMustBeLoopback")
            values["OLLAMA_URL"] = endpoint
        return HttpProvider(self.agent, config, values)

    def detect(self):
        configured = self.transport_type == "LOCAL" or self.control.secrets.has_secret(
            self.transport_id
        )
        return {
            "transport": self.transport_id,
            "install_status": "NOT_APPLICABLE",
            "configuration": "CONFIGURED" if configured else "NOT_CONFIGURED",
            "auth_state": "NOT_AUTHENTICATED",
            "billing_source": self.billing_source(),
            "detected_at": now().isoformat(),
        }

    def authenticate(self):
        raise ValueError("Use API credential control; Ollama needs no provider credential")

    def logout(self):
        if self.transport_type == "API":
            self.control.secrets.delete_secret(self.transport_id)

    def health_check(self):
        return self.adapter().health_check()

    def list_models(self):
        adapter = self.adapter()
        if self.transport_type == "LOCAL":
            data = adapter.transport("/api/tags")
            return {
                "models": [m["name"] for m in data.get("models", [])],
                "endpoint": adapter.base,
                "installed": data.get("models", []),
            }
        if not adapter.key:
            return {"models": [], "configuration": "NOT_CONFIGURED"}
        data = adapter.transport("/models")
        return {"models": [m["id"] for m in data.get("data", [])]}

    def billing_source(self):
        return "LOCAL" if self.transport_type == "LOCAL" else "API"

    def capabilities(self):
        return {
            "native": ["structured_output"],
            "granted": ["structured_output"],
            "outer_boundary": "HOST_VALIDATED_DATA_ONLY",
            "shell": False,
        }

    def estimate_cost(self, input_tokens, output_tokens):
        return self.adapter().estimate_cost(input_tokens, output_tokens)

    def execute(self, request):
        adapter = self.adapter()
        self.active_adapter = adapter
        adapter.resources = getattr(self, "resources", None)
        try:
            result = adapter.execute(request)
            return result
        finally:
            self.actual_model = getattr(adapter, "actual_model", None)
            self.reasoning_tokens = getattr(adapter, "reasoning_tokens", None)
            self.evidence = getattr(adapter, "evidence", {})
            self.active_adapter = None

    def cancel(self):
        active = getattr(self, "active_adapter", None)
        if active:
            active.cancel()
