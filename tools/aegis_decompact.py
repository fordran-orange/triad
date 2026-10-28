"""Rewrite a compacted (layout 2) Aegis experiment's trials back into plain chunks.

    python tools/aegis_decompact.py <experiment_id> [--data-root <path>] [--dry-run]

A stub from Optimization Lab v2, Phase 2, Task 1 (both lint lists name it); Task 5 implements it.
"""

from __future__ import annotations

from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    print("not implemented until Task 5")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
