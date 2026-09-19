"""Restricted file broker. No provider receives OS tools, credentials or a shell."""

import hashlib
import stat
import time
from pathlib import Path

from trading_core.control import PROTECTED, beneath, relative_path
from trading_core.settings import ROOT
from trading_core.work import WorkItem


class ToolGateway:
    def __init__(self, work: WorkItem, root: Path = ROOT):
        self.work = WorkItem.model_validate(work.model_dump())
        self.root = root.resolve()
        self.calls = 0
        self.started = time.monotonic()
        self.evidence: list[str] = []
        self.changed: list[str] = []

    def check(self, tool: str, path: str) -> Path:
        self.calls += 1
        if (
            self.calls > self.work.compute_budget.max_tool_calls
            or time.monotonic() - self.started > self.work.compute_budget.timeout_seconds
        ):
            raise PermissionError("Tool/time budget exhausted")
        if tool not in self.work.allowed_tools:
            raise PermissionError("Tool not granted")
        relative = relative_path(path)
        # Product content and mixed operator notes are not shared model context.
        for product in ("triad", "p2p"):
            if self.work.owner != product and any(
                beneath(relative, prefix)
                for prefix in (
                    f"products/{product}",
                    f"app/products/{product}",
                    f"docs/vault/{product}",
                    f"research/{product}",
                )
            ):
                raise PermissionError("Cross-product artifact access denied")
        if (
            beneath(relative, "docs/improvements")
            or beneath(relative, "research/improvements")
            or beneath(relative, "research/experiments")
            or beneath(relative, "research/generated")
            or beneath(relative, "docs/vault/02_Journal/generated")
        ):
            # Canonical record registration wins; legacy unregistered outputs belong
            # to the original Triad lineage. Unknown products cannot read them.
            owner = "triad"
            if self.root == ROOT.resolve():
                from trading_core.store import Store

                with Store().connect() as conn:
                    row = conn.execute(
                        "SELECT owner FROM core.artifact_owners WHERE path=%s", (relative,)
                    ).fetchone()
                if row:
                    owner = row["owner"]
            for product in ("core", "p2p", "triad"):
                if beneath(relative, "research/generated/" + product):
                    owner = product
            if self.work.owner != owner:
                raise PermissionError("Cross-product artifact access denied")
        if beneath(relative, "docs/vault") and not beneath(relative, "docs/vault/02_Journal/generated"):
            raise PermissionError("Operator notes are not agent context")
        if any(
            p.casefold() in {".git", ".venv", ".env"} or p.casefold().startswith(".env.")
            for p in relative.split("/")
        ):
            raise PermissionError("Secret and runtime paths cannot enter agent scope")
        if any(beneath(relative, p) for p in (*PROTECTED, *self.work.forbidden_paths)):
            raise PermissionError("Protected or explicitly forbidden path")
        if not any(beneath(relative, p) for p in self.work.allowed_paths):
            raise PermissionError("Path outside assignment scope")
        if tool == "write_artifact":
            research = beneath(relative, "research/generated")
            code = beneath(relative, "app/extensions")
            if not (
                (
                    research
                    and self.work.authority_tier >= 1
                    and "write_research" in self.work.execution_permissions
                )
                or (
                    code
                    and self.work.authority_tier >= 2
                    and "write_code" in self.work.execution_permissions
                )
            ):
                raise PermissionError("Write requires an approved tier and supported output root")
        elif "read" not in self.work.execution_permissions:
            raise PermissionError("Read permission missing")
        target = self.root / relative
        for part in [target, *target.parents]:
            if part == self.root:
                break
            if part.is_symlink() or (
                part.exists()
                and getattr(part.lstat(), "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
            ):
                raise PermissionError("Reparse points and symlinks are not allowed")
        if not target.resolve().is_relative_to(self.root):
            raise PermissionError("Resolved path escaped project")
        if target.exists() and target.is_file() and target.stat().st_nlink > 1:
            raise PermissionError("Hard-linked files are not allowed")
        return target

    def read(self, path: str) -> str:
        target = self.check("read_file", path)
        if target.stat().st_size > 64000:
            raise PermissionError("File exceeds bounded read size")
        data = target.read_bytes()
        self.evidence.append(f"sha256:{hashlib.sha256(data).hexdigest()}:{path}")
        return data.decode("utf-8-sig")

    def write(self, path: str, content: str) -> None:
        if len(content.encode()) > 64000:
            raise PermissionError("Artifact too large")
        target = self.check("write_artifact", path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Existing files are never overwritten; source-code changes remain future reviewed patches.
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        self.changed.append(path)
        self.evidence.append(f"sha256:{hashlib.sha256(target.read_bytes()).hexdigest()}:{path}")
