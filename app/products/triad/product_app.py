"""Product application endpoints; separate from protected Triad coordination."""

from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from products.triad.bar_inspection import inspect_bars
from products.triad.research_dataset import DatasetRequest, prepare_dataset
from products.triad.cost_sensitivity import calculate_cost_sensitivity
from products.triad.trade_ledger import analyze_trade_ledger


class CostAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Literal["LONG", "SHORT"]
    quantity: Decimal = Field(gt=0, le=1000000, allow_inf_nan=False)
    entry_price: Decimal = Field(gt=0, le=1000000, allow_inf_nan=False)
    exit_price: Decimal = Field(gt=0, le=1000000, allow_inf_nan=False)
    commission_per_order: Decimal = Field(ge=0, le=1000, allow_inf_nan=False)
    commission_per_share: Decimal = Field(ge=0, le=100, allow_inf_nan=False)
    commission_bps: Decimal = Field(ge=0, le=1000, allow_inf_nan=False)
    full_spread_bps: Decimal = Field(ge=0, le=1000, allow_inf_nan=False)
    slippage_bps: Decimal = Field(ge=0, le=1000, allow_inf_nan=False)


class TradeLedgerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initial_balance: str = Field(strict=True, max_length=32)
    csv_text: str = Field(strict=True, max_length=1_000_000)


class BarInspectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str = Field(strict=True, max_length=1_000_000)


app = FastAPI(title="Triad product application")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/boundaries")
def boundaries():
    return {
        "product": "triad-trading",
        "stage": "early",
        "live_account": False,
        "order_entry": False,
        "portfolio_management": False,
        "validated_strategy": False,
        "research_readiness_establishes_strategy_edge": False,
    }


@app.post("/research/cost-sensitivity")
def cost_sensitivity(assumptions: CostAssumptions):
    return calculate_cost_sensitivity(assumptions.model_dump())


@app.exception_handler(RequestValidationError)
async def bounded_request_errors(request: Request, error: RequestValidationError):
    path = request.url.path
    if path.endswith("/research/dataset-preparation"):
        return JSONResponse(status_code=422, content={"detail": "Invalid dataset request: bounded CSV, explicit source metadata and aware nonempty window required."})
    if path.endswith("/research/trade-ledger"):
        # Do not echo submitted text or arbitrarily many unknown field names.
        return JSONResponse(status_code=422, content={"detail":
            "Invalid request: require only initial_balance (decimal string, <=32 characters) "
            "and csv_text (string, <=1,000,000 characters and UTF-8 bytes)."})
    if path.endswith("/research/bar-inspection"):
        # Do not echo submitted CSV or unknown field names.
        return JSONResponse(status_code=422, content={"detail":
            "Invalid request: require only csv_text (string, <=1,000,000 characters and UTF-8 bytes)."})
    return await request_validation_exception_handler(request, error)


@app.post("/research/trade-ledger")
def trade_ledger(payload: TradeLedgerRequest):
    try:
        return analyze_trade_ledger(payload.initial_balance, payload.csv_text)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/research/bar-inspection")
def bar_inspection(payload: BarInspectionRequest):
    try:
        return inspect_bars(payload.csv_text)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/research/dataset-preparation")
def dataset_preparation(payload: DatasetRequest):
    try:
        return prepare_dataset(payload)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid OHLCV CSV: check documented columns, values, duplicates and byte/row limits.") from None
