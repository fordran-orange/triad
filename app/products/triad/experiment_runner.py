"""Ownership-pinned experiment runner connecting prepared datasets to Core.

preflight validates ownership and Core research-contract eligibility before any
Experiment is constructed. run_experiment then builds a fixture-conformance
Experiment from the preflight-returned ResearchInput and runs it through Core.
"""

from trading_core.product_sdk import ResearchInput
from trading_core.research.contracts import Costs, Experiment, Partition, Slippage, Sizing

from products.triad.research_adapter import run_research, validate_research_input


def preflight(core_input):
    supplied = ResearchInput.model_validate(core_input)
    if supplied.owner != "triad":
        raise PermissionError("Research input belongs to another product")
    validate_research_input(supplied)
    return supplied


def run_experiment(core_input, period, hold, directions, fees, slippage, sizing):
    supplied = preflight(core_input)
    symbols = tuple(sorted({bar.symbol for bar in supplied.bars}))
    experiment = Experiment(
        name="Product experiment",
        description="Triad product-submitted fixture experiment",
        hypothesis="Fixture strategy behavior on the supplied dataset",
        dataset_id=supplied.dataset_id,
        dataset_version=supplied.dataset_version,
        symbols=symbols,
        start_time=supplied.start,
        end_time=supplied.end,
        parameters={"period": period, "hold": hold},
        directions=tuple(directions),
        fees_model=Costs(**fees),
        slippage_model=Slippage(**slippage),
        position_sizing_model=Sizing(**sizing),
        code_commit="triad-product-app",
        environment={"purpose": "triad product experiment"},
        acceptance_criteria=("Explicit fixture identity and deterministic result",),
        partitions=(Partition(name="test", start=supplied.start, end=supplied.end),),
    )
    return run_research(supplied, experiment, strategy=None)
