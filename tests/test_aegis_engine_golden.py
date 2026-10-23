"""Mission 13 identity: backtests, carried runs, experiment cells and a walk-forward without stops
give exactly the output today's engine gave (`tests/products/aegis/engine_golden.py`)."""

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.aegis

sys.path.insert(0, str(Path(__file__).resolve().parent / "products" / "aegis"))
import engine_golden

GOLDEN = json.loads(engine_golden.FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cases():
    return engine_golden.cases()


def _first_difference(a, b, path="") -> str | None:
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}/{key}: present on one side only"
            found = _first_difference(a[key], b[key], f"{path}/{key}")
            if found:
                return found
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} items != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            found = _first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"


@pytest.mark.parametrize("key", sorted(GOLDEN))
def test_engine_output_equals_the_golden(cases, key):
    assert key in cases, f"case {key} is no longer produced"
    assert _first_difference(cases[key], GOLDEN[key], key) is None
