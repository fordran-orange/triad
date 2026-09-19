"""Installed defaults with explicit host overrides; never depend on checkout files."""

from importlib.resources import files

from trading_core.settings import ROOT


def resource(relative):
    override = ROOT / relative
    if override.is_file():
        return override
    # Only Core's own resources are resolved here.
    if relative.startswith("config/core/"):
        return files("trading_core").joinpath("resources/config", relative.split("/")[-1])
    if relative.startswith("infrastructure/postgres/"):
        return files("trading_core").joinpath("resources/sql", relative.split("/")[-1])
    raise ValueError("Unknown Core resource")
