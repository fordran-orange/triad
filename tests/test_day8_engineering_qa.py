"""Independent exact engineering authority and candidate integrity probes."""
# ruff: noqa: F811

import hashlib
import os
import subprocess
from types import SimpleNamespace

import pytest
from test_day3_integration import engine  # noqa: F401
from test_engineering import PATH, SCRIPT, grant
from trading_core.contracts import FileChange
from trading_core.engineering import EngineeringGit, grant_for, issue_grant, run_approved_checks
from trading_core.intelligence.records import Records
from trading_core.ledger import Stopped
from trading_core.providers.bounded_tools import BoundedTools
from trading_core.store import Store
from trading_core.work import WorkItem


def repository(tmp_path, *, existing=False, **updates):
    root = tmp_path / "repo"
    root.mkdir()
    for args in (
        ("init", "-b", "main"),
        ("config", "user.email", "qa@localhost"),
        ("config", "user.name", "Independent QA"),
    ):
        subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)
    (root / "README.md").write_text("# Isolated fixture\n")
    if existing:
        target = root / PATH
        target.parent.mkdir(parents=True)
        target.write_text("<h1>Old</h1>")
    subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=root, capture_output=True, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    g = grant().model_copy(update={"base_commit": base, **updates})
    git = EngineeringGit(g, root=root, worktrees=tmp_path / "worktrees")
    metadata = git.isolate("independent-fixture", "CLAUDE")
    return git, metadata


@pytest.mark.integration
def test_native_existing_asset_preserves_original_hash_for_host_apply(tmp_path):
    git, metadata = repository(tmp_path, existing=True)
    broker = BoundedTools(
        {PATH: "<h1>Old</h1>"}, writable=("app/products/triad/features",), exact_files=(PATH,)
    )
    broker.call("propose_file_change", {"path": PATH, "content": "<h1>New</h1>"})
    changes = broker.changes()
    assert changes[0].original_sha256 == hashlib.sha256(b"<h1>Old</h1>").hexdigest()
    assert git.apply(metadata, changes)["passed"]


def test_verify_rechecks_grant_byte_ceiling(tmp_path):
    git, metadata = repository(tmp_path, max_bytes=10)
    git.apply(metadata, (FileChange(path=PATH, content="123"),))
    git.commit(metadata, "CLAUDE")
    target = git.path(metadata["worktree"], PATH, ())
    target.write_text("x" * 11)
    git.git("add", "--", PATH, cwd=metadata["worktree"])
    git.commit(metadata, "CLAUDE")
    with pytest.raises(PermissionError):
        git.verify(metadata, git.grant_limits())


def test_git_rejects_links_stale_sources_and_baseline_move(tmp_path):
    git, metadata = repository(tmp_path, existing=True)
    with pytest.raises(PermissionError, match="Stale source"):
        git.apply(metadata, (FileChange(path=PATH, content="new", original_sha256="0" * 64),))
    target = git.path(metadata["worktree"], PATH, ())
    alias = target.with_name("linked.html")
    os.link(target, alias)
    with pytest.raises(PermissionError, match="Aliased"):
        git.path(metadata["worktree"], PATH, ())
    alias.unlink()
    git.apply(
        metadata,
        (
            FileChange(
                path=PATH,
                content="<h1>New</h1>",
                original_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            ),
        ),
    )
    git.commit(metadata, "CLAUDE")
    git.review_commit(metadata, "qa-fixture", "PASS")
    (git.root / "other.md").write_text("# Concurrent change\n")
    git.git("add", "other.md")
    git.git("commit", "-m", "concurrent baseline")
    with pytest.raises(PermissionError, match="Baseline moved"):
        git.merge(
            metadata,
            {
                "decision": "APPROVE",
                "change_commit": metadata["change_commit"],
                "reviewer": "CODEX",
                "worker": "CLAUDE",
                "review_id": "qa-fixture",
            },
            git.grant_limits(),
        )


@pytest.mark.integration
def test_canonical_grants_reject_forgery_revocation_and_scoped_ingestion(engine):
    records = Records(engine.host.store)
    work = engine.host.create(
        WorkItem(
            owner="triad",
            title="QA engineering grant",
            description="Exact UI fixture",
            assigned_agent="CLAUDE",
            reviewer="CODEX",
            work_type="development",
            authority_tier=2,
            allowed_paths=(PATH,),
            allowed_tools=("read_file", "write_artifact"),
            execution_permissions=("read", "write_code"),
            review_required=True,
        )
    )
    request = SimpleNamespace(
        work_item_id=work.work_item_id,
        agent_id="CLAUDE",
        control_epoch=0,
        allowed_paths=(PATH,),
        execution_permissions=("write_code",),
        role="IMPLEMENT",
    )
    with pytest.raises(KeyError):
        grant_for(engine.ledger, request)
    work, _ = engine.start_work(work)
    issued = issue_grant(
        records, work, base_commit="fixture", files=(PATH,), test_id="qa", test_script=SCRIPT
    )
    assert grant_for(engine.ledger, request) == issued
    for key, value in (
        ("agent_id", "CODEX"),
        ("allowed_paths", (PATH.replace("probe", "other"),)),
        ("role", "REVIEW"),
        ("execution_permissions", ("write_docs",)),
    ):
        with pytest.raises(PermissionError):
            grant_for(engine.ledger, SimpleNamespace(**(vars(request) | {key: value})))
    scoped = Records(Store(engine.host.store.settings, scope="triad"))
    for kind in ("EngineeringGrant", "EngineeringTestRun"):
        with pytest.raises(PermissionError):
            scoped.append(kind, {}, owner="triad")
        with pytest.raises(PermissionError):
            scoped.ledger.put(kind, {})
    with pytest.raises(PermissionError):
        issue_grant(
            scoped, work, base_commit="fixture", files=(PATH,), test_id="qa", test_script=SCRIPT
        )
    engine.ledger.operate("disable", agent="CLAUDE")
    with pytest.raises(Stopped):
        grant_for(engine.ledger, request)
    engine.ledger.operate("enable", agent="CLAUDE")
    engine.ledger.operate("kill")
    engine.ledger.operate("resume")
    with pytest.raises(Stopped):
        grant_for(engine.ledger, request)


@pytest.mark.integration
def test_approved_checks_are_offline_read_only_and_guarded():
    script = (
        "import os,pathlib,socket; "
        "assert 'OPENAI_API_KEY' not in os.environ; "
        "assert not pathlib.Path('/var/run/docker.sock').exists(); "
        "p=pathlib.Path('" + PATH + "'); "
        "assert p.read_text()=='<h1>Probe</h1>'; "
        "print('offline checks')"
    )
    g = grant().model_copy(update={"test_sha256": hashlib.sha256(script.encode()).hexdigest()})
    assert (
        run_approved_checks(g, {PATH: "<h1>Probe</h1>"}, script, guard=lambda: None)["status"]
        == "PASS"
    )
    writer = "from pathlib import Path; Path('" + PATH + "').write_text('mutation')"
    g = grant().model_copy(update={"test_sha256": hashlib.sha256(writer.encode()).hexdigest()})
    assert (
        run_approved_checks(g, {PATH: "<h1>Probe</h1>"}, writer, guard=lambda: None)["status"]
        == "FAIL"
    )

    def stopped():
        raise Stopped("fixture stop")

    with pytest.raises(Stopped):
        run_approved_checks(grant(), {PATH: "<h1>Probe</h1>"}, SCRIPT, guard=stopped)
