import hashlib
import subprocess

import pytest
from pydantic import ValidationError
from trading_core.product_changes import ProductFileChange, ProductGit

OLD = "app/products/triad/old.py"
NEW = "app/products/triad/new.py"


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    target = tmp_path / OLD
    target.parent.mkdir(parents=True)
    target.write_text("value = 1\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "baseline")
    return tmp_path, {"worktree": str(tmp_path), "base_commit": git("rev-parse", "HEAD")}, git


def test_rename_records_both_paths_and_deletion(repo):
    root, metadata, git = repo
    original = (root / OLD).read_bytes()
    broker = ProductGit((OLD, NEW), root=root)
    changes = (
        ProductFileChange(
            path=OLD, operation="DELETE", original_sha256=hashlib.sha256(original).hexdigest()
        ),
        ProductFileChange(path=NEW, content=original.decode()),
    )
    proof = broker.apply(metadata, changes)
    assert set(proof["files"]) == {OLD, NEW}
    assert proof["sources"][OLD] is None
    assert proof["hashes"][OLD] is None
    assert not (root / OLD).exists()
    assert (root / NEW).read_bytes() == original
    git("commit", "-m", "rename")
    assert broker.verify(metadata)["hashes"] == proof["hashes"]


def test_stale_delete_does_not_apply_any_part_of_patch(repo):
    root, metadata, _ = repo
    broker = ProductGit((OLD, NEW), root=root)
    with pytest.raises(PermissionError, match="changed"):
        broker.apply(
            metadata,
            (
                ProductFileChange(path=NEW, content="new"),
                ProductFileChange(path=OLD, operation="DELETE", original_sha256="0" * 64),
            ),
        )
    assert (root / OLD).is_file()
    assert not (root / NEW).exists()


@pytest.mark.parametrize(
    "values",
    [
        {"operation": "DELETE"},
        {"operation": "DELETE", "original_sha256": "0" * 64, "content": "not empty"},
        {"operation": "WRITE"},
        {"content": "x", "original_sha256": "bad"},
    ],
)
def test_invalid_operations_rejected(values):
    with pytest.raises(ValidationError):
        ProductFileChange(path=OLD, **values)


def test_protected_deletion_rejected():
    with pytest.raises(PermissionError):
        ProductFileChange(
            path="app/products/triad/server.py", operation="DELETE", original_sha256="0" * 64
        )
