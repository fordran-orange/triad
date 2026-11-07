"""The local-only HTTP middleware every worker mounts: Core's gateway and each product worker.

This module imports the web framework and nothing of Core, so a product worker that mounts the
middleware loads neither the operator surface (`trading_core.api`) nor what it imports (Brain,
Orchestrator, the runtime, status, work). `trading_core.api` re-exports `local_headers` from here.
"""

from fastapi import Request
from fastapi.responses import JSONResponse


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
