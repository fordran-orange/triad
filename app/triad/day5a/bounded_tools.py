"""Compatibility import; implementation is owned by trading_core.providers.bounded_tools."""
import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("trading_core.providers.bounded_tools")
