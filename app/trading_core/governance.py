"""Product merge exclusions; authority remains in Core's reviewed execution gates.

These exclusions supplement exact scope, independent QA and merge-time authority
checks. A provider working directory is never a filesystem security boundary.
"""

from pathlib import PurePosixPath

PROTECTED_CORE_PATHS = frozenset(
    {
        "agents.md",
        "pyproject.toml",
        "requirements.lock",
        "docker-compose.yml",
        ".gitignore",
        ".gitattributes",
    }
)
PROTECTED_CORE_PREFIXES = (
    "app/trading_core/",
    "app/platform_host/",
    "app/triad/",
    "app/products/aegis/",
    "app/products/p2p/",
    "products/aegis/",
    "products/p2p/",
    "config/",
    "control-plane/",
    "agents/",
    "data/",
    "databases/",
    "infrastructure/",
    "tools/",
    "docs/vault/",
    ".github/",
    ".git/",
    ".codex/",
    ".claude/",
    ".grok/",
)


def normalize_repo_path(path: str) -> str:
    if not isinstance(path, str) or not path or "\x00" in path:
        raise PermissionError("A repository-relative file path is required")
    value = path.replace("\\", "/")
    parts = value.split("/")
    if (
        value.startswith("/")
        or any(part == ".." or ":" in part for part in parts)
        or any(part and part != "." and part != part.rstrip(" .") for part in parts)
    ):
        raise PermissionError("Path escapes or aliases repository scope")
    normalized = PurePosixPath(value).as_posix()
    if normalized == ".":
        raise PermissionError("A repository-relative file path is required")
    return normalized


def is_protected_core_path(path: str) -> bool:
    value = normalize_repo_path(path).casefold()
    return (
        value in PROTECTED_CORE_PATHS
        or (value.startswith("app/") and not value.startswith("app/products/triad/"))
        or (value.startswith("products/") and not value.startswith("products/triad/"))
        or PurePosixPath(value).name == "agents.md"
        or any(part.startswith(".") for part in PurePosixPath(value).parts)
        or any(
            value == prefix.rstrip("/") or value.startswith(prefix)
            for prefix in PROTECTED_CORE_PREFIXES
        )
    )


def assert_product_merge_allowed(paths) -> None:
    blocked = sorted({normalize_repo_path(path) for path in paths if is_protected_core_path(path)})
    if blocked:
        raise PermissionError(
            "Product run touched protected Core or private scope: " + ", ".join(blocked)
        )
