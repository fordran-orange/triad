"""Neutral local composition: Core runs here; products run in separate processes."""

import os

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from trading_core.api import app


async def forward(request: Request, product: str):
    port = int(
        os.environ.get(product.upper() + "_WORKER_PORT", {"triad": "8101", "aegis": "8102"}[product])
    )
    path = request.url.path
    query = request.url.query
    try:
        async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
            result = await client.request(
                request.method,
                f"http://127.0.0.1:{port}{path}" + ("?" + query if query else ""),
                content=await request.body(),
                headers={
                    k: v
                    for k, v in request.headers.items()
                    if k.lower() in {"authorization", "content-type", "origin"}
                },
            )
        return Response(
            result.content,
            status_code=result.status_code,
            media_type=result.headers.get("content-type", "application/json"),
        )
    except httpx.RequestError:
        return JSONResponse(
            {
                "detail": f"{product.upper()} worker is unavailable. Core controls remain available at /core."
            },
            status_code=503,
        )


@app.api_route("/triad", methods=["GET"])
@app.api_route("/triad/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
@app.api_route("/api/day3/{path:path}", methods=["GET", "POST"])
async def triad_proxy(request: Request, path: str = ""):
    return await forward(request, "triad")


@app.api_route("/aegis", methods=["GET"])
@app.api_route("/aegis/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def aegis_proxy(request: Request, path: str = ""):
    return await forward(request, "aegis")


@app.api_route("/p2p", methods=["GET"])
@app.api_route("/p2p/{path:path}", methods=["GET"])
async def legacy_product_redirect(request: Request, path: str = ""):
    target = "/aegis" + ("/" + path if path else "")
    if request.url.query:
        target += "?" + request.url.query
    return RedirectResponse(target, status_code=307)
