"""Independent exact-asset finalization QA; no vendor calls or production writes."""

import hashlib
from types import SimpleNamespace

import pytest
from trading_core.contracts import AgentRunResult, FileChange
from trading_core.providers.bounded_tools import BoundedTools
from trading_core.providers.native_agents import NativeRun
from trading_core.runtime import ProviderError

pytestmark = pytest.mark.core

PATH = "app/products/triad/features/probe.html"


def setup_native(*, original=None, observed=True, guard=lambda: None):
    native = NativeRun([], guard)
    native.observed_asset_output = observed
    native.broker = BoundedTools(
        original or {}, writable=("app/products/triad/features",), exact_files=(PATH,)
    )
    return native


def result(**changes):
    return AgentRunResult(run_id="qa", status="CODE_CHANGE", summary="bounded", **changes)


def test_empty_result_without_writes_cannot_create_files():
    native = setup_native()
    parsed, _, _ = native.finish(result().model_dump(mode="json"), 3, 4)
    assert parsed.files_changed == ()
    assert native.evidence["finalization"] == "HOST_OBSERVED_ASSETS"


@pytest.mark.parametrize("path,content", [(PATH, "exact"), (PATH, "forged"), ("app/trading_core/control.py", "forged")])
def test_any_competing_final_payload_rejected(path, content):
    native = setup_native()
    native.broker.files[PATH] = "exact"
    native.broker.calls.append({"tool": "propose_file_change", "path": PATH})
    with pytest.raises(ProviderError, match="NativeDuplicateAssetPayload"):
        native.finish(result(files_changed=(FileChange(path=path, content=content),)).model_dump(mode="json"), 3, 4)


def test_original_hash_and_read_evidence_retained():
    native = setup_native(original={PATH: "old"})
    native.broker.files[PATH] = "new"
    with pytest.raises(ProviderError, match="NativeReadEvidenceMissing"):
        native.finish(result().model_dump(mode="json"), 3, 4)
    native.broker.calls.extend([{"tool": "read_file", "path": PATH}, {"tool": "propose_file_change", "path": PATH}])
    parsed, _, _ = native.finish(result().model_dump(mode="json"), 3, 4)
    assert parsed.files_changed == (FileChange(path=PATH, content="new", original_sha256=hashlib.sha256(b"old").hexdigest()),)


def test_stale_epoch_guard_rechecked_before_finalization():
    def revoked():
        raise PermissionError("authority epoch changed")
    native = setup_native(guard=revoked)
    native.broker.files[PATH] = "new"
    with pytest.raises(PermissionError, match="authority epoch changed"):
        native.finish(result().model_dump(mode="json"), 3, 4)


@pytest.mark.parametrize("field", ["commands_executed", "permission_requests", "claims", "actions_taken", "tests_run"])
def test_final_result_claims_still_rejected(field):
    native = setup_native()
    raw = result().model_dump(mode="json")
    raw[field] = ["unobserved"]
    with pytest.raises((ProviderError, ValueError)):
        native.finish(raw, 3, 4)


def test_legacy_staged_payload_matching_unchanged():
    native = setup_native(observed=False)
    native.broker.files[PATH] = "staged"
    with pytest.raises(ProviderError, match="NativeProposalEvidenceMismatch"):
        native.finish(result().model_dump(mode="json"), 3, 4)
    parsed, _, _ = native.finish(result(files_changed=(FileChange(path=PATH, content="staged"),)).model_dump(mode="json"), 3, 4)
    assert parsed.files_changed[0].content == "staged"
    assert "finalization" not in native.evidence


def test_exact_prompt_and_legacy_prompt_remain_distinct():
    request = SimpleNamespace(model_dump_json=lambda **kwargs: "request")
    assert "Keep files_changed empty: Core reconstructs" in setup_native().prompt(request, {})
    assert "For implementation report staged file contents" in setup_native(observed=False).prompt(request, {})


def test_ungranted_sibling_rejected_without_container_launch(monkeypatch):
    native = setup_native()
    monkeypatch.setattr(native.broker.sandbox, "run", lambda *a, **k: pytest.fail("ungranted tool reached sandbox"))
    with pytest.raises(PermissionError):
        native.broker.call("propose_file_change", {"path": PATH.replace("probe", "ungranted"), "content": "bad"})
    assert native.broker.changes() == ()
    assert native.broker.denials == 1


def test_actual_offline_write_becomes_authoritative_final_asset():
    native = setup_native(original={PATH: "old"})
    assert native.broker.call("read_file", {"path": PATH}) == "old"
    native.broker.call("propose_file_change", {"path": PATH, "content": "<h1>Observed</h1>\n"})
    parsed, _, _ = native.finish(result().model_dump(mode="json"), 3, 4)
    assert len(parsed.files_changed) == 1
    change = parsed.files_changed[0]
    assert change.path == PATH and change.content == "<h1>Observed</h1>\n"
    assert change.original_sha256 == hashlib.sha256(b"old").hexdigest()
    assert [c["tool"] for c in native.evidence["calls"]] == ["read_file", "propose_file_change"]
    assert native.evidence["denials"] == 0
