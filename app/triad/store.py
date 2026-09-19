"""Compatibility import; implementation is owned by trading_core.store."""
import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("trading_core.store")
