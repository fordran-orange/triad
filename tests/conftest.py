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
    "$env:TRIAD_PYTEST_SCOPE = 'aegis'; .venv-aegis\\Scripts\\python.exe -m pytest "
    "tests\\test_aegis_api.py"
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
    config._triad_run = None


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


def pytest_collection_finish(session):
    """The count that will run: after pytest's own -k, -m and --deselect, which act on the items
    after this guard has (review finding 1)."""
    session.config._triad_run = len(session.items)


def _narrowed(config) -> list[str]:
    """Why this run may hold less than the whole scope, as the operator would name it. "The full
    scope" is claimed only for a run from the rootdir on the configured testpaths with nothing
    that selects or collects less (QA defect D1: -o, -p no:, -c and a subdirectory narrowed
    collection itself and still read as the full scope)."""
    reasons = []
    here = Path(config.invocation_params.dir)
    if here != Path(config.rootpath):
        reasons.append(f"run from {here}, not the rootdir {config.rootpath}")
    if config.args_source == pytest.Config.ArgsSource.ARGS:
        reasons.append("paths " + " ".join(config.args))
    elif config.args_source != pytest.Config.ArgsSource.TESTPATHS:
        reasons.append("not the configured testpaths")
    for override in getattr(config.option, "override_ini", None) or []:
        reasons.append(f"-o {override}")
    for plugin in getattr(config.option, "plugins", None) or []:
        if plugin.startswith("no:") and plugin != "no:cacheprovider":
            reasons.append(f"-p {plugin}")
    if getattr(config.option, "inifilename", None):
        reasons.append(f"-c {config.option.inifilename}")
    for name, flag in (("keyword", "-k"), ("markexpr", "-m")):
        value = getattr(config.option, name, "")
        if value:
            reasons.append(f"{flag} {value}")
    for name, flag in (
        ("deselect", "--deselect"),
        ("ignore", "--ignore"),
        ("ignore_glob", "--ignore-glob"),
    ):
        values = getattr(config.option, name, None) or []
        if values:
            reasons.append(f"{flag} {' '.join(str(v) for v in values)}")
    if getattr(config.option, "lf", False):
        reasons.append("--last-failed")
    return reasons


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
    owned = counts[scope]
    run = config._triad_run if config._triad_run is not None else owned
    others = ", ".join(f"{owner} {counts[owner]}" for owner in OWNERS if owner != scope)
    elsewhere = f"{total - owned} owned by other scopes deselected ({others})"
    reasons = _narrowed(config)
    if run < owned and not reasons:
        reasons.append("a plugin deselected some")
    if reasons:
        terminalreporter.write_line(
            f"scope {scope}: {run} run of {owned} owned here, PARTIAL (narrowed by "
            f"{'; '.join(reasons)}); {elsewhere}"
        )
    else:
        terminalreporter.write_line(
            f"scope {scope}: {run} run, the full scope; {elsewhere}; one scope of three, "
            "tools\\verify.ps1 runs them all"
        )
