"""Build the credential-free test image from reviewed pinned dependencies."""

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
dockerfile = root / "infrastructure/product-tests.Dockerfile"
lock = root / "requirements.lock"
digest = hashlib.sha256(dockerfile.read_bytes() + lock.read_bytes()).hexdigest()
tag = "triad-product-tests:" + digest[:16]
with tempfile.TemporaryDirectory(prefix="triad-product-image-") as directory:
    shutil.copyfile(dockerfile, Path(directory) / "Dockerfile")
    shutil.copyfile(lock, Path(directory) / "requirements.lock")
    subprocess.run(
        ["docker", "build", "--label", "org.triad.product-tests=" + digest, "-t", tag, directory],
        check=True,
    )
print(
    subprocess.check_output(
        ["docker", "image", "inspect", tag, "--format", "{{.Id}}"], text=True
    ).strip()
)
