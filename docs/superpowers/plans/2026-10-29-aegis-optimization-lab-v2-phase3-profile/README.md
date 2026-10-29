# Phase 3 Task 0 evidence: the R3 Track A and Track B misses, profiled in process (2026-10-29)

The scripts that measured the causes behind the Phase 3 plan's Task 0, with their saved outputs.
They ran on the Aegis interpreter (`C:\Triad\.venv-aegis\Scripts\python.exe`, `PYTHONPATH` set to
the worktree's `app`) against a copy of the 1M synthetic fixture `demo-synthetic-1m` (made by
`tests/products/aegis/lab_fixture.py`), never against the scratch root or the product store. The
copy itself (`data/`) is not kept here.

- `common.py`: loads the copied fixture, a `LabCache` and the benchmark's request set.
- `prof1.py`: per-request timings, cache traffic and memory, in the benchmark's order.
- `prof2.py` (`prof2-summary.txt`, `prof2-matrix.txt`): cProfile of summary and the aggregate matrix.
- `prof3.py`: memory tracing (`tracemalloc`, the Arrow pool, `release_unused()`).
- `prof4.py` (`prof4.txt`): the cache-miss read and `_canonical`.
- `prof5.py`: prototypes of the fixes, each compared bit for bit with the current code.
- `prof6.py`, `prof7.py`: the experiment job's host growth (`analysis.neighbours_sampled`, `clusters`).
