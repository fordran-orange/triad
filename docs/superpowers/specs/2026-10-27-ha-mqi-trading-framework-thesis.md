# HA-MQI Trading Framework: Working Thesis, Operating Rules, and Indicator Definitions

> Randall Ford's thesis document, received 2026-10-27 as `HA_MQI_Trading_Framework_Thesis.docx` and converted to Markdown without changes to its content. It is the source of the indicator definitions for the Aegis indicator mission (Optimization Lab v2 plan, §11.2). Prepared from observed daily-chart behavior and iterative chart review.

## Thesis summary

The working framework treats HA-MQI as the primary state engine for daily-chart trend transitions. HA-MQI provides the entry and exit signal; RocketRSI serves as a force multiplier and early exhaustion flag; Elliott Oscillator acts as a compression / phase filter; the 9 EMA acts as a one-bar blocker to prevent obvious countertrend spikes; an adaptive Chandelier stop protects profits once momentum decay is detected; and an event calendar blocks trades around scheduled gap risk (earnings, Fed, NFP, and similar events).

## 1. Operating thesis

The objective is not to predict every reversal. The objective is to identify tradable daily-chart trend states, enter only when the market transitions into organized movement, and preserve capital when that state deteriorates.

In the current working model, HA-MQI is the cleanest entry/exit trigger found so far on the daily chart. It appears to identify the transition from chaos or consolidation into directional trend, with a directionally meaningful oscillation that lines up with price cycles.

RocketRSI is not a required condition for the trade. It is a force multiplier: when RocketRSI has been exhausted recently, the market tends to offer better right-tail potential and the position can justify larger size. When RocketRSI is not supportive, the base HA-MQI engine still trades, but with less conviction.

Elliott Oscillator is not used as an entry trigger. It is used as a state filter to identify compressed / stable cycles where the HA-MQI oscillation is more likely to be actionable. The 9 EMA blocker is a narrow one-bar guardrail intended to prevent buys into a candle that is still resolving downside pressure.

## 2. Indicator definitions and formulas

### 2.1 Heikin Ashi construction

```
HA_Close   = (Open + High + Low + Close) / 4
HA_Open(t) = (HA_Open(t-1) + HA_Close(t-1)) / 2
HA_High    = max(High, HA_Open, HA_Close)
HA_Low     = min(Low, HA_Open, HA_Close)
```

The current HA-MQI work uses the Heikin Ashi body midpoint as its input series:

```
HA_BodyMid(t) = (HA_Open(t) + HA_Close(t)) / 2
```

### 2.2 HA-MQI (Heikin Ashi Momentum Quality Index)

HA-MQI is a normalized trend-quality statistic built from log returns of the selected input series. In the current operating version, the input is the Heikin Ashi body midpoint. The signal rises when same-direction movement accumulates faster than the local noise standard deviation, and falls when the market loses directional coherence.

```
r(t)   = ln( S(t) / S(t-1) )                 where S(t) = HA_BodyMid(t)
MQI(t) = [ Σ_{i=0}^{N-1} r(t-i) ] / [ σ_r(t,N) * sqrt(N) ]
MQI_smooth(t) = SMA( MQI(t), 10 )
```

Current settings: N = 10 bars; Smooth = 10 bars; input = HA body midpoint.

Interpretation: HA-MQI is positive when directional trend quality is stronger than the recent noise level, and negative when trend quality deteriorates. The smooth line provides the trend-quality baseline; the crossover is treated as a state change, not merely an oscillator event.

### 2.3 RocketRSI

RocketRSI is used as an exhaustion / force-multiplier indicator. It is especially useful when it has been below -2 within the last 10 bars before a buy signal, because that historically corresponds to stronger winners. The current working settings are 10 / 8.

```
momentum(t)  = Close(t) - Close(t-9)
filter(t)    = EhlersSuperSmoother( momentum(t), cutoff = 8 )
rawMyRsi(t)  = Σ[ filter(t-i) - filter(t-i-1) ] / Σ| filter(t-i) - filter(t-i-1) |   over 10 bars
myRsi        = clamp(rawMyRsi, -0.999, +0.999)
RocketRSI(t) = 0.5 * ln( (1 + myRsi) / (1 - myRsi) )
```

Current settings: Length = 10; Cutoff length = 8.

### 2.4 Elliott Oscillator

Elliott Oscillator is being used as a compression / phase-location filter rather than a primary signal. The current working settings are 5 / 20. In the current thesis, the oscillator is best thought of as a state gate: when its fast and slow components are close together, the market is more likely to be compressed and stable enough for an HA-MQI crossover to matter.

```
EO(t) = EMA_5(Close) - EMA_20(Close)
```

Current settings: Fast EMA = 5; Slow EMA = 20.

## 3. Trading framework

| Component | Role | Current rule / setting |
|---|---|---|
| Entry | HA-MQI up-cross | Enter when HA-MQI crosses above the smooth HA-MQI line. |
| Blocker | 9 EMA one-bar guard | Do not buy if the last bar closed on the wrong side of the 9 EMA. |
| State filter | Elliott compression | Prefer trades when Elliott fast/slow are compressed and cycle timing is favorable. |
| Size modifier | RocketRSI exhaustion | If RocketRSI was below -2 within the last 10 bars, the trade may justify larger size. |
| Exit | HA-MQI down-cross | Hard exit. If an open position sees HA-MQI cross down, exit immediately. |
| Protection | Chandelier stop | Once armed, the stop stays armed until exit and may only tighten. |
| Gap risk | Event calendar | Do not open new trades into earnings or major scheduled macro events; block new entries within 2 days of earnings and around major event risk. |

Priority rule: HA-MQI down-cross always overrides the Chandelier. If the thesis has failed, the trade is exited even if the stop has not yet been hit.

## 4. Operating notes and current interpretation

50 / 144 EMA was tested and is too slow for the daily chart; it filtered out the biggest winners and is not part of the current entry model.

The 9 EMA blocker is a one-bar guardrail designed to prevent a false HA-MQI cross when a strong candle still sits inside downside pressure.

Elliott Oscillator appears useful as a compression / phase-state filter, but it still needs broader proof.

RocketRSI behaves like a force multiplier. The strongest historical runs usually followed RocketRSI below -2 within roughly 10 bars of the HA-MQI trigger.

Once RocketRSI has peaked and begun decaying, the Chandelier becomes the profit-protection mechanism. Scheduled event risk is blocked outright rather than managed technically.

## 5. Current settings snapshot

| Component | Current settings | Status / use |
|---|---|---|
| HA-MQI (working version) | Length 10 / Smooth 10 | Primary entry and hard exit state engine |
| RocketRSI | Length 10 / Cutoff 8 | Force multiplier; historical exhaustion marker |
| Elliott Oscillator | Fast 5 / Slow 20 | Compression / phase-state filter |
| 9 EMA blocker | Close must not be below 9 EMA on the trigger bar | One-bar guardrail |
| Chandelier stop | Armed after RocketRSI decay; only tightens | Profit protection / emergency exit |
| Event filter | Block trades within 2 days of earnings and around major macro events | Gap-risk governance |

## 6. Closing thesis

The current thesis is that the market can be traded more reliably as a state machine than as a single signal. HA-MQI identifies the transition into organized trend and defines the thesis for entry and exit. Elliott helps identify compressed cycle states. RocketRSI modifies confidence and position size. The 9 EMA prevents one-bar false starts. The Chandelier protects profits once the trend matures. Scheduled event risk is excluded entirely rather than managed technically. The system is not trying to catch every move; it is trying to own the moves that are sufficiently organized to pay for the ones that fail.

### The 5-layer confluence matrix

To trigger a valid long entry, all five mathematical conditions must align simultaneously:

- **Macro reset filter (EWO < 0.5):** ensures the major Wave 3 momentum peak has completely cooled down, preventing entries from chasing an overextended market.
- **Structural energy accumulation (EWO compressed):** confirms the market is in a tight consolidation phase (Wave 2 or Wave 4 squeeze), winding up like a coiled spring.
- **Absolute exhaustion (RocketRSI < -2):** identifies extreme oversold conditions where late-stage sellers have been completely flushed out, allowing for a tight, high-R:R entry point.
- **Trend circuit breaker (price / HA midpoint > 9 EMA):** acts as an anti-trap filter. It turns off the system if the asset is still trading entirely under heavy daily markdown, ignoring single-bar short squeezes.
- **Execution trigger (HA-MQI crossover):** executes the trade when the raw Heikin-Ashi Momentum / Moving Average Quantitative Indicator crosses cleanly above its 10-period SMA baseline, proving momentum is increasing faster than anticipated.
