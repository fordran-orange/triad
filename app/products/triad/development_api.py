"""Read-only product lifecycle. Execution remains an explicitly invoked host job."""

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from products.triad.development import Development

router = APIRouter()


def development():
    return Development()


DEP = Depends(development)


@router.get("/triad/development")
def shell():
    return FileResponse(Path(__file__).parent / "static/development.html")


@router.get("/triad/assets/development.js")
def script():
    return FileResponse(
        Path(__file__).parent / "static/development.js", media_type="text/javascript"
    )


@router.get("/triad/api/development")
def dashboard(service=DEP):
    return service.dashboard()


@router.get("/triad/api/development/artifact")
def artifact(path: str, service=DEP):
    return service.artifact(path)
