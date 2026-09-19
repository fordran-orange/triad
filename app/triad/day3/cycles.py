"""Compatibility import; implementation is owned by products.triad.cycles."""
import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("products.triad.cycles")
