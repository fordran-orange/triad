"""Product merge exclusions; authority remains in Core's reviewed execution gates.

Product work may modify only its own product surface plus the shared low-risk text/test
areas already permitted here. Shared Core, configuration, authority, credentials,
retained data and other products remain protected.
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

PRODUCT_PREFIXES = {
    "triad": ("app/products/triad/", "products/triad/"),
    "aegis": ("app/products/aegis/", "products/aegis/"),
}

PROTECTED_CORE_PREFIXES = (
    "app/trading_core/",
    "app/platform_host/",
    "app/triad/",
    "app/products/p2p/",
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


def _allowed_product_prefixes(product: str) -> tuple[str, ...]:
    try:
        return PRODUCT_PREFIXES[product.casefold()]
    except (AttributeError, KeyError):
        raise ValueError(f"Unknown product scope: {product!r}") from None


def is_protected_core_path(path: str, *, product: str = "triad") -> bool:
    value = normalize_repo_path(path).casefold()
    allowed = _allowed_product_prefixes(product)
    allowed_app = tuple(prefix for prefix in allowed if prefix.startswith("app/"))
    allowed_products = tuple(prefix for prefix in allowed if prefix.startswith("products/"))
    return (
        value in PROTECTED_CORE_PATHS
        or (value.startswith("app/") and not value.startswith(allowed_app))
        or (value.startswith("products/") and not value.startswith(allowed_products))
        or PurePosixPath(value).name == "agents.md"
        or any(part.startswith(".") for part in PurePosixPath(value).parts)
        or any(
            value == prefix.rstrip("/") or value.startswith(prefix)
            for prefix in PROTECTED_CORE_PREFIXES
        )
    )


def assert_product_merge_allowed(paths, *, product: str = "triad") -> None:
    blocked = sorted(
        {
            normalize_repo_path(path)
            for path in paths
            if is_protected_core_path(path, product=product)
        }
    )
    if blocked:
        raise PermissionError(
            "Product run touched protected Core or private scope: " + ", ".join(blocked)
        )
