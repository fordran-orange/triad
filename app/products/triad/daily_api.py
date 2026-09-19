"""Readable daily product surfaces; scheduling changes require local operator auth."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from trading_core.api import require_operator

from products.triad.daily import Daily, DailySchedule

router = APIRouter()


def daily():
    return Daily()


DEP = Depends(daily)


@router.get("/triad/daily-debrief")
def shell():
    return FileResponse(Path(__file__).parent / "static/daily.html")


@router.get("/triad/assets/daily.js")
def script():
    return FileResponse(Path(__file__).parent / "static/daily.js", media_type="text/javascript")


@router.get("/triad/api/daily-debriefs")
def debriefs(service=DEP):
    return {"debriefs": service.debriefs()}


@router.get("/triad/api/daily-schedule")
def schedule(service=DEP):
    from products.triad.daily_scheduler import next_cycle

    config = service.schedule()
    return {**config, "next_cycle": next_cycle(config)}


@router.post("/triad/api/daily-schedule", dependencies=[Depends(require_operator)])
def configure(body: DailySchedule, service=DEP):
    identifier = service.configure(body)
    return {"record_id": identifier, "schedule": service.schedule()}


@router.get("/triad/product/research-readiness")
def readiness():
    path = Path(__file__).parent / "features/research_readiness.html"
    if not path.is_file():
        raise HTTPException(
            503, "Research Readiness is awaiting the independently reviewed product build"
        )
    return FileResponse(path)


@router.get("/triad/assets/research-readiness.js")
def readiness_script():
    path = Path(__file__).parent / "features/research_readiness.js"
    if not path.is_file():
        raise HTTPException(503, "Research Readiness is awaiting its reviewed build")
    return FileResponse(path, media_type="text/javascript")
