"""No-inference checks: vendor auth, protocol/tool catalogs, real offline file tools.

Does not create provider proofs, spend model tokens, modify budgets or read auth files.
"""

import tempfile

from triad.day5a.bounded_tools import BoundedTools, ToolServer
from triad.day5a.codex_executor import LineProcess
from triad.day5a.control import ProviderControl
from triad.day5a.native_agents import (
    GrokSession,
    claude_arguments,
    claude_initialize,
    grok_preflight,
)


def main():
    control = ProviderControl()
    for tid in ("claude_code_cli", "grok_build_cli"):
        adapter = control.transport(tid)
        if not adapter.readonly_ready():
            raise RuntimeError("Unsupported version or Docker unavailable: " + tid)
        auth = adapter.authentication_status()
        if (
            auth.get("auth_state") != "AUTHENTICATED"
            or auth.get("billing_source") != "SUBSCRIPTION"
        ):
            raise RuntimeError("Subscription login not verified: " + tid)
        broker = BoundedTools({"README.md": "# Triad fixture\n"}, writable=("docs/improvements",))
        with tempfile.TemporaryDirectory(prefix="triad-native-check-") as cwd:
            if adapter.agent == "CLAUDE":
                with ToolServer(broker) as server:
                    app = LineProcess(
                        adapter.command() + claude_arguments(server.url, True), cwd=cwd
                    )
                    try:
                        claude_initialize(
                            app, lambda: None, {t["name"] for t in broker.definitions()}
                        )
                    finally:
                        app.close()
            else:
                grok_preflight(adapter.command(), cwd)
                session = GrokSession(adapter.command(), cwd, broker=broker)
                try:
                    session.authenticate()
                    session.start()
                    assert set(session.tools) == {"read_file", "search_replace"}
                finally:
                    session.close()
        assert broker.call("read_file", {"path": "README.md"}) == "# Triad fixture\n"
        broker.call(
            "propose_file_change",
            {"path": "docs/improvements/check.md", "content": "Fixture proposal\n"},
        )
        assert broker.changes()[0].content == "Fixture proposal\n"
        print(
            tid
            + ": subscription auth, protocol, tool catalog, offline read/proposal PASS (no inference)"
        )


if __name__ == "__main__":
    main()
