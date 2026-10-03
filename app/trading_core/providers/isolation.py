"""Credential-free offline tool execution. Only the trusted host may create grants.

This is NOT a vendor login container. Vendor adapters must mediate *all* tool
calls before this boundary can establish safe native CLI execution.
"""

import json
import re
import threading
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import uuid4

from trading_core.providers.process import ManagedProcess
from trading_core.security import ensure_no_secret
from trading_core.settings import ROOT

IMAGE = "python@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285"
LABEL = "triad.offline-tools=1"
MAX_BYTES = 48000

# Runs as a different uid from tools. No host paths are mounted or read.
SEED = r"""
import json, os, pathlib, sys
d=json.load(sys.stdin)
root=pathlib.Path('/workspace')
for name, content in d['files'].items():
    p=root/name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')
for name in d['writable']:
    (root/name).mkdir(parents=True, exist_ok=True)
for p in root.rglob('*'):
    writable=any(p.is_relative_to(root/n) for n in d['writable'])
    p.chmod((0o777 if writable else 0o555) if p.is_dir() else (0o666 if writable else 0o444))
root.chmod(0o555)
"""

# All output is untrusted. Walk with dir fds and O_NOFOLLOW, including parents;
# hostile tools may still be running, so never resolve/follow their symlinks.
EXPORT = r"""
import json, os, stat
result={}; total=0; count=0
def walk(fd, prefix=''):
    global total, count
    for name in os.listdir(fd):
        count+=1
        if count>128: raise ValueError('too many workspace entries')
        s=os.stat(name, dir_fd=fd, follow_symlinks=False)
        path=prefix+name
        if stat.S_ISDIR(s.st_mode):
            child=os.open(name, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW, dir_fd=fd)
            try: walk(child, path+'/')
            finally: os.close(child)
        elif stat.S_ISREG(s.st_mode):
            child=os.open(name, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK, dir_fd=fd)
            try:
                opened=os.fstat(child)
                if not stat.S_ISREG(opened.st_mode) or opened.st_nlink!=1: raise ValueError('special or linked file')
                data=os.read(child, 48001)
                total+=len(data)
                if total>48000: raise ValueError('workspace output too large')
                result[path]=data.decode('utf-8')
            finally: os.close(child)
        else: raise ValueError('links and special files are not exportable')
fd=os.open('/workspace', os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try: walk(fd)
finally: os.close(fd)
print(json.dumps(result, ensure_ascii=False))
"""


def safe_path(path):
    if not isinstance(path, str) or not path or len(path) > 240:
        raise ValueError("Invalid workspace path")
    parts = PurePosixPath(path).parts
    if (
        not parts
        or path != str(PurePosixPath(path))
        or path.startswith("/")
        or any(p in {".", ".."} or p.startswith(".") for p in parts)
        or not re.fullmatch(r"[A-Za-z0-9_./ -]+", path)
    ):
        raise ValueError("Only relative, non-hidden workspace paths are accepted")
    return path


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    status: str
    stdout: str
    stderr: str
    duration: float
    files: dict[str, str]
    deleted: tuple[str, ...]
    image: str = IMAGE
    boundary: str = "DOCKER_OFFLINE_TOOLS"


class OfflineSandbox:
    """Run one tool against an explicit text snapshot, never a host directory.

    `writable` is a tuple of approved relative directories, not model-selected
    permissions. Files returned are proposals; this class never applies them.
    Supply the WorkItem/control-epoch guard for production use.
    """

    def __init__(self, image=None, *, profile="standard"):
        if image is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise ValueError("Test image must use an immutable local image ID")
        self.image = image or IMAGE
        if profile not in {"standard", "product"} or (profile == "product" and image is None):
            raise ValueError("Product resource profile requires a reviewed immutable image")
        self.profile = profile
        self.cancelled = threading.Event()
        self.runner = None

    def cancel(self):
        self.cancelled.set()
        if self.runner:
            self.runner.cancel()

    @staticmethod
    def _docker(args, *, stdin="", timeout=20, output_limit=131072):
        result = ManagedProcess().run(
            ["docker", *args],
            cwd=ROOT,
            stdin=stdin,
            timeout=timeout,
            output_limit=output_limit,
        )
        if result.status != "EXITED" or result.exit_code:
            raise RuntimeError("Isolated runtime operation failed: " + args[0])
        return result.stdout.strip()

    @classmethod
    def available(cls):
        try:
            return cls._docker(["info", "--format", "{{.OSType}}"]) == "linux" and bool(
                cls._docker(["image", "inspect", IMAGE, "--format", "{{.Id}}"])
            )
        except (OSError, RuntimeError):
            return False

    @staticmethod
    def create_options(name, image=IMAGE, *, profile="standard"):
        options = [
            "create",
            "--pull=never",
            "--name",
            name,
            "--label",
            LABEL,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--user=10002:10002",
            "--pids-limit=64",
            "--memory=256m",
            "--memory-swap=256m",
            "--cpus=1",
            "--ulimit",
            "nofile=128:128",
            "--ulimit",
            "fsize=67108864:67108864",
            "--restart=no",
            "--log-driver=none",
            "--ipc=none",
            "--tmpfs",
            "/workspace:rw,nosuid,nodev,noexec,size=64m,uid=10002,gid=10002,mode=0700",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777",
            "--workdir=/workspace",
            "--env=HOME=/tmp",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            "--entrypoint=python",
            image,
            "-I",
            "-c",
            "import time; time.sleep(180)",
        ]
        if profile == "product":
            replacements = {
                "--pids-limit=64": "--pids-limit=128",
                "--memory=256m": "--memory=768m",
                "--memory-swap=256m": "--memory-swap=768m",
                "nofile=128:128": "nofile=512:512",
                "/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777": "/tmp:rw,nosuid,nodev,noexec,size=96m,mode=1777",
            }
            options = [replacements.get(value, value) for value in options]
        elif profile != "standard":
            raise ValueError("Unknown sandbox resource profile")
        return options

    def run(
        self,
        argv,
        files,
        *,
        writable=(),
        timeout=30,
        guard=lambda: None,
        max_bytes=MAX_BYTES,
        max_files=64,
        export_failed=False,
    ):
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(x, str) and "\0" not in x for x in argv)
            or sum(len(x) for x in argv) > 16000
            or not 0 < timeout <= 120
        ):
            raise ValueError("A bounded argument vector and timeout are required")
        if type(max_bytes) is not int or not MAX_BYTES <= max_bytes <= 1000000:
            raise ValueError("Invalid host snapshot capacity")
        if type(max_files) is not int or not 64 <= max_files <= 2048:
            raise ValueError("Invalid host file capacity")
        if type(export_failed) is not bool:
            raise ValueError("Invalid host export policy")
        if not isinstance(files, dict) or len(files) > max_files or len(writable) > 5:
            raise ValueError("Workspace exceeds file/directory limit")
        files = {safe_path(k): v for k, v in files.items()}
        writable = tuple(safe_path(p) for p in writable)
        if not all(isinstance(v, str) for v in files.values()):
            raise ValueError("Only text snapshots are supported")
        if sum(len(v.encode()) for v in files.values()) > max_bytes:
            raise ValueError("Input snapshot too large")
        ensure_no_secret({"argv": argv, "files": files})

        def check():
            if self.cancelled.is_set():
                raise PermissionError("Isolated execution cancelled")
            guard()

        check()
        name = "triad-tools-" + uuid4().hex
        # No option comes from model output. In particular: no -v, env-file,
        # device, published port, privileged mode or host namespace is exposed.
        options = self.create_options(name, self.image, profile=self.profile)
        try:
            self._docker(options)
            check()
            self._docker(["start", name])
            self._docker(
                ["exec", "-i", name, "python", "-I", "-c", SEED],
                stdin=json.dumps({"files": files, "writable": writable}),
            )
            self.runner = ManagedProcess()
            result = self.runner.run(
                ["docker", "exec", "--user=10001:10001", name, *argv],
                cwd=ROOT,
                timeout=timeout,
                guard=check,
            )
            check()
            if result.status != "EXITED" or (result.exit_code != 0 and not export_failed):
                return SandboxResult(
                    result.exit_code,
                    result.status,
                    result.stdout,
                    result.stderr,
                    result.duration,
                    {},
                    (),
                    image=self.image,
                )
            export_script = (
                EXPORT.replace("48001", str(max_bytes + 1))
                .replace(">48000", ">" + str(max_bytes))
                .replace(">128", ">" + str(max_files * 8))
            )
            # Valid text snapshots can exceed ordinary command output capacity.
            # JSON escapes use at most six bytes per source byte; path overhead
            # is bounded by safe_path and the host's file count. This larger
            # capacity applies only to the fixed host export, never model tools.
            export_capacity = max(131072, max_bytes * 6 + max_files * 256 + 4096)
            exported = json.loads(
                self._docker(
                    ["exec", name, "python", "-I", "-c", export_script],
                    output_limit=export_capacity,
                )
            )
            check()
            if not isinstance(exported, dict):
                raise TypeError("Invalid workspace export")
            if len(exported) > max_files:
                raise ValueError("Exported workspace exceeds file capacity")
            changed = {}
            deleted = []
            for path in set(files) | set(exported):
                safe_path(path)
                if path in exported and not isinstance(exported[path], str):
                    raise ValueError("Invalid file output")
                if files.get(path) == exported.get(path):
                    continue
                if not any(path.startswith(p + "/") for p in writable):
                    raise PermissionError("Tool changed a path outside its write grant")
                if path in exported:
                    changed[path] = exported[path]
                else:
                    deleted.append(path)
            ensure_no_secret(changed)
            return SandboxResult(
                result.exit_code,
                result.status,
                result.stdout,
                result.stderr,
                result.duration,
                changed,
                tuple(sorted(deleted)),
                image=self.image,
            )
        finally:
            # Killing the docker client alone would leave the daemon's process
            # alive. Forced removal also kills descendants and erases tmpfs.
            self._docker(["rm", "--force", name])
            self.runner = None
