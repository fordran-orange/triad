"""Shared setup for the Lab profiling scripts: a copy of the 1M fixture under this folder."""
import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
EXP = "demo-synthetic-1m"


class PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t),
    ]


def mem():
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wt.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
    k32.K32GetProcessMemoryInfo.restype = wt.BOOL
    ok = k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    assert ok, ctypes.get_last_error()
    return {"ws_mb": pmc.WorkingSetSize / 2**20, "private_mb": pmc.PrivateUsage / 2**20,
            "peak_ws_mb": pmc.PeakWorkingSetSize / 2**20}


def setup():
    from trading_core.process_power import opt_out_of_power_throttling
    opt_out_of_power_throttling()
    from products.aegis import api
    from products.aegis.experiments import ExperimentStore
    from products.aegis.lab.cache import LabCache
    from products.aegis.runs import JsonRunRepository

    store = ExperimentStore(JsonRunRepository(DATA))
    cache = LabCache()
    document = store.get(EXP)
    source = f"exp:{EXP}"

    def call(method, path, body):
        if path.endswith("/summary"):
            return api.lab_summary(source, runner=None, experiments=store, cache=cache)
        request = api.QueryRequest.model_validate(body)
        return api.lab_query(source, request, runner=None, experiments=store, cache=cache)

    return store, cache, document, call


def operations(document):
    paths = [p.path for p in document.surface.parameters]
    values = {p.path: p.values() for p in document.surface.parameters}
    objective = document.objective
    lab = f"lab/{quote(f'exp:{document.id}', safe=':')}"
    matrix = {"view": "matrix", "rows": paths[0], "cols": paths[1], "metric": objective,
              "mode": "aggregate"}
    two_ranges = {"ranges": {path: [values[path][1], values[path][-2]] for path in paths[2:4]}}
    middle = values[paths[2]][len(values[paths[2]]) // 2]

    def query(flt=None, **body):
        return ("POST", f"{lab}/query", {"filter": flt or {}, **body})

    return {
        "open": [("GET", f"{lab}/summary", None), query(**matrix),
                 query(view="page", offset=0, limit=500)],
        "filter_heatmap": [query(two_ranges, **matrix), query(two_ranges, view="counts")],
        "stat_change": [query(**matrix | {"stat": "median"})],
        "page": [query(view="page", offset=123456, limit=500)],
        "exact_slice": [query(**matrix | {"mode": "exact", "fixed": {paths[2]: middle}})],
        "parallel": [query(view="parallel", axes=paths[:6], metric=objective)],
    }


def label(step):
    method, path, body = step
    if body is None:
        return "summary"
    b = dict(body)
    tag = b["view"]
    if b["view"] == "matrix":
        tag += f"/{b.get('mode')}/{b.get('stat', 'best')}"
    if b["filter"]:
        tag += "+ranges"
    return tag
