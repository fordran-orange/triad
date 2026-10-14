"""Product scope and alternate Git entry points fail closed before side effects."""

import pytest
from trading_core.git_tools import GitChanges
from trading_core.governance import (
    assert_product_merge_allowed,
    is_protected_core_path,
    normalize_repo_path,
)

pytestmark = pytest.mark.core


@pytest.mark.parametrize(
    "path",
    [
        "app/trading_core/intelligence/quality.py",
        "app/trading_core/runtime.py",
        "app/trading_core/engineering.py",
        "app/trading_core/providers/autonomous_cli.py",
        "APP/TRADING_CORE/ledger.py",
        "app/platform_host/api.py",
        "app/products/aegis/server.py",
        "app/products/p2p/server.py",
        "app/products/__init__.py",
        "app/other_product/__init__.py",
        "products/aegis/docs/private.md",
        "products/other-product/charter.json",
        "config/triad/product.json",
        "control-plane/policy.json",
        "infrastructure/postgres/003_autonomy.sql",
        "databases/migration.sql",
        "data/research/manifest.json",
        "tools/start_backend.ps1",
        "docs/vault/02_Journal/generated/record.md",
        ".github/workflows/check.yml",
        "docs/AGENTS.md",
        "pyproject.toml",
        ".env",
    ],
)
def test_product_cannot_modify_shared_authority_private_evidence_or_other_product(path):
    assert is_protected_core_path(path)
    with pytest.raises(PermissionError, match="protected"):
        assert_product_merge_allowed([path])


@pytest.mark.parametrize(
    "path",
    [
        "../docs/escape.md",
        "docs/../app/trading_core/ledger.py",
        "/docs/file.md",
        "C:/Triad/docs/file.md",
        "C:docs/file.md",
        "\\\\server\\share\\file.md",
        "docs/file.md:stream",
        "docs/file.md.",
        "docs /file.md",
        "",
        ".",
        "\x00",
    ],
)
def test_traversal_absolute_and_windows_alias_paths_rejected(path):
    with pytest.raises(PermissionError):
        normalize_repo_path(path)


def test_normal_product_and_legacy_text_paths_remain_available():
    paths = [
        "app/products/triad/features/research_readiness.html",
        "products/triad/docs/PRODUCT_MAP.md",
        "docs/improvements/accepted.md",
        "research/proposal.md",
        "tests/test_product_fixture.py",
    ]
    assert_product_merge_allowed(paths)
    assert normalize_repo_path("./docs/improvements/accepted.md") == "docs/improvements/accepted.md"
    assert normalize_repo_path("docs\\improvements\\accepted.md") == "docs/improvements/accepted.md"


@pytest.mark.parametrize("entry", ["stage_autonomous", "commit_autonomous", "merge_autonomous"])
def test_unreviewed_git_entry_points_cannot_run_even_with_forged_metadata(entry, tmp_path):
    broker = GitChanges(tmp_path, tmp_path / "worktrees")

    def unexpected(*args, **kwargs):
        pytest.fail("Denied alternate entry point must not invoke Git")

    broker.git = unexpected
    metadata = {
        "base_commit": "a" * 40,
        "change_commit": "b" * 40,
        "review_commit": "c" * 40,
        "worktree": str(tmp_path),
        "checks": {"passed": True},
        "decision": "PASS",
    }
    args = (metadata, "CLAUDE") if entry == "commit_autonomous" else (metadata,)
    with pytest.raises(PermissionError):
        getattr(broker, entry)(*args)
