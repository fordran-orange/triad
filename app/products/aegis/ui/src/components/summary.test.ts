import { describe, expect, it } from 'vitest';
import { breakdownRows } from './SummaryTab';

const cell = (trades: number, net_pnl: number) => ({ trades, net_pnl, win_rate: trades ? 0.5 : null, expectancy: trades ? net_pnl / trades : null });

describe('temporal breakdown rows', () => {
  it('lists ALL first, then every tag any side produced, sorted', () => {
    const rows = breakdownRows({
      long: { ALL: cell(2, 10), 'CLOCK:open': cell(1, 4) },
      short: { ALL: cell(1, -3), 'CROSSOVER:cash_open': cell(1, -3) },
      combined: { ALL: cell(3, 7) },
    });
    expect(rows.map((r) => r.tag)).toEqual(['ALL', 'CLOCK:open', 'CROSSOVER:cash_open']);
    expect(rows[1].long?.trades).toBe(1);
    expect(rows[1].short).toBeUndefined();
    expect(rows[0].combined?.trades).toBe(3);
  });
});
