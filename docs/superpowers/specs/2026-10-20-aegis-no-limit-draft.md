# Aegis "no limit": ten years of 1-minute bars, slimmer saved runs, and saving what matters (DRAFT)

Status: a draft for the operator's review, written while the operator was away. Nothing here is
built. It is the next mission candidate after the limits change, and it needs the decisions in
§6 first (two of them touch the result hash and retained data, which AGENTS.md puts behind the
operator's explicit approval and independent QA).

## 1. Intent (operator, 2026-10-20)

- "200k after this run. goal is no limit."
- "What about only saving relevant runs? Would that help? Maybe as a selectable option."

## 2. Where the limits are now (measured)

- The bar cap is 200,000 (the limits change). Ten years of QQQ 1-minute bars is 947,519 bars.
- The store: `data/aegis` was 617 MB on 2026-10-20, of which saved backtests were 525 MB (85%,
  384 runs). Optimizations (6 MB) and experiments (5 MB) keep only each cell's numbers.
- One saved run of 32,585 bars is 12.5 MB:

  | Part | Share | Note |
  |---|---|---|
  | Per-bar equity of each side | 52% | needed for drawdown and charts, at far lower resolution |
  | Per-bar indicator values | 36% | stored twice (`result.<side>.series` and `series`); recomputable from the archive |
  | Trades and markers | 11% | markers stored twice |

- A ten-year 15m run is 26.6 MB. At today's format a ten-year 1-minute run would be about 400 MB,
  and its bars about 95 MB to the page.
- The result hash covers the strategy, the pinned data, each side's per-bar series and equity,
  trades, metrics, the combined trades/equity/metrics, the temporal breakdown and the markers
  (`results.canonical_payload`).

## 3. Proposal

**A. A slim run format, for new runs.** Keep what a person reads, drop what can be recomputed:

- the indicator series are not stored (the Library chart and the Charts page recompute them from
  the archive already);
- each side's equity is stored at its trade exits plus a per-bar curve resampled to at most a few
  thousand points for charts (metrics and drawdown are computed on the full curve before saving);
- markers once.

Estimated: a run's size follows its trades, not its bars: a ten-year 1-minute run in the tens of
MB rather than 400.

**B. A chart for long ranges.** The worker aggregates candles to the resolution the chart can show
(for example at most 20,000 per view) and sends detail as the operator zooms; markers aggregate
the same way. The Charts and Library pages use it above a threshold; below it nothing changes.

**C. Saving what matters (a setting).**

- "Save every backtest" (today's behaviour) or "Save only what I keep": a run stays in the
  session's list and is saved when starred, labelled or kept.
- Optionally: keep the last N unstarred runs; older ones move to Recently deleted (restorable).
- Always kept: runs an experiment, study, walk-forward or acceptance record refers to.

**D. The bar cap.** With A and B in place, the cap rises to the archive's size (or goes), and
the refusal remains only as a guard on memory.

**E. Existing runs.** Unchanged unless the operator asks for a one-time migration (a separate,
approved step with independent QA).

## 4. Order

A, then B, then D, then C. Each is testable on its own; E only on request.

## 5. What stays

The pinned raw archive, `research_eligible: false`, the exchange closed, the per-side engine and
its metrics, every Mission 3–9 and limits acceptance item.

## 6. Decisions for the operator

1. **The result hash (retained data).** Keep today's definition and compute it on the full result
   before the run is slimmed: every recorded hash stays valid, but a slim run can only be
   re-verified by rerunning it. Or redefine the hash over the slim payload: re-verifiable from
   the file, but every recorded hash (including the acceptance's Mission 3 and 5 hashes) changes.
   Recommendation: keep the definition.
2. **Equity resolution.** A few thousand points per curve for charts (metrics stay exact), or more?
3. **The save setting's default.** Keep "Save every backtest" as the default, or switch?
4. **Existing runs (retained data).** Leave them as they are, or migrate them once to the slim
   format (needs explicit approval and independent QA)?
5. **Long-range charts.** At most 20,000 candles per view when zoomed out: right order of size?
