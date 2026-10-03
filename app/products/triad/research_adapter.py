"""Triad's reusable consumer of the shared pure Core research interface."""

from trading_core.product_sdk import ProductResearch, ResearchInput
from trading_core.research.contracts import Experiment


def run_research(
    supplied: ResearchInput, experiment: Experiment, *, strategy=None, guard=lambda: None
):
    return ProductResearch("triad").run(supplied, experiment, strategy=strategy, guard=guard)


def validate_research_input(supplied: ResearchInput):
    """Validate with the real owner-scoped SDK; no engine execution."""
    return ProductResearch("triad").frame(supplied)
