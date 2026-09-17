"""Local operator surface. Mutation requires an operator token; no agent authority API."""

import hmac
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from triad.brain import Brain
from triad.orchestrator import Orchestrator
from triad.status import system_status
from triad.work import ElevationRequest, WorkItem


@asynccontextmanager
async def lifespan(app):
    stop = threading.Event()

    def scheduled_loop():
        from triad.day3.scheduler import tick
        from triad.jobs import Jobs

        while not stop.wait(5):
            try:
                jobs = Jobs()
                tick(jobs.cycles, submit=jobs.submit)
                jobs.once()
            except Exception:  # noqa: BLE001 - scheduler must remain inspectable during outages
                import logging

                logging.getLogger("triad.scheduler").warning(
                    "Scheduled tick failed; inspect canonical cycle state"
                )

    worker = threading.Thread(target=scheduled_loop, daemon=True)
    worker.start()
    yield
    stop.set()
    worker.join(timeout=1)


app = FastAPI(title="Triad bounded orchestration", version="0.4.0", lifespan=lifespan)


def service():
    return Orchestrator()


ENGINE_DEPENDENCY = Depends(service)


def require_operator(
    request: Request,
    authorization: str = Header(default=""),
    engine: Orchestrator = ENGINE_DEPENDENCY,
):
    expected = engine.store.settings.triad_operator_token.get_secret_value()
    origin = request.headers.get("origin")
    if origin and origin not in {"http://127.0.0.1:8000", "http://localhost:8000"}:
        raise HTTPException(403, "Untrusted origin")
    if len(expected) < 32 or not hmac.compare_digest(authorization, "Bearer " + expected):
        raise HTTPException(401, "Operator authorization required")


@app.middleware("http")
async def local_headers(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    if host not in {"127.0.0.1", "localhost", "testserver"}:
        return JSONResponse({"detail": "Local host required"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
    )
    return response


@app.exception_handler(KeyError)
async def not_found(request, exc):
    return JSONResponse({"detail": "Record not found"}, status_code=404)


@app.exception_handler(ValueError)
async def invalid_operation(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(PermissionError)
async def denied_operation(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=403)


@app.get("/", include_in_schema=False)
def operator_shell():
    return FileResponse(Path(__file__).parent / "static/day3.html")


@app.get("/health/live")
def liveness():
    return {"status": "ok", "scope": "api_process_only"}


@app.get("/api/foundation")
def foundation():
    return {
        "phase": "Day 4",
        "live_trading_authority": False,
        "execution_engine": "bounded_research_only",
        "policy_mutation_api": False,
        "local_model_role": "helper_only",
        "market_data": "1m_ohlcv_parquet",
    }


@app.get("/api/status")
def status(engine: Orchestrator = ENGINE_DEPENDENCY):
    return system_status(engine.store)


@app.get("/api/dashboard")
def dashboard(engine: Orchestrator = ENGINE_DEPENDENCY):
    try:
        items = [w.model_dump(mode="json") for w in engine.store.list_work()]
        records = engine.store.records(limit=300)
        agents = []
        for agent in engine.registry.agents.values():
            assignments = [w for w in items if w["assigned_agent"] == agent.agent_id]
            active = next(
                (w for w in assignments if w["status"] in {"ASSIGNED", "IN_PROGRESS"}), None
            )
            agents.append(
                agent.model_dump(mode="json")
                | {
                    "current_assignment": active["title"] if active else None,
                    "status": "working"
                    if active
                    else "ready"
                    if agent.integration == "ollama"
                    else "demo only",
                    "last_action": assignments[0]["status"] if assignments else "No assignments",
                }
            )
        return {
            "work_items": items,
            "records": records,
            "agents": agents,
            "rotation": engine.registry.rotation,
            "projections": engine.store.projection_status(),
            "policy": {
                "version": "day2-v1",
                "live_execution": False,
                "governance": "human-only; approval disabled",
                "tiers": {
                    "0": "Observe",
                    "1": "Research",
                    "2": "Development",
                    "3": "Simulation",
                    "4": "Live — disabled",
                    "5": "Governance — human only",
                },
            },
        }
    except Exception as exc:  # noqa: BLE001 - unavailable is not an empty successful dashboard
        raise HTTPException(503, f"Operational store unavailable: {type(exc).__name__}") from None


@app.get("/api/work/{work_id}")
def work_detail(work_id: str, engine: Orchestrator = ENGINE_DEPENDENCY):
    work = engine.store.get(work_id)
    try:
        lineage, graph_error = Brain(engine.store).lineage(work_id), None
    except Exception as exc:  # noqa: BLE001
        lineage, graph_error = [], type(exc).__name__
    return {
        "work": work.model_dump(mode="json"),
        "events": engine.store.events(work_id),
        "records": engine.store.records(work_id=work_id),
        "lineage": lineage,
        "graph_error": graph_error,
    }


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["deterministic_demo", "real"] = "deterministic_demo"
    auto_review: bool = True


class DemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker: str = "CODEX"
    parent: str | None = None


@app.post("/api/work", dependencies=[Depends(require_operator)], status_code=201)
def create_work(work: WorkItem, engine: Orchestrator = ENGINE_DEPENDENCY):
    return engine.create(work)


@app.post("/api/work/{work_id}/run", dependencies=[Depends(require_operator)], status_code=202)
def run_work(
    work_id: str,
    body: RunRequest,
    background: BackgroundTasks,
    engine: Orchestrator = ENGINE_DEPENDENCY,
):
    work = engine.store.get(work_id)
    if work.status not in {"CREATED", "FAILED", "BLOCKED", "CHANGES_REQUESTED"}:
        raise HTTPException(409, "Assignment is not executable")
    background.add_task(engine.run, work_id, mode=body.mode, auto_review=body.auto_review)
    return {"work_item_id": work_id, "accepted": True}


@app.post("/api/demo", dependencies=[Depends(require_operator)], status_code=202)
def demo(body: DemoRequest, background: BackgroundTasks, engine: Orchestrator = ENGINE_DEPENDENCY):
    work = engine.demo(worker=body.worker, parent=body.parent)
    background.add_task(engine.run, work.work_item_id)
    return {"work_item_id": work.work_item_id, "execution_mode": "deterministic_demo"}


@app.post("/api/work/{work_id}/review", dependencies=[Depends(require_operator)])
def review(work_id: str, engine: Orchestrator = ENGINE_DEPENDENCY):
    return engine.review(work_id)


@app.post("/api/elevation-requests", dependencies=[Depends(require_operator)], status_code=201)
def elevation(request: ElevationRequest, engine: Orchestrator = ENGINE_DEPENDENCY):
    return engine.request_elevation(request)


@app.post("/api/projections/retry", dependencies=[Depends(require_operator)])
def retry_projection(engine: Orchestrator = ENGINE_DEPENDENCY):
    return Brain(engine.store).flush()


from triad.day3.api import router as day3_router

app.include_router(day3_router)


@app.get("/day2", include_in_schema=False)
def day2_shell():
    return FileResponse(Path(__file__).parent / "static/index.html")
