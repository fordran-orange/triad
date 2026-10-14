"""Safety regression tests for operator-supplied gzip retention."""

import gzip
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

spec = importlib.util.spec_from_file_location(
    "hf_audit", Path(__file__).resolve().parents[1] / "tools/audit_hfdatalibrary.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_existing_identical_and_conflicting_files_are_never_overwritten(tmp_path):
    source, target = tmp_path / "input.gz", tmp_path / "output"
    source.write_bytes(gzip.compress(b"original"))
    compressed = source.read_bytes()
    first = audit.extract(source, target)
    assert first["action"] == "decompressed_new"
    assert first["uncompressed_size"] == 8
    assert audit.extract(source, target)["action"] == "verified_existing_identical"
    target.write_bytes(b"different")
    assert audit.extract(source, target)["errors"]
    assert target.read_bytes() == b"different"
    assert source.read_bytes() == compressed


def test_corrupt_gzip_and_expansion_ceiling_leave_no_output(tmp_path):
    source, target = tmp_path / "input.gz", tmp_path / "output"
    source.write_bytes(gzip.compress(b"abcdef")[:-4])
    assert audit.extract(source, target)["errors"]
    assert not target.exists()
    source.write_bytes(gzip.compress(b"abcdef"))
    assert audit.extract(source, target, max_bytes=3)["errors"]
    assert not target.exists()
    assert list(tmp_path.iterdir()) == [source]
