"""Narrow host-granted product UI editing; no shell, backend or Git model tools.

This separate profile leaves legacy text proposals unchanged. Providers can stage
only exact feature assets. Trusted checks run against a credential-free offline
snapshot; Git and all merge decisions remain host owned.
"""

import hashlib
from pathlib import Path

from pydantic import Field

from trading_core.control import relative_path
from trading_core.git_tools import GitChanges
from trading_core.intelligence.records import Records
from trading_core.providers.isolation import OfflineSandbox, safe_path
from trading_core.resource_policy import scope_digest
from trading_core.security import ensure_no_secret
from trading_core.work import Record, now


class EngineeringGrant(Record):
    work_item_id: str
    owner: str
    agent: str
    epoch: int
    scope_digest: str
    base_commit: str
    writable_files: tuple[str, ...] = Field(min_length=1, max_length=3)
    max_files: int = Field(default=3, ge=1, le=3)
    max_lines: int = Field(default=600, ge=1, le=600)
    max_bytes: int = Field(default=32000, ge=1, le=32000)
    test_id: str
    test_sha256: str
    capability: str = "isolated_product_ui_edit"
    created_at: str = Field(default_factory=lambda: now().isoformat())


def checked_paths(owner, paths):
    if owner not in {"triad", "aegis"}:
        raise PermissionError("Engineering scope requires an explicit product")
    prefix = f"app/products/{owner}/features/"
    if len({p.casefold() for p in paths}) != len(paths):
        raise PermissionError("Duplicate or aliased writable paths")
    for path in paths:
        if (
            relative_path(path) != path
            or safe_path(path) != path
            or not path.startswith(prefix)
            or Path(path).suffix not in {".html", ".js", ".css"}
            or any(part.startswith(".") for part in Path(path).parts)
        ):
            raise PermissionError("Only exact product feature UI assets are supported")


def issue_grant(records, work, *, base_commit, files, test_id, test_script):
    if records.store.scope is not None:
        raise PermissionError("Only Core host can issue engineering grants")
    control = records.ledger.guard(work_id=work.work_item_id)
    if (
        work.authority_tier != 2
        or work.work_type != "development"
        or set(work.execution_permissions) != {"read", "write_code"}
        or not work.review_required
        or not work.reviewer
        or work.reviewer == work.assigned_agent
        or not set(files) <= set(work.allowed_paths)
    ):
        raise PermissionError("Engineering grant exceeds the immutable reviewed assignment")
    checked_paths(work.owner, files)
    grant = EngineeringGrant(
        work_item_id=work.work_item_id,
        owner=work.owner,
        agent=work.assigned_agent,
        epoch=control["epoch"],
        scope_digest=scope_digest(work),
        base_commit=base_commit,
        writable_files=files,
        test_id=test_id,
        test_sha256=hashlib.sha256(test_script.encode()).hexdigest(),
    )
    records.append(
        "EngineeringGrant",
        grant.model_dump(mode="json"),
        owner=work.owner,
        identifier="engineering-" + work.work_item_id,
    )
    return grant


def grant_for(ledger, request):
    records = Records(ledger.store)
    raw = records.get("engineering-" + request.work_item_id)
    grant = EngineeringGrant.model_validate(
        {k: v for k, v in raw.items() if k in EngineeringGrant.model_fields}
    )
    work = ledger.store.get(request.work_item_id)
    ledger.guard(request.agent_id, request.work_item_id, request.control_epoch)
    checked_paths(grant.owner, grant.writable_files)
    if (
        raw["kind"] != "EngineeringGrant"
        or raw["owner"] != work.owner
        or grant.owner != work.owner
        or grant.scope_digest != scope_digest(work)
        or grant.agent != request.agent_id
        or grant.epoch != request.control_epoch
        or grant.capability != "isolated_product_ui_edit"
        or set(request.allowed_paths) != set(grant.writable_files)
        or request.execution_permissions != ("write_code",)
        or request.role != "IMPLEMENT"
        or request.agent_id != "CLAUDE"
    ):
        raise PermissionError("Request does not match host engineering grant")
    return grant


class EngineeringGit(GitChanges):
    def __init__(self, grant, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.grant = grant
        checked_paths(grant.owner, grant.writable_files)

    def path(self, root, path, scopes):
        if path not in self.grant.writable_files:
            raise PermissionError("File is outside exact engineering grant")
        # Preserve legacy filesystem protections for the exact executable assets.
        import stat

        relative_path(path)
        target = Path(root) / path
        for parent in (target, *target.parents):
            if parent == Path(root):
                break
            if parent.is_symlink() or (
                parent.exists()
                and getattr(parent.lstat(), "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
            ):
                raise PermissionError("Reparse point rejected")
        if not target.resolve().is_relative_to(Path(root).resolve()) or (
            target.exists() and target.stat().st_nlink > 1
        ):
            raise PermissionError("Aliased or escaping path")
        return target

    def verify(self, metadata, limits, staged=False):
        if metadata["base_commit"] != self.grant.base_commit:
            raise PermissionError("Grant baseline differs")
        # Parent verifies diff/files, bounded content, secrets and whitespace using
        # this exact-file path method. No proposed code executes on the host.
        checks = super().verify(metadata, self.grant_limits(), staged)
        if sum(len(text.encode()) for text in checks["sources"].values()) > self.grant.max_bytes:
            raise PermissionError("Engineering byte ceiling exceeded at verification")
        return checks

    def grant_limits(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            max_files=self.grant.max_files,
            max_lines=self.grant.max_lines,
            allowed_directories=self.grant.writable_files,
        )

    def apply(self, metadata, changes, limits=None):
        if sum(len(c.content.encode()) for c in changes) > self.grant.max_bytes:
            raise PermissionError("Engineering byte ceiling exceeded")
        return super().apply(metadata, changes, self.grant_limits())


def run_approved_checks(grant, files, script, *, guard, resources=None):
    if hashlib.sha256(script.encode()).hexdigest() != grant.test_sha256:
        raise PermissionError("Unapproved acceptance test implementation")
    if set(files) != set(grant.writable_files):
        raise PermissionError("Checks require the complete exact candidate snapshot")
    checked_paths(grant.owner, files)
    ensure_no_secret(files)
    guard()
    if resources:
        resources.consume_tool()
    snapshot = {p: hashlib.sha256(text.encode()).hexdigest() for p, text in files.items()}
    result = OfflineSandbox().run(
        ["python", "-I", "-c", script], files, timeout=60, writable=(), guard=guard
    )
    guard()
    if result.files or result.deleted:
        raise PermissionError("Acceptance checks must be read-only")
    if resources and result.status == "EXITED" and result.exit_code == 0:
        resources.observe("authorized_read", "approved-checks:" + str(snapshot))
    return {
        "test_id": grant.test_id,
        "test_sha256": grant.test_sha256,
        "snapshot": snapshot,
        "image": result.image,
        "boundary": result.boundary,
        "exit_code": result.exit_code,
        "status": "PASS" if result.status == "EXITED" and result.exit_code == 0 else "FAIL",
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration": result.duration,
        "executed_at": now().isoformat(),
    }
