"""Standalone reader: Python + pyarrow only; no Triad import or running services."""

import argparse
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq


def validate(root, dataset_manifest, run_manifest):
    root = Path(root).resolve()
    dataset = json.loads(Path(dataset_manifest).read_text(encoding="utf-8"))
    run = json.loads(Path(run_manifest).read_text(encoding="utf-8"))
    assert run["status"] == "COMPLETED", "Run is not a completed result"
    row_count = 0
    for relative in dataset["canonical_paths"]:
        path = (root / relative).resolve()
        assert path.is_relative_to(root), "Archive escaped bundle root"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == dataset["file_checksums"][relative]
        row_count += pq.ParquetFile(path).read().num_rows
    assert row_count == dataset["row_count"]
    artifacts = {}
    for name, artifact in run["result_artifacts"].items():
        path = (root / artifact["path"]).resolve()
        assert path.is_relative_to(root)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
        artifacts[name] = (
            pq.ParquetFile(path).read().to_pylist()
            if path.suffix == ".parquet"
            else json.loads(path.read_text(encoding="utf-8"))
        )
    assert artifacts["metrics"] == run["metrics"]
    assert artifacts["parameters"]["dataset_version"] == dataset["dataset_version"]
    return {
        "dataset_rows": row_count,
        "trades": len(artifacts["trades"]),
        "equity_points": len(artifacts["equity"]),
        "metrics_directions": sorted(artifacts["metrics"]),
        "services_required": False,
        "hashes": "PASS",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root")
    parser.add_argument("dataset_manifest")
    parser.add_argument("run_manifest")
    args = parser.parse_args()
    print(json.dumps(validate(args.root, args.dataset_manifest, args.run_manifest), indent=2))
