"""Machine-enforced Core governance boundary for autonomous product runs.

Triad agents may work broadly inside their run worktree, but the merge gate must
reject changes to the small set of files that can increase authority, expose
credentials, alter capability-evidence semantics, change trading authority, or
weaken the merge/provenance boundary.
"""

from pathlib import PurePosixPath

PROTECTED_CORE_PATHS = frozenset(
    {
        "app/trading_core/governance.py",
        "app/trading_core/git_tools.py",
        "app/trading_core/ledger.py",
        "app/trading_core/policy.py",
        "app/trading_core/execution.py",
        "app/trading_core/providers/control.py",
        "app/trading_core/providers/contracts.py",
        "app/trading_core/providers/secrets.py",
        "app/trading_core/providers/verification.py",
        "app/trading_core/resources/config/runtime.json",
    }
)

PROTECTED_CORE_PREFIXES = (
    "app/trading_core/resources/sql/",
)


def normalize_repo_path(path: str) -> str:
    value = PurePosixPath(str(path).replace("\\", "/")).as_posix().lstrip("./")
    if value.startswith("../") or value == "..":
        raise PermissionError("Path escapes repository")
    return value


def is_protected_core_path(path: str) -> bool:
    value = normalize_repo_path(path)
    return value in PROTECTED_CORE_PATHS or any(
        value.startswith(prefix) for prefix in PROTECTED_CORE_PREFIXES
    )


def assert_product_merge_allowed(paths) -> None:
    blocked = sorted({normalize_repo_path(path) for path in paths if is_protected_core_path(path)})
    if blocked:
        raise PermissionError(
            "Autonomous product run touched protected Core governance: " + ", ".join(blocked)
        )
