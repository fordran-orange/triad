"""Independently startable Triad product worker and UI."""

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from trading_core.api import denied_operation, invalid_operation, local_headers, not_found

from products.triad.api import router
from products.triad.daily_api import router as daily_router
from products.triad.development_api import router as development_router


@asynccontextmanager
async def lifespan(app):
    stop = threading.Event()

    def loop():
        from products.triad.daily_process import launch, reconcile
        from products.triad.daily_scheduler import tick as daily_tick
        from products.triad.jobs import Jobs
        from products.triad.scheduler import tick

        while not stop.is_set():
            try:
                jobs = Jobs()
                reconcile()
                daily_tick(run=launch)
                tick(jobs.cycles, submit=jobs.submit)
                jobs.once()
            except Exception:  # noqa: BLE001 - retryable worker boundary
                logging.getLogger(__name__).warning("Triad worker unavailable; retrying")
            if stop.wait(10):
                break

    worker = threading.Thread(target=loop, daemon=True)
    worker.start()
    yield
    stop.set()
    from trading_core.providers.process import ManagedProcess

    ManagedProcess.shutdown()
    worker.join(timeout=1)


import subprocess

from trading_core.settings import ROOT

LOADED_REVISION = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
app = FastAPI(title="Triad product", lifespan=lifespan)
app.middleware("http")(local_headers)
app.add_exception_handler(KeyError, not_found)
app.add_exception_handler(ValueError, invalid_operation)
app.add_exception_handler(PermissionError, denied_operation)
app.include_router(router)
app.include_router(development_router)
app.include_router(daily_router)
from products.triad.product_app import app as product_app

app.mount("/triad/product-api", product_app)


@app.get("/triad")
def shell():
    return FileResponse(Path(__file__).parent / "static/day3.html")


@app.get("/health/live")
def live():
    return {"status": "ok", "product": "triad", "loaded_revision": LOADED_REVISION}


@app.get("/triad/api/work")
def work():
    from trading_core.api import dashboard

    from products.triad.cycles import Cycles

    return dashboard(Cycles().host)


@app.get("/triad/product")
def trading_product_shell():
    return FileResponse(Path(__file__).parent / "static/product.html")
