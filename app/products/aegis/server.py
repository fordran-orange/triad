"""Sparse human-directed product shell. Exchange and autonomous strategy selection are off."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from trading_core.api import local_headers
from trading_core.store import Store

app = FastAPI(title="Aegis human-directed product")
app.middleware("http")(local_headers)


@app.get("/aegis")
def shell():
    return FileResponse(Path(__file__).parent / "static/index.html")


@app.get("/health/live")
def live():
    return {"status": "ok", "product": "aegis"}


@app.get("/aegis/api/status")
def status():
    return {
        "product": "aegis",
        "mode": "human_directed",
        "status": "INACTIVE",
        "preservation": "PRESERVED",
        "exchange": "CLOSED",
        "work_items": [w.model_dump(mode="json") for w in Store(scope="aegis").list_work()],
    }
