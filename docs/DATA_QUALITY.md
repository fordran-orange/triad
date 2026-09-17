# Deterministic data quality

The gate checks schema, timezone awareness/metadata, symbol consistency, finite positive prices, nonnegative volume, OHLC relationships, minute alignment, ingestion timing, duplicate source records, duplicate timestamps, source order, unexpected session bars and missing expected timestamps. Invalid rows produce indexed failures; they are not silently dropped, repaired, sorted, deduplicated or filled. Raw JSON is preserved before normalization, and corruption is detected by raw/Parquet/manifest checksums.

Expected bars come only from the requested regular-session window. Calendar is replaceable and fails closed outside its verified 2026 range. Holidays/weekends are not gaps; DST uses America/New_York. Nov 27 and Dec 24 have 13:00 closes. PRE_MARKET, AFTER_HOURS, CLOSED and HOLIDAY classifications are supported; extended bars are not part of this initial canonical regular-session contract. Early-close after-hours classification uses a documented 17:00 template, otherwise 20:00; it is not a claim about every venue's future extended session.

Calendar source: [NYSE official holidays and hours](https://www.nyse.com/trade/hours-calendars), consulted 2026-09-17. The local finite calendar snapshot is versioned XNYS-2026-v1. Exchange notices and coverage extension require an explicit reviewed update.

Resampling groups within a session anchored at 09:30 local, left-closed/right-open. Open=first, high=max, low=min, close=last, volume=sum. No overnight blending. Terminal shorter hourly bars are retained and flagged; truncated input buckets retain actual coverage, are flagged partial_dataset_bucket and cannot be backtested. Full-session daily bars end at the calendar close.


Optional derived fields: trade_count is summed only when every constituent count is present; otherwise it is null. VWAP is volume-weighted over positive-volume minutes only when their VWAPs are all present; zero total volume or missing required values yields null. It is never copied from the first minute.
