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


def aegis_scope(monkeypatch):
    monkeypatch.setenv("TRIAD_PYTEST_SCOPE", "aegis")
    monkeypatch.setenv("TRIAD_PYTEST_INTERPRETER_SCOPE", "aegis")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)


def test_unset_scope_is_a_usage_error(pytester, monkeypatch):
    monkeypatch.delenv("TRIAD_PYTEST_SCOPE", raising=False)
    tree(pytester)
    result = pytester.runpytest_subprocess()
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*TRIAD_PYTEST_SCOPE is not set*", "*tools\\verify.ps1*"])
    assert "passed" not in result.stdout.str()


def test_the_hint_runs_in_powershell(pytester, monkeypatch):
    """The refusal's example must work in the shell this host uses (review: POSIX VAR=x cmd
    does not run in PowerShell or cmd)."""
    monkeypatch.delenv("TRIAD_PYTEST_SCOPE", raising=False)
    tree(pytester)
    stderr = pytester.runpytest_subprocess().stderr.str()
    assert "$env:TRIAD_PYTEST_SCOPE = 'aegis'; .venv-aegis\\Scripts\\python.exe -m pytest" in stderr
    assert "TRIAD_PYTEST_SCOPE=aegis .venv-aegis" not in stderr


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
    aegis_scope(monkeypatch)
    tree(pytester)
    result = pytester.runpytest_subprocess("-q")
    result.assert_outcomes(passed=2, deselected=2)
    result.stdout.fnmatch_lines(
        [
            (
                "*scope aegis: 2 run, the full scope; 2 owned by other scopes deselected"
                " (core 1, triad 1); one scope of three*"
            )
        ]
    )
    assert "PARTIAL" not in result.stdout.str()


def test_a_keyword_filter_reports_a_partial_run(pytester, monkeypatch):
    """Review finding 1: pytest's own -k runs after the guard; the count must be the final one."""
    aegis_scope(monkeypatch)
    tree(pytester)
    result = pytester.runpytest_subprocess("-q", "-k", "test_b")
    result.assert_outcomes(passed=1, deselected=3)
    result.stdout.fnmatch_lines(
        ["*scope aegis: 1 run of 2 owned here, PARTIAL (narrowed by -k test_b)*"]
    )
    assert "the full scope" not in result.stdout.str()


def test_inherited_addopts_are_reported_as_partial(pytester, monkeypatch):
    aegis_scope(monkeypatch)
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k 'not test_b'")
    tree(pytester)
    result = pytester.runpytest_subprocess("-q")
    result.assert_outcomes(passed=1, deselected=3)
    result.stdout.fnmatch_lines(
        ["*scope aegis: 1 run of 2 owned here, PARTIAL (narrowed by -k not test_b)*"]
    )


def test_explicit_paths_are_reported_as_partial(pytester, monkeypatch):
    aegis_scope(monkeypatch)
    tree(pytester)
    result = pytester.runpytest_subprocess("-q", "test_aegis_owned.py")
    result.assert_outcomes(passed=2)
    result.stdout.fnmatch_lines(
        ["*scope aegis: 2 run of 2 owned here, PARTIAL (narrowed by paths test_aegis_owned.py)*"]
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


def test_triads_trusted_gate_runs_only_triad_owned_modules():
    """Review finding 5: Triad's post-merge verification runs under the Triad scope; a module it
    names that another owner holds would be deselected while the gate still reports PASS."""
    source = ROOT / "app" / "products" / "triad" / "daily_verification.py"
    named = [
        node.value
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("tests/")
        and node.value.endswith(".py")
    ]
    assert named == ["tests/test_readiness.py", "tests/test_day8_daily_ui_qa.py"], named
    assert {name: module_owners(ROOT / name) for name in named} == {
        name: ["triad"] for name in named
    }


@pytest.mark.parametrize(
    ("module", "owner"),
    [
        # spec §2 item 4, by name
        ("tests/test_engineering.py", "triad"),
        ("tests/test_application_plan_validator.py", "triad"),
        ("tests/test_architecture.py", "core"),
        ("tests/test_day7_a2_qa.py", "core"),
        ("tests/test_governance.py", "core"),
        ("tests/test_ownership_integration.py", "core"),
        ("tests/test_product_worker_supervisor.py", "core"),
        # Triad's trusted post-merge gate runs it (ledger ruling, Task 2)
        ("tests/test_readiness.py", "triad"),
    ],
)
def test_owners_the_spec_and_the_rulings_assign(module, owner):
    assert module_owners(ROOT / module) == [owner]
