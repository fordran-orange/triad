"""Aegis human-directed product host. Live exchange execution remains disabled."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from trading_core.api import local_headers
from trading_core.process_power import opt_out_of_power_throttling
from trading_core.store import Store

from products.aegis import api, kernel
from products.aegis.strategy import default_strategy

log = logging.getLogger("aegis")


@asynccontextmanager
async def lifespan(_: FastAPI):
    opt_out_of_power_throttling()
    # Optimizations still queued/running in the repository belong to a dead worker.
    lost = api.get_runner().mark_lost_on_startup()
    if lost:
        log.warning("marked %d unfinished optimization(s) as lost: %s", len(lost), lost)
    # A delete or restore a crash stopped part way is finished before anything lists the trash.
    healed = api.get_repository().heal_trash()
    if healed:
        log.warning("finished %d interrupted Recently deleted move(s): %s", len(healed), healed)
    api.warm_in_background(api.get_store())  # spec §6: first touches warm, off the request path
    yield


app = FastAPI(title="Aegis human-directed product", lifespan=lifespan)
app.middleware("http")(local_headers)


UI_DIST = Path(__file__).parent / "ui" / "dist"
UI_NOT_BUILT = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<title>Aegis</title></head><body style="background:#071018;color:#d8e5ef;'
    'font:14px system-ui;padding:24px"><p>Aegis workstation UI not built; run '
    "<code>tools/build_aegis_ui.ps1</code> and reload.</p></body></html>"
)


@app.get("/aegis")
def shell():
    index = UI_DIST / "index.html"
    if index.is_file():
        return FileResponse(index, media_type="text/html; charset=utf-8")
    return HTMLResponse(UI_NOT_BUILT, media_type="text/html; charset=utf-8")


@app.get("/health/live")
def live():
    return {"status": "ok", "product": "aegis"}


@app.get("/aegis/api/status")
def status():
    return {
        "product": "aegis",
        "mode": "human_directed",
        "status": "ACTIVE_DEVELOPMENT",
        "preservation": "PRODUCT_FIRST_RESET",
        "exchange": "CLOSED",
        "kernel_available": kernel.AVAILABLE,
        "kernel_error": kernel.IMPORT_ERROR,
        "work_items": [w.model_dump(mode="json") for w in Store(scope="aegis").list_work()],
    }


@app.get("/aegis/api/strategy/default")
def strategy_default():
    return default_strategy().model_dump(mode="json")


app.include_router(api.router)

# Static mount last so /aegis/api/* routes above win; html=True serves index.html at /aegis/.
if UI_DIST.is_dir():
    app.mount("/aegis", StaticFiles(directory=UI_DIST, html=True), name="aegis-ui")
