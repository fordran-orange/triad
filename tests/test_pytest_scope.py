"""The scope guard (Mission 7 spec §2 items 4–5, §3.3): a default or wrong pytest cannot show a
partial green, and every module is owned."""

import ast

import pytest
from trading_core.settings import ROOT

pytestmark = pytest.mark.core
pytest_plugins = ["pytester"]
CONFTEST = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
INI = "[pytest]\nmarkers =\n    core: c\n    triad: t\n    aegis: a\n"


def tree(pytester):
    pytester.makeini(INI)
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(
        test_core_owned="import pytest\npytestmark = pytest.mark.core\ndef test_c(): pass\n",
        test_aegis_owned=(
            "import pytest\npytestmark = pytest.mark.aegis\n"
            "def test_a(): pass\ndef test_b(): pass\n"
        ),
        test_triad_owned="import pytest\npytestmark = pytest.mark.triad\ndef test_t(): pass\n",
    )


def test_unset_scope_is_a_usage_error(pytester, monkeypatch):
    monkeypatch.delenv("TRIAD_PYTEST_SCOPE", raising=False)
    tree(pytester)
    result = pytester.runpytest_subprocess()
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*TRIAD_PYTEST_SCOPE is not set*", "*tools\\verify.ps1*"])
    assert "passed" not in result.stdout.str()


def test_scope_must_match_the_interpreter(pytester, monkeypatch):
    monkeypatch.setenv("TRIAD_PYTEST_SCOPE", "aegis")
    monkeypatch.setenv("TRIAD_PYTEST_INTERPRETER_SCOPE", "core")
    tree(pytester)
    result = pytester.runpytest_subprocess()
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*scope aegis*interpreter*core*.venv-aegis*"])
    assert "passed" not in result.stdout.str()


def test_an_unknown_scope_is_a_usage_error(pytester, monkeypatch):
    monkeypatch.setenv("TRIAD_PYTEST_SCOPE", "everything")
    tree(pytester)
    result = pytester.runpytest_subprocess()
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*TRIAD_PYTEST_SCOPE=everything is not one of*"])


def test_matching_scope_runs_only_its_owner_and_says_so(pytester, monkeypatch):
    monkeypatch.setenv("TRIAD_PYTEST_SCOPE", "aegis")
    monkeypatch.setenv("TRIAD_PYTEST_INTERPRETER_SCOPE", "aegis")
    tree(pytester)
    result = pytester.runpytest_subprocess("-q")
    result.assert_outcomes(passed=2, deselected=2)
    result.stdout.fnmatch_lines(
        ["*scope aegis: 2 selected; 2 deselected (core 1, triad 1); this is one scope of three*"]
    )


def test_unowned_module_fails_collection(pytester, monkeypatch):
    monkeypatch.setenv("TRIAD_PYTEST_SCOPE", "core")
    monkeypatch.setenv("TRIAD_PYTEST_INTERPRETER_SCOPE", "core")
    tree(pytester)
    pytester.makepyfile(test_orphan="def test_o(): pass\n")
    result = pytester.runpytest_subprocess()
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*test_orphan.py: no owner marker*"])
    assert "passed" not in result.stdout.str()


def test_a_module_with_two_owners_fails_collection(pytester, monkeypatch):
    monkeypatch.setenv("TRIAD_PYTEST_SCOPE", "inventory")
    monkeypatch.setenv("TRIAD_PYTEST_INTERPRETER_SCOPE", "core")
    tree(pytester)
    pytester.makepyfile(
        test_twice="import pytest\npytestmark = [pytest.mark.core, pytest.mark.aegis]\n"
        "def test_x(): pass\n"
    )
    result = pytester.runpytest_subprocess("--collect-only", "-q")
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*test_twice.py: several owner markers*"])


def test_inventory_counts_every_owner_and_only_collects(pytester, monkeypatch):
    monkeypatch.setenv("TRIAD_PYTEST_SCOPE", "inventory")
    monkeypatch.setenv("TRIAD_PYTEST_INTERPRETER_SCOPE", "core")
    tree(pytester)
    result = pytester.runpytest_subprocess("--collect-only", "-q")
    result.stdout.fnmatch_lines(["*inventory: core 1, triad 1, aegis 2, total 4*"])
    assert pytester.runpytest_subprocess().ret == 4  # inventory without --collect-only


def module_owners(path):
    """The owner marks in a module's top-level `pytestmark` (a mark or a list of marks)."""
    text = path.read_text(encoding="utf-8")
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            values = node.value.elts if isinstance(node.value, ast.List) else [node.value]
            return [
                v.attr
                for v in values
                if isinstance(v, ast.Attribute) and v.attr in ("core", "triad", "aegis")
            ]
    return []


def test_every_module_in_this_repository_declares_one_owner():
    modules = list((ROOT / "tests").rglob("test_*.py"))
    wrong = {
        str(p.relative_to(ROOT)): owners for p in modules if len(owners := module_owners(p)) != 1
    }
    assert len(modules) >= 170 and not wrong, wrong
