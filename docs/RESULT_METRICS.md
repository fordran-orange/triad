# Results and mathematical limits

Metrics are per independent LONG/SHORT portfolio: net return from marked equity, compounded trade geometric mean, arithmetic mean trade return, max drawdown, volatility, Sharpe, Sortino, Calmar, profit factor, expectancy in USD, win rate, mean win/loss, trade count, turnover, average sampled gross exposure/equity, largest win/loss and longest loss streak. MAE is the mean nonpositive adverse price fraction; MFE the mean nonnegative favorable fraction. Holding time uses elapsed minutes. Time-to-profit/failure uses the first positive/negative marked open-trade P&L after entry fees, observed at bar close; null means never observed. It is not a barrier probability estimate.

Equity Parquet retains cash, gross/net exposure, log returns and drawdown. Geometric mean trade return is not portfolio CAGR: overlapping capital/allocations matter. CAGR is null for less than a year; annualized volatility/Sharpe/Sortino are null below 20 daily returns. Daily annualization uses 252 and zero risk-free rate. Zero denominator, no-loss profit factor and empty samples yield null, never misleading infinity/zero quality scores. The three-day fixture therefore leaves several annualized measures undefined.

Cost sensitivity records actual fee/slippage drag and an analytic extra-1bp-per-side drag at fixed quantities/fills. It is not a reoptimized strategy. Trade-sequence analysis preserves the actual sequence and separates compound product from drawdown path. Positive results alone are not decision-quality evidence.


Review correction: MAE/MFE include the observable exit opening price before a position is removed. Later high/low values of that exit bar remain excluded, so exit gaps are counted without introducing future information. Historical metrics retain their original engine identity.
