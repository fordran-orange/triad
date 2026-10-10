# Chart technology spike — result (2026-10-09)

Plan task 1 of `docs/superpowers/plans/2026-10-09-aegis-workstation-slice.md`. Time-boxed; the spike page was throwaway and has been deleted. Evidence: a built Vite page loaded through a throwaway FastAPI server that applied Core's exact `local_headers` middleware (same `Content-Security-Policy`), inspected in the built-in browser.

## Decision

**`CHART_BACKEND = "vela"`** — `@luxalgo/vela` **0.8.3** (the npm release at spike time; the design cited 0.7.0), Apache-2.0 core only. No Pine/PineTS. `lightweight-charts` remains the fallback behind the same adapter and was not needed.

## Answers

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Server-computed EMA/SMA numeric lines without the AGPL Pine engine? | **Yes.** `registerNativeIndicator({ type, paneHint: 'price', overlay: true, multiInstance: true, inputsSchema, defaultInputs, create })` from `@luxalgo/vela`; the instance's `start(ctx, inputs)` calls `ctx.emit({ series: [{ id, title, paneId: '', kind: 'line', overlay: true, points: [{ time, value }], style: { color, width, lineStyle: 'solid' } }] })` with `value: null` for warm-up gaps. Instances are added with `chart.addNativeIndicator(type, { inputs })`; each gets a legend row with its live value. | Two instances (`native-2`, `native-3`) drew EMA 9 and SMA 30 from supplied arrays; `chart.inspect().totals.series == 3` (plus Volume). |
| 2 | Trade markers acceptable? | **Yes.** Emit `labels: [{ id, paneId: '', xloc: 'bar_time', x: time, y: 0, yloc: 'belowbar' \| 'abovebar', text: 'L' \| 'S', style: 'arrowup' \| 'arrowdown', color, textColor, size: 'normal', textAlign: 'center', fontFamily: 'default', overlay: true }]` from a second native type registered with `legend: false` (host-owned, no legend row). Renders green up-arrows under entry bars and red down-arrows above, labelled. The `series` kind `'markers'` is also accepted but the native renderer only handles the shape tokens `circle, cross, diamond, flag, square, xcross` (not `arrowUp`); labels are the clearer path. | 15 crosses → 15 labels visible; `inspect().totals.labels == 15`. |
| 3 | Runs under Core's CSP (`default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'`)? | **Yes, unchanged.** Zero `securitypolicyviolation` events, zero console errors. Bundle scan: no `new Worker(`, `createObjectURL`, `blob:`, `eval(`, `new Function(`, `WebAssembly`, `importScripts`, or `fetch(` in the core chunks; WebGL2 is requested via `getContext` and falls back to canvas2d (it did here: `hasWebGL: false`, renderer `native`). | Served from `127.0.0.1:8109` with the same middleware; headers verified with curl. |
| 4 | Attribution / NOTICE? | The package `NOTICE` (Apache-2.0 §4(d)) requires a visible attribution on every screen that shows a chart. The library renders its own logomark watermark by default (`renderer` feature `attribution`, observed `true`). **Keep the watermark on**; ship the NOTICE text in the workstation's About area. Disabling the watermark is permitted only with an equivalent visible "Vela" link, which we will not do. | `NOTICE` and `README.md` "License and attribution" in the package; watermark visible bottom-left in the spike. |

## Other facts for the adapter

- Constructor: `new Vela(container, { data: OHLCV[], timeframe: '60', theme: 'dark' })`; `OHLCV = { time (epoch ms, open time), open, high, low, close, volume? }`. Timeframe strings are canonical minutes (`'1'`, `'15'`, `'30'`, `'60'`) or `'D'`.
- Data swap: `chart.setMarket({ data })` (function present). Lifecycle: `chart.ready()`, `chart.resize()`, `chart.destroy()`.
- Crosshair: `chart.renderer.onCrosshairMove((e) => …)` with `e.time`, `e.price`, `e.paneKind` ('price' | 'study'), `e.values` (Map by series id); confirmed firing on hover.
- Overlay instances: `IndicatorHandle.setInputs({...})` re-emits (our `setInputs` recomputes from the registry); `handle.remove()` removes.
- Bundle size: the built spike chunk is ~1.3 MB minified (Vite warned >500 kB); acceptable for a local tool.
- Exports used: `Vela`, `registerNativeIndicator` from `'@luxalgo/vela'` (also re-exported from `'@luxalgo/vela/plugin'`).

## Adapter mapping (for Task 9)

- `setBars(bars, timeframe)` → first call constructs `new Vela(el, { data, timeframe, theme: 'dark' })`; later calls `setMarket({ data })`.
- `setOverlays([{ id, color, points }])` → one `aegis-line` native instance per overlay id, points pushed through a module-level registry; `setInputs` to refresh; remove stale ids.
- `setMarkers([{ time, price, side, kind }])` → single legend-less `aegis-markers` native instance emitting labels (`arrowup`/`belowbar` for entries, `arrowdown`/`abovebar` for exits; green long, red short).
- `onCrosshair(cb)` → `renderer.onCrosshairMove`; `resize()`/`destroy()` pass through.
