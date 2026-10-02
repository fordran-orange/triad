import pytest
from trading_core.providers.isolation import OfflineSandbox
from trading_core.providers.process import ManagedProcess


@pytest.mark.parametrize("limit", [True, 0, 131071, 8000001, 1.5, "200000"])
def test_reject_unbounded_or_invalid_host_capture(limit, tmp_path):
    with pytest.raises(ValueError, match="Host output capacity"):
        ManagedProcess().run(["unused"], cwd=tmp_path, output_limit=limit)


@pytest.fixture
def sandbox():
    if not OfflineSandbox.available():
        pytest.skip("Pinned offline Docker runtime unavailable")
    return OfflineSandbox()


def test_valid_large_workspace_exports_after_command(sandbox):
    files = {"app/products/triad/large.py": "#" + "x" * 150000}
    result = sandbox.run(
        ["python", "-c", "print('ready')"], files,
        writable=("app/products/triad",), max_bytes=1000000, max_files=2048,
    )
    assert result.status == "EXITED" and result.exit_code == 0
    assert result.stdout.strip() == "ready"
    assert result.files == {} and result.deleted == ()


def test_escaped_json_expansion_does_not_lose_valid_workspace(sandbox):
    text = "\t" * 80000
    result = sandbox.run(
        ["python", "-c", "from pathlib import Path; Path('products/triad/new.txt').write_text('done')"],
        {"products/triad/escaped.txt": text}, writable=("products/triad",),
        max_bytes=1000000, max_files=2048,
    )
    assert result.status == "EXITED" and result.exit_code == 0
    assert result.files == {"products/triad/new.txt": "done"}


def test_model_command_output_still_has_original_cap(sandbox):
    result = sandbox.run(
        ["python", "-c", "print('x'*300000)"], {},
        max_bytes=1000000, max_files=2048,
    )
    assert result.status == "OUTPUT_LIMIT"
    assert len(result.stdout.encode()) <= 131072
    assert result.files == {} and result.deleted == ()
