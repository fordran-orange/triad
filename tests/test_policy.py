import json

import pytest
from pydantic import ValidationError
from triad.policy import AuthorityRequest, Intent, TrustedPrincipal, compile_policy
from triad.settings import ROOT

pytestmark = pytest.mark.triad


def intent(**changes):
    source = json.loads((ROOT / "control-plane/intent.example.json").read_text())
    return Intent(**(source | changes))


def test_human_compiles_frozen_policy():
    policy = compile_policy(intent(), principal=TrustedPrincipal(subject="operator", kind="human"))
    assert not policy.intent.live_trading_authority
    assert len(policy.intent_sha256) == 64
    with pytest.raises(ValidationError):
        policy.intent.compute_tokens = 9000


def test_agent_cannot_grant_authority():
    with pytest.raises(PermissionError):
        compile_policy(intent(), principal=TrustedPrincipal(subject="agent", kind="agent"))


@pytest.mark.parametrize(
    "changes",
    [
        {"live_trading_authority": True},
        {"tools": ["broker_submit"]},
        {"tasks": ["approve_live_trades"]},
        {"tasks": ["change_system_policy"]},
        {"compute_tokens": 8193},
        {"compute_seconds": 121},
        {"compute_tokens": -1},
        {"risk_limits": {"max_order_notional": 1}},
        {"data_scope": ["canonical"]},
        {"execution_permissions": ["read"]},
        {"unknown_authority": True},
    ],
)
def test_invalid_authority(changes):
    with pytest.raises(ValidationError):
        intent(**changes)


def test_agent_request_stays_pending():
    request = AuthorityRequest(
        agent_id="helper", reason="Need larger summary budget", requested_intent=intent()
    )
    assert request.status == "pending_human_review"
    with pytest.raises(ValidationError):
        AuthorityRequest(
            agent_id="helper", reason="Request", requested_intent=intent(), status="approved"
        )


def test_compiler_revalidates_unchecked_copy():
    tampered = intent().model_copy(update={"live_trading_authority": True})
    with pytest.raises(ValidationError):
        compile_policy(tampered, principal=TrustedPrincipal(subject="operator", kind="human"))


def test_hash_stable_for_set_order():
    principal = TrustedPrincipal(subject="operator", kind="human")
    assert (
        compile_policy(intent(), principal=principal).intent_sha256
        == compile_policy(
            intent(tools=["write_scratch", "read_logs", "read_docs"]), principal=principal
        ).intent_sha256
    )
