"""Independently startable Triad product worker and UI."""

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from trading_core.api import denied_operation, invalid_operation, local_headers, not_found

from products.triad.api import router
from products.triad.daily_api import router as daily_router
from products.triad.development_api import router as development_router


@asynccontextmanager
async def lifespan(app):
    stop = threading.Event()

    def loop():
        from products.triad.daily import Daily
        from products.triad.daily_process import launch, reconcile
        from products.triad.daily_scheduler import tick as daily_tick
        from products.triad.daily_wakeup import WAKE, delay
        from products.triad.jobs import Jobs
        from products.triad.scheduler import tick

        while not stop.is_set():
            WAKE.clear()
            wait = 300
            try:
                jobs = Jobs()
                reconcile()
                daily_tick(run=launch)
                tick(jobs.cycles, submit=jobs.submit)
                wait = delay(Daily())
            except Exception:  # noqa: BLE001 - retryable worker boundary
                logging.getLogger(__name__).warning("Triad worker unavailable; retrying")
                wait = 30
            WAKE.wait(wait)

    def queue_loop():
        from products.triad.daily_wakeup import QUEUE_WAKE
        from products.triad.jobs import Jobs

        while not stop.is_set():
            QUEUE_WAKE.clear()
            try:
                result = Jobs().once()
                if result.get("status") in {"COMPLETED", "BLOCKED", "CANCELLED"}:
                    continue  # Drain queued jobs without delaying the next job.
            except Exception:  # noqa: BLE001 - isolated queue worker retry boundary
                logging.getLogger(__name__).warning("Triad queue unavailable; retrying")
            QUEUE_WAKE.wait(300)

    from products.triad.daily_wakeup import listen

    workers = [
        threading.Thread(target=f, daemon=True) for f in (loop, queue_loop, lambda: listen(stop))
    ]
    for worker in workers:
        worker.start()
    yield
    stop.set()
    from products.triad.daily_wakeup import wake

    wake()
    from trading_core.providers.process import ManagedProcess

    ManagedProcess.shutdown()
    for worker in workers:
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
    from products.triad.sequential_mission import insert_panel, mission_panel

    source = (Path(__file__).parent / "static/product.html").read_text(encoding="utf-8")
    # Keep the operator mission outside the autonomous product file's content.
    return HTMLResponse(insert_panel(source, mission_panel()))


@app.get("/triad/api/application-plan")
def application_plan():
    from products.triad.sequential_application import current_plan

    return current_plan()
