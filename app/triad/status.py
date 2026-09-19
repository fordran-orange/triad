"""Compatibility import; implementation is owned by trading_core.status."""
import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("trading_core.status")
