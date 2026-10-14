"""Shared power-throttling opt-out (Mission 4 spec §4): applied on Windows, declined elsewhere,
never raising, and called first in every worker lifespan."""

import inspect
import sys

import pytest
from trading_core import process_power

pytestmark = pytest.mark.triad


def test_opt_out_applies_on_windows_and_declines_elsewhere():
    assert process_power.opt_out_of_power_throttling() is (sys.platform == "win32")


def test_opt_out_returns_false_and_logs_when_refused(monkeypatch, caplog):
    monkeypatch.setattr(process_power, "_set_process_information", lambda state: (False, 87))
    monkeypatch.setattr(process_power.sys, "platform", "win32")
    with caplog.at_level("WARNING", logger="trading_core.process_power"):
        assert process_power.opt_out_of_power_throttling() is False
    assert "refused" in caplog.text and "87" in caplog.text


def test_every_worker_lifespan_opts_out():
    from products.aegis import server as aegis
    from trading_core import api as core

    from products.triad import server as triad

    for module in (core, triad, aegis):
        source = inspect.getsource(module.lifespan)
        assert "opt_out_of_power_throttling()" in source.split("yield")[0], module.__name__


def test_opt_out_returns_false_when_the_call_itself_blows_up(monkeypatch):
    def explode(state):
        raise TypeError("bad argument")

    monkeypatch.setattr(process_power, "_set_process_information", explode)
    monkeypatch.setattr(process_power.sys, "platform", "win32")
    assert process_power.opt_out_of_power_throttling() is False
