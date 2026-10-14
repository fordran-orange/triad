"""Real Git checkouts must agree with the text snapshot supplied to providers."""

import hashlib
import subprocess

import pytest
from trading_core.product_changes import ProductFileChange, ProductGit
from trading_core.product_workspace import ProductWorkspace

pytestmark = pytest.mark.core

PATH = "app/products/triad/static/product.html"
OTHER = "app/products/triad/other.py"


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args, cwd=root):
        return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@localhost")
    git("config", "core.autocrlf", "true")
    for path in (PATH, OTHER):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"first\nsecond\n")
    git("add", ".")
    git("commit", "-m", "fixture")
    broker = ProductGit((PATH, OTHER), root=root, worktrees=tmp_path / "worktrees")
    metadata = broker.isolate("fixture", "CLAUDE")
    from pathlib import Path

    target = Path(metadata["worktree"]) / PATH
    assert target.read_bytes() == b"first\r\nsecond\r\n"
    yield broker, metadata, target
    git("worktree", "remove", "--force", metadata["worktree"])


@pytest.mark.parametrize("operation", ["WRITE", "DELETE"])
def test_workspace_patch_applies_to_git_crlf_checkout(checkout, operation):
    broker, metadata, target = checkout
    workspace = ProductWorkspace(
        {PATH: target.read_text(encoding="utf-8")}, image="sha256:" + "1" * 64, guard=lambda: None
    )
    if operation == "DELETE":
        workspace.call("delete_file", {"path": PATH})
    else:
        workspace.call("write_file", {"path": PATH, "content": "changed\n"})
    check = broker.apply(metadata, workspace.changes())
    assert check["passed"] and check["files"] == [PATH]
    assert (target.read_bytes() == b"changed\n") if operation == "WRITE" else not target.exists()


def test_legacy_raw_hash_still_accepted(checkout):
    broker, metadata, target = checkout
    change = ProductFileChange(
        path=PATH,
        content="changed\n",
        original_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
    )
    assert broker.apply(metadata, [change])["passed"]


@pytest.mark.parametrize(
    "changed", [b"first \r\nsecond\r\n", b"FIRST\r\nsecond\r\n", b"first\r\nsecond"]
)
def test_substantive_changes_rejected_without_partial_writes(checkout, changed):
    broker, metadata, target = checkout
    from pathlib import Path

    other = Path(metadata["worktree"]) / OTHER
    before = other.read_bytes()
    changes = [
        ProductFileChange(
            path=OTHER,
            content="must not write\n",
            original_sha256=hashlib.sha256(before).hexdigest(),
        ),
        ProductFileChange(
            path=PATH,
            content="replacement\n",
            original_sha256=hashlib.sha256(b"first\nsecond\n").hexdigest(),
        ),
    ]
    target.write_bytes(changed)
    with pytest.raises(PermissionError, match="source changed"):
        broker.apply(metadata, changes)
    assert other.read_bytes() == before
    assert target.read_bytes() == changed


def test_missing_and_empty_files_are_distinct(checkout):
    broker, metadata, target = checkout
    target.write_bytes(b"")
    with pytest.raises(PermissionError, match="source changed"):
        broker.apply(metadata, [ProductFileChange(path=PATH, content="new", original_sha256=None)])
    target.unlink()
    with pytest.raises(PermissionError, match="source changed"):
        broker.apply(
            metadata,
            [
                ProductFileChange(
                    path=PATH, content="new", original_sha256=hashlib.sha256(b"").hexdigest()
                )
            ],
        )
