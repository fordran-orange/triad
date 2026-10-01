"""Stateless additive USD estimates against unchanged reference prices."""

from decimal import Decimal, localcontext


def calculate_cost_sensitivity(assumptions):
    """Return decimal strings to preserve precision, including very small inputs.

    No fills are simulated. Full spread is charged as half on each leg.
    breakeven_reference_exit_price is the positive exit at which 1x supplied
    costs make net P&L zero, with quantity, entry, and cost inputs held fixed.
    """
    with localcontext() as context:
        context.prec = 50
        values = {k: Decimal(str(v)) for k, v in assumptions.items() if k != "direction"}
        q = values["quantity"]
        entry = values["entry_price"]
        exit_price = values["exit_price"]
        notional = q * (entry + exit_price)
        gross = q * (exit_price - entry) * (1 if assumptions["direction"] == "LONG" else -1)
        commission = (2 * values["commission_per_order"]
                      + 2 * q * values["commission_per_share"]
                      + notional * values["commission_bps"] / 10000)
        spread = notional * values["full_spread_bps"] / 20000
        slippage = notional * values["slippage_bps"] / 10000
        unit_total = commission + spread + slippage
        fixed = (2 * values["commission_per_order"]
                 + 2 * q * values["commission_per_share"])
        rate = (values["commission_bps"] / 10000
                + values["full_spread_bps"] / 20000
                + values["slippage_bps"] / 10000)
        if assumptions["direction"] == "LONG":
            reference_exit = (
                (q * entry * (1 + rate) + fixed) / (q * (1 - rate))
                if rate < 1 else None
            )
        else:
            reference_exit = (q * entry * (1 - rate) - fixed) / (q * (1 + rate))
            if reference_exit <= 0:
                reference_exit = None
        scenarios = []
        for multiplier in (1, 2, 3):
            total = multiplier * unit_total
            net = gross - total
            scenarios.append({
                "label": f"{multiplier}x supplied costs",
                "multiplier": multiplier,
                "commission": str(multiplier * commission),
                "spread_cost": str(multiplier * spread),
                "slippage_cost": str(multiplier * slippage),
                "total_cost": str(total),
                "net_pnl": str(net),
                "net_return_on_entry_notional_pct": str(100 * net / (q * entry)),
            })
        return {
            "currency": "USD",
            "monetary_encoding": "decimal strings",
            "return_unit": "percent",
            "direction": assumptions["direction"],
            "assumptions": {k: str(v) for k, v in assumptions.items()},
            "gross_pnl": str(gross),
            "round_trip_reference_notional": str(notional),
            "breakeven_cost_multiplier": str(gross / unit_total) if unit_total != 0 else None,
            "breakeven_reference_exit_price": None if reference_exit is None else str(reference_exit),
            "scenarios": scenarios,
        }
