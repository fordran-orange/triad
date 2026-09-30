"""Product application endpoints; separate from protected Triad coordination."""

from fastapi import FastAPI

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
