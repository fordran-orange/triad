import json, time
from fastapi.encoders import jsonable_encoder
from common import operations, setup, label
store, cache, document, call = setup()
ops = operations(document)
for step in [ops["open"][0], ops["open"][1], ops["open"][2]]:
    out = call(*step)
    t = time.perf_counter(); enc = jsonable_encoder(out); t1 = time.perf_counter(); body = json.dumps(enc); t2 = time.perf_counter()
    print(f"{label(step):25s} jsonable_encoder {1000*(t1-t):.1f} ms, dumps {1000*(t2-t1):.1f} ms, {len(body)/1024:.0f} KB")
