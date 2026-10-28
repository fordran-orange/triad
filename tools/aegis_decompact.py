"""Rewrite a compacted (layout 2) Aegis experiment's trials back into plain chunks.

    python tools/aegis_decompact.py <experiment_id> [--data-root <path>] [--dry-run]

Every part's rows are written back as `NNNNNN.parquet`, grouped by their `chunk` column, with
their layout-2 columns as they are; then the manifest and the parts are removed, so tools that
read chunk files see every trial again. The folder stays layout 2 (its chunks carry `trial_no`),
so the worker still projects it to the legacy columns and a resume keeps writing layout-2 chunks.
Refused while the experiment is `running` or `queued`; nothing is written or removed before every
check has passed (`products.aegis.lab.store.decompact`). Prints the report as JSON.

Optimization Lab v2, Phase 2, Task 5. Retained-data tool: independent QA at R3 (AGENTS.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

REFUSED_STATUSES = ("running", "queued")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("experiment_id")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="the Aegis data root (default: AEGIS_DATA_ROOT, else the checkout's data/aegis)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change and change nothing"
    )
    args = parser.parse_args(argv)

    from products.aegis.experiments import ExperimentStore
    from products.aegis.lab import store as lab_store
    from products.aegis.runs import JsonRunRepository

    store = ExperimentStore(JsonRunRepository(args.data_root))
    try:
        document = store.get(args.experiment_id)
    except KeyError:
        print(f"refused: no experiment {args.experiment_id!r}", file=sys.stderr)
        return 2
    if document.status in REFUSED_STATUSES:
        print(
            f"refused: experiment {args.experiment_id} is {document.status}; "
            "pause it or let it finish first",
            file=sys.stderr,
        )
        return 2
    cells_dir = store.cells_dir(args.experiment_id)
    try:
        report = lab_store.decompact(cells_dir, dry_run=args.dry_run)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"experiment_id": args.experiment_id, "dry_run": args.dry_run, **report},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
