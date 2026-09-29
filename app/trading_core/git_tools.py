"""Host Git broker: bounded text changes on isolated branches; review before protected merge."""

import hashlib
import os
import stat
import subprocess
from pathlib import Path

from trading_core.control import beneath, relative_path
from trading_core.governance import assert_product_merge_allowed
from trading_core.security import ensure_no_secret
from trading_core.settings import ROOT


class GitChanges:
    def __init__(self, root=ROOT, worktrees=None):
        self.root = Path(root).resolve()
        self.worktrees = Path(worktrees or (ROOT / "data/temp/day3-worktrees")).resolve()

    def git(self, *args, cwd=None):
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper()
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "HOMEDRIVE",
                "HOMEPATH",
                "USERPROFILE",
                "PROGRAMFILES",
            }
        }
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=NUL", *args],
            cwd=cwd or self.root,
            env=env,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError("Git operation failed: " + args[0])
        return result.stdout.strip()

    def clean_baseline(self):
        if self.git("branch", "--show-current") != "main" or self.git("status", "--porcelain"):
            raise PermissionError("Protected baseline must be clean main")
        return self.git("rev-parse", "HEAD")

    def isolate(self, work_id, agent):
        if not all(
            c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for c in work_id
        ):
            raise ValueError("Unsafe work identifier")
        base = self.clean_baseline()
        branch = f"codex/triad/{agent.lower()}/{work_id}"
        path = (self.worktrees / work_id).resolve()
        if not path.is_relative_to(self.worktrees) or path.exists():
            raise PermissionError("Worktree collision")
        self.worktrees.mkdir(parents=True, exist_ok=True)
        self.git("worktree", "add", "-b", branch, str(path), base)
        return {
            "branch": branch,
            "base_commit": base,
            "worktree": str(path),
            "change_commit": None,
            "review_commit": None,
            "merge_commit": None,
        }

    @staticmethod
    def path(root, path, scopes):
        name = relative_path(path)
        if not any(beneath(name, p) for p in scopes) or Path(name).suffix.lower() not in {
            ".md",
            ".json",
            ".txt",
        }:
            raise PermissionError("Only scoped non-executable text changes allowed")
        if any(p.startswith(".") for p in Path(name).parts):
            raise PermissionError("Hidden paths denied")
        target = Path(root) / name
        for parent in (target, *target.parents):
            if parent == Path(root):
                break
            if parent.is_symlink() or (
                parent.exists()
                and getattr(parent.lstat(), "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
            ):
                raise PermissionError("Reparse point rejected")
        if not target.resolve().is_relative_to(Path(root).resolve()):
            raise PermissionError("Path escape")
        if target.exists() and target.stat().st_nlink > 1:
            raise PermissionError("Hardlink rejected")
        return target

    def apply(self, metadata, changes, limits):
        if (
            not changes
            or len(changes) > limits.max_files
            or len({c.path.casefold() for c in changes}) != len(changes)
        ):
            raise PermissionError("Change file count exceeded or duplicated")
        root = Path(metadata["worktree"])
        total = 0
        prepared = []
        for change in changes:
            ensure_no_secret(change.model_dump(mode="json"))
            target = self.path(root, change.path, limits.allowed_directories)
            old = target.read_bytes() if target.exists() else b""
            if target.exists() and hashlib.sha256(old).hexdigest() != change.original_sha256:
                raise PermissionError("Stale source hash")
            if not target.exists() and change.original_sha256 is not None:
                raise PermissionError("Unexpected base file")
            total += len(old.splitlines()) + len(change.content.splitlines())
            if len(old) > 32000 or len(change.content.encode()) > 32000:
                raise PermissionError("File size exceeded")
            if total > limits.max_lines:
                raise PermissionError("Change line ceiling exceeded")
            prepared.append((target, change))
        for target, change in prepared:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(change.content, encoding="utf-8", newline="\n")
        self.git("add", "--", *[c.path for c in changes], cwd=root)
        if not self.git("diff", "--cached", "--stat", cwd=root):
            raise ValueError("No effective change")
        return self.verify(metadata, limits, staged=True)

    def verify(self, metadata, limits, staged=False):
        root = Path(metadata["worktree"])
        paths = self.git(
            "diff",
            "--name-only",
            *(("--cached",) if staged else (metadata["base_commit"], "HEAD")),
            cwd=root,
        ).splitlines()
        if not paths or len(paths) > limits.max_files:
            raise PermissionError("Invalid changed file count")
        hashes = {}
        sources = {}
        lines = 0
        for path in paths:
            target = self.path(root, path, limits.allowed_directories)
            if not target.is_file():
                if metadata.get("reverts_commit"):
                    continue
                raise PermissionError("Deletion is not an approved Day 3 operation")
            if target.stat().st_size > 32000:
                raise PermissionError("File size exceeded")
            text = target.read_text(encoding="utf-8")
            ensure_no_secret(text)
            if path.endswith(".md") and not text.startswith("# "):
                raise ValueError("Markdown requires a level-one heading")
            if path.endswith(".json"):
                import json

                json.loads(text)
            hashes[path] = hashlib.sha256(target.read_bytes()).hexdigest()
            sources[path] = text
        diff = self.git(
            "diff",
            *(("--cached",) if staged else (metadata["base_commit"], "HEAD")),
            "--",
            cwd=root,
        )
        lines = sum(
            1
            for line in diff.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        )
        if lines > limits.max_lines:
            raise PermissionError("Diff line budget exceeded")
        self.git(
            "diff",
            "--check",
            *(("--cached",) if staged else (metadata["base_commit"], "HEAD")),
            cwd=root,
        )
        return {
            "passed": True,
            "checks": [
                "approved path scope",
                "file and diff ceilings",
                "UTF-8 and Markdown/JSON validation",
                "secret exclusion",
                "git diff --check",
            ],
            "hashes": hashes,
            "files": paths,
            "lines": lines,
            "sources": sources,
            "diff": diff,
        }


    def stage_autonomous(self, metadata):
        """Stage and validate an agent-authored run-worktree diff.

        Autonomous agents may edit broadly inside the run worktree. Core keeps authority:
        protected governance, secret scanning, diff validity and merge remain host-owned.
        """
        root = Path(metadata["worktree"]).resolve()
        if not root.is_relative_to(self.worktrees) or not root.exists():
            raise PermissionError("Autonomous diff must come from a Core-created worktree")
        self.git("add", "-A", cwd=root)
        paths = self.git("diff", "--cached", "--name-only", cwd=root).splitlines()
        if not paths:
            raise ValueError("Autonomous run produced no effective change")
        assert_product_merge_allowed(paths)
        for path in paths:
            relative_path(path)
            if any(part.startswith(".") and part not in {".github"} for part in Path(path).parts):
                raise PermissionError("Hidden or credential-bearing paths are not product output")
        diff = self.git("diff", "--cached", "--", cwd=root)
        ensure_no_secret(diff)
        self.git("diff", "--check", "--cached", cwd=root)
        hashes = {}
        for path in paths:
            target = root / path
            if target.is_file():
                hashes[path] = hashlib.sha256(target.read_bytes()).hexdigest()
        return {
            "passed": True,
            "checks": [
                "protected Core governance exclusion",
                "secret scan",
                "git diff --check",
            ],
            "hashes": hashes,
            "files": paths,
            "diff": diff,
        }

    def commit_autonomous(self, metadata, agent, summary="autonomous product improvement"):
        checks = self.stage_autonomous(metadata)
        self.git("commit", "-m", f"Triad {agent}: {summary}"[:180], cwd=metadata["worktree"])
        metadata["change_commit"] = self.git("rev-parse", "HEAD", cwd=metadata["worktree"])
        return metadata, checks

    def merge_autonomous(self, metadata):
        """Fast-forward an already machine-validated run branch; no human approval gate."""
        if self.clean_baseline() != metadata["base_commit"]:
            raise PermissionError("Main moved since the autonomous run started")
        paths = self.git(
            "diff", "--name-only", metadata["base_commit"], metadata["change_commit"],
            cwd=metadata["worktree"],
        ).splitlines()
        assert_product_merge_allowed(paths)
        self.git("merge", "--ff-only", metadata["change_commit"])
        metadata["merge_commit"] = self.git("rev-parse", "HEAD")
        return metadata

    def commit(self, metadata, agent):
        self.git(
            "commit",
            "-m",
            f"Triad {agent}: bounded reviewed-candidate improvement",
            cwd=metadata["worktree"],
        )
        metadata["change_commit"] = self.git("rev-parse", "HEAD", cwd=metadata["worktree"])
        return metadata

    def review_commit(self, metadata, review_id, decision):
        if self.git("rev-parse", "HEAD", cwd=metadata["worktree"]) != metadata["change_commit"]:
            raise PermissionError("Changed since review input")
        self.git(
            "commit",
            "--allow-empty",
            "-m",
            f"Triad independent review {review_id}: {decision}",
            cwd=metadata["worktree"],
        )
        metadata["review_commit"] = self.git("rev-parse", "HEAD", cwd=metadata["worktree"])
        return metadata

    def merge(self, metadata, review, limits):
        if (
            review.get("decision") != "APPROVE"
            or review.get("change_commit") != metadata["change_commit"]
            or not review.get("reviewer")
            or review.get("reviewer") == review.get("worker")
        ):
            raise PermissionError("Only matching independently reviewed work may merge")
        if (
            not metadata.get("review_commit")
            or self.git("rev-parse", "HEAD", cwd=metadata["worktree"]) != metadata["review_commit"]
        ):
            raise PermissionError("Review commit no longer matches")
        if self.clean_baseline() != metadata["base_commit"]:
            raise PermissionError("Baseline moved; fresh review required")
        proof = self.verify(metadata, limits)
        assert_product_merge_allowed(proof["files"])
        self.git(
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.eol=lf",
            "merge",
            "--no-ff",
            metadata["review_commit"],
            "-m",
            f"Triad protected merge after review {review['review_id']}",
        )
        metadata["merge_commit"] = self.git("rev-parse", "HEAD")
        return metadata

    def prepare_revert(self, metadata, work_id, agent):
        if not metadata.get("merge_commit"):
            raise PermissionError("Only merged changes can be rolled back")
        result = self.isolate(work_id, agent)
        self.git("revert", "--no-edit", metadata["change_commit"], cwd=result["worktree"])
        result["change_commit"] = self.git("rev-parse", "HEAD", cwd=result["worktree"])
        result["reverts_commit"] = metadata["change_commit"]
        return result
