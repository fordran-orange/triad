"""Build only reviewed, explicit inputs; never send repository data or secrets."""

import subprocess
import tempfile
from pathlib import Path

from trading_core.product_changes import test_image_digest
from trading_core.product_sdk import SDK_FILES
from trading_core.settings import ROOT


def main():
    digest = test_image_digest(ROOT)
    with tempfile.TemporaryDirectory(prefix="triad-product-image-") as temporary:
        context = Path(temporary)
        for path in (
            "infrastructure/product-tests.Dockerfile",
            "requirements.lock",
            "infrastructure/product-tests.lock",
            *SDK_FILES,
        ):
            target = context / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / path).read_bytes())
        subprocess.run(
            [
                "docker",
                "build",
                "--label",
                "org.triad.product-tests=" + digest,
                "-t",
                "triad-product-tests:" + digest[:16],
                "-f",
                str(context / "infrastructure/product-tests.Dockerfile"),
                str(context),
            ],
            check=True,
            timeout=900,
        )
    print("Reviewed test image: triad-product-tests:" + digest[:16])


if __name__ == "__main__":
    main()
