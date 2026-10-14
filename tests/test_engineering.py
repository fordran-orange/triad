"""Narrow asset editing does not grant executable host tools or protected paths."""

import hashlib

import pytest
from trading_core.contracts import FileChange
from trading_core.engineering import (
    EngineeringGit,
    EngineeringGrant,
    checked_paths,
    run_approved_checks,
)
from trading_core.git_tools import GitChanges
from trading_core.providers.bounded_tools import BoundedTools
from trading_core.providers.isolation import OfflineSandbox

# Owned by Triad (spec §2 item 4): it drives Triad's product workspace through Core.
pytestmark = pytest.mark.triad

PATH = "app/products/triad/features/probe.html"
SCRIPT = (
    "from pathlib import Path; assert Path('"
    + PATH
    + "').read_text() == '<h1>Probe</h1>'; print('CHECKED')"
)


def grant():
    return EngineeringGrant(
        work_item_id="test",
        owner="triad",
        agent="CLAUDE",
        epoch=0,
        scope_digest="test",
        base_commit="test",
        writable_files=(PATH,),
        test_id="probe-v1",
        test_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),
    )


@pytest.mark.parametrize(
    "path",
    [
        "app/products/triad/server.py",
        "app/products/triad/features/hook.py",
        "app/trading_core/control.py",
        "app/products/aegis/features/probe.html",
        "app/products/triad/features/../server.js",
        "app/products/triad/features/.env",
        "app/products/triad/features/probe.html:secret",
    ],
)
def test_protected_or_unsupported_assets_denied(path):
    with pytest.raises((PermissionError, ValueError)):
        checked_paths("triad", (path,))


def test_exact_paths_and_legacy_text_policy(tmp_path):
    g = EngineeringGit(grant(), root=tmp_path)
    assert g.path(tmp_path, PATH, ()) == tmp_path / PATH
    with pytest.raises(PermissionError):
        g.path(tmp_path, PATH.replace("probe", "other"), ())
    with pytest.raises(PermissionError):
        GitChanges.path(tmp_path, PATH, ("app/products/triad/features",))
    with pytest.raises(PermissionError):
        checked_paths("triad", (PATH, PATH.upper()))


def test_native_broker_exact_file_denies_sibling_before_execution():
    broker = BoundedTools({}, writable=("app/products/triad/features",), exact_files=(PATH,))
    with pytest.raises(PermissionError):
        broker.call(
            "propose_file_change", {"path": PATH.replace("probe", "other"), "content": "oops"}
        )
    assert broker.denials == 1 and not broker.calls


def test_approved_check_identity_and_scope_checked_before_docker():
    with pytest.raises(PermissionError):
        run_approved_checks(grant(), {PATH: "<h1>Probe</h1>"}, "print('fake')", guard=lambda: None)
    with pytest.raises(PermissionError):
        run_approved_checks(grant(), {"bad.html": ""}, SCRIPT, guard=lambda: None)


@pytest.mark.integration
def test_actual_offline_approved_checks_and_native_staging():
    assert OfflineSandbox.available(), "Pinned offline boundary must be available"
    broker = BoundedTools({}, writable=("app/products/triad/features",), exact_files=(PATH,))
    broker.call("propose_file_change", {"path": PATH, "content": "<h1>Probe</h1>"})
    assert broker.changes() == (FileChange(path=PATH, content="<h1>Probe</h1>"),)
    result = run_approved_checks(grant(), broker.files, SCRIPT, guard=lambda: None)
    assert result["status"] == "PASS" and result["stdout"].strip() == "CHECKED"
    assert result["snapshot"][PATH] == hashlib.sha256(b"<h1>Probe</h1>").hexdigest()
    assert result["boundary"] == "DOCKER_OFFLINE_TOOLS"
    assert (
        run_approved_checks(grant(), {PATH: "<h1>Wrong</h1>"}, SCRIPT, guard=lambda: None)["status"]
        == "FAIL"
    )
