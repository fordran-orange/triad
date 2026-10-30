#!/usr/bin/env bash
# Lint the Aegis scope of the checkout this script lives in (Optimization Lab v2 plan, Phase 0).
#
#   tools/lint_aegis.sh          # check: ruff check + ruff format --check (the verify.ps1 gate)
#   tools/lint_aegis.sh fix      # ruff check --fix + ruff format, same scope
#
# The scope is written out literally below, never held in a variable that could expand empty,
# because a bare `ruff format` once reformatted the whole repository. The paths are resolved
# from this script's own location, so a worktree lints itself and never C:\Triad. ruff comes
# from the checkout's Core environment when it has one, else from the main checkout's
# (worktrees share no virtual environment); the files linted are always the local ones.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-check}"

if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    PYTHON="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    COMMON="$(git -C "$ROOT" rev-parse --git-common-dir)"
    case "$COMMON" in
        /*|[A-Za-z]:*) MAIN="$(cd "$(dirname "$COMMON")" && pwd)" ;;
        *) MAIN="$(cd "$ROOT/$(dirname "$COMMON")" && pwd)" ;;
    esac
    PYTHON="$MAIN/.venv/Scripts/python.exe"
    [ -x "$PYTHON" ] || PYTHON="$MAIN/.venv/bin/python"
fi
[ -x "$PYTHON" ] || { echo "lint_aegis: no Core environment found for $ROOT" >&2; exit 2; }

cd "$ROOT"
# The same scope as tools/verify.ps1's lint gate; the test glob is expanded here, in ROOT.
scope=(app/products/aegis tests/products/aegis tools/aegis_contracts.py
    tests/conftest.py tests/test_pytest_scope.py tests/test_environments.py
    tests/test_architecture.py tests/test_day8_workflow_qa.py
    tools/run_daily_product_cycle.py tools/accept_environments.py
    tests/test_lab_store.py tests/test_lab_query.py tests/test_lab_sharpe.py
    tests/test_lab_identity.py tests/test_lab_blocks.py tests/test_lab_tasks.py tools/aegis_decompact.py
    tests/test_lab_analytics.py tests/lab_stat_fixtures.py tests/test_lab_robustness.py
    tests/test_aegis_*.py)

case "$MODE" in
    check)
        "$PYTHON" -m ruff check "${scope[@]}"
        "$PYTHON" -m ruff format --check "${scope[@]}"
        ;;
    fix)
        "$PYTHON" -m ruff check --fix "${scope[@]}"
        "$PYTHON" -m ruff format "${scope[@]}"
        "$PYTHON" -m ruff check "${scope[@]}"
        ;;
    *)
        echo "usage: tools/lint_aegis.sh [check|fix]" >&2
        exit 2
        ;;
esac
echo "lint_aegis ($MODE): ok on $ROOT"
