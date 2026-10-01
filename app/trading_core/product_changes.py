"""Host-staged product changes. Models supply data, never host commands or authority."""

import hashlib
import json
import stat
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from trading_core.control import beneath, relative_path
from trading_core.git_tools import GitChanges
from trading_core.governance import assert_product_merge_allowed
from trading_core.providers.isolation import OfflineSandbox
from trading_core.security import ensure_no_secret
from trading_core.work import Record

PRODUCT_ROOTS = ("app/products/triad", "products/triad", "tests/products/triad")


class ProductFileChange(Record):
    """Explicit product operations; renames are a reviewed delete plus write."""

    path: str
    operation: Literal["WRITE", "DELETE"] = "WRITE"
    content: str | None = Field(default=None, max_length=1000000)
    original_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_operation(self):
        product_path(self.path)
        if self.operation == "DELETE":
            if self.content is not None or self.original_sha256 is None:
                raise ValueError("Delete requires an original hash and no replacement content")
        elif self.content is None:
            raise ValueError("Write requires replacement content")
        return self


class RequiredCheck(Record):
    check_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    method: Literal["SOURCE_REVIEW", "PYTHON_UNIT_TEST"]
    description: str = Field(min_length=1)


class CheckAssessment(Record):
    check_id: str
    status: Literal["VERIFIED", "NOT_VERIFIED", "BLOCKED"]
    evidence_ids: tuple[str, ...]
    reason: str = Field(min_length=1)


class AcceptanceAssessment(Record):
    checks: tuple[CheckAssessment, ...]


def acceptance_problems(required, assessment, commit, proofs):
    """An approval cannot waive missing, stale or unsuccessful required checks."""
    required = [RequiredCheck.model_validate(c) for c in required]
    assessment = AcceptanceAssessment.model_validate(assessment)
    expected = {c.check_id for c in required}
    actual = [c.check_id for c in assessment.checks]
    if (
        not required
        or len(expected) != len(required)
        or len(actual) != len(set(actual))
        or set(actual) != expected
    ):
        return ("Every mandatory criterion requires exactly one assessment",)
    source = "candidate:" + commit
    evidence = {source, *proofs}
    failures = []
    for required_check in required:
        checked = next(c for c in assessment.checks if c.check_id == required_check.check_id)
        # Accept only known labels attached to the exact host-supplied IDs.
        # Retain the raw assessment for provenance; never resolve arbitrary IDs.
        references = set()
        for identifier in checked.evidence_ids:
            prefix, separator, value = identifier.partition(":")
            if (
                separator
                and prefix in {"test_record_id", "repeated_test_record_id"}
                and value in proofs
            ):
                references.add(value)
            else:
                references.add(identifier)
        if checked.status != "VERIFIED" or not checked.evidence_ids or not references <= evidence:
            failures.append(required_check.check_id + ": evidence is missing or unverified")
        if required_check.method == "SOURCE_REVIEW" and source not in references:
            failures.append(required_check.check_id + ": exact candidate source review required")
        if required_check.method == "PYTHON_UNIT_TEST" and (
            not proofs
            or not set(proofs) <= references
            or any(
                p.get("status") != "PASS"
                or p.get("test_status") != "PASSED"
                or p.get("executed_tests", 0) < 1
                or p.get("commit") != commit
                for p in proofs.values()
            )
        ):
            failures.append(
                required_check.check_id + ": passing exact-candidate unit tests required"
            )
    return tuple(failures)


# The autonomous developers cannot rewrite their own coordinator or its tests.
ORCHESTRATION = (
    "__init__.py",
    "api.py",
    "server.py",
    "acceptance.py",
    "contracts.py",
    "cycles.py",
    "cycle_history.py",
    "jobs.py",
    "ledger.py",
    "scheduler.py",
    "resources.py",
    "readiness.py",
    "qa_reference.py",
    "daily",
    "development",
    "sequential",
    "no_change.py",
    "static/day3",
    "static/daily",
    "static/cycles",
    "static/development",
    "resources/",
)


def reviewed_test_image():
    from trading_core.settings import ROOT

    digest = hashlib.sha256(
        (ROOT / "infrastructure/product-tests.Dockerfile").read_bytes()
        + (ROOT / "requirements.lock").read_bytes()
    ).hexdigest()
    row = json.loads(
        subprocess.check_output(
            ["docker", "image", "inspect", "triad-product-tests:" + digest[:16]], text=True
        )
    )[0]
    if row.get("Config", {}).get("Labels", {}).get("org.triad.product-tests") != digest:
        raise PermissionError("Product test image does not match reviewed pinned dependencies")
    return row["Id"]


def activate(records, implementation, commit):
    from trading_core.intelligence.quality import Quality

    if records.store.scope is not None:
        raise PermissionError("Only Core can activate product execution")
    qa = Quality(records).require_pass(implementation, commit)
    image = reviewed_test_image()
    if not any(image in check for check in qa["tests_repeated"]):
        raise PermissionError("Independent QA must identify the tested immutable image")
    build = records.get(implementation)
    if build["owner"] != "core" or "app/products/triad/sequential.py" not in build["files"]:
        raise PermissionError("Independent review of the sequential executor is required")
    records.ledger.guard()
    return records.append(
        "ProductCyclePolicy",
        {
            "implementation": implementation,
            "commit": commit,
            "qa_id": qa["id"],
            "enabled": True,
            "order": ["CODEX", "CLAUDE", "GROK"],
            "token_policy": "TARGET",
            "acceptance_contract": "required-checks-v1",
            "maintenance_only": ["LOCAL_QWEN"],
            "test_image": image,
        },
    )


def active_policy(records):
    from trading_core.intelligence.quality import Quality

    policies = records.list("ProductCyclePolicy")
    if not policies or not policies[-1].get("enabled"):
        raise PermissionError("Reviewed sequential product policy has not been activated")
    policy = policies[-1]
    qa = Quality(records).require_pass(policy["implementation"], policy["commit"])
    if qa["id"] != policy["qa_id"] or policy["owner"] != "core":
        raise PermissionError("Product policy approval changed")
    return policy


def protected_orchestration(path):
    value = path.casefold()
    prefix = "app/products/triad/"
    if not value.startswith(prefix):
        return False
    tail = value[len(prefix) :]
    return any(
        tail == p
        or (
            p.endswith(("/", "daily", "development", "sequential", "day3", "cycles"))
            and tail.startswith(p)
        )
        for p in ORCHESTRATION
    )


def product_path(path):
    if relative_path(path) != path or not any(beneath(path, p) for p in PRODUCT_ROOTS):
        raise PermissionError("Change must belong to the active product")
    assert_product_merge_allowed((path,))
    if protected_orchestration(path):
        raise PermissionError("Triad orchestration is protected")
    if any(p.startswith(".") for p in Path(path).parts):
        raise PermissionError("Hidden product paths are protected")
    return path


class ProductGit(GitChanges):
    def __init__(self, approved_files, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.approved_files = tuple(approved_files)
        if not self.approved_files or len({p.casefold() for p in approved_files}) != len(
            approved_files
        ):
            raise PermissionError("An unambiguous reviewed file manifest is required")
        for p in self.approved_files:
            product_path(p)

    def path(self, root, path, scopes=None):
        product_path(path)
        if path not in self.approved_files:
            raise PermissionError("File was not in the independently approved proposal")
        root = Path(root).resolve()
        target = root / path
        for parent in (target, *target.parents):
            if parent == root:
                break
            if parent.is_symlink() or (
                parent.exists()
                and getattr(parent.lstat(), "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
            ):
                raise PermissionError("Aliased product path rejected")
        if not target.resolve().is_relative_to(root) or (
            target.exists() and target.stat().st_nlink > 1
        ):
            raise PermissionError("Escaping or linked product file rejected")
        return target

    def apply(self, metadata, changes, limits=None):
        names = [c.path for c in changes]
        if not names or len({p.casefold() for p in names}) != len(names):
            raise PermissionError("Missing or duplicate product patch")
        prepared = []
        for c in changes:
            target = self.path(metadata["worktree"], c.path)
            ensure_no_secret(c.model_dump(mode="json"))
            previous = None
            fingerprints = {None}
            if target.exists():
                raw = target.read_bytes()
                previous = hashlib.sha256(raw).hexdigest()
                fingerprints = {previous}
                # Workspace snapshots use read_text's universal newlines. Git
                # may materialize the same committed text as CRLF on Windows.
                # Retain raw hashes for existing patch callers; normalize only
                # newlines, never other whitespace or missing/empty files.
                try:
                    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
                except UnicodeDecodeError:
                    pass
                else:
                    fingerprints.add(hashlib.sha256(text.encode("utf-8")).hexdigest())
            if c.original_sha256 not in fingerprints:
                raise PermissionError("Product source changed since proposal")
            operation = getattr(c, "operation", "WRITE")
            if operation == "DELETE" and previous is None:
                raise PermissionError("Cannot delete a missing product file")
            prepared.append((target, c.content, operation))
        for target, content, operation in prepared:
            if operation == "DELETE":
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="\n")
        self.git("add", "--", *names, cwd=metadata["worktree"])
        return self.verify(metadata, staged=True)

    def verify(self, metadata, limits=None, staged=False):
        root = metadata["worktree"]
        revisions = ("--cached",) if staged else (metadata["base_commit"], "HEAD")
        paths = self.git("diff", "--no-renames", "--name-only", *revisions, cwd=root).splitlines()
        deleted = set(
            self.git(
                "diff", "--no-renames", "--diff-filter=D", "--name-only", *revisions, cwd=root
            ).splitlines()
        )
        if not paths:
            raise ValueError("No effective product change")
        sources = {}
        hashes = {}
        for p in paths:
            target = self.path(root, p)
            if p in deleted:
                if target.exists():
                    raise PermissionError("Deleted path has an unreviewed replacement")
                sources[p] = None
                hashes[p] = None
                continue
            if not target.is_file():
                raise PermissionError("Candidate file is missing")
            text = target.read_text(encoding="utf-8")
            ensure_no_secret(text)
            if p.endswith(".json"):
                json.loads(text)
            sources[p] = text
            hashes[p] = hashlib.sha256(target.read_bytes()).hexdigest()
        self.git("diff", "--check", *revisions, cwd=root)
        return {
            "passed": True,
            "files": paths,
            "sources": sources,
            "hashes": hashes,
            "diff": self.git("diff", *revisions, "--", cwd=root),
            "checks": [
                "Protected governance and orchestration excluded",
                "Exact reviewed product paths",
                "Secret scan",
                "git diff --check",
            ],
        }


def check_candidate(files, guard, image=None):
    """Trusted test program in a network-free, credential-free disposable container."""
    for p in files:
        product_path(p)
    script = """import ast, json, pathlib, unittest, sys
sys.path.insert(0, str(pathlib.Path('app').resolve()))
count=0
root=pathlib.Path('.')
for p in root.rglob('*'):
 if p.is_file() and p.suffix=='.py': ast.parse(p.read_text(),filename=str(p))
 if p.is_file() and p.suffix=='.json': json.loads(p.read_text())
tests=root/'tests/products/triad'
if tests.exists():
 suite=unittest.defaultTestLoader.discover(str(tests))
 count=suite.countTestCases()
 result=unittest.TextTestRunner().run(suite)
 if not result.wasSuccessful(): raise SystemExit(1)
print(json.dumps({'syntax':'PASS','unit_tests':count,'test_status':'PASSED' if count else 'NOT_PRESENT'}))
"""
    result = OfflineSandbox(image=image).run(
        ["python", "-B", "-c", script],
        files,
        writable=(),
        timeout=120,
        guard=guard,
        max_bytes=1000000,
    )
    if result.status != "EXITED" or result.exit_code != 0:
        raise ValueError("Isolated product checks failed: " + result.stderr[-2000:])
    measured = json.loads(result.stdout.strip().splitlines()[-1])
    return {
        "status": "PASS",
        "executed_tests": measured["unit_tests"],
        "test_status": measured["test_status"],
        "stdout": result.stdout,
        "boundary": result.boundary,
        "image": result.image,
        "snapshot": {p: hashlib.sha256(s.encode()).hexdigest() for p, s in files.items()},
    }
