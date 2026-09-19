"""Build the credential-free executor image from the pinned official npm binary."""

import base64
import hashlib
import io
import subprocess
import tarfile
import urllib.request
from pathlib import Path

from triad.day5a.isolation import IMAGE

VERSION = "0.155.0-alpha.2.6"
INTEGRITY = (
    "SoHKksEPErOt1TvsWGLF2wUoJTQ8M+nAajBn/p/hrHo5CyXpl1aGO4RL5hHdZ5HDcFiR6cKtOYXv0fgsEIcJzw=="
)
TAG = "triad-codex-executor:0.155.0-alpha.2.6"


def main():
    root = Path(__file__).resolve().parents[1]
    build = root / "data/temp/codex-executor-build"
    build.mkdir(parents=True, exist_ok=True)
    url = f"https://registry.npmjs.org/@openai/codex/-/codex-{VERSION}-linux-x64.tgz"
    cache = build / "package.tgz"
    if cache.exists():
        data = cache.read_bytes()
    else:
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
        cache.write_bytes(data)
    if base64.b64encode(hashlib.sha512(data).digest()).decode() != INTEGRITY:
        raise RuntimeError("Executor package integrity mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        matches = [m for m in archive.getmembers() if m.name.endswith("/bin/codex")]
        if len(matches) != 1 or not matches[0].isfile():
            raise RuntimeError("Unexpected executor package layout")
        with archive.extractfile(matches[0]) as source:
            (build / "codex").write_bytes(source.read())
    (build / "Dockerfile").write_text(
        f"FROM {IMAGE}\nCOPY --chmod=0555 codex /usr/local/bin/codex\n"
        f'LABEL triad.executor.version="{VERSION}"\n'
        "RUN codex --version\n",
        encoding="utf-8",
    )
    (build / ".dockerignore").write_text("*\n!Dockerfile\n!codex\n", encoding="utf-8")
    subprocess.run(["docker", "build", "--tag", TAG, str(build)], check=True)


if __name__ == "__main__":
    main()
