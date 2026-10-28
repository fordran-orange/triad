import { describe, expect, it } from 'vitest';
import { KPI_LABELS, KPI_ORDER } from './labKpiLabels';
import { xState } from './labQuery';

describe('the KPI strip', () => {
  it('has one label and one title per data-kpi entry, in strip order', () => {
    expect(KPI_ORDER).toEqual(['trials', 'valid', 'planned', 'coverage', 'best', 'failed']);
    expect(Object.keys(KPI_LABELS).sort()).toEqual([...KPI_ORDER].sort());
    for (const key of KPI_ORDER) {
      expect(KPI_LABELS[key].label.length, key).toBeGreaterThan(0);
      expect(KPI_LABELS[key].title.length, key).toBeGreaterThan(0);
    }
  });

  it('no KPI label or title contains "backtest" (§6.4: a trial is not a backtest)', () => {
    for (const key of KPI_ORDER) {
      expect(KPI_LABELS[key].label.toLowerCase(), key).not.toContain('backtest');
      expect(KPI_LABELS[key].title.toLowerCase(), key).not.toContain('backtest');
    }
  });
});

describe('xState (the X state every panel renders)', () => {
  it('yields the message and a Retry label', () => {
    const x = xState('matrix failed');
    expect(x.message).toBe('matrix failed');
    expect(x.retryLabel).toBe('Retry');
    expect(x).toEqual({ message: 'matrix failed', retryLabel: 'Retry' });
  });
});
