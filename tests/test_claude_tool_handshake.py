import pytest
from trading_core.providers import native_agents as native
from trading_core.runtime import ProviderError


class App:
    def __init__(self, servers):
        self.servers = iter(servers)
        self.sent = []

    def send(self, request):
        self.sent.append(request)

    def receive(self, **kwargs):
        kwargs["guard"]()
        request = self.sent[-1]
        data = {} if request["request_id"] == "initialize" else {"mcpServers": next(self.servers)}
        return {
            "type": "control_response",
            "response": {
                "request_id": request["request_id"],
                "subtype": "success",
                "response": data,
            },
        }


def server(status="connected", tools=("read_file",)):
    return [{"name": "triad", "status": status, "tools": [{"name": t} for t in tools]}]


def test_pending_then_connected_catalog(monkeypatch):
    monkeypatch.setattr(native.time, "sleep", lambda _: None)
    app = App([server("pending", ()), server("pending", ()), server()])
    native.claude_initialize(app, lambda: None, {"read_file"})
    assert [r["request_id"] for r in app.sent] == ["initialize", "mcp", "mcp-1", "mcp-2"]


@pytest.mark.parametrize(
    "catalog",
    [
        server(tools=("read_file", "shell")),
        server("failed", ()),
        server("pending", ("shell",)),
        [],
        [{"name": "other", "status": "pending"}],
    ],
)
def test_other_catalogs_fail_immediately(catalog):
    app = App([catalog])
    with pytest.raises(ProviderError, match="NativeToolCatalogMismatch"):
        native.claude_initialize(app, lambda: None, {"read_file"})
    assert len(app.sent) == 2


def test_pending_has_finite_deadline(monkeypatch):
    now = [0]
    monkeypatch.setattr(native.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(native.time, "sleep", lambda t: now.__setitem__(0, now[0] + t))
    app = App([server("pending", ())] * 100)
    with pytest.raises(ProviderError, match="ClaudeToolConnectionTimeout"):
        native.claude_initialize(app, lambda: None, {"read_file"})
    assert now[0] == 20


def test_cancel_during_pending_stops_before_another_query(monkeypatch):
    stop = [False]
    monkeypatch.setattr(native.time, "sleep", lambda _: stop.__setitem__(0, True))

    def guard():
        if stop[0]:
            raise PermissionError("cancelled")

    app = App([server("pending", ()), server()])
    with pytest.raises(PermissionError, match="cancelled"):
        native.claude_initialize(app, guard, {"read_file"})
    assert len(app.sent) == 2
