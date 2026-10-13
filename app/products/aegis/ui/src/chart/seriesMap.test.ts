import { describe, expect, it } from 'vitest';
import { SeriesMap } from './seriesMap';

describe('SeriesMap', () => {
  it('maps emitted series ids to overlay ids and forgets them with their overlays', () => {
    const map = new SeriesMap();
    map.set('ctx1:ema', 'ema');
    map.set('ctx1:sma', 'sma');
    map.set('ctx2:macd.line', 'macd.line');
    map.set('ctx2:macd.signal', 'macd.signal');
    expect(map.overlayOf('ctx1:ema')).toBe('ema');
    map.forget(['ema']);
    expect(map.overlayOf('ctx1:ema')).toBeUndefined();
    expect(map.size).toBe(3);
    map.forget(['macd.line', 'macd.signal']);
    expect(map.size).toBe(1);
    map.clear();
    expect(map.size).toBe(0);
  });
});
