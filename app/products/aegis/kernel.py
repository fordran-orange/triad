"""The compiled simulation kernel (Mission 6 spec §4.1).

One numba-compiled function over plain arrays reproduces `backtest._simulate_side`'s arithmetic
in the same order: next-bar-open fills with slippage, the quantity budget, marked equity with a
running peak, realized settlement, the end-of-data close, the travelling exit signal and carried
positions. Strings, dates and tags never enter; `backtest.py` prepares the arrays and converts
the result back into the reference engine's dicts. When numba is absent `AVAILABLE` is false and
the reference engine runs instead; nothing degrades silently.
"""

from __future__ import annotations

import math

import numpy as np

try:
    from numba import njit

    AVAILABLE = True
    IMPORT_ERROR: str | None = None
except Exception as exc:  # noqa: BLE001 - any import failure means "no kernel", reported upstream
    AVAILABLE = False
    IMPORT_ERROR = type(exc).__name__

    def njit(*_args, **_kwargs):  # pragma: no cover - only reached without numba
        def wrap(function):
            return function

        return wrap


TRADE_COLUMNS = (
    "entry_index",
    "exit_index",
    "signal_index",
    "exit_signal_index",
    "entry_price",
    "exit_price",
    "quantity",
    "gross",
    "net",
    "ret",
    "carried_in",
)
SCALARS = (
    "ending_cash",
    "ending_equity",
    "open_present",
    "open_signal_index",
    "open_entry_index",
    "open_entry_price",
    "open_quantity",
    "open_entry_fee",
    "open_capital_at_entry",
    "open_exit_signal_index",
)
ERROR_TRADES_FULL = 1


def trade_capacity(n_bars: int) -> int:
    """Rows in the trades buffer: a trade needs an entry fill and an exit fill on distinct bars,
    plus a carried position and the end-of-data close (plan ruling P10)."""
    return n_bars // 2 + 2


@njit(cache=True, nogil=True)
def _simulate(
    open_,
    high,
    low,
    close,
    entry,
    exit_,
    warm,
    evaluating,
    permitted,
    side_sign,
    initial_capital,
    allocation_fraction,
    commission,
    slippage_bps,
    close_at_end,
    carried,
    capacity,
):
    n = open_.shape[0]
    trades = np.zeros((capacity, 11))
    n_trades = 0
    equity = np.zeros(n)
    drawdown = np.zeros(n)
    in_position = np.zeros(n, dtype=np.uint8)
    n_points = 0
    scalars = np.zeros(10)
    error = 0

    cash = initial_capital
    has_position = False
    entry_price = 0.0
    quantity = 0.0
    entry_fee = 0.0
    capital_at_entry = 0.0
    position_entry_index = -1.0
    position_signal_index = -1.0
    position_carried = 0.0
    pending = 0  # 0 none, 1 enter, 2 exit
    pending_signal_index = -1
    pending_carried = False
    if carried[0] > 0.0:
        has_position = True
        entry_price = carried[1]
        quantity = carried[2]
        entry_fee = carried[3]
        capital_at_entry = carried[4]
        position_carried = 1.0
        if carried[5] > 0.0:
            pending = 2
            pending_signal_index = -1
            pending_carried = True
    peak = initial_capital
    exit_carry_index = -1

    for i in range(n):
        ev = evaluating[i]
        if pending != 0 and i > pending_signal_index and (ev or not pending_carried):
            if pending == 1 and not has_position:
                fill = open_[i] * (1.0 + side_sign * slippage_bps / 10000.0)
                budget = cash * allocation_fraction
                q = math.floor(max(0.0, (budget - commission) / fill))
                if q > 0:
                    has_position = True
                    entry_price = fill
                    quantity = float(q)
                    entry_fee = commission
                    capital_at_entry = cash
                    position_entry_index = float(i)
                    position_signal_index = float(pending_signal_index)
                    position_carried = 0.0
            elif pending == 2 and has_position:
                fill = open_[i] * (1.0 - side_sign * slippage_bps / 10000.0)
                gross = side_sign * quantity * (fill - entry_price)
                net = gross - entry_fee - commission
                if n_trades >= capacity:
                    error = ERROR_TRADES_FULL
                    break
                trades[n_trades, 0] = position_entry_index
                trades[n_trades, 1] = float(i)
                trades[n_trades, 2] = position_signal_index
                trades[n_trades, 3] = float(pending_signal_index)
                trades[n_trades, 4] = entry_price
                trades[n_trades, 5] = fill
                trades[n_trades, 6] = quantity
                trades[n_trades, 7] = gross
                trades[n_trades, 8] = net
                trades[n_trades, 9] = net / capital_at_entry
                trades[n_trades, 10] = position_carried
                n_trades += 1
                cash = capital_at_entry + net
                has_position = False
            pending = 0
            pending_carried = False

        if not ev:
            continue

        if has_position:
            marked = capital_at_entry + side_sign * quantity * (close[i] - entry_price) - entry_fee
        else:
            marked = cash
        in_position[n_points] = 1 if has_position else 0
        peak = max(peak, marked)
        equity[n_points] = marked
        if peak != 0.0:
            drawdown[n_points] = marked / peak - 1.0
        else:
            drawdown[n_points] = 0.0
        n_points += 1

        if i >= n - 1:
            if (not close_at_end) and has_position and warm[i] and exit_[i]:
                exit_carry_index = i
            continue
        if not warm[i]:
            continue
        if (not has_position) and entry[i] and permitted[i]:
            pending = 1
            pending_signal_index = i
            pending_carried = False
        elif has_position and exit_[i]:
            pending = 2
            pending_signal_index = i
            pending_carried = False

    if error == 0:
        if has_position and not close_at_end:
            scalars[2] = 1.0
            scalars[3] = position_signal_index
            scalars[4] = position_entry_index
            scalars[5] = entry_price
            scalars[6] = quantity
            scalars[7] = entry_fee
            scalars[8] = capital_at_entry
            scalars[9] = float(exit_carry_index)
        elif has_position:
            fill = close[n - 1] * (1.0 - side_sign * slippage_bps / 10000.0)
            gross = side_sign * quantity * (fill - entry_price)
            net = gross - entry_fee - commission
            if n_trades >= capacity:
                error = ERROR_TRADES_FULL
            else:
                trades[n_trades, 0] = position_entry_index
                trades[n_trades, 1] = float(n - 1)
                trades[n_trades, 2] = position_signal_index
                trades[n_trades, 3] = float(n - 1)
                trades[n_trades, 4] = entry_price
                trades[n_trades, 5] = fill
                trades[n_trades, 6] = quantity
                trades[n_trades, 7] = gross
                trades[n_trades, 8] = net
                trades[n_trades, 9] = net / capital_at_entry
                trades[n_trades, 10] = position_carried
                n_trades += 1
                cash = capital_at_entry + net
                if n_points > 0:
                    equity[n_points - 1] = cash
    scalars[0] = cash
    if n_points > 0:
        scalars[1] = equity[n_points - 1]
    else:
        scalars[1] = initial_capital
    if scalars[9] == 0.0 and scalars[2] == 0.0:
        scalars[9] = -1.0
    return trades, n_trades, equity, drawdown, in_position, n_points, scalars, error


def simulate_arrays(
    open_,
    high,
    low,
    close,
    entry,
    exit_,
    warm,
    evaluating,
    permitted,
    side_sign: int,
    initial_capital: float,
    allocation_fraction: float,
    commission: float,
    slippage_bps: float,
    close_at_end: bool,
    carried: np.ndarray,
):
    """Run the compiled loop; see the module docstring for the returned arrays."""
    capacity = trade_capacity(int(open_.shape[0]))
    result = _simulate(
        np.ascontiguousarray(open_, dtype=np.float64),
        np.ascontiguousarray(high, dtype=np.float64),
        np.ascontiguousarray(low, dtype=np.float64),
        np.ascontiguousarray(close, dtype=np.float64),
        np.ascontiguousarray(entry, dtype=np.bool_),
        np.ascontiguousarray(exit_, dtype=np.bool_),
        np.ascontiguousarray(warm, dtype=np.bool_),
        np.ascontiguousarray(evaluating, dtype=np.bool_),
        np.ascontiguousarray(permitted, dtype=np.bool_),
        int(side_sign),
        float(initial_capital),
        float(allocation_fraction),
        float(commission),
        float(slippage_bps),
        bool(close_at_end),
        np.ascontiguousarray(carried, dtype=np.float64),
        capacity,
    )
    if result[7] == ERROR_TRADES_FULL:
        raise RuntimeError(f"trades buffer full (capacity {capacity})")
    return result


__all__ = [
    "AVAILABLE",
    "IMPORT_ERROR",
    "SCALARS",
    "TRADE_COLUMNS",
    "simulate_arrays",
    "trade_capacity",
]
