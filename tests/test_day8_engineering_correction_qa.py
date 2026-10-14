"""Native final results retain observed base hashes, never model-supplied hashes."""

import hashlib

import pytest
from test_engineering import PATH
from trading_core.contracts import AgentRunResult, FileChange
from trading_core.providers.bounded_tools import BoundedTools
from trading_core.providers.native_agents import NativeRun
from trading_core.runtime import ProviderError

pytestmark = pytest.mark.core


@pytest.mark.parametrize("claimed_hash", [None, "f" * 64])
def test_native_finish_binds_original_hash_to_observed_bytes(claimed_hash):
    broker = BoundedTools(
        {PATH: "old"}, writable=("app/products/triad/features",), exact_files=(PATH,)
    )
    broker.files[PATH] = "new"
    broker.calls = [{"tool": "read_file", "path": PATH}]
    native = NativeRun([], lambda: None)
    native.broker = broker
    result = AgentRunResult(
        run_id="fixture",
        status="CODE_CHANGE",
        summary="fixture proposal",
        files_changed=(FileChange(path=PATH, content="new", original_sha256=claimed_hash),),
    )
    observed, _, _ = native.finish(result.model_dump(mode="json"), 1, 1)
    assert observed.files_changed[0].original_sha256 == hashlib.sha256(b"old").hexdigest()
    changed = result.model_copy(
        update={"files_changed": (FileChange(path=PATH, content="unstaged"),)}
    )
    with pytest.raises(ProviderError, match="NativeProposalEvidenceMismatch"):
        native.finish(changed.model_dump(mode="json"), 1, 1)
