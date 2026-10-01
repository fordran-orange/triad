import hashlib
import json
from types import SimpleNamespace

import pytest
from trading_core.product_workspace import ProductWorkspace

PATH = "app/products/triad/example.py"
NEW = "app/products/triad/new.py"
IMAGE = "sha256:" + "1" * 64


def workspace():
    return ProductWorkspace({PATH: "old\n"}, image=IMAGE, guard=lambda: None)


def test_edit_rename_delete_use_original_host_hash():
    w = workspace()
    w.call("write_file", {"path": PATH, "content": "new\n"})
    w.call("rename_file", {"path": PATH, "destination": NEW})
    assert json.loads(w.call("list_files", {})) == [NEW]
    changes = {c.path: c for c in w.changes()}
    assert changes[PATH].operation == "DELETE"
    assert changes[PATH].original_sha256 == hashlib.sha256(b"old\n").hexdigest()
    assert changes[NEW].content == "new\n"
    assert changes[NEW].original_sha256 is None
    w.call("delete_file", {"path": NEW})
    assert len(w.changes()) == 1


@pytest.mark.parametrize(
    "name,args",
    [
        ("write_file", {"path": "app/products/triad/server.py", "content": "bad"}),
        ("rename_file", {"path": PATH, "destination": "app/trading_core/control.py"}),
        ("delete_file", {"path": "../secret"}),
        ("write_file", {"path": PATH.upper(), "content": "alias"}),
        ("run_command", {"argv": ["echo", "ok"], "env": {"KEY": "secret"}}),
        ("grant", {}),
    ],
)
def test_denied_operations_are_atomic(name, args):
    w = workspace()
    with pytest.raises((PermissionError, ValueError)):
        w.call(name, args)
    assert w.files == {PATH: "old\n"}


def test_failed_test_feedback_preserves_safe_edits(monkeypatch):
    w = workspace()

    def run(argv, files, **kwargs):
        assert kwargs["export_failed"]
        assert kwargs["guard"] == w.guard
        return SimpleNamespace(
            files={PATH: "fixed\n"},
            deleted=(),
            status="EXITED",
            exit_code=1,
            image=IMAGE,
            boundary="DOCKER_OFFLINE_TOOLS",
            stdout="",
            stderr="assert failed",
        )

    monkeypatch.setattr(w.sandbox, "run", run)
    result = json.loads(w.call("run_command", {"argv": ["python", "test.py"]}))
    assert result["exit_code"] == 1
    assert w.files[PATH] == "fixed\n"
    assert w.calls[-1]["exit_code"] == 1


def test_command_cannot_export_protected_paths(monkeypatch):
    w = workspace()
    monkeypatch.setattr(
        w.sandbox,
        "run",
        lambda *a, **k: SimpleNamespace(
            files={PATH: "changed", "app/products/triad/server.py": "bad"},
            deleted=(),
            status="EXITED",
            exit_code=0,
            image=IMAGE,
            boundary="DOCKER_OFFLINE_TOOLS",
            stdout="",
            stderr="",
        ),
    )
    with pytest.raises(PermissionError):
        w.call("run_command", {"argv": ["python", "script.py"]})
    assert w.files == {PATH: "old\n"}


def test_cancellation_before_commit_preserves_snapshot():
    w = workspace()
    checks = []

    def guard():
        checks.append(True)
        if len(checks) > 1:
            raise PermissionError("cancelled")

    w.guard = guard
    with pytest.raises(PermissionError):
        w.call("write_file", {"path": PATH, "content": "changed"})
    assert w.files == {PATH: "old\n"}


@pytest.mark.integration
def test_real_shell_edit_then_failed_test_is_retained():
    # Explicit opt-in avoids concurrent Docker cleanup in unrelated suites.
    import os

    if os.getenv("TRIAD_WORKSPACE_INTEGRATION") != "1":
        pytest.skip("Enable isolated workspace acceptance explicitly")
    from trading_core.product_changes import reviewed_test_image

    w = ProductWorkspace({PATH: "old\n"}, image=reviewed_test_image(), guard=lambda: None)
    result = json.loads(
        w.call(
            "run_command",
            {
                "argv": [
                    "python",
                    "-c",
                    "import os,pathlib; assert os.getuid()==10001; assert not pathlib.Path('/var/run/docker.sock').exists(); pathlib.Path('app/products/triad/example.py').write_text('new\\n'); raise SystemExit(3)",
                ]
            },
        )
    )
    assert result["exit_code"] == 3
    assert w.files[PATH] == "new\n"
