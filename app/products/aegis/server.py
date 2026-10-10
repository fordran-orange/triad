"""Aegis human-directed product host. Live exchange execution remains disabled."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from trading_core.api import local_headers
from trading_core.store import Store

from products.aegis.backtest import BacktestRequest, run_backtest
from products.aegis.strategy import default_strategy

app = FastAPI(title="Aegis human-directed product")
app.middleware("http")(local_headers)


UI_DIST = Path(__file__).parent / "ui" / "dist"
UI_NOT_BUILT = (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<title>Aegis</title></head><body style=\"background:#071018;color:#d8e5ef;"
    "font:14px system-ui;padding:24px\"><p>Aegis workstation UI not built; run "
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
        "work_items": [w.model_dump(mode="json") for w in Store(scope="aegis").list_work()],
    }


@app.get("/aegis/api/strategy/default")
def strategy_default():
    return default_strategy().model_dump(mode="json")


@app.post("/aegis/api/backtest")
def backtest(request: BacktestRequest):
    return run_backtest(request)


# Static mount last so /aegis/api/* routes above win; html=True serves index.html at /aegis/.
if UI_DIST.is_dir():
    app.mount("/aegis", StaticFiles(directory=UI_DIST, html=True), name="aegis-ui")
