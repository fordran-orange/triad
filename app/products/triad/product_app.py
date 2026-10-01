"""Product application endpoints; separate from protected Triad coordination."""

from decimal import Decimal
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from products.triad.cost_sensitivity import calculate_cost_sensitivity


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
