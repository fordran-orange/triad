# Execution and cost assumptions

Signals use only the completed current bar and earlier observations. Orders execute at the next observed regular-session bar's open, never at the signal bar's open or close. A close timestamp may equal the next interval's start in clock time; these remain different bars. Overnight signals may execute at the next session open. Known experiment-end liquidation occurs at the last bar's open; no entry is accepted there. The final bar's subsequent prices do not determine that exit.

Fill = open adjusted adversely by configured slippage basis points plus half the spread basis points. Commissions apply on each fill: fixed + per-share quantity + notional basis points. Zero-cost mode uses all zero fields. Gross P&L uses unadjusted entry/exit opens; net P&L subtracts both-side fees and modeled slippage/spread. No claim of realistic order-book liquidity, market impact, intrabar stop ordering, borrow availability/cost, dividends, financing or corporate actions is made.

Short signals are evaluated separately, not inferred from long success. Shorts assume synthetic unlimited borrow at zero borrow fee for engine tests; this prevents use as a live performance estimate. Positions have explicit entry/exit reasons, quantities and decision timestamps. Prices are float64 and orders have whole-share sizing; exchange tick rounding is not modeled.
