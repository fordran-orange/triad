"""Vendor status adapters. Unverified native isolation fails closed before inference."""

import json
import shutil
from pathlib import Path

from triad.day3.adapters import HttpProvider, ProviderError
from triad.day3.contracts import ProviderHealth
from triad.day5a.contracts import SPECS
from triad.day5a.process import ManagedProcess
from triad.settings import ROOT
from triad.work import now


def classify_failure(text):
    lower = text.lower()
    for words, code in [
        (("usage limit", "quota exceeded", "limit reached"), "USAGE_LIMIT_REACHED"),
        (("rate limit", "429"), "RATE_LIMITED"),
        (("expired",), "AUTH_EXPIRED"),
        (("unauthorized", "401", "invalid api key"), "AUTH_FAILED"),
        (("not logged in", "login required", "not authenticated"), "AUTH_REQUIRED"),
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
        self.model = control.policy(self.agent).models.get(
            transport_id, "qwen3:4b" if transport_id == "ollama" else "Auto"
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
        }

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

    def command(self):
        name = self.spec["cli"]
        found = shutil.which(name + ".exe") or shutil.which(name)
        if found and Path(found).suffix.lower() == ".exe":
            return [found]
        # npm scripts are invoked through Node, never cmd.exe / shell=True.
        prefix = ROOT / "data/temp/provider-cli/node_modules"
        if name == "claude":
            native = prefix / "@anthropic-ai/claude-code/bin/claude.exe"
            if native.is_file():
                return [str(native)]
            script = prefix / "@anthropic-ai/claude-code/cli.js"
        elif name == "grok":
            script = prefix / "@xai-official/grok/bin/grok"
        else:
            return None
        if script.is_file() and (node := shutil.which("node.exe")):
            return [node, str(script)]
        return None

    def detect(self):
        command = self.command()
        data = {
            "transport": self.transport_id,
            "detected_at": now().isoformat(),
            "cli_name": self.spec["cli"],
            "executable": command,
            "cli_version": None,
            "minimum_supported_version": None,
            "compatibility_status": "NOT_VERIFIED",
            "install_status": "NOT_INSTALLED",
            "installation_instructions": self.spec["docs"],
        }
        if command:
            try:
                result = ManagedProcess().run(command + ["--version"], cwd=ROOT)
                if result.exit_code == 0 and result.status == "EXITED":
                    data.update(install_status="INSTALLED", cli_version=result.stdout.strip()[:200])
                else:
                    data["install_status"] = "DETECTION_FAILED"
            except (OSError, RuntimeError):
                data["install_status"] = "DETECTION_FAILED"
        return data

    def authentication_status(self):
        command = self.command()
        if not command:
            return {"auth_state": "NOT_AUTHENTICATED", "billing_source": "UNKNOWN"}
        if self.agent == "GROK":
            return {
                "auth_state": "NOT_AUTHENTICATED",
                "billing_source": "UNKNOWN",
                "auth_detail": "No verified noninteractive auth-status adapter yet",
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
        if not command:
            raise ValueError("CLI not installed; open installation instructions")
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
        auth = self.authentication_status()
        return ProviderHealth(
            agent=self.agent,
            provider=self.provider,
            model=self.model,
            status="UNAVAILABLE",
            error_class=(
                "OuterBoundaryUnavailable"
                if auth["auth_state"] == "AUTHENTICATED"
                else "AuthenticationRequired"
            ),
        )

    def list_models(self):
        return {
            "models": ["Auto"],
            "discovery": "NOT_SUPPORTED",
            "detail": "Explicit model IDs may be selected; actual model requires run evidence",
        }

    def billing_source(self):
        return self.control.snapshot(self.transport_id).get("billing_source", "UNKNOWN")

    def capabilities(self):
        return {
            "native": [
                "file_read",
                "file_write",
                "shell",
                "git",
                "web",
                "MCP",
                "structured_output",
                "tool_use",
                "worktree_support",
            ],
            "granted": [],
            "outer_boundary": "NOT_IMPLEMENTED",
            "execution_blocker": "OuterBoundaryUnavailable",
        }

    def estimate_cost(self, input_tokens, output_tokens):
        return 0.0  # reservation only; subscription monetary usage remains null

    def execute(self, request):
        # A job object/worktree is not a security boundary. Never launch an agent
        # with host credentials/files reachable while isolation is unverified.
        raise ProviderError("UNAVAILABLE", "OuterBoundaryUnavailable")

    def cancel(self):
        self.runner.cancel()


class HTTPTransport(BaseTransport):
    def adapter(self):
        config = json.loads((ROOT / "agents/day3.json").read_text())["providers"][self.agent]
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
            values["OLLAMA_URL"] = "http://127.0.0.1:11434"
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
        result = adapter.execute(request)
        self.actual_model = getattr(adapter, "actual_model", None)
        return result
