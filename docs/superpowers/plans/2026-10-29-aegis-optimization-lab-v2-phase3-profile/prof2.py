"""cProfile of each slow request, warm (its cache entry loaded by the call just before)."""
import cProfile
import io
import pstats
import sys
import time

from common import label, operations, setup

store, cache, document, call = setup()
ops = operations(document)
steps = [ops["open"][0], ops["open"][1], ops["open"][2], ops["filter_heatmap"][0],
         ops["filter_heatmap"][1], ops["stat_change"][0]]
only = sys.argv[1:] or None
for step in steps:
    name = label(step)
    if only and name not in only:
        continue
    call(*step)  # warm
    hits = cache.stats()["misses"]
    t = time.perf_counter()
    call(*step)
    plain = (time.perf_counter() - t) * 1000
    assert cache.stats()["misses"] == hits, "warm call missed"
    prof = cProfile.Profile()
    prof.enable()
    call(*step)
    prof.disable()
    out = io.StringIO()
    st = pstats.Stats(prof, stream=out)
    st.sort_stats("tottime").print_stats(22)
    st.sort_stats("cumulative").print_stats(40)
    text = out.getvalue()
    print(f"\n######## {name}: warm {plain:.0f} ms (no profiler)")
    keep = []
    for line in text.splitlines():
        if line.strip() and not line.startswith(("   Ordered", "   List reduced")):
            keep.append(line.replace("C:\\Triad\\.claude\\worktrees\\zen-thompson-50e9bb\\app\\", "")
                        .replace("C:\\Triad\\.venv-aegis\\Lib\\site-packages\\", "site:"))
    print("\n".join(keep))
