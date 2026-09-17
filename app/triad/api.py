from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI(title="Triad operator foundation", version="0.1.0")


@app.get("/", include_in_schema=False)
def operator_shell():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health/live")
def liveness():
    return {"status": "ok", "scope": "api_process_only"}


@app.get("/api/foundation")
def foundation():
    return {
        "phase": "Day 1",
        "live_trading_authority": False,
        "execution_engine": "not_implemented",
        "policy_mutation_api": False,
        "local_model_role": "helper_only",
        "market_data": "1m_ohlcv_parquet",
        "service_health": "Run tools/health_check.py; not inferred from API liveness",
    }
