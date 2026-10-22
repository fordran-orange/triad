"""Mission 12: a real QQQ 1-minute study's canonical output, so today's study path and the frame
path can be compared on real bars (DST changes, session gaps). Nothing is saved to the operator's
store: the study runs in a temporary repository on the raw archive.

    .venv-aegis\\Scripts\\python.exe tests\\products\\aegis\\study_identity.py capture OUT.json
    .venv-aegis\\Scripts\\python.exe tests\\products\\aegis\\study_identity.py compare OUT.json

`capture` writes the canonical output (the document's windows and report, and every full window
record); `compare` runs the same study again and reports the first difference, or "identical".
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tests"))

START, END = date(2025, 1, 2), date(2025, 4, 30)
IN_SAMPLE, OUT_OF_SAMPLE = 6_000, 3_000


def canonical(repository, document) -> dict:
    from products.aegis.studies import StudyStore

    store = StudyStore(repository)
    full = {
        symbol: [store.read_window(document.id, symbol, w["index"]) for w in windows]
        for symbol, windows in document.windows.items()
    }
    return json.loads(
        json.dumps(
            {"windows": document.windows, "report": document.report, "full": full}, default=str
        )
    )


def run_study() -> tuple[dict, float]:
    from products.aegis import api
    from products.aegis.data import ArchiveStore
    from products.aegis.jobs import JobRunner
    from products.aegis.runs import JsonRunRepository
    from products.aegis.studies import StudyJob, StudyRequest, StudyStore, create_study
    from test_aegis_studies import make_parent

    store = ArchiveStore()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as folder:
        repository = JsonRunRepository(Path(folder) / "aegis")
        experiments, parent = make_parent(repository)
        data = parent.data.model_copy(update={"timeframe": "1m", "start": START, "end": END})
        parent = parent.model_copy(update={"data": data})
        experiments.save(parent)
        bars, pinned = api._study_bars(store, ["QQQ"], "1m", START, END)
        request = StudyRequest(
            experiment_id=parent.id,
            name="study identity",
            symbols=["QQQ"],
            in_sample_bars=IN_SAMPLE,
            out_of_sample_bars=OUT_OF_SAMPLE,
        )
        document = create_study(
            StudyStore(repository),
            experiments,
            request,
            api._timestamps(bars),
            2,
            START,
            END,
            data={symbol: api._provenance(source) for symbol, source in pinned.items()},
        )
        JobRunner(repository).start(StudyJob(document, bars, pinned, repository))
        studies = StudyStore(repository)
        while studies.get(document.id).status not in ("done", "failed", "cancelled"):
            time.sleep(0.5)
        done = studies.get(document.id)
        assert done.status == "done", done.error
        return canonical(repository, done), time.perf_counter() - started


def first_difference(a, b, path="") -> str | None:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}/{key}: present on one side only"
            found = first_difference(a[key], b[key], f"{path}/{key}")
            if found:
                return found
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} items vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            found = first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if a == b else f"{path}: {a!r} vs {b!r}"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mode, out = sys.argv[1], Path(sys.argv[2])
    output, seconds = run_study()
    windows = len(output["windows"].get("QQQ", []))
    if mode == "capture":
        out.write_text(json.dumps(output, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"captured {windows} windows in {seconds:.1f} s -> {out} ({out.stat().st_size:,} bytes)"
        )
        return
    found = first_difference(json.loads(out.read_text(encoding="utf-8")), output)
    print(
        f"{windows} windows in {seconds:.1f} s: "
        + ("identical" if found is None else f"DIFFERENT at {found}")
    )
    sys.exit(0 if found is None else 1)


if __name__ == "__main__":
    main()
