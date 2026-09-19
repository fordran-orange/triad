from importlib.resources import files

from trading_core.settings import ROOT


def product_resource(name):
    override = ROOT / (
        "config/triad/product.json" if name == "product.json" else "infrastructure/postgres/" + name
    )
    return override if override.is_file() else files("products.triad").joinpath("resources", name)
