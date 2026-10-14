"""Scope guard (Mission 7 spec §3.3): every test module is owned by core, triad or aegis and runs
only in that owner's environment, so no pytest invocation can show a partial green as if it were
the whole suite. Set TRIAD_PYTEST_SCOPE to the owner and use its interpreter, or run
tools\\verify.ps1 for all three scopes."""

import os
import sys
from pathlib import Path

import pytest

OWNERS = ("core", "triad", "aegis")
ENVIRONMENTS = {"core": ".venv", "triad": ".venv-triad", "aegis": ".venv-aegis"}
PREFIXES = {name: owner for owner, name in ENVIRONMENTS.items()}
HOW = (
    "Run tools\\verify.ps1 for all three scopes, or one scope with its own interpreter, e.g. "
    "TRIAD_PYTEST_SCOPE=aegis .venv-aegis\\Scripts\\python.exe -m pytest tests\\test_aegis_api.py"
)


def interpreter_scope() -> str:
    """The owner this interpreter serves, from the name of its environment directory.
    TRIAD_PYTEST_INTERPRETER_SCOPE overrides it for the guard's own tests only."""
    override = os.environ.get("TRIAD_PYTEST_INTERPRETER_SCOPE")
    return override or PREFIXES.get(Path(sys.prefix).name, "unknown")


def pytest_configure(config):
    scope = os.environ.get("TRIAD_PYTEST_SCOPE", "").strip()
    if not scope:
        raise pytest.UsageError(f"TRIAD_PYTEST_SCOPE is not set: no tests were run.\n{HOW}")
    if scope == "inventory":
        if not config.option.collectonly:
            raise pytest.UsageError(
                "TRIAD_PYTEST_SCOPE=inventory only counts owners; add --collect-only.\n" + HOW
            )
    elif scope not in OWNERS:
        raise pytest.UsageError(
            f"TRIAD_PYTEST_SCOPE={scope} is not one of {', '.join(OWNERS)} or inventory.\n{HOW}"
        )
    else:
        found = interpreter_scope()
        if found != scope:
            raise pytest.UsageError(
                f"scope {scope} cannot run on this interpreter ({found}, {sys.prefix}); "
                f"it needs {ENVIRONMENTS[scope]}.\n{HOW}"
            )
    config._triad_scope = scope
    config._triad_counts = None


def _owners(item) -> set[str]:
    return {mark.name for mark in item.iter_markers() if mark.name in OWNERS}


def pytest_collection_modifyitems(config, items):
    scope = getattr(config, "_triad_scope", None)
    if scope is None:
        return
    counts = dict.fromkeys(OWNERS, 0)
    unowned: dict[str, str] = {}
    for item in items:
        owners = _owners(item)
        if len(owners) == 1:
            counts[next(iter(owners))] += 1
        else:
            reason = "no owner marker" if not owners else "several owner markers"
            unowned[str(item.path)] = reason
    if unowned:
        lines = [f"{path}: {reason}" for path, reason in sorted(unowned.items())]
        raise pytest.UsageError(
            "every test module needs exactly one owner, "
            "pytestmark = pytest.mark.core | triad | aegis:\n" + "\n".join(lines)
        )
    config._triad_counts = counts
    if scope == "inventory":
        return
    kept = [item for item in items if _owners(item) == {scope}]
    removed = [item for item in items if _owners(item) != {scope}]
    items[:] = kept
    if removed:
        config.hook.pytest_deselected(items=removed)


def pytest_report_header(config):
    scope = getattr(config, "_triad_scope", "?")
    return f"TRIAD_PYTEST_SCOPE={scope} on interpreter {Path(sys.prefix).name}"


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    counts = getattr(config, "_triad_counts", None)
    scope = getattr(config, "_triad_scope", None)
    if counts is None or scope is None:
        return
    total = sum(counts.values())
    if scope == "inventory":
        line = ", ".join(f"{owner} {counts[owner]}" for owner in OWNERS)
        terminalreporter.write_line(f"inventory: {line}, total {total}")
        return
    others = ", ".join(f"{owner} {counts[owner]}" for owner in OWNERS if owner != scope)
    terminalreporter.write_line(
        f"scope {scope}: {counts[scope]} selected; {total - counts[scope]} deselected "
        f"({others}); this is one scope of three, tools\\verify.ps1 runs them all"
    )
