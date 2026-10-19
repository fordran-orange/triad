"""The TypeScript contracts file must be regenerated whenever the Pydantic models change."""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.aegis

ROOT = Path(__file__).resolve().parents[1]


def load_generator():
    path = ROOT / "tools" / "aegis_contracts.py"
    spec = importlib.util.spec_from_file_location("aegis_contracts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contracts_ts_is_current():
    generator = load_generator()
    expected = generator.render()
    current = (ROOT / "app/products/aegis/ui/src/contracts.ts").read_text(encoding="utf-8")
    assert current == expected, "ui/src/contracts.ts is stale; run tools/aegis_contracts.py"


def test_generated_contracts_cover_the_strategy_and_backtest_models():
    text = load_generator().render()
    for name in (
        "StrategySpec",
        "StrategySide",
        "IndicatorSpec",
        "RuleSpec",
        "TemporalContext",
        "ExecutionSpec",
        "OptimizationParameter",
        "BacktestRequest",
        "BacktestSettings",
        "EventPoint",
    ):
        assert f"export interface {name}" in text or f"export type {name}" in text, name
    assert "export type Direction = 'long' | 'short'" in text
    assert "export type WindowMode = 'allow' | 'block' | 'analyze' | 'modify_risk'" in text


def test_indicator_kinds_constant_matches_python():
    import json

    from products.aegis.kinds import KINDS

    text = load_generator().render()
    marker = "export const INDICATOR_KINDS: Record<string, IndicatorKind> = "
    assert marker in text
    emitted = json.loads(text.split(marker, 1)[1].split(";\n", 1)[0])
    assert set(emitted) == set(KINDS)
    for name, info in KINDS.items():
        assert emitted[name] == {
            "outputs": list(info.outputs),
            "pane": info.pane,
            "params": dict(info.params),
            "integer_params": sorted(info.integer_params),
            "requires": list(info.requires),
            "default_length": info.default_length,
            "warmup_terms": list(info.warmup_terms),
            "warmup_offset": info.warmup_offset,
        }, name


def test_parameter_maps_are_typed_as_number_records():
    text = load_generator().render()
    assert "params?: Record<string, number>" in text


def test_generated_contracts_cover_the_study_models():
    text = load_generator().render()
    for name in ("StudyRequest", "StudyPlan", "SymbolPlan", "StudyDocument"):
        assert f"export interface {name} " in text, name
